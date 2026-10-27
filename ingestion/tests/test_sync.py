import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from ingestion.config import Config, SyncConfig
from ingestion.contract import CHUNKER_VERSION, SCHEMA_VERSION, SourceName
from ingestion.pipeline import IngestionError, Inputs, run
from ingestion.settings import Settings
from ingestion.snapshots.store import LocalStore
from ingestion.sources.postgres import Document
from ingestion.sync import (
    SyncAborted,
    SyncResult,
    check_guards,
    plan_sync,
    sync,
)
from tests.conftest import (
    FIXTURES,
    FakeEmbedder,
    FakeIndex,
    FakeWriter,
    cdtn_documents,
    make_config,
    make_inputs,
)


def two_information_pages() -> dict[SourceName, list[Document]]:
    """The fixture rows, with a second information page: a source that loses one
    document is not empty."""
    documents = cdtn_documents()
    (first,) = documents["information"]
    documents["information"] = [
        first,
        replace(first, cdtn_id="i0002", title="Seuils"),
    ]
    return documents


def build_index(
    store: LocalStore,
    config: Config,
    documents: dict[SourceName, list[Document]] | None = None,
) -> FakeIndex:
    writer = FakeWriter()
    run(
        config,
        make_inputs(store, config, documents),
        writer_factory=lambda: writer,
        embedder_factory=FakeEmbedder,
    )
    return FakeIndex.built_from(writer)


def sync_with(
    index: FakeIndex,
    config: Config,
    store: LocalStore,
    documents: dict[SourceName, list[Document]] | None = None,
    **kwargs,
) -> tuple[SyncResult, FakeEmbedder]:
    """`documents` replaces the Postgres rows of this run."""
    embedder = FakeEmbedder()
    result = sync(
        config, make_inputs(store, config, documents), index, embedder, **kwargs
    )
    return result, embedder


def embedded_texts(embedder: FakeEmbedder) -> list[str]:
    return [text for call in embedder.calls for text in call]


# plan_sync


def hashes(**chunks: tuple[str, str]) -> dict[str, tuple[str, str]]:
    return chunks


def test_plan_sync_cases():
    existing = hashes(
        same=("d1", "e1"),
        edited=("d2", "e2"),
        retitled=("d3", "e3"),
        gone=("d4", "e4"),
    )
    desired = hashes(
        same=("d1", "e1"),
        edited=("d2b", "e2b"),
        retitled=("d3b", "e3"),
        brand_new=("d5", "e5"),
        moved=("d4", "e4"),  # same text as `gone`, under another id
    )
    plan = plan_sync("information", desired, existing)
    assert plan.unchanged == 1
    assert plan.to_update == ["retitled"]
    assert plan.to_embed == ["edited", "brand_new"]
    assert plan.to_reuse == {"moved": "e4"}
    assert plan.to_delete == ["gone"]
    assert plan.created == 2  # brand_new, moved


def test_plan_sync_reuses_the_vector_of_an_edited_chunk_back_to_old_text():
    existing = hashes(a=("d1", "e1"), b=("d2", "e2"))
    desired = hashes(a=("d1", "e2"), b=("d2", "e2"))
    plan = plan_sync("information", desired, existing)
    assert plan.to_reuse == {"a": "e2"}
    assert plan.to_embed == []


def test_plan_sync_of_an_unchanged_source_is_empty():
    same = hashes(a=("d1", "e1"))
    plan = plan_sync("information", same, dict(same))
    assert (plan.unchanged, plan.to_embed, plan.to_update, plan.to_delete) == (
        1,
        [],
        [],
        [],
    )


# guards


def _plan(existing: int, desired: int, deleted: int):
    plan = plan_sync(
        "judilibre",
        {f"k{i}": ("d", "e") for i in range(desired)},
        {f"k{i}": ("d", "e") for i in range(existing)},
    )
    assert len(plan.to_delete) == deleted
    return plan


def test_guard_trips_on_an_empty_input():
    with pytest.raises(SyncAborted, match="no chunk to index"):
        check_guards(_plan(existing=10, desired=0, deleted=10), SyncConfig())


def test_guard_trips_over_the_ratio():
    config = SyncConfig(max_delete_ratio=0.1, min_deleted=0)
    with pytest.raises(SyncAborted, match="30 of 100"):
        check_guards(_plan(existing=100, desired=70, deleted=30), config)
    check_guards(_plan(existing=100, desired=90, deleted=10), config)


