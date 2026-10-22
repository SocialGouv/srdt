import csv
import json
from collections import Counter

import pytest

from retrieval_eval.audit import (
    CONTINUATION_COLUMNS,
    MAX_CELL_CHARS,
    SHEET_FIELDS,
    SHEET_MAX_CHARS,
    AuditError,
    _allocate_equal,
    export_sheet,
    import_sheet,
    sample_audit,
    split_document,
)
from retrieval_eval.data import DocRecord, Qrel, Query, Ranking, text_sha256


def qrel(qid: str, doc: str, grade: int, text: str = "t") -> Qrel:
    return Qrel(
        query_id=qid,
        doc_id=doc,
        grade=grade,
        labeller="llm:m",
        prompt_version="v1",
        text_sha256=text_sha256(text),
        rationale="le modèle explique",
    )


def many_qrels(n_queries: int = 30, per_query: int = 12) -> list[Qrel]:
    return [
        qrel(f"q{i}", f"d{j}", (i + j) % 3)
        for i in range(n_queries)
        for j in range(per_query)
    ]


def production_rankings(n_queries: int = 30) -> list[Ranking]:
    return [
        Ranking(
            query_id=f"q{i}",
            variant="hybrid+rerank",
            doc_ids=[f"d{j}" for j in range(12)],
            scores=[None] * 12,
        )
        for i in range(n_queries)
    ]


def test_allocate_equal_redistributes_what_small_cells_cannot_give():
    quota = _allocate_equal({("a",): 2, ("b",): 50, ("c",): 50}, 30)
    assert quota == {("a",): 2, ("b",): 14, ("c",): 14}
    assert _allocate_equal({("a",): 3}, 10) == {("a",): 3}


def test_sample_is_stratified_capped_per_query_and_reproducible():
    qrels, rankings = many_qrels(), production_rankings()
    items = sample_audit(qrels, rankings, n=60, seed=1, per_query_cap=3)

    assert len(items) == 60
    assert max(Counter(i.query_id for i in items).values()) <= 3
    cells = Counter((i.llm_grade, i.in_production_top) for i in items)
    # equal share is 10 per cell; the cap may shift a few picks, but no cell is starved
    # (capping before stratifying left the "not in production top" cells at 2-8)
    assert len(cells) == 6 and min(cells.values()) >= 8
    assert items == sample_audit(qrels, rankings, n=60, seed=1, per_query_cap=3)
    assert items != sample_audit(qrels, rankings, n=60, seed=2, per_query_cap=3)
    assert len({i.audit_id for i in items}) == 60


def test_sample_flags_production_top_k_membership():
    qrels = [qrel("q", f"d{j}", 1) for j in range(12)]
    ranking = [
        Ranking(
            query_id="q",
            variant="hybrid+rerank",
            doc_ids=[f"d{j}" for j in range(12)],
            scores=[None] * 12,
        )
    ]
    items = sample_audit(qrels, ranking, n=12, seed=0, per_query_cap=12)
    top = {i.doc_id for i in items if i.in_production_top}
    assert top == {f"d{j}" for j in range(10)}  # K_RERANK


def test_sample_can_be_limited_to_some_queries():
    items = sample_audit(
        many_qrels(), production_rankings(), n=50, seed=0, query_ids={"q1", "q2"}
    )
    assert {i.query_id for i in items} <= {"q1", "q2"}
    assert len(items) <= 6  # cap of 3 per query


def make_world(tmp_path):
    items = sample_audit(many_qrels(3, 4), production_rankings(3), n=6, seed=0)
    queries = {
        f"q{i}": Query(
            query_id=f"q{i}",
            text=f"question {i}",
            source="prod",
            idcc="1979",
            split="dev",
        )
        for i in range(3)
    }
    docs = {
        f"d{j}": DocRecord(
            doc_id=f"d{j}",
            title=f"Fiche {j}",
            url=f"https://x/{j}",
            source="information",
            text="t",
            text_sha256=text_sha256("t"),
        )
        for j in range(4)
    }
    sheet, key = tmp_path / "sheet.csv", tmp_path / "key.json"
    return items, queries, docs, sheet, key


