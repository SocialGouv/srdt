import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from conftest import ROOT

from retrieval_eval.audit import SHEET_MAX_CHARS, AuditItem, import_sheet
from retrieval_eval.data import DocRecord, Query, text_sha256
from retrieval_eval.labelling_ui import (
    TEMPLATE,
    build_labelling_html,
    dataset_id,
    grade_names,
)

GUIDELINE = (ROOT / "retrieval/prompts/v1/guideline.fr.md").read_text(encoding="utf-8")


def world(n: int = 4, text: str = "Texte du document."):
    queries = {
        f"q{i}": Query(
            query_id=f"q{i}",
            text=f"Question {i} ?",
            source="prod",
            idcc="1979" if i == 0 else None,
            split="dev",
        )
        for i in range(n)
    }
    docs = {
        f"d{i}": DocRecord(
            doc_id=f"d{i}",
            title=f"Fiche {i}",
            url=f"https://example.org/{i}",
            source="information",
            text=f"{text} {i}",
            text_sha256=text_sha256(f"{text} {i}"),
        )
        for i in range(n)
    }
    items = [
        AuditItem(
            audit_id=f"a{i:04d}",
            query_id=f"q{i}",
            doc_id=f"d{i}",
            text_sha256=docs[f"d{i}"].text_sha256,
            in_production_top=bool(i % 2),
            llm_grade=2,  # must never reach the page
            stratum="consensus-relevant",  # nor the stratum or the weight
            weight=7.5,
        )
        for i in range(n)
    ]
    return items, queries, docs


def embedded_data(html: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="data">(.*?)</script>', html, re.S
    )
    assert match, "data block not found"
    return json.loads(match.group(1))


def test_the_page_embeds_the_pairs_and_nothing_a_model_or_the_pool_said():
    items, queries, docs = world()
    html, kept = build_labelling_html(items, queries, docs, GUIDELINE)
    data = embedded_data(html)

    assert len(kept) == 4 and len(data["items"]) == 4
    first = data["items"][0]
    assert first["query"] == "Question 0 ?" and first["idcc"] == "1979"
    assert first["text"] == "Texte du document. 0" and first["url"].endswith("/0")
    assert set(first) == {
        "audit_id", "query", "idcc", "title", "source", "url", "text", "chars"
    }  # fmt: skip
    # blind: neither the grade of a model nor where production ranked the document
    for leak in (
        "llm_grade",
        "in_production",
        "found_by",
        "hybrid",
        "knn",
        "stratum",
        "consensus",
        '"weight"',  # the data key (CSS has font-weight)
    ):
        assert leak not in html


def test_the_guideline_is_embedded_without_its_maintainer_comment():
    html, _ = build_labelling_html(*world(), GUIDELINE)
    data = embedded_data(html)
    assert "DRAFT" not in data["guideline"] and "<!--" not in data["guideline"]
    assert "Barème de pertinence" in data["guideline"]


def test_grade_buttons_are_named_after_the_real_guideline():
    assert grade_names(GUIDELINE) == {
        2: "répond directement",
        1: "utile mais partiel",
        0: "inutile",
    }
    assert grade_names("no grades here") == {}


def test_document_text_cannot_break_out_of_the_script_element():
    nasty = "</script><script>alert(1)</script> <!--   end"
    items, queries, docs = world(n=1, text=nasty)
    html, _ = build_labelling_html(items, queries, docs, GUIDELINE)

    assert html.count("</script>") == 3  # data, core, ui: none added by the text
    # a `<script` inside a script element only matters after `<!--`: none is left
    assert "<!--" not in html
    assert embedded_data(html)["items"][0]["text"] == f"{nasty} 0"


def test_stale_or_missing_documents_are_left_out():
    items, queries, docs = world()
    docs["d1"] = docs["d1"].model_copy(update={"text_sha256": "changed"})
    del docs["d2"]
    _, kept = build_labelling_html(items, queries, docs, GUIDELINE)
    assert [i.doc_id for i in kept] == ["d0", "d3"]

    with pytest.raises(ValueError, match="no pair"):
        build_labelling_html(items, queries, {}, GUIDELINE)