def test_guard_ignores_few_deletions_in_a_small_source():
    check_guards(_plan(existing=10, desired=5, deleted=5), SyncConfig(min_deleted=25))


def test_guard_ratio_per_source():
    config = SyncConfig(
        max_delete_ratio=0.1, min_deleted=0, per_source={"judilibre": 0.5}
    )
    check_guards(_plan(existing=100, desired=70, deleted=30), config)


# sync


def test_second_sync_embeds_and_writes_nothing(store: LocalStore, config: Config):
    index = build_index(store, config)
    before = dict(index.docs)

    result, embedder = sync_with(index, config, store)

    assert embedder.calls == []
    assert index.writes == [(0, 0, 0)]
    assert index.docs == before
    for plan in result.plans.values():
        assert plan.unchanged == plan.desired > 0


def test_editing_one_document_touches_only_its_chunks(
    store: LocalStore, config: Config
):
    index = build_index(store, config)
    documents = cdtn_documents()
    (information,) = documents["information"]
    blocks = information.document["contents"][0]["blocks"]
    blocks[0]["markdown"] = "# Effectifs\n\nCalcul modifié."
    before = dict(index.docs)

    result, embedder = sync_with(index, config, store, documents)

    changed = {i for i, d in index.docs.items() if before.get(i) != d}
    assert changed
    assert {index.docs[i].metadata.source for i in changed} == {"information"}
    assert len(embedded_texts(embedder)) == len(changed)
    assert all("Calcul modif" in t for t in embedded_texts(embedder))
    assert (
        index.docs[next(iter(changed))].embed_hash
        != before[next(iter(changed))].embed_hash
    )
    assert sum(len(p.to_embed) for p in result.plans.values()) == len(changed)


def test_removing_a_document_deletes_exactly_its_chunks(
    store: LocalStore, config: Config
):
    index = build_index(store, config, two_information_pages())
    documents = two_information_pages()
    documents["information"] = documents["information"][:1]
    doomed = {i for i, d in index.docs.items() if d.metadata.id == "i0002"}
    assert doomed

    result, embedder = sync_with(index, config, store, documents)

    assert embedder.calls == []
    assert set(result.plans["information"].to_delete) == doomed
    assert result.plans["information"].unchanged
    assert not doomed & set(index.docs)


def test_sync_keeps_the_vector_of_a_chunk_whose_metadata_changed(
    store: LocalStore, config: Config, tmp_path: Path
):
    """A changed LEGI article updates the CDTN chunks that link to it, without
    embedding them."""
    index = build_index(store, config)
    code = json.loads((FIXTURES / "LEGITEXT000006072050.json").read_text())
    article = code["children"][0]["children"][0]["children"][0]
    assert article["data"]["num"] == "L1111-1"
    article["data"]["num"] = "L1111-1-1"
    changed = tmp_path / "LEGITEXT000006072050.json"
    changed.write_text(json.dumps(code))
    store.put_snapshot("legi", "2.576.0", {"LEGITEXT000006072050.json": changed}, {})
    before = dict(index.docs)

    result, embedder = sync_with(index, config, store)

    for source in ("contributions", "contributions_idcc", "information"):
        assert result.plans[source].to_embed == []
    assert result.plans["contributions"].to_update
    (chunk_id,) = result.plans["contributions"].to_update[:1]
    assert index.docs[chunk_id].embedding == before[chunk_id].embedding
    assert index.docs[chunk_id].doc_hash != before[chunk_id].doc_hash
    assert index.docs[chunk_id].embed_hash == before[chunk_id].embed_hash
    # only the code du travail text changed
    assert result.plans["code_du_travail"].to_embed
    assert all("L1111-1-1" in t for t in embedded_texts(embedder))


def test_dry_run_reads_but_does_not_write(store: LocalStore, config: Config):
    index = build_index(store, config, two_information_pages())
    documents = two_information_pages()
    documents["information"] = documents["information"][:1]
    before = dict(index.docs)

    result, embedder = sync_with(index, config, store, documents, dry_run=True)

    assert result.plans["information"].to_delete
    assert index.docs == before
    assert index.events == []
    assert embedder.calls == []


