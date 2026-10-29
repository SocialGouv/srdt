import json
import os

import pytest

from ingestion.contract import SOURCES
from ingestion.pipeline import Inputs, chunk_source
from tests.test_contract import EXAMPLES

# UPDATE_EXAMPLES=1 pytest tests/test_sources.py rewrites schema/examples/
UPDATE = os.environ.get("UPDATE_EXAMPLES") == "1"


@pytest.mark.parametrize("source", SOURCES)
def test_examples(inputs: Inputs, source):
    """The published examples are the first chunk of each source on the fixtures."""
    chunk = chunk_source(source, inputs)[0]
    document = chunk.to_document("bge-m3", [0.1, 0.2, 0.3])
    generated = json.dumps(
        document.model_dump(mode="json", exclude_unset=True),
        indent=2,
        ensure_ascii=False,
    )
    path = EXAMPLES / f"{source}.json"
    if UPDATE:
        path.parent.mkdir(exist_ok=True)
        path.write_text(generated + "\n")
    assert path.read_text() == generated + "\n"


def test_code_du_travail(inputs: Inputs):
    (chunk,) = chunk_source("code_du_travail", inputs)
    assert chunk.metadata.id == "LEGISCTA000000000002"
    assert chunk.metadata.title == (
        "Code du travail Partie législative Chapitre Ier : Champ d'application"
    )
    assert [a.num for a in chunk.metadata.articles or []] == ["L1111-1", "L1111-2"]
    assert chunk.content.startswith("Article L1111-1 \n Les dispositions")


def test_cdtn_links_resolve_to_the_code_du_travail_chunk(inputs: Inputs):
    (contribution,) = chunk_source("contributions", inputs)
    links = contribution.metadata.legi_links or []
    # structured reference and old article version: one article, deduplicated
    assert [(link.cid, link.chunk_id) for link in links] == [
        ("LEGIARTI000000000010", "LEGISCTA000000000002")
    ]
    assert contribution.metadata.url == (
        "https://code.travail.gouv.fr/contribution/la-periode-d'essai"
    )

    (fiche,) = chunk_source("page_fiche_ministere_travail", inputs)
    (outside,) = fiche.metadata.legi_links or []
    assert outside.kind is None and outside.chunk_id is None


def test_conventions(inputs: Inputs):
    chunks = chunk_source("conventions", inputs)
    # empty article and "Textes Salaires" left out, attached text under both CCs
    assert len(chunks) == 4
    assert {c.metadata.idcc for c in chunks} == {"1486", "1501"}
    shared = [c for c in chunks if c.metadata.id == "KALIARTI000000000003"]
    assert len({c.chunk_id for c in shared}) == 2
    assert shared[0].content.startswith(
        "Textes Attachés > Avenant n° 1 du 3 mars 2020 — Article 1\n"
    )


def test_judilibre(inputs: Inputs):
    chunks = chunk_source("judilibre", inputs)
    # the summary-less entry is skipped
    assert [c.metadata.id for c in chunks] == [
        "65a7c1f2d4e5f60718293a4b-0",
        "65e8a0b1c2d3e4f506172839-0",
    ]
    assert chunks[0].metadata.title == "CONTRAT DE TRAVAIL, EXECUTION,Salaire"
    assert chunks[1].metadata.title == "23-10.001"
    assert chunks[1].metadata.decision_date == "2024-03-06"
