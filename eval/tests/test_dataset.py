"""The labeller error profile, `report --human --key`, and the dataset export."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import (
    cohen_kappa_score,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
)
from test_retrieval_cli import cli, world  # noqa: F401  (a pytest fixture)
from test_screening import weighted_world

from retrieval_eval.data import load_qrels
from retrieval_eval.jsonl import append_jsonl
from retrieval_eval.labeller import LabelPromptBook
from retrieval_eval.report import labeller_profile, render_profile

PROMPTS = Path(__file__).resolve().parents[1] / "retrieval" / "prompts"
PROMPT_SHA = LabelPromptBook(PROMPTS, "v1", 120000).sha256


def value(profile, section: str, measure: str) -> float:
    t = profile.table
    return float(
        t[(t["section"] == section) & (t["measure"] == measure)]["value"].iloc[0]
    )


# --- profile ------------------------------------------------------------------


def test_graded_part_matches_scikit_learn_with_the_weights():
    keys, grades, weights, human, models = weighted_world()
    profile = labeller_profile(human, models["llm:noisy"], weights, n_boot=200, seed=0)
    y_h = [grades[k] for k in keys]
    y_m = [q.grade for q in models["llm:noisy"]]
    w = [weights[k] for k in keys]

    assert profile.weighted and profile.n_pairs == len(keys)
    assert value(profile, "graded", "kappa (quadratic weights)") == pytest.approx(
        cohen_kappa_score(y_h, y_m, weights="quadratic", sample_weight=w)
    )
    agree = sum(wi for a, b, wi in zip(y_h, y_m, w, strict=True) if a == b) / sum(w)
    assert value(profile, "graded", "exact agreement") == pytest.approx(agree)
    higher = sum(wi for a, b, wi in zip(y_h, y_m, w, strict=True) if b > a) / sum(w)
    lower = sum(wi for a, b, wi in zip(y_h, y_m, w, strict=True) if b < a) / sum(w)
    assert value(profile, "graded", "labeller grades higher than the human") == (
        pytest.approx(higher)
    )
    assert value(profile, "graded", "labeller grades lower than the human") == (
        pytest.approx(lower)
    )
    assert profile.confusion.sum() == pytest.approx(sum(w))


def test_per_grade_precision_and_recall():
    keys, grades, weights, human, models = weighted_world(seed=3)
    profile = labeller_profile(human, models["llm:noisy"], weights, n_boot=50)
    c = profile.confusion
    for g in range(3):
        assert value(
            profile, "graded", f"grade {g}: precision (labeller says {g}, human agrees)"
        ) == pytest.approx(c[g, g] / c[:, g].sum())
        assert value(
            profile, "graded", f"grade {g}: recall (human says {g}, labeller agrees)"
        ) == pytest.approx(c[g, g] / c[g, :].sum())


@pytest.mark.parametrize(
    "view, threshold",
    [("useful (grade >= 1 vs 0)", 1), ("answers directly (grade 2 vs below)", 2)],
)
def test_binary_views_match_scikit_learn(view, threshold):
    keys, grades, weights, human, models = weighted_world(seed=1)
    profile = labeller_profile(human, models["llm:noisy"], weights, n_boot=100)
    y_h = [grades[k] >= threshold for k in keys]
    y_m = [q.grade >= threshold for q in models["llm:noisy"]]
    w = [weights[k] for k in keys]
    expect = {
        "precision": precision_score(y_h, y_m, sample_weight=w),
        "recall": recall_score(y_h, y_m, sample_weight=w),
        "f1": f1_score(y_h, y_m, sample_weight=w),
        "kappa": cohen_kappa_score(y_h, y_m, sample_weight=w),
        "mcc": matthews_corrcoef(y_h, y_m, sample_weight=w),
    }
    for measure, expected in expect.items():
        assert value(profile, view, measure) == pytest.approx(expected), measure
    assert value(profile, view, "human says True") == pytest.approx(
        np.average(y_h, weights=w)
    )


def test_intervals_bracket_the_estimates_and_unweighted_needs_no_weights():
    _, _, weights, human, models = weighted_world(n_queries=40)
    profile = labeller_profile(human, models["llm:noisy"], weights, n_boot=300)
    kappa = profile.table[profile.table["measure"] == "kappa (quadratic weights)"].iloc[
        0
    ]
    assert kappa["low"] < kappa["value"] < kappa["high"]

    plain = labeller_profile(human, models["llm:noisy"], None, n_boot=50)
    assert not plain.weighted and plain.confusion.sum() == len(human)


def test_only_the_pairs_of_the_weights_are_used_and_no_overlap_is_an_error():
    keys, _, weights, human, models = weighted_world()
    kept = dict(list(weights.items())[:50])
    assert labeller_profile(human, models["llm:noisy"], kept, n_boot=20).n_pairs == 50
    with pytest.raises(ValueError, match="share no"):
        labeller_profile(human, [], weights)


def test_the_rendering_is_graded_first_and_says_binary_is_a_view():
    _, _, weights, human, models = weighted_world()
    text = render_profile(
        labeller_profile(human, models["llm:noisy"], weights, n_boot=50),
        "llm:noisy",
        "human:r",
    )
    assert text.index("### Graded (0/1/2)") < text.index("### Binary view: useful")
    assert "### Binary view: answers directly" in text
    assert "binary views below only exist to read the metrics" in text
    assert "| human:r = 2 |" in text and "llm:noisy = 1" in text


# --- report --human --key -----------------------------------------------------


@pytest.fixture
def graded(world):  # noqa: F811
    """The fake run's labels, with the prompt hash of the real prompts, a human who
    agrees on most pairs, and a weighted key over the first four queries."""
    llm = [
        q.model_copy(update={"prompt_sha256": PROMPT_SHA})
        for q in load_qrels(world["llm"])
    ]
    path = world["tmp"] / "qrels" / "llm-sha.jsonl"
    append_jsonl(path, llm)
    human = [
        q.model_copy(
            update={"labeller": "human:r", "grade": 1 if q.doc_id == "d2" else q.grade}
        )
        for q in llm
        if q.query_id in {"q0", "q1", "q2", "q3"}
    ]
    human_path = world["tmp"] / "qrels" / "human.jsonl"
    append_jsonl(human_path, human)
    key = world["tmp"] / "key.json"
    key.write_text(
        json.dumps(
            [
                {
                    "audit_id": f"a{i:04d}",
                    "query_id": q.query_id,
                    "doc_id": q.doc_id,
                    "text_sha256": q.text_sha256,
                    "in_production_top": False,
                    "llm_grade": None,
                    "stratum": "disputed",
                    "weight": 2.5,
                }
                for i, q in enumerate(human, start=1)
            ]
        )
    )
    return dict(world, llm_sha=path, human=human_path, key=key)


def test_report_with_human_and_key_appends_the_profile(graded):
    code = cli(
        graded,
        "report",
        "--run-id",
        "r1",
        "--qrels",
        str(graded["llm_sha"]),
        "--human",
        str(graded["human"]),
        "--key",
        str(graded["key"]),
        "--bootstrap",
        "100",
    )
    assert code == 0
    run_dir = graded["runs"] / "r1"
    text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Labeller error profile: llm:albert/gpt-oss-120b against human:r" in text
    assert "### Graded (0/1/2)" in text and "each weighted by the pool pairs" in text
    table = list(csv.DictReader((run_dir / "labeller_profile.csv").open()))
    assert {r["section"] for r in table} >= {"graded", "useful (grade >= 1 vs 0)"}


def test_report_without_human_has_no_profile(graded):
    cli(graded, "report", "--run-id", "r1", "--qrels", str(graded["llm_sha"]))
    run_dir = graded["runs"] / "r1"
    assert "Labeller error profile" not in (run_dir / "report.md").read_text()
    assert not (run_dir / "labeller_profile.csv").exists()


# --- export-dataset -----------------------------------------------------------


def export(graded, *extra, out="dataset"):
    return cli(
        graded,
        "export-dataset",
        "--run-id",
        "r1",
        "--qrels",
        str(graded["llm_sha"]),
        "--depth",
        "10",
        "--out",
        str(graded["tmp"] / out),
        *extra,
    )


def test_export_writes_one_graded_row_per_pooled_pair(graded):
    assert export(graded) == 0
    out = graded["tmp"] / "dataset"
    rows = [json.loads(line) for line in (out / "pairs.jsonl").read_text().splitlines()]
    assert len(rows) == 12 * 6  # 12 queries, the 6 documents of the run
    first = rows[0]
    assert first["grade"] in (0, 1, 2) and first["split"] in ("dev", "test")
    assert "relevant" not in first  # the label is graded: no boolean is stored
    assert set(first) >= {
        "query_id",
        "doc_id",
        "rationale",
        "labeller",
        "prompt_sha256",
        "text_sha256",
        "rank_knn",
        "rank_hybrid_rerank",
        "in_production_top10",
        "human_grade",
        "human_gold",
    }
    by_doc = {r["doc_id"]: r for r in rows if r["query_id"] == "q0"}
    assert by_doc["d0"]["rank_hybrid_rerank"] == 1 and by_doc["d0"]["rank_knn"] == 3
    assert by_doc["d5"]["rank_hybrid_rerank"] == 6 and by_doc["d5"]["rank_knn"] == 6
    assert all(r["in_production_top10"] for r in rows)  # 6 documents, all in the top 10
    assert not any(r["human_gold"] for r in rows)
    docs = [
        json.loads(line) for line in (out / "documents.jsonl").read_text().splitlines()
    ]
    assert len(docs) == 6 and all(d["text_sha256"] for d in docs)
    assert len((out / "queries.jsonl").read_text().splitlines()) == 12
    with (out / "pairs.csv").open(newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 72


def test_export_marks_the_gold_pairs_and_puts_the_profile_in_the_data_card(graded):
    assert (
        export(
            graded,
            "--human",
            str(graded["human"]),
            "--key",
            str(graded["key"]),
            "--bootstrap",
            "100",
        )  # fmt: skip
        == 0
    )
    out = graded["tmp"] / "dataset"
    rows = [json.loads(line) for line in (out / "pairs.jsonl").read_text().splitlines()]
    gold = [r for r in rows if r["human_gold"]]
    assert len(gold) == 4 * 6 and {r["query_id"] for r in gold} == {
        "q0",
        "q1",
        "q2",
        "q3",
    }
    assert {r["human_grade"] for r in gold if r["doc_id"] == "d2"} == {1}
    card = (out / "README.md").read_text(encoding="utf-8")
    assert "Labels are **graded 0/1/2**; no binary label is stored" in card
    assert "How far to trust the grades" in card and "### Graded (0/1/2)" in card
    assert (
        "selection bar" in card and "below the bar" in card or "reaches the bar" in card
    )
    assert PROMPT_SHA in card and "`llm:albert/gpt-oss-120b`" in card


def test_export_data_card_without_a_human_has_no_trust_section(graded):
    export(graded)
    card = (graded["tmp"] / "dataset" / "README.md").read_text(encoding="utf-8")
    assert "How far to trust" not in card and "## Limits" in card
    assert "répond directement" in card  # grade names come from the guideline


def test_export_refuses_a_dataset_with_holes(graded, capsys):
    qrels = load_qrels(graded["llm_sha"])
    holes = graded["tmp"] / "qrels" / "holes.jsonl"
    append_jsonl(
        holes, [q for q in qrels if not (q.query_id == "q5" and q.doc_id == "d3")]
    )
    code = cli(
        graded,
        "export-dataset",
        "--run-id",
        "r1",
        "--qrels",
        str(holes),
        "--depth",
        "10",
        "--out",
        str(graded["tmp"] / "x"),
    )
    err = capsys.readouterr().err
    assert code == 2 and "1 pooled pairs cannot be exported" in err
    assert not (graded["tmp"] / "x").exists()


def test_export_refuses_labels_made_on_another_text(graded, capsys):
    qrels = load_qrels(graded["llm_sha"])
    stale = graded["tmp"] / "qrels" / "stale.jsonl"
    append_jsonl(
        stale,
        [
            q.model_copy(update={"text_sha256": "old"}) if q.doc_id == "d1" else q
            for q in qrels
        ],
    )
    code = cli(
        graded, "export-dataset", "--run-id", "r1", "--qrels", str(stale),
        "--depth", "10", "--out", str(graded["tmp"] / "x"),
    )  # fmt: skip
    assert code == 2 and "not graded on this text" in capsys.readouterr().err


def test_export_refuses_labels_made_with_other_prompts_or_length_limit(graded, capsys):
    assert export(graded, "--max-chars", "12000", out="y") == 2
    assert "prompt hashes" in capsys.readouterr().err
    assert not (graded["tmp"] / "y").exists()


def test_export_needs_a_labeller_when_the_files_hold_several(graded, capsys):
    both = graded["tmp"] / "qrels" / "both.jsonl"
    qrels = load_qrels(graded["llm_sha"])
    append_jsonl(
        both, qrels + [q.model_copy(update={"labeller": "llm:other"}) for q in qrels]
    )
    code = cli(
        graded, "export-dataset", "--run-id", "r1", "--qrels", str(both),
        "--depth", "10", "--out", str(graded["tmp"] / "x"),
    )  # fmt: skip
    assert code == 2 and "--labeller" in capsys.readouterr().err