def test_guard_aborts_before_anything_is_written(store: LocalStore):
    config = make_config(sync=SyncConfig(max_delete_ratio=0.1, min_deleted=0))
    index = build_index(store, config, two_information_pages())
    documents = two_information_pages()
    documents["information"] = documents["information"][:1]
    # something else changes too: it must not be written either
    (fiche,) = documents["fiches_service_public"]
    documents["fiches_service_public"] = [replace(fiche, text="Autre texte.")]
    before = dict(index.docs)

    with pytest.raises(SyncAborted, match="information.*would be deleted"):
        sync_with(index, config, store, documents)
    assert index.docs == before
    assert index.events == []

    sync_with(index, config, store, documents, allow_prune=True)
    assert index.events == ["apply", "meta"]
    assert not any(d.metadata.id == "i0002" for d in index.docs.values())


def test_embedding_failure_writes_nothing(store: LocalStore, config: Config):
    index = build_index(store, config)
    documents = cdtn_documents()
    (information,) = documents["information"]
    information.document["contents"][0]["blocks"][0]["markdown"] = "# Autre\n\nTexte."
    before = dict(index.docs)

    class Failing:
        def embed(self, texts: Sequence[str]):
            raise RuntimeError("Albert is down")

    inputs = Inputs(
        store=store,
        config=config,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        postgres_loader=lambda _s, sources: {
            s: d for s, d in documents.items() if s in sources
        },
    )
    with pytest.raises(RuntimeError, match="Albert is down"):
        sync(config, inputs, index, Failing())
    assert index.docs == before
    assert index.events == []


def test_sync_updates_the_meta_after_the_data(store: LocalStore, config: Config):
    index = build_index(store, config)
    index.meta["built_at"] = "2026-01-01T00:00:00+00:00"

    sync_with(index, config, store)

    assert index.events == ["apply", "meta"]
    assert index.meta["built_at"] == "2026-01-01T00:00:00+00:00"
    assert datetime.fromisoformat(index.meta["synced_at"])
    assert index.meta["sources"]["conventions"]["snapshots"] == {"kali": "3.514.0"}
    assert index.meta["embedding_model_id"] == "test-model"


def test_only_syncs_a_subset_and_keeps_the_other_sources_meta(
    store: LocalStore, config: Config
):
    index = build_index(store, config)
    index.meta["sources"]["conventions"] = {"snapshots": {"kali": "3.400.0"}}

    result, _ = sync_with(index, config, store, only=["judilibre"])

    assert list(result.plans) == ["judilibre"]
    assert index.meta["sources"]["conventions"] == {"snapshots": {"kali": "3.400.0"}}


def test_a_source_left_out_of_the_include_list_is_reported_then_pruned(
    store: LocalStore,
):
    full = make_config()
    index = build_index(store, full)
    config = make_config(
        [s for s in full.include if s != "judilibre"],
        sync=SyncConfig(),
    )
    judilibre = {i for i, d in index.docs.items() if d.metadata.source == "judilibre"}
    assert judilibre

    result, _ = sync_with(index, config, store)
    assert result.excluded == ["judilibre"]
    assert judilibre <= set(index.docs)

    result, _ = sync_with(index, config, store, prune_excluded=True)
    assert result.pruned == {"judilibre": len(judilibre)}
    assert not judilibre & set(index.docs)
    assert "judilibre" not in index.meta["sources"]


@pytest.mark.parametrize(
    ("meta_change", "message"),
    [
        ({"schema_version": "2.0.0"}, "schema 2.0.0"),
        ({"embedding_model_id": "other"}, "other"),
        ({"dim": 1024}, "1024"),
        ({"chunker_version": "0"}, "chunked by version 0"),
    ],
)
def test_incompatible_index_is_refused(
    store: LocalStore, config: Config, meta_change: dict, message: str
):
    index = build_index(store, config)
    assert index.meta["schema_version"] == SCHEMA_VERSION
    assert index.meta["chunker_version"] == CHUNKER_VERSION
    index.meta.update(meta_change)
    with pytest.raises(IngestionError, match=f"{message}.*run ingest index"):
        sync_with(index, config, store)


def test_index_without_meta_is_refused(store: LocalStore, config: Config):
    index = FakeIndex([], {})
    index.meta = None  # type: ignore[assignment]
    with pytest.raises(IngestionError, match="legacy"):
        sync_with(index, config, store)


def test_missing_index_is_refused(store: LocalStore, config: Config):
    index = build_index(store, config)
    index.alias_exists = lambda alias: False  # type: ignore[method-assign]
    with pytest.raises(IngestionError, match="run ingest index"):
        sync_with(index, config, store)
