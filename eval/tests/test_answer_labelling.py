import csv
import json
import shutil
import subprocess
import textwrap

import pytest
from conftest import ROOT

from answer_eval.contexts import Context
from answer_eval.generate import Answer
from answer_eval.labelling import (
    TEMPLATE,
    Key,
    LabelImportError,
    build_page,
    criterion_definitions,
    import_labels,
    judge_dataset,
    render_markdown,
    select_generators,
)
from answer_eval.prompt import Chunk, ChunkMetadata
from answer_eval.report import build_report
from judge_eval.data import load_dataset

CRITERIA = criterion_definitions(ROOT / "prompts" / "v1")
GENERATORS = ("mistral-large-secret", "glm-secret", "gpt-oss-secret")


def context(query_id: str, idcc: str | None = None) -> Context:
    fiche = Chunk(
        content="Texte de la fiche.",
        metadata=ChunkMetadata(
            id="f1", source="fiches_service_public", url="https://ex.org/f1", title="F"
        ),
        grade=2,
    )
    return Context(
        query_id=query_id,
        text=f"Question {query_id} ?",
        idcc=idcc,
        idcc_name="CC" if idcc else None,
        fiches=[fiche],
        code=[],
        idcc_chunks=[],
    )


def answer(generator: str, query_id: str, text: str | None = None) -> Answer:
    return Answer(
        generator=generator,
        query_id=query_id,
        status="ok",
        answer=text or f"### Réponse\n\nTexte n° {len(generator)} pour {query_id}.",
        prompt_sha256="s",
    )


def world():
    contexts = [context("q1", idcc="1147"), context("q2")]
    answers = [answer(g, q.query_id) for q in contexts for g in GENERATORS]
    return contexts, answers


def page_data(html: str) -> dict:
    start = html.index('<script type="application/json" id="data">') + len(
        '<script type="application/json" id="data">'
    )
    return json.loads(html[start : html.index("</script>", start)])


def test_page_is_blind_and_shuffled_per_question_from_the_seed():
    contexts, answers = world()
    html, key, warnings = build_page("run", contexts, answers, CRITERIA, seed=3)
    assert warnings == []
    for generator in GENERATORS:
        assert generator.split("-secret")[0] + "-secret" not in html
    assert "item_id" not in html and "::" not in html

    data = page_data(html)
    assert [q["number"] for q in data["questions"]] == [1, 2]
    assert [a["label_id"] for a in data["questions"][0]["answers"]] == [
        "01-A",
        "01-B",
        "01-C",
    ]
    assert data["questions"][0]["idcc_name"] == "CC"
    assert [c["key"] for c in data["criteria"]] == [
        "correct_en_droit",
        "suffisant",
        "intelligible",
    ]
    assert "DRAFT" not in data["criteria"][0]["definition"]  # maintainer note
    assert data["questions"][0]["sources"][0]["items"][0]["title"] == "F"

    # the key unblinds, and the same seed gives the same order
    order = [i.generator for i in key.items]
    assert sorted(order[:3]) == sorted(GENERATORS)
    again = build_page("run", contexts, answers, CRITERIA, seed=3)[1]
    assert [i.generator for i in again.items] == order
    orders = {
        tuple(
            i.generator
            for i in build_page("r", contexts, answers, CRITERIA, seed=s)[1].items[:3]
        )
        for s in range(12)
    }
    assert len(orders) > 1  # the seed matters


def test_model_markup_is_escaped():
    text = "Bonjour <script>alert(1)</script> [lien](javascript:alert(1)) <b>gras</b>"
    rendered = render_markdown(text)
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "<b>" not in rendered
    assert 'href="javascript' not in rendered
    assert "<table>" in render_markdown("| a | b |\n|---|---|\n| 1 | 2 |")

    contexts, _ = world()
    html, _, _ = build_page(
        "run", contexts[:1], [answer("m", "q1", text)], CRITERIA, seed=0
    )
    # only the template's own scripts (data, vault, core, ui)
    assert html.count("<script") == 4


