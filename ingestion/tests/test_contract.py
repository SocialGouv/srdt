import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel

from ingestion.cli import SCHEMA_FILE
from ingestion.contract import (
    Article,
    Chunk,
    ChunkDocument,
    ChunkMetadata,
    json_schema,
)
from ingestion.mapping import mappings

EXAMPLES = Path(__file__).parents[1] / "schema" / "examples"


def make_chunk(**metadata: Any) -> Chunk:
    return Chunk.model_validate(
        {
            "id": "KALIARTI1",
            "content": "Article 1\nTexte",
            "metadata": {
                "id": "KALIARTI1",
                "source": "conventions",
                "title": "Article 1",
                "url": "https://example.org/KALIARTI1",
                "idcc": "1486",
                "idx": 0,
                "initial_id": "KALIARTI1",
                "articles": [],
                **metadata,
            },
        }
    )


def test_chunk_id_includes_idcc():
    assert make_chunk().chunk_id == "conventions:1486:KALIARTI1:0"
    assert make_chunk(idcc=None, idx=2).chunk_id == "conventions:-:KALIARTI1:2"


def test_hashes():
    chunk = make_chunk()
    retitled = make_chunk(title="Autre titre")
    assert chunk.compute_doc_hash() == make_chunk().compute_doc_hash()
    assert chunk.compute_doc_hash() != retitled.compute_doc_hash()

    document = chunk.to_document("model-a", [0.0])
    assert document.embed_hash == retitled.to_document("model-a", [0.0]).embed_hash
    assert document.embed_hash != chunk.to_document("model-b", [0.0]).embed_hash


def test_stored_fields_keep_nulls_and_omit_unset_optionals():
    stored = make_chunk(idcc=None).stored_fields()
    assert stored["metadata"]["idcc"] is None
    assert "number" not in stored["metadata"]
    assert "legi_links" not in stored["metadata"]
    assert "number" in make_chunk(number=None).stored_fields()["metadata"]


def _fields(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)


@pytest.mark.parametrize("engine", ["opensearch", "elasticsearch"])
def test_mapping_declares_every_field(engine):
    properties = mappings(3, engine)["properties"]
    assert set(properties) == _fields(ChunkDocument)
    metadata = properties["metadata"]["properties"]
    assert set(metadata) == _fields(ChunkMetadata)
    assert set(metadata["articles"]["properties"]) == _fields(Article)


def test_committed_schema_is_up_to_date():
    assert json.loads(SCHEMA_FILE.read_text()) == json_schema()


def test_examples_match_the_schema():
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_FILE.read_text()))
    examples = sorted(EXAMPLES.glob("*.json"))
    assert examples
    for path in examples:
        validator.validate(json.loads(path.read_text()))
