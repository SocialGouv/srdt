"""Write side of the search index, on OpenSearch or Elasticsearch (`SEARCH_ENGINE`).

Each run builds a new `{alias}-{timestamp}` index, copies into it the chunks of the
sources it does not rebuild, then moves the alias and deletes the older indices.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from opensearchpy import OpenSearch
from opensearchpy.helpers import scan

from ingestion.contract import ChunkDocument
from ingestion.mapping import index_settings, mappings
from ingestion.settings import SearchEngine, Settings, secret

BULK_BATCH_SIZE = 200
# hashes per vector lookup
VECTOR_LOOKUP_SIZE = 500

# Replaces what changed without touching `content` and `embedding`. A partial `doc`
# update would merge the metadata and keep keys that are gone (legi_links, number).
UPDATE_SCRIPT = (
    "ctx._source.id = params.id; "
    "ctx._source.metadata = params.metadata; "
    "ctx._source.doc_hash = params.doc_hash"
)

logger = logging.getLogger(__name__)


class IndexWriter(Protocol):
    def current_meta(self, alias: str) -> dict[str, Any] | None: ...
    def alias_exists(self, alias: str) -> bool: ...
    def create_index(self, alias: str, dim: int, meta: dict[str, Any]) -> str: ...
    def copy_other_sources(self, alias: str, index: str, sources: list[str]) -> int: ...
    def bulk_index(self, index: str, documents: Iterable[ChunkDocument]) -> int: ...
    def publish(self, alias: str, index: str) -> None: ...


@dataclass(frozen=True)
class MetadataUpdate:
    """New id, metadata and doc_hash of a chunk whose text (and vector) is unchanged."""

    chunk_id: str
    id: str
    metadata: dict[str, Any]
    doc_hash: str


class SyncWriter(Protocol):
    """What `ingest sync` needs to change the live index in place."""

    def current_meta(self, alias: str) -> dict[str, Any] | None: ...
    def alias_exists(self, alias: str) -> bool: ...
    def scan_hashes(self, alias: str, source: str) -> dict[str, tuple[str, str]]: ...
    def fetch_vectors(
        self, alias: str, embed_hashes: Sequence[str]
    ) -> dict[str, list[float]]: ...
    def apply(
        self,
        alias: str,
        documents: Iterable[ChunkDocument],
        updates: Iterable[MetadataUpdate],
        deletes: Iterable[str],
    ) -> None: ...
    def delete_source(self, alias: str, source: str) -> int: ...
    def update_meta(self, alias: str, meta: dict[str, Any]) -> None: ...


def build_client(hostname: str, credentials: str) -> OpenSearch:
    """Both engines are reached with the same client: the REST endpoints are the same.

    `user:password` is sent as basic auth. A value without `:` is the base64
    `user:password` token that deployed environments hold: it is sent as is
    (`Authorization: Basic <token>`)."""
    auth: dict[str, Any]
    if ":" in credentials:
        auth = {"http_auth": credentials}
    else:
        auth = {"headers": {"Authorization": f"Basic {credentials}"}}
    return OpenSearch(
        hosts=[hostname],
        verify_certs=False,
        ssl_show_warn=False,
        timeout=60,
        **auth,
    )


class SearchIndexWriter:
    def __init__(self, settings: Settings):
        settings.require("search_hostname", "search_credentials")
        self.engine: SearchEngine = settings.search_engine
        self.client = build_client(
            str(settings.search_hostname), secret(settings.search_credentials)
        )

    def alias_exists(self, alias: str) -> bool:
        return bool(self.client.indices.exists_alias(name=alias))

    def current_meta(self, alias: str) -> dict[str, Any] | None:
        """_meta of the index behind `alias`; None when there is no index or when it
        was built by the legacy api ingestion (no _meta)."""
        if not self.alias_exists(alias):
            return None
        mapping = self.client.indices.get_mapping(index=alias)
        (index_mapping,) = mapping.values()
        return index_mapping["mappings"].get("_meta")

    def create_index(self, alias: str, dim: int, meta: dict[str, Any]) -> str:
        name = f"{alias}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        self.client.indices.create(
            index=name,
            body={
                "mappings": {**mappings(dim, self.engine), "_meta": meta},
                "settings": index_settings(self.engine),
            },
        )
        logger.info(f"Created index {name}")
        return name

    def copy_other_sources(self, alias: str, index: str, sources: list[str]) -> int:
        """Copy into `index` the chunks of the current `alias` index whose source is
        not in `sources` (reindexed by the engine, embeddings included)."""
        if not self.alias_exists(alias):
            logger.info(f"No current {alias} index, nothing to copy")
            return 0
        response = self.client.reindex(
            body={
                "source": {
                    "index": alias,
                    "query": {
                        "bool": {"must_not": [{"terms": {"metadata.source": sources}}]}
                    },
                },
                "dest": {"index": index},
            },
            params={"request_timeout": 3600},
        )
        if response.get("failures"):
            raise RuntimeError(f"Reindex failures: {response['failures'][:3]}")
        logger.info(f"Copied {response['total']} chunks from the current {alias} index")
        return response["total"]

    def bulk_index(self, index: str, documents: Iterable[ChunkDocument]) -> int:
        return self._bulk(
            (
                {"index": {"_index": index, "_id": document.chunk_id}},
                document.model_dump(mode="json", exclude_unset=True),
            )
            for document in documents
        )

    def _bulk(
        self, actions: Iterable[tuple[dict[str, Any], dict[str, Any] | None]]
    ) -> int:
        """Send (action, source) pairs by batches; a delete has no source."""
        count = 0
        operations: list[dict[str, Any]] = []
        batch = 0
        for action, source in actions:
            operations.append(action)
            if source is not None:
                operations.append(source)
            batch += 1
            if batch >= BULK_BATCH_SIZE:
                self._send(operations)
                count += batch
                operations, batch = [], 0
        if operations:
            self._send(operations)
            count += batch
        return count

    def _send(self, operations: list[dict[str, Any]]) -> None:
        response = self.client.bulk(body=operations)
        if response["errors"]:
            errors = [
                result["error"]
                for item in response["items"]
                for result in item.values()
                if "error" in result
            ]
            raise RuntimeError(f"{len(errors)} bulk errors, first: {errors[0]}")

    def scan_hashes(self, alias: str, source: str) -> dict[str, tuple[str, str]]:
        """`_id` -> (doc_hash, embed_hash) of the chunks of `source`."""
        hits = scan(
            self.client,
            index=alias,
            query={
                "query": {"term": {"metadata.source": source}},
                "_source": ["doc_hash", "embed_hash"],
            },
            size=1000,
        )
        return {
            hit["_id"]: (
                hit["_source"].get("doc_hash", ""),
                hit["_source"].get("embed_hash", ""),
            )
            for hit in hits
        }

    def fetch_vectors(
        self, alias: str, embed_hashes: Sequence[str]
    ) -> dict[str, list[float]]:
        """Vector of one chunk per embed_hash (identical text, same model)."""
        vectors: dict[str, list[float]] = {}
        for start in range(0, len(embed_hashes), VECTOR_LOOKUP_SIZE):
            batch = list(embed_hashes[start : start + VECTOR_LOOKUP_SIZE])
            response = self.client.search(
                index=alias,
                body={
                    "size": len(batch),
                    "query": {"terms": {"embed_hash": batch}},
                    "collapse": {"field": "embed_hash"},
                    "_source": ["embed_hash", "embedding"],
                },
            )
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                if "embedding" in source:
                    vectors[source["embed_hash"]] = source["embedding"]
        return vectors

    def apply(
        self,
        alias: str,
        documents: Iterable[ChunkDocument],
        updates: Iterable[MetadataUpdate],
        deletes: Iterable[str],
    ) -> None:
        """Write to the live index: new and re-embedded chunks, then metadata
        updates, then deletions. One refresh at the end."""
        indexed = self._bulk(
            (
                {"index": {"_index": alias, "_id": document.chunk_id}},
                document.model_dump(mode="json", exclude_unset=True),
            )
            for document in documents
        )
        updated = self._bulk(
            (
                {"update": {"_index": alias, "_id": update.chunk_id}},
                {
                    "script": {
                        "lang": "painless",
                        "source": UPDATE_SCRIPT,
                        "params": {
                            "id": update.id,
                            "metadata": update.metadata,
                            "doc_hash": update.doc_hash,
                        },
                    }
                },
            )
            for update in updates
        )
        deleted = self._bulk(
            ({"delete": {"_index": alias, "_id": chunk_id}}, None)
            for chunk_id in deletes
        )
        self.client.indices.refresh(index=alias)
        logger.info(f"Indexed {indexed}, updated {updated}, deleted {deleted} chunks")

    def delete_source(self, alias: str, source: str) -> int:
        response = self.client.delete_by_query(
            index=alias,
            body={"query": {"term": {"metadata.source": source}}},
            params={"refresh": "true", "request_timeout": 600},
        )
        return response["deleted"]

    def update_meta(self, alias: str, meta: dict[str, Any]) -> None:
        # replaces the whole _meta: `meta` is the merged one
        self.client.indices.put_mapping(index=alias, body={"_meta": meta})

    def publish(self, alias: str, index: str) -> None:
        """Make `index` searchable, move `alias` to it, delete the older indices."""
        self.client.indices.put_settings(
            index=index, body={"index": {"refresh_interval": None}}
        )
        self.client.indices.refresh(index=index)

        actions: list[dict[str, Any]] = [{"add": {"alias": alias, "index": index}}]
        if self.alias_exists(alias):
            actions.insert(0, {"remove": {"alias": alias, "index": f"{alias}-*"}})
        self.client.indices.update_aliases(body={"actions": actions})
        logger.info(f"Alias {alias} -> {index}")

        stale = [
            name
            for name in self.client.indices.get(index=f"{alias}-*").keys()
            if name != index
        ]
        if stale:
            logger.info(f"Deleting {len(stale)} old indices: {', '.join(stale)}")
            self.client.indices.delete(index=stale)
