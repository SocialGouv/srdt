"""Bring the live index up to date in place, embedding only what changed.

`ingest index` rebuilds the index from scratch; `sync` diffs the chunks of each source
against the index (by `doc_hash` and `embed_hash`) and writes the difference.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ingestion.config import Config, SyncConfig
from ingestion.contract import CHUNKER_VERSION, Chunk, SourceName, embed_hash
from ingestion.embed import Embedder, batched
from ingestion.index_writer import MetadataUpdate, SyncWriter
from ingestion.pipeline import (
    IngestionError,
    Inputs,
    chunk_sources,
    meta_problem,
    select_sources,
)

logger = logging.getLogger(__name__)

Hashes = dict[str, tuple[str, str]]  # chunk id -> (doc_hash, embed_hash)


class SyncAborted(IngestionError):
    """A guard tripped: the change looks like a broken input, not an update."""


@dataclass
class SourcePlan:
    source: SourceName
    existing: int
    desired: int
    unchanged: int = 0
    created: int = 0  # chunk ids that are not in the index yet
    to_update: list[str] = field(default_factory=list)  # new metadata, same vector
    to_reuse: dict[str, str] = field(default_factory=dict)  # chunk id -> embed_hash
    to_embed: list[str] = field(default_factory=list)
    to_delete: list[str] = field(default_factory=list)

    def counts(self, batch_size: int) -> dict[str, int]:
        return {
            "unchanged": self.unchanged,
            "created": self.created,
            "metadata_updated": len(self.to_update),
            "reused": len(self.to_reuse),
            "embedded": len(self.to_embed),
            "deleted": len(self.to_delete),
            "albert_calls": math.ceil(len(self.to_embed) / batch_size),
        }


def plan_sync(source: SourceName, desired: Hashes, existing: Hashes) -> SourcePlan:
    """Diff the chunks a source should have against the ones the index has."""
    plan = SourcePlan(source, existing=len(existing), desired=len(desired))
    in_index = {embed for _, embed in existing.values()}
    for chunk_id, (doc, embed) in desired.items():
        old = existing.get(chunk_id)
        if old is None:
            plan.created += 1
        if old is not None and old[1] == embed:
            if old[0] == doc:
                plan.unchanged += 1
            else:
                plan.to_update.append(chunk_id)
        elif embed in in_index:
            # same text elsewhere in the source (the chunk moved): keep its vector
            plan.to_reuse[chunk_id] = embed
        else:
            plan.to_embed.append(chunk_id)
    plan.to_delete = [chunk_id for chunk_id in existing if chunk_id not in desired]
    return plan


def check_guards(plan: SourcePlan, config: SyncConfig) -> None:
    if plan.desired == 0 and plan.existing > 0:
        raise SyncAborted(
            f"{plan.source}: no chunk to index but {plan.existing} in the index "
            "(empty input?)"
        )
    deleted = len(plan.to_delete)
    ratio = config.max_ratio(plan.source)
    if deleted > config.min_deleted and deleted > ratio * plan.existing:
        raise SyncAborted(
            f"{plan.source}: {deleted} of {plan.existing} chunks would be deleted "
            f"(limit {ratio:.0%})"
        )


def check_compatible(current: dict[str, Any] | None, config: Config) -> dict[str, Any]:
    problem = meta_problem(current, config)
    if current is not None and not problem:
        if current.get("chunker_version") != CHUNKER_VERSION:
            problem = (
                f"The current index was chunked by version "
                f"{current.get('chunker_version')}, this is {CHUNKER_VERSION}"
            )
    if problem or current is None:
        raise IngestionError(f"{problem}: run ingest index")
    return current


@dataclass
class SyncResult:
    plans: dict[SourceName, SourcePlan]
    # in the index but no longer in the include list
    excluded: list[str] = field(default_factory=list)
    pruned: dict[str, int] = field(default_factory=dict)

    def summary(self, batch_size: int) -> dict[str, Any]:
        return {
            "sources": {s: p.counts(batch_size) for s, p in self.plans.items()},
            "excluded": self.excluded,
            "pruned": self.pruned,
        }


def _hashes(chunks: Sequence[Chunk], model_id: str) -> Hashes:
    return {
        c.chunk_id: (c.compute_doc_hash(), embed_hash(model_id, c.content))
        for c in chunks
    }


def sync(
    config: Config,
    inputs: Inputs,
    writer: SyncWriter,
    embedder: Embedder | None,
    *,
    only: Sequence[str] | None = None,
    dry_run: bool = False,
    allow_prune: bool = False,
    prune_excluded: bool = False,
) -> SyncResult:
    sources = select_sources(config, only)
    alias = inputs.settings.search_index
    if not writer.alias_exists(alias):
        raise IngestionError(f"No {alias} index: run ingest index")
    current = check_compatible(writer.current_meta(alias), config)
    logger.info(f"Sources: {', '.join(sources)}")

    # Everything is read and checked before anything is embedded or written.
    model_id = config.embedding.model_id
    chunks_by_source = chunk_sources(sources, inputs)
    plans: dict[SourceName, SourcePlan] = {}
    for source, chunks in chunks_by_source.items():
        plan = plan_sync(
            source,
            _hashes(chunks, model_id),
            writer.scan_hashes(alias, source),
        )
        if not allow_prune:
            check_guards(plan, config.sync)
        plans[source] = plan
        logger.info(f"{source}: {plan.counts(config.embedding.batch_size)}")

    excluded = [s for s in (current.get("sources") or {}) if s not in config.include]
    result = SyncResult(plans, excluded=excluded)
    for source in excluded:
        logger.warning(
            f"{source} is in the index but not in the include list"
            + ("" if prune_excluded else " (--prune-excluded to delete it)")
        )
    if dry_run:
        return result

    # 1. embed: the step most likely to fail, nothing is written yet
    by_id = {c.chunk_id: c for chunks in chunks_by_source.values() for c in chunks}
    texts: dict[str, str] = {}  # embed_hash -> text, identical texts are embedded once
    for plan in plans.values():
        for chunk_id in plan.to_embed:
            chunk = by_id[chunk_id]
            texts[embed_hash(model_id, chunk.content)] = chunk.content
    vectors: dict[str, list[float]] = {}
    if texts:
        if embedder is None:
            raise IngestionError("An embedder is needed to sync")
        hashes = list(texts)
        for batch in batched(hashes, config.embedding.batch_size):
            embedded = embedder.embed([texts[h] for h in batch])
            vectors.update(zip(batch, embedded, strict=True))
        logger.info(f"Embedded {len(texts)} texts")

    # 2. vectors of the chunks that moved
    wanted = sorted({h for p in plans.values() for h in p.to_reuse.values()})
    found = writer.fetch_vectors(alias, wanted) if wanted else {}
    missing = [h for h in wanted if len(found.get(h, ())) != config.embedding.dim]
    if missing:
        raise IngestionError(
            f"{len(missing)} vectors to reuse could not be read from the index "
            "(does the engine return vectors in _source?)"
        )
    vectors.update(found)

    # 3. write
    documents = []
    updates = []
    deletes = []
    for plan in plans.values():
        for chunk_id in [*plan.to_embed, *plan.to_reuse]:
            chunk = by_id[chunk_id]
            vector = vectors[embed_hash(model_id, chunk.content)]
            documents.append(chunk.to_document(model_id, vector))
        for chunk_id in plan.to_update:
            chunk = by_id[chunk_id]
            updates.append(
                MetadataUpdate(
                    chunk_id,
                    chunk.id,
                    chunk.stored_fields()["metadata"],
                    chunk.compute_doc_hash(),
                )
            )
        deletes += plan.to_delete
    writer.apply(alias, documents, updates, deletes)
    if prune_excluded:
        for source in excluded:
            result.pruned[source] = writer.delete_source(alias, source)
            logger.info(f"Deleted {result.pruned[source]} chunks of {source}")

    # 4. _meta last: after a failure the data is ahead of it, never behind
    kept = {s: m for s, m in (current.get("sources") or {}).items()}
    for source in result.pruned:
        kept.pop(source, None)
    writer.update_meta(
        alias,
        {
            **current,
            "synced_at": datetime.now(UTC).isoformat(),
            "sources": {**kept, **{s: inputs.source_meta(s) for s in sources}},
        },
    )
    return result
