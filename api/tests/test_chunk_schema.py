"""The api reads the chunks that ingestion/ writes, as published in its JSON schema
(ingestion/schema/chunk.v1.schema.json, with one example per source)."""

import json
from pathlib import Path

import jsonschema
import pytest

from srdt_analysis.clients.search_handler import SearchIndexHandler

SCHEMA_DIR = Path(__file__).parents[2] / "ingestion" / "schema"
SCHEMA = json.loads((SCHEMA_DIR / "chunk.v1.schema.json").read_text())
EXAMPLES = sorted((SCHEMA_DIR / "examples").glob("*.json"))


@pytest.fixture
def handler(monkeypatch) -> SearchIndexHandler:
    # the clients are only built, never called
    for name, value in {
        "SEARCH_CREDENTIALS": "user:password",  # pragma: allowlist secret
        "SEARCH_HOSTNAME": "http://localhost:9200",
        "ALBERT_API_KEY": "key",  # pragma: allowlist secret
        "ALBERT_ENDPOINT": "http://localhost:8000",
        "ALBERT_VECTORISATION_MODEL": "model",
    }.items():
        monkeypatch.setenv(name, value)
    return SearchIndexHandler()


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