def test_missing_answers_are_reported():
    contexts, answers = world()
    _, key, warnings = build_page("run", contexts, answers[:-1], CRITERIA)
    assert warnings == ["q2: 2 answer(s) of 3 models"]
    assert len(key.items) == 5


OLD_COLUMNS = [
    "label_id",
    "correct_en_droit",
    "suffisant",
    "intelligible",
    "comment",
    "flag",
    "seconds",
]
COLUMNS = [*OLD_COLUMNS[:4], "sources_suffisantes", *OLD_COLUMNS[4:]]


def write_csv(path, rows, columns=COLUMNS):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def full(label_id, value="Oui", **extra):
    return {
        "label_id": label_id,
        "correct_en_droit": value,
        "suffisant": value,
        "intelligible": "Oui",
        **extra,
    }


def test_import_round_trip_and_judge_dataset(tmp_path):
    contexts, answers = world()
    _, key, _ = build_page("run", contexts, answers, CRITERIA, seed=1)
    sheet = tmp_path / "labels.csv"
    write_csv(
        sheet,
        [
            full("01-A", comment="cite, « mal »", flag="1", seconds="42"),
            full("01-B", "Non"),
            {"label_id": "01-C", "correct_en_droit": "Oui"},  # incomplete
            {"label_id": "02-A"},  # untouched
            {"label_id": "01-Q", "sources_suffisantes": "Non", "comment": "CC absente"},
            {"label_id": "02-Q", "comment": "à voir"},  # incomplete
        ],
    )
    labels, questions, incomplete = import_labels(sheet, key, answers, "remi")
    assert incomplete == ["01-C", "02-Q"]
    assert [(q.query_id, q.sources_suffisantes, q.comment) for q in questions] == [
        ("q1", False, "CC absente")
    ]
    by_label = {i.label_id: i for i in key.items}
    first = next(h for h in labels if h.item_id == by_label["01-A"].item_id)
    assert first.labels == {
        "correct_en_droit": True,
        "suffisant": True,
        "intelligible": True,
    }
    assert (first.comment, first.flag, first.seconds) == ("cite, « mal »", True, 42)
    assert first.generator == by_label["01-A"].generator

    rows = judge_dataset(labels, answers, contexts)
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    items = load_dataset(path)  # what judge-eval reads
    assert len(items) == 2 and items[0].question == "Question q1 ?"

    summary, side_by_side, per_answer = build_report(
        "run", contexts, answers, [], {"remi": {h.item_id: h for h in labels}}
    )
    assert "## Human remi" in summary
    assert "sources sufficient" not in summary  # no question label given
    assert "remi: correct Oui, suffisant Oui, intelligible Oui — « cite, « mal » »" in (
        side_by_side
    )
    assert any(r["human:remi:correct_en_droit"] is False for r in per_answer)


def test_import_refuses_unknown_ids_bad_values_and_changed_answers(tmp_path):
    contexts, answers = world()
    _, key, _ = build_page("run", contexts, answers, CRITERIA)
    sheet = tmp_path / "labels.csv"

    write_csv(sheet, [full("09-Z")])
    with pytest.raises(LabelImportError, match="unknown"):
        import_labels(sheet, key, answers, "remi")

    write_csv(sheet, [full("01-A", "oui")])
    with pytest.raises(LabelImportError, match="not one of"):
        import_labels(sheet, key, answers, "remi")

    write_csv(sheet, [full("01-A")])
    changed = [a.model_copy(update={"answer": "autre texte"}) for a in answers]
    with pytest.raises(LabelImportError, match="changed"):
        import_labels(sheet, key, changed, "remi")


NODE = shutil.which("node")


