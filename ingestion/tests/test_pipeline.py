import json
from pathlib import Path

import pytest

from ingestion.contract import SCHEMA_VERSION, Chunk
from ingestion.pipeline import (
    IngestionError,
    Inputs,
    check_unique_ids,
    run,
)
from ingestion.snapshots.store import LocalStore
from tests.conftest import FakeEmbedder, FakeWriter, make_config, make_inputs


def _run(inputs: Inputs, writer: FakeWriter, **kwargs):
    embedder = FakeEmbedder()
    result = run(
        inputs.config,
        inputs,
        writer_factory=lambda: writer,
        embedder_factory=lambda: embedder,
        **kwargs,
    )
    return result, embedder


def test_dry_run_dumps_without_writing(inputs: Inputs, tmp_path: Path):
    def no_writer():
        raise AssertionError("dry run must not write")

    result = run(
        inputs.config,
        inputs,
        dry_run=True,
        dump=tmp_path,
        writer_factory=no_writer,
        embedder_factory=no_writer,
    )
    assert result.counts["conventions"] == 4
    lines = (tmp_path / "conventions.jsonl").read_text().splitlines()
    assert lines == sorted(lines)
    assert json.loads(lines[0]).keys() == {"content", "id", "metadata"}


def test_full_run(inputs: Inputs):
    writer = FakeWriter()
    result, embedder = _run(inputs, writer)

    assert writer.published == ("chunks", "chunks-test")
    assert result.index == "chunks-test"
    assert len(writer.documents) == sum(result.counts.values())
    assert len({d.chunk_id for d in writer.documents}) == len(writer.documents)
    document = writer.documents[0]
    assert document.embedding == [float(len(document.content)), 0.0, 1.0]

    meta = writer.meta or {}
    assert meta["schema_version"] == SCHEMA_VERSION
    assert (meta["embedding_model_id"], meta["dim"]) == ("test-model", 3)
    assert meta["sources"]["conventions"]["snapshots"] == {"kali": "3.514.0"}
    assert meta["sources"]["contributions"]["snapshots"] == {"legi": "2.575.0"}
    assert meta["sources"]["contributions"]["postgres_read_at"]


def test_snapshot_pin(store: LocalStore, tmp_path: Path):
    config = make_config(["judilibre"])
    config.snapshots["judilibre"] = "19990101"
    with pytest.raises(RuntimeError, match="judilibre/19990101 not found"):
        run(config, make_inputs(store, config), dry_run=True)


def test_only_must_be_in_the_include_list(store: LocalStore):
    config = make_config(["judilibre"])
    with pytest.raises(IngestionError, match="conventions"):
        run(config, make_inputs(store, config), only=["conventions"], dry_run=True)


def test_partial_run_on_a_legacy_index_is_refused(store: LocalStore):
    config = make_config(["judilibre"])
    with pytest.raises(IngestionError, match="legacy"):
        _run(make_inputs(store, config), FakeWriter(current=None, exists=True))


def test_partial_run_on_another_model_is_refused(store: LocalStore):
    config = make_config(["judilibre"])
    current = {"schema_version": SCHEMA_VERSION, "embedding_model_id": "other"}
    with pytest.raises(IngestionError, match="other"):
        _run(make_inputs(store, config), FakeWriter(current=current, exists=True))


def test_partial_run_copies_the_other_sources(store: LocalStore):
    config = make_config(["judilibre"])
    current = {
        "schema_version": SCHEMA_VERSION,
        "embedding_model_id": "test-model",
        "dim": 3,
        "sources": {
            "conventions": {"snapshots": {"kali": "3.400.0"}},
            "judilibre": {"snapshots": {"judilibre": "20260101"}},
        },
    }
    writer = FakeWriter(current=current, exists=True)
    _run(make_inputs(store, config), writer)
    assert writer.copied_excluding == ["judilibre"]
    assert (writer.meta or {})["sources"] == {
        "conventions": {"snapshots": {"kali": "3.400.0"}},
        "judilibre": {"snapshots": {"judilibre": "20261023"}},
    }


def test_duplicate_chunk_ids_are_refused(inputs: Inputs):
    chunk = Chunk.model_validate(
        {
            "id": "x",
            "content": "x",
            "metadata": {
                "id": "x",
                "source": "information",
                "title": "x",
                "url": "x",
                "idcc": None,
                "idx": 0,
                "initial_id": None,
                "articles": None,
            },
        }
    )
    with pytest.raises(IngestionError, match="duplicate"):
        check_unique_ids("information", [chunk, chunk])
