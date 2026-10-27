"""The api reads the chunks that ingestion/ writes, as published in its JSON schema
(ingestion/schema/chunk.v1.schema.json, with one example per source)."""

import json
from pathlib import Path

import jsonschema
import pytest

from srdt_analysis.clients.search_handler import SearchIndexHandler
from srdt_analysis.core.settings import get_settings

SCHEMA_DIR = Path(__file__).parents[2] / "ingestion" / "schema"
SCHEMA = json.loads((SCHEMA_DIR / "chunk.v1.schema.json").read_text())
EXAMPLES = sorted((SCHEMA_DIR / "examples").glob("*.json"))


@pytest.fixture
def handler() -> SearchIndexHandler:
    # the clients are only built, never called
    return SearchIndexHandler()


def test_handler_uses_the_configured_index(monkeypatch, handler):
    assert handler.index == "chunks"
    monkeypatch.setenv("SEARCH_INDEX", "chunks-v2")
    get_settings.cache_clear()
    assert SearchIndexHandler().index == "chunks-v2"


def test_every_source_has_an_example():
    assert len(EXAMPLES) == 8


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_chunk_results_from_published_chunks(handler, path: Path):
    document = json.loads(path.read_text())
    jsonschema.Draft202012Validator(SCHEMA).validate(document)

    result = handler.to_chunk_result(
        {"_id": "chunk-id", "_score": 0.5, "_source": document}
    )
    metadata = document["metadata"]
    assert result.id_chunk == "chunk-id"
    assert result.content == document["content"]
    assert (result.metadata.id, result.metadata.source, result.metadata.idcc) == (
        metadata["id"],
        metadata["source"],
        metadata["idcc"],
    )