def run_node(script: str) -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    core = source[source.index("// --- core:start") : source.index("// --- core:end")]
    done = subprocess.run(
        [NODE, "-e", core + "\n" + textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_csv_round_trip_and_states():
    out = run_node(
        """
        const criteria = ['correct_en_droit', 'suffisant', 'intelligible'];
        const ids = ['01-A', '01-B', '02-A'];
        const labels = {
          '01-A': {values: {correct_en_droit: 'Oui', suffisant: 'Non',
                            intelligible: 'Oui'},
                   comment: 'a, "b"\\nc é', flag: true, seconds: 31.6},
          '01-B': {values: {suffisant: 'Oui'}, comment: '', flag: false, seconds: 3},
        };
        const csv = buildCsv(ids, labels, criteria);
        const back = labelsFromCsv(csv, new Set(ids), criteria, ['Oui', 'Non']);
        const bad = labelsFromCsv(
          'label_id,correct_en_droit,suffisant,intelligible\\n01-A,oui,,\\nzz,Oui,,\\n',
          new Set(ids), criteria, ['Oui', 'Non']);
        console.log(JSON.stringify({
          header: csv.split('\\r\\n')[0], back, bad,
          q1: questionState(['01-A', '01-B'], labels, criteria),
          q2: questionState(['02-A'], labels, criteria),
          sum: summarise(ids, labels, criteria),
        }));
        """
    )
    r = json.loads(out)
    assert r["header"] == ",".join(COLUMNS)
    assert r["back"]["applied"] == 2
    assert r["back"]["labels"]["01-A"] == {
        "values": {
            "correct_en_droit": "Oui",
            "suffisant": "Non",
            "intelligible": "Oui",
        },
        "comment": 'a, "b"\nc é',
        "flag": True,
        "seconds": 32,
    }
    assert r["bad"]["applied"] == 0 and len(r["bad"]["skipped"]) == 2
    assert r["q1"] == {"complete": 1, "state": "part"}
    assert r["q2"] == {"complete": 0, "state": ""}
    assert r["sum"]["done"] == 1 and r["sum"]["flagged"] == 1


def test_question_label_ids_in_page_and_key():
    contexts, answers = world()
    html, key, _ = build_page("run", contexts, answers, CRITERIA, seed=3)
    data = page_data(html)
    assert [q["label_id"] for q in data["questions"]] == ["01-Q", "02-Q"]
    assert [(q.label_id, q.query_id) for q in key.questions] == [
        ("01-Q", "q1"),
        ("02-Q", "q2"),
    ]
    # a key written before the question label rebuilds the mapping from its items
    old = Key.model_validate(key.model_dump(exclude={"questions"}))
    assert old.questions == []
    assert old.question_ids() == {"01-Q": "q1", "02-Q": "q2"}


def test_import_old_csv_and_old_key(tmp_path):
    contexts, answers = world()
    _, key, _ = build_page("run", contexts, answers, CRITERIA, seed=1)
    old_key = Key.model_validate(key.model_dump(exclude={"questions"}))
    sheet = tmp_path / "old.csv"
    write_csv(sheet, [full("01-A"), full("02-B", "Non")], columns=OLD_COLUMNS)
    labels, questions, incomplete = import_labels(sheet, old_key, answers, "remi")
    assert len(labels) == 2 and questions == [] and incomplete == []

    write_csv(sheet, [full("01-A"), {"label_id": "02-Q", "sources_suffisantes": "Oui"}])
    _, questions, _ = import_labels(sheet, old_key, answers, "remi")
    assert [(q.query_id, q.sources_suffisantes) for q in questions] == [("q2", True)]

    write_csv(sheet, [{"label_id": "01-Q", "sources_suffisantes": "oui"}])
    with pytest.raises(LabelImportError, match="sources_suffisantes"):
        import_labels(sheet, key, answers, "remi")


def test_report_sources_section(tmp_path):
    contexts, answers = world()  # q1 has an IDCC, q2 none
    cc = "Je ne dispose pas d'information spécifique sur votre convention collective."
    answers = [
        a.model_copy(update={"answer": cc})
        if (a.generator, a.query_id) == (GENERATORS[0], "q1")
        else a
        for a in answers
    ]
    _, key, _ = build_page("run", contexts, answers, CRITERIA, seed=1)
    sheet = tmp_path / "labels.csv"
    write_csv(
        sheet,
        [
            {"label_id": "01-Q", "sources_suffisantes": "Non", "comment": "pas la CC"},
            {"label_id": "02-Q", "sources_suffisantes": "Oui"},
        ],
    )
    _, questions, _ = import_labels(sheet, key, answers, "remi")
    summary, side_by_side, rows = build_report(
        "run", contexts, answers, [], None, {"remi": {q.query_id: q for q in questions}}
    )
    assert "| remi | 50% (2) |" in summary
    # CC refusals only on IDCC questions: q1, judged « Non »
    assert f"| {GENERATORS[0]} | - | 1/1 | 0/1 | 0/1 |" in summary
    assert f"| {GENERATORS[1]} | - | 0/1 | 0/1 | 0/1 |" in summary
    assert "- sources suffisantes (remi): Non — « pas la CC »" in side_by_side
    assert {r["human:remi:sources_suffisantes"] for r in rows} == {True, False}


def test_select_generators():
    _, answers = world()
    extra = answer("glm-secret+32k", "q1")
    kept, left_out = select_generators(
        [*answers, extra], {"mistral-large-secret", "glm-secret", "absent"}
    )
    assert {a.base for a in kept} == {"mistral-large-secret", "glm-secret"}
    assert extra in kept  # a variant counts for its model
    assert left_out == ["gpt-oss-secret"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_page_question_labels_in_csv_progress_and_navigation():
    out = run_node(
        """
        const criteria = ['correct_en_droit', 'suffisant', 'intelligible'];
        const all = {correct_en_droit: 'Oui', suffisant: 'Oui', intelligible: 'Non'};
        const ids = ['01-A', '01-B', '01-Q', '02-A', '02-Q'];
        const labels = {
          '01-A': {values: all, comment: '', flag: false, seconds: 10},
          '01-B': {values: all, comment: '', flag: false, seconds: 10},
          '01-Q': {values: {sources_suffisantes: 'Non'},
                   comment: 'pas la CC, "art. 4"'},
          '02-Q': {values: {}, comment: 'à voir'},
        };
        const csv = buildCsv(ids, labels, criteria);
        const back = labelsFromCsv(csv, new Set(ids), criteria, ['Oui', 'Non']);
        // a CSV of the page before the sources label
        const old = labelsFromCsv(
          'label_id,correct_en_droit,suffisant,intelligible,comment,flag,seconds\\n'
          + '01-A,Oui,Oui,Non,,,12\\n', new Set(ids), criteria, ['Oui', 'Non']);
        const units = [
          {pos: 0, id: '01-A'}, {pos: 1, id: '01-B'},
          {pos: 1, id: '01-Q', sources: true},
          {pos: 2, id: '02-A'}, {pos: 2, id: '02-Q', sources: true},
        ];
        const partial = {...labels, '01-Q': {values: {}}};
        console.log(JSON.stringify({
          rows: csv.split('\\r\\n'), back, old,
          q1: questionState(['01-A', '01-B', '01-Q'], labels, criteria),
          q1partial: questionState(['01-A', '01-B', '01-Q'], partial, criteria),
          sum: summarise(ids, labels, criteria),
          next: nextTodo(units, partial, criteria, 1),
          nextAfterQ1: nextTodo(units, labels, criteria, 1),
          none: nextTodo(units.slice(0, 3), labels, criteria, 0),
        }));
        """
    )
    r = json.loads(out)
    assert r["rows"][3] == '01-Q,,,,Non,"pas la CC, ""art. 4""",,'
    assert r["rows"][1] == "01-A,Oui,Oui,Non,,,,10"
    assert r["back"]["labels"]["01-Q"] == {
        "values": {"sources_suffisantes": "Non"},
        "comment": 'pas la CC, "art. 4"',
        "flag": False,
        "seconds": 0,
    }
    assert r["back"]["labels"]["02-Q"]["values"] == {}  # comment only: kept
    assert r["old"]["applied"] == 1 and r["old"]["labels"]["01-A"]["seconds"] == 12
    assert r["q1"] == {"complete": 3, "state": "full"}
    assert r["q1partial"] == {"complete": 2, "state": "part"}
    s = r["sum"]
    assert (s["done"], s["total"]) == (3, 5)
    assert (s["answersDone"], s["answers"]) == (2, 3)
    assert (s["questionsDone"], s["questions"]) == (1, 2)
    assert r["next"] == 2  # the sources label of question 1, before question 2
    assert r["nextAfterQ1"] == 3
    assert r["none"] is None
