"""load -> chunk -> embed -> write, for the sources of the include list."""

import json
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingestion.config import SOURCE_DATASETS, Config, Dataset
from ingestion.contract import (
    CHUNKER_VERSION,
    SCHEMA_MAJOR,
    SCHEMA_VERSION,
    SOURCES,
    Chunk,
    SourceName,
)
from ingestion.embed import Embedder, batched
from ingestion.index_writer import IndexWriter
from ingestion.settings import Settings
from ingestion.snapshots.store import Manifest, SnapshotStore
from ingestion.sources.cdtn import CDTN_SOURCES, chunk_cdtn
from ingestion.sources.judilibre import chunk_decision
from ingestion.sources.kali import chunk_cc, is_agreement_file
from ingestion.sources.legi import (
    CODE_DU_TRAVAIL_FILE,
    LegiIndex,
    chunk_code_du_travail,
)
from ingestion.sources.postgres import Document, load_documents
from ingestion.text.chunker import Chunker

logger = logging.getLogger(__name__)

PostgresLoader = Callable[
    [Settings, Sequence[SourceName]], dict[SourceName, list[Document]]
]


class IngestionError(RuntimeError):
    pass


@dataclass
class Inputs:
    """Raw inputs of a run, loaded on first use: snapshots and CDTN documents."""

    store: SnapshotStore
    config: Config
    settings: Settings
    postgres_loader: PostgresLoader = load_documents
    _manifests: dict[Dataset, Manifest] = field(default_factory=dict)
    _documents: dict[SourceName, list[Document]] | None = None
    _documents_read_at: str | None = None
    _legi_code: dict | None = None
    _legi_index: LegiIndex | None = None

    def manifest(self, dataset: Dataset) -> Manifest:
        if dataset not in self._manifests:
            snapshot_id = self.store.resolve(dataset, self.config.snapshot_ref(dataset))
            self._manifests[dataset] = self.store.manifest(dataset, snapshot_id)
            logger.info(f"{dataset}: snapshot {snapshot_id}")
        return self._manifests[dataset]

    def read_json(self, dataset: Dataset, path: str) -> Any:
        with open(self.store.fetch_file(self.manifest(dataset), path)) as f:
            return json.load(f)

    def legi_code(self) -> dict:
        code = self._legi_code
        if code is None:
            code = self._legi_code = self.read_json("legi", CODE_DU_TRAVAIL_FILE)
        return code

    def legi_index(self) -> LegiIndex:
        index = self._legi_index
        if index is None:
            index = self._legi_index = LegiIndex(self.legi_code())
        return index

    def documents(self, source: SourceName) -> list[Document]:
        # one read for all the CDTN sources of the run
        documents = self._documents
        if documents is None:
            sources: list[SourceName] = [
                s for s in self.config.include if s in CDTN_SOURCES
            ]
            self._documents_read_at = datetime.now(UTC).isoformat()
            documents = self._documents = self.postgres_loader(self.settings, sources)
        return documents[source]

    def source_meta(self, source: SourceName) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "snapshots": {
                dataset: self.manifest(dataset).snapshot_id
                for dataset in SOURCE_DATASETS[source]
            }
        }
        if source in CDTN_SOURCES:
            meta["postgres_read_at"] = self._documents_read_at
        return meta


def chunk_source(source: SourceName, inputs: Inputs) -> list[Chunk]:
    if source in CDTN_SOURCES:
        return chunk_cdtn(source, inputs.documents(source), inputs.legi_index())
    if source == "code_du_travail":
        return chunk_code_du_travail(inputs.legi_code())

    chunker = Chunker()
    chunks: list[Chunk] = []
    if source == "conventions":
        for path in inputs.manifest("kali").paths():
            if is_agreement_file(path):
                chunks += chunk_cc(inputs.read_json("kali", path), chunker)
        return chunks
    if source == "judilibre":
        for path in inputs.manifest("judilibre").paths():
            for decision in inputs.read_json("judilibre", path):
                chunks += chunk_decision(decision, chunker)
        return chunks
    raise IngestionError(f"No loader for source {source}")


