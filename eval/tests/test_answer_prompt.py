import json
import shutil
import subprocess

import pytest
from conftest import ROOT

from answer_eval.prompt import (
    Chunk,
    ChunkMetadata,
    WebPrompts,
    format_chunks,
    messages,
    system_prompt,
)

SCRIPT = ROOT / "scripts" / "web_prompts.mjs"
TEMPLATES = ROOT / "generation" / "prompts" / "web-v2.0.json"
REPO = ROOT.parent

requires_web_ts = pytest.mark.skipif(
    shutil.which("node") is None or not (REPO / "web/node_modules/typescript").exists(),
    reason="node or web/node_modules/typescript not available",
)


def chunk(doc_id: str, content: str = "Texte.", source="fiches_service_public"):
    return Chunk(
        content=content,
        metadata=ChunkMetadata(
            id=doc_id,
            source=source,
            url=f"https://example.org/{doc_id}",
            title=f"Titre {doc_id}",
        ),
    )


CASES = [
    {  # no IDCC: general template, no convention block
        "text": "Question ?",
        "idcc": None,
        "idcc_name": None,
        "fiches": [chunk("a", "Contenu A\n\nsuite"), chunk("b")],
        "code": [chunk("c", "Article L1234-1", "code_du_travail")],
        "idcc_chunks": [],
    },
    {  # IDCC with convention extracts
        "text": "Question CC ?",
        "idcc": "1147",
        "idcc_name": "Convention collective du personnel des cabinets médicaux",
        "fiches": [chunk("a")],
        "code": [],
        "idcc_chunks": [chunk("k", "Stipulation", "conventions")],
    },
    {  # IDCC without any extract: no convention block (CAS 2 of the template)
        "text": "Question ?",
        "idcc": "0953",
        "idcc_name": "Charcuterie de détail",
        "fiches": [],
        "code": [],
        "idcc_chunks": [],
    },
]


def python_render(case: dict) -> str:
    return system_prompt(
        WebPrompts(TEMPLATES),
        idcc=case["idcc"],
        idcc_name=case["idcc_name"],
        fiches=case["fiches"],
        code=case["code"],
        idcc_chunks=case["idcc_chunks"],
    )


@requires_web_ts
def test_system_prompt_is_identical_to_the_web(tmp_path):
    """The exported templates and the Python builders give, byte for byte, what the
    current TypeScript sources give. A failure after a web prompt change means:
    re-export the templates (as a new file) and/or update prompt.py."""
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    **case,
                    **{
                        k: [c.model_dump() for c in case[k]]
                        for k in ("fiches", "code", "idcc_chunks")
                    },
                }
                for case in CASES
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(SCRIPT), "render", str(cases_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = json.loads(result.stdout)
    for case, web in zip(CASES, expected, strict=True):
        assert python_render(case) == web


def test_idcc_placeholders_are_all_replaced():
    system = python_render(CASES[1])
    assert "${IDCC" not in system and "[URL_convention_collective]" not in system
    assert "cabinets médicaux** (IDCC 1147)" in system
    assert "https://code.travail.gouv.fr/convention-collective/1147" in system
    assert "## Conventions collectives (1 à 5" in system
    assert "## Conventions collectives (1 à 5" not in python_render(CASES[2])
    assert "## Jurisprudence (0 à 5 extraits)" not in system


def test_format_chunks_and_messages():
    assert format_chunks([chunk("a", "X")]) == (
        "Source: fiches_service_public (https://example.org/a)\n"
        "Titre: Titre a\nContenu: X\n---"
    )
    assert messages("S", "Q ?") == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Q ?"},
    ]


def test_stale_sources(tmp_path):
    prompts = WebPrompts(TEMPLATES)
    assert set(prompts.sources) >= {
        "web/src/prompts/generate.ts",
        "web/src/prompts/shared.ts",
    }
    assert set(prompts.stale_sources(tmp_path)) == set(prompts.sources)
