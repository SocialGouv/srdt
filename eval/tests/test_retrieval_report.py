import math

import numpy as np
import pytest
from sklearn.metrics import cohen_kappa_score

from retrieval_eval.data import Qrel, Query, Ranking
from retrieval_eval.report import (
    agreement_table,
    build_report,
    paired_grades,
    render_agreement,
    render_markdown,
)


def query(
    qid: str, split: str = "dev", idcc: str | None = None, bucket="short"
) -> Query:
    return Query(
        query_id=qid,
        text=qid,
        source="prod",
        idcc=idcc,
        length_bucket=bucket,
        split=split,
    )


def ranking(qid: str, variant: str, ids: list[str]) -> Ranking:
    return Ranking(query_id=qid, variant=variant, doc_ids=ids, scores=[None] * len(ids))


def world(n: int = 40):
    """`good` ranks the relevant document first, `bad` last, for every query."""
    queries = {
        f"q{i}": query(
            f"q{i}", "dev" if i < 10 else "test", "1979" if i % 4 == 0 else None
        )
        for i in range(n)
    }
    grades = {f"q{i}": {"rel": 2, "meh": 1, "no1": 0, "no2": 0} for i in range(n)}
    rankings = []
    for i in range(n):
        rankings.append(ranking(f"q{i}", "good", ["rel", "meh", "no1", "no2"]))
        rankings.append(ranking(f"q{i}", "bad", ["no1", "no2", "meh", "rel"]))
    return queries, grades, rankings


def row(report, slice_, variant, metric):
    m = report.metrics
    hit = m[
        (m["slice"] == slice_) & (m["variant"] == variant) & (m["metric"] == metric)
    ]
    return hit.iloc[0]


def test_a_better_variant_scores_higher_with_a_paired_interval_above_zero():
    queries, grades, rankings = world()
    report = build_report(rankings, queries, grades, ks=(2, 4), n_boot=200, seed=0)

    assert row(report, "all", "good", "mrr(>=1)")["mean"] == 1.0
    assert row(report, "all", "bad", "mrr(>=2)")["mean"] == pytest.approx(1 / 4)
    assert row(report, "all", "good", "recall@2(>=1)")["mean"] == 1.0
    assert row(report, "all", "bad", "recall@2(>=1)")["mean"] == 0.0

    pair = report.pairwise
    pair = pair[(pair["slice"] == "all") & (pair["metric"] == "ndcg@4")].iloc[0]
    assert (pair["a"], pair["b"]) == ("bad", "good")  # sorted variant order
    assert pair["delta"] < 0 and pair["high"] < 0 and pair["p_a_better"] == 0.0


def test_slices_count_the_labelled_queries_they_contain():
    queries, grades, rankings = world(40)
    report = build_report(rankings, queries, grades, ks=(4,), n_boot=50)
    assert report.n_queries["all"] == 40
    assert report.n_queries["dev"] == 10 and report.n_queries["test"] == 30
    assert report.n_queries["with idcc"] == 10 and report.n_queries["no idcc"] == 30
    assert "keyword" not in report.n_queries  # empty slice is skipped


def test_unlabelled_queries_are_left_out_and_undefined_ones_are_counted():
    queries, grades, rankings = world(10)
    grades.pop("q0")  # never labelled
    grades["q1"] = {"no1": 0}  # labelled, nothing relevant: recall undefined
    report = build_report(rankings, queries, grades, ks=(4,), n_boot=50)

    assert report.n_queries["all"] == 9
    recall = row(report, "all", "good", "recall@4(>=1)")
    assert recall["n_queries"] == 8
    assert not math.isnan(recall["mean"])


def test_a_query_missing_for_one_variant_is_undefined_for_it_not_zero():
    queries, grades, rankings = world(10)
    rankings = [r for r in rankings if not (r.query_id == "q3" and r.variant == "bad")]
    report = build_report(rankings, queries, grades, ks=(4,), n_boot=50)
    assert row(report, "all", "good", "ndcg@4")["n_queries"] == 10
    assert row(report, "all", "bad", "ndcg@4")["n_queries"] == 9


def test_nothing_labelled_is_an_error():
    queries, _, rankings = world(3)
    with pytest.raises(ValueError, match="nothing to report"):
        build_report(rankings, queries, {}, ks=(4,))


def test_markdown_states_the_caveats_and_lists_every_variant():
    queries, grades, rankings = world(12)
    report = build_report(rankings, queries, grades, ks=(10,), n_boot=50)
    text = render_markdown(report, 50, {"qrels": "llm:m"})
    assert "lower bounds" in text and "qrels: llm:m" in text
    assert "| good |" in text and "| bad |" in text
    assert "## all (12 queries with labels)" in text
    assert "Paired differences" in text


# --- agreement ---------------------------------------------------------------


def qrel(qid, doc, grade, labeller, sha="s") -> Qrel:
    return Qrel(
        query_id=qid, doc_id=doc, grade=grade, labeller=labeller, text_sha256=sha
    )


def labelled(seed: int = 0):
    rng = np.random.default_rng(seed)
    human, llm = [], []
    for q in range(25):
        for d in range(8):
            h = int(rng.integers(0, 3))
            m = int(np.clip(h + rng.integers(-1, 2) * (rng.random() < 0.4), 0, 2))
            human.append(qrel(f"q{q}", f"d{d}", h, "human:r"))
            llm.append(qrel(f"q{q}", f"d{d}", m, "llm:m"))
    return human, llm


def test_agreement_matches_sklearn_and_ci_brackets_the_point_estimate():
    human, llm = labelled()
    table, confusion = agreement_table(human, llm, n_boot=300, seed=1)
    y1 = [q.grade for q in human]
    y2 = [q.grade for q in llm]

    kappa = table[table["measure"] == "kappa (quadratic weights)"].iloc[0]
    assert kappa["value"] == pytest.approx(
        cohen_kappa_score(y1, y2, weights="quadratic")
    )
    assert kappa["low"] < kappa["value"] < kappa["high"]
    assert table["n_pairs"].iloc[0] == 200 and table["n_queries"].iloc[0] == 25
    assert confusion.sum() == 200
    useful = table[table["measure"].str.contains(">= 1")].iloc[0]
    assert useful["value"] == pytest.approx(
        cohen_kappa_score([g >= 1 for g in y1], [g >= 1 for g in y2])
    )


def test_only_pairs_on_the_same_document_text_are_compared():
    human = [qrel("q", "d1", 2, "human:r", "v1"), qrel("q", "d2", 1, "human:r", "v1")]
    llm = [qrel("q", "d1", 2, "llm:m", "v1"), qrel("q", "d2", 0, "llm:m", "changed")]
    assert paired_grades(human, llm) == [("q", 2, 2)]
    with pytest.raises(ValueError, match="no .* pair"):
        agreement_table(human[1:], llm[1:])


def test_render_agreement_shows_the_confusion_matrix():
    human, llm = labelled()
    table, confusion = agreement_table(human, llm, n_boot=50)
    text = render_agreement(table, confusion, "human:r", "llm:m")
    assert "Agreement of llm:m with human:r" in text
    assert "200 pairs over 25 queries" in text
    assert "human:r = 0" in text and "llm:m = 2" in text