def test_the_sheet_is_blind_and_the_key_holds_the_llm_grades(tmp_path):
    items, queries, docs, sheet, key = make_world(tmp_path)
    assert export_sheet(items, queries, docs, sheet, key) == len(items)

    content = sheet.read_text(encoding="utf-8")
    assert "le modèle explique" not in content
    rows = list(csv.DictReader(content.splitlines(keepends=True)))
    assert list(rows[0]) == SHEET_FIELDS
    assert all(r["grade"] == "" for r in rows)
    assert rows[0]["idcc"] == "1979" and rows[0]["document"] == "t"
    assert {k["audit_id"] for k in json.loads(key.read_text())} == {
        r["audit_id"] for r in rows
    }
    assert "llm_grade" in key.read_text() and "llm_grade" not in content


def test_pairs_without_a_matching_snapshot_are_left_out(tmp_path):
    items, queries, docs, sheet, key = make_world(tmp_path)
    docs["d0"] = docs["d0"].model_copy(update={"text_sha256": "changed"})
    written = export_sheet(items, queries, docs, sheet, key)
    assert written == len([i for i in items if i.doc_id != "d0"])


def fill(sheet, grades):
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    for row, grade in zip(rows, grades, strict=False):
        row["grade"] = grade
    with sheet.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def test_import_turns_filled_rows_into_human_qrels_and_counts_blanks(tmp_path):
    items, queries, docs, sheet, key = make_world(tmp_path)
    export_sheet(items, queries, docs, sheet, key)
    rows = fill(sheet, ["2", " 1 ", "0", "", "2"])

    qrels, blank = import_sheet(sheet, key, "remi", "v1")

    assert len(qrels) == 4 and blank == len(rows) - 4
    first = qrels[0]
    assert first.labeller == "human:remi" and first.grade == 2
    assert (first.query_id, first.doc_id) == (items[0].query_id, items[0].doc_id)
    assert first.text_sha256 == items[0].text_sha256
    assert first.prompt_version == "v1"


@pytest.mark.parametrize("bad", ["3", "oui", "1.5", "-1"])
def test_import_rejects_grades_outside_0_1_2(tmp_path, bad):
    items, queries, docs, sheet, key = make_world(tmp_path)
    export_sheet(items, queries, docs, sheet, key)
    fill(sheet, [bad])
    with pytest.raises(AuditError, match="not one of"):
        import_sheet(sheet, key, "remi", "v1")


def test_import_rejects_an_unknown_audit_id(tmp_path):
    items, queries, docs, sheet, key = make_world(tmp_path)
    export_sheet(items, queries, docs, sheet, key)
    rows = fill(sheet, ["1"])
    rows[0]["audit_id"] = "a9999"
    with sheet.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(AuditError, match="unknown"):
        import_sheet(sheet, key, "remi", "v1")


# --- long documents ----------------------------------------------------------


def _rebuild(parts: dict[str, str]) -> str:
    """The text back from the columns, markers removed."""
    import re

    marker = re.compile(r"\n\[… (suite dans la colonne \w+|document tronqué[^\]]*)\]$")
    return "".join(
        marker.sub("", parts[c]) for c in ("document", *CONTINUATION_COLUMNS)
    )


@pytest.mark.parametrize(
    "size, filled",
    [
        (0, 0),
        (10, 1),
        (MAX_CELL_CHARS, 1),  # exactly one cell: no pointer to a next, empty column
        (MAX_CELL_CHARS + 1, 2),
        (75_000, 3),
        (SHEET_MAX_CHARS, 4),
    ],
)
def test_split_document_loses_nothing_up_to_the_sheet_limit(size, filled):
    text = "".join(chr(97 + i % 26) for i in range(size))
    parts = split_document(text)

    assert _rebuild(parts) == text
    assert sum(bool(v) for v in parts.values()) == filled
    assert all(len(v) <= 32_767 for v in parts.values())  # fits a spreadsheet cell
    assert "tronqué" not in "".join(parts.values())


def test_split_document_points_to_the_next_column_and_says_when_it_cuts():
    parts = split_document("x" * 70_000)
    assert parts["document"].endswith("[… suite dans la colonne document_2]")
    assert parts["document_2"].endswith("[… suite dans la colonne document_3]")
    assert "suite" not in parts["document_3"] and parts["document_4"] == ""

    huge = split_document("y" * (SHEET_MAX_CHARS + 5))
    assert huge["document_4"].endswith("[… document tronqué dans cette feuille]")
    assert _rebuild(huge) == "y" * SHEET_MAX_CHARS


def test_sheet_columns_put_grade_before_the_continuations():
    assert SHEET_FIELDS.index("grade") < SHEET_FIELDS.index("document_2")
    assert SHEET_FIELDS[-3:] == list(CONTINUATION_COLUMNS)