def select_sources(config: Config, only: Sequence[str] | None) -> list[SourceName]:
    if not only:
        return list(config.include)
    unknown = [s for s in only if s not in config.include]
    if unknown:
        raise IngestionError(f"Not in the include list: {', '.join(unknown)}")
    return [s for s in config.include if s in only]


def check_unique_ids(source: SourceName, chunks: list[Chunk]) -> None:
    duplicates = [i for i, n in Counter(c.chunk_id for c in chunks).items() if n > 1]
    if duplicates:
        raise IngestionError(
            f"{source}: {len(duplicates)} duplicate chunk ids, e.g. {duplicates[0]}"
        )


def write_dump(directory: Path, chunks_by_source: dict[SourceName, list[Chunk]]):
    """One JSONL file per source, sorted lines: comparable between two runs."""
    directory.mkdir(parents=True, exist_ok=True)
    for source, chunks in chunks_by_source.items():
        lines = sorted(
            json.dumps(c.stored_fields(), sort_keys=True, ensure_ascii=False)
            for c in chunks
        )
        (directory / f"{source}.jsonl").write_text("\n".join(lines) + "\n")


def check_partial_run(
    sources: list[SourceName], current: dict[str, Any] | None, config: Config
) -> None:
    """Chunks of the other sources are copied from the current index: refuse when
    they would not match what this run writes."""
    if set(sources) >= set(SOURCES):
        return
    if current is None:
        raise IngestionError(
            "The current index has no _meta (legacy ingestion): "
            "run once with every source"
        )
    if str(current.get("schema_version", "")).split(".")[0] != SCHEMA_MAJOR:
        raise IngestionError(
            f"The current index uses schema {current.get('schema_version')}: "
            "run once with every source"
        )
    if (current.get("embedding_model_id"), current.get("dim")) != (
        config.embedding.model_id,
        config.embedding.dim,
    ):
        raise IngestionError(
            f"The current index was embedded with {current.get('embedding_model_id')} "
            f"({current.get('dim')}): run once with every source"
        )


@dataclass
class RunResult:
    counts: dict[SourceName, int]
    index: str | None = None
    copied: int = 0


def run(
    config: Config,
    inputs: Inputs,
    *,
    only: Sequence[str] | None = None,
    dry_run: bool = False,
    dump: Path | None = None,
    writer_factory: Callable[[], IndexWriter] | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> RunResult:
    sources = select_sources(config, only)
    logger.info(f"Sources: {', '.join(sources)}")

    chunks_by_source: dict[SourceName, list[Chunk]] = {}
    for source in sources:
        chunks = chunk_source(source, inputs)
        check_unique_ids(source, chunks)
        chunks_by_source[source] = chunks
        logger.info(f"{source}: {len(chunks)} chunks")
    result = RunResult(counts={s: len(c) for s, c in chunks_by_source.items()})

    if dump:
        write_dump(dump, chunks_by_source)
        logger.info(f"Dumped chunks to {dump}")
    if dry_run:
        return result
    if writer_factory is None or embedder_factory is None:
        raise IngestionError("A writer and an embedder are needed to index")

    alias = config.index.alias
    writer = writer_factory()
    current = writer.current_meta(alias)
    if writer.alias_exists(alias):
        check_partial_run(sources, current, config)

    copied_sources = {
        s: m
        for s, m in ((current or {}).get("sources") or {}).items()
        if s not in sources
    }
    meta = {
        "schema_version": SCHEMA_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "embedding_model_id": config.embedding.model_id,
        "dim": config.embedding.dim,
        "built_at": datetime.now(UTC).isoformat(),
        "sources": {
            **copied_sources,
            **{s: inputs.source_meta(s) for s in sources},
        },
    }
    index = writer.create_index(alias, config.embedding.dim, meta)
    result.index = index
    result.copied = writer.copy_other_sources(alias, index, list(sources))

    embedder = embedder_factory()
    model_id = config.embedding.model_id
    for source, chunks in chunks_by_source.items():
        written = 0
        for batch in batched(chunks, config.embedding.batch_size):
            vectors = embedder.embed([c.content for c in batch])
            documents = (
                c.to_document(model_id, v) for c, v in zip(batch, vectors, strict=True)
            )
            written += writer.bulk_index(index, documents)
        logger.info(f"{source}: indexed {written} chunks")

    writer.publish(alias, index)
    return result