def test_text_beyond_the_sheet_limit_is_cut_like_the_sheet_and_says_so():
    items, queries, docs = world(n=1, text="x" * (SHEET_MAX_CHARS + 50))
    html, _ = build_labelling_html(items, queries, docs, GUIDELINE)
    row = embedded_data(html)["items"][0]
    assert row["chars"] == SHEET_MAX_CHARS + 50 + 2  # the real length is reported
    assert row["text"].startswith("x" * SHEET_MAX_CHARS)
    assert "tronqué" in row["text"] and len(row["text"]) < SHEET_MAX_CHARS + 100


def test_dataset_id_changes_with_the_sample_so_saved_labels_never_cross():
    items, _, _ = world()
    assert dataset_id(items) == dataset_id(list(items))
    assert dataset_id(items) != dataset_id(items[:3])
    assert dataset_id(items) != dataset_id(
        [AuditItem(**{**i.__dict__, "text_sha256": "other"}) for i in items]
    )


# --- the logic of the page, run with Node (no DOM) -------------------------------

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def core_js() -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    start = source.index("// --- core:start")
    end = source.index("// --- core:end")
    return source[start:end]


def run_node(script: str) -> str:
    program = core_js() + "\n" + textwrap.dedent(script)
    done = subprocess.run(
        [NODE, "-e", program], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


ITEMS_JS = "const items = [{audit_id:'a0001'},{audit_id:'a0002'},{audit_id:'a0003'}];"


@needs_node
def test_csv_round_trips_commas_quotes_newlines_and_accents():
    out = run_node(
        ITEMS_JS
        + """
        const comment = 'a, "b"\\nligne 2 é';
        const labels = {a0001: {grade: 2, comment, flag: true, seconds: 12.4, first: 1},
                        a0002: {grade: null, comment: '', flag: false, seconds: 0}};
        const csv = buildCsv(items, labels);
        const back = labelsFromCsv(csv, new Set(items.map(i => i.audit_id)));
        console.log(JSON.stringify({csv, back}));
        """
    )
    result = json.loads(out)
    assert result["csv"].splitlines()[0] == (
        "audit_id,grade,comment,flag,seconds,first_grade"
    )
    back = result["back"]
    assert back["applied"] == 1  # the untouched rows carry nothing to restore
    assert back["labels"]["a0001"] == {
        "grade": 2,
        "comment": 'a, "b"\nligne 2 é',
        "flag": True,
        "seconds": 12,
        "first": 1,  # the first grade survives the round trip
    }
    assert back["skipped"] == []


@needs_node
def test_loading_reports_unknown_ids_and_invalid_grades_without_applying_them():
    out = run_node(
        ITEMS_JS
        + """
        const csv = ['audit_id,grade,comment', 'a0001,1,ok', 'zzzz,2,', 'a0002,3,',
                     'a0003,,'].join('\\r\\n');
        const known = new Set(items.map(i => i.audit_id));
        console.log(JSON.stringify(labelsFromCsv(csv, known)));
        """
    )
    result = json.loads(out)
    assert list(result["labels"]) == ["a0001"]
    assert result["skipped"] == ["unknown id zzzz", "a0002: grade 3"]
    bad = json.loads(
        run_node("console.log(JSON.stringify(labelsFromCsv('x,y\\n1,2', new Set())))")
    )
    assert bad["applied"] == 0 and "audit_id" in bad["skipped"][0]


@needs_node
def test_progress_filter_and_time_estimate():
    out = run_node(
        """
        const items = Array.from({length: 10}, (_, i) => ({audit_id: 'a' + i}));
        const labels = {};
        for (let i = 0; i < 6; i++) {
          labels['a' + i] = {grade: i % 3, flag: i === 1, seconds: 120};
        }
        labels.a7 = {grade: null, comment: 'later', flag: true, seconds: 30};
        console.log(JSON.stringify({
          s: summarise(items, labels),
          todo: items.filter(i => matchesFilter('todo', labels[i.audit_id])).length,
          done: items.filter(i => matchesFilter('done', labels[i.audit_id])).length,
          flag: items.filter(i => matchesFilter('flag', labels[i.audit_id])).length,
          few: summarise(items.slice(0, 3), labels).perItem,
          d: [formatDuration(2400), formatDuration(5400), formatDuration(null)],
        }));
        """
    )
    r = json.loads(out)
    assert r["s"]["done"] == 6 and r["s"]["flagged"] == 2 and r["s"]["total"] == 10
    assert r["s"]["perItem"] == 120 and r["s"]["remaining"] == 4 * 120
    assert (r["todo"], r["done"], r["flag"]) == (4, 6, 2)
    assert r["few"] is None  # under 5 timed items: no estimate yet
    assert r["d"] == ["40 min", "1 h 30", ""]


@needs_node
def test_a_csv_exported_by_the_page_is_read_by_audit_import(tmp_path: Path):
    items, queries, docs = world(n=3)
    key = tmp_path / "key.json"
    key.write_text(
        json.dumps([i.__dict__ for i in items], ensure_ascii=False), encoding="utf-8"
    )
    out = run_node(
        """
        const items = [{audit_id:'a0000'},{audit_id:'a0001'},{audit_id:'a0002'}];
        const labels = {
          a0000: {grade: 2, comment: 'direct, "clair"', flag: false, seconds: 40},
          a0001: {grade: 0, comment: '', flag: true, seconds: 5},
        };
        process.stdout.write(buildCsv(items, labels));
        """
    )
    sheet = tmp_path / "labels.csv"
    sheet.write_text(out, encoding="utf-8", newline="")

    qrels, blank = import_sheet(sheet, key, "remi", "v1")

    assert [(q.doc_id, q.grade, q.rationale) for q in qrels] == [
        ("d0", 2, 'direct, "clair"'),
        ("d1", 0, None),
    ]
    assert blank == 1  # the third pair was not labelled
    assert qrels[0].text_sha256 == items[0].text_sha256


@needs_node
def test_the_page_scripts_parse():
    """A syntax error in the UI block would only show in a browser."""
    html, _ = build_labelling_html(*world(), GUIDELINE)
    for block in re.findall(r"<script id=\"(?:core|ui)\">(.*?)</script>", html, re.S):
        done = subprocess.run(
            [NODE, "--check", "-"],
            input=block,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr


@needs_node
def test_a_csv_from_before_first_grade_existed_takes_its_grade_as_the_first():
    out = run_node(
        ITEMS_JS
        + """
        const csv = 'audit_id,grade,comment,flag,seconds\\r\\na0001,2,,,9\\r\\n';
        console.log(JSON.stringify(labelsFromCsv(csv, new Set(['a0001'])).labels));
        """
    )
    assert json.loads(out)["a0001"]["first"] == 2


@needs_node
def test_quick_and_changed_pairs_can_be_found_again():
    out = run_node(
        """
        const items = ['a', 'b', 'c', 'd', 'e'].map(id => ({audit_id: id}));
        const labels = {
          a: {grade: 2, first: 2, seconds: 8},    // quick, unchanged
          b: {grade: 1, first: 2, seconds: 45},   // changed, slow
          c: {grade: 0, first: 1, seconds: 12},   // changed and quick
          d: {grade: null, first: null, seconds: 3},  // not graded: never "quick"
          e: {grade: 1, first: 1, seconds: 20},   // exactly the limit: not quick
        };
        const ids = (filter) => items
          .filter(i => matchesFilter(filter, labels[i.audit_id]))
          .map(i => i.audit_id);
        console.log(JSON.stringify({
          quick: ids('quick'), changed: ids('changed'), todo: ids('todo'),
          s: summarise(items, labels),
        }));
        """
    )
    r = json.loads(out)
    assert (
        r["quick"] == ["a", "c"] and r["changed"] == ["b", "c"] and r["todo"] == ["d"]
    )
    assert (r["s"]["quick"], r["s"]["changed"], r["s"]["done"]) == (2, 2, 4)
