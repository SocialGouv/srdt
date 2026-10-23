"""Write side of the search index, on OpenSearch or Elasticsearch (`SEARCH_ENGINE`).

Each run builds a new `{alias}-{timestamp}` index, copies into it the chunks of the
sources it does not rebuild, then moves the alias and deletes the older indices.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from opensearchpy import OpenSearch

from ingestion.contract import ChunkDocument
from ingestion.mapping import index_settings, mappings
from ingestion.settings import SearchEngine, Settings, secret

BULK_BATCH_SIZE = 200

logger = logging.getLogger(__name__)


class IndexWriter(Protocol):
    def current_meta(self, alias: str) -> dict[str, Any] | None: ...
    def alias_exists(self, alias: str) -> bool: ...
    def create_index(self, alias: str, dim: int, meta: dict[str, Any]) -> str: ...
    def copy_other_sources(self, alias: str, index: str, sources: list[str]) -> int: ...
    def bulk_index(self, index: str, documents: Iterable[ChunkDocument]) -> int: ...
    def publish(self, alias: str, index: str) -> None: ...


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
        count = 0
        operations: list[dict[str, Any]] = []
        for document in documents:
            operations.append({"index": {"_index": index, "_id": document.chunk_id}})
            operations.append(document.model_dump(mode="json", exclude_unset=True))
            if len(operations) >= 2 * BULK_BATCH_SIZE:
                count += self._bulk(operations)
                operations = []
        if operations:
            count += self._bulk(operations)
        return count

    def _bulk(self, operations: list[dict[str, Any]]) -> int:
        response = self.client.bulk(body=operations)
        if response["errors"]:
            errors = [
                item["index"]["error"]
                for item in response["items"]
                if "error" in item["index"]
            ]
            raise RuntimeError(f"{len(errors)} bulk errors, first: {errors[0]}")
        return len(operations) // 2

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
