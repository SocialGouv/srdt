"""Screened sampling: strata from fast models' grades, weights, weighted agreement."""

import numpy as np
import pytest
from sklearn.metrics import cohen_kappa_score
from test_selection import pool_world

from retrieval_eval.audit import (
    STRATA,
    default_allocation,
    sample_screened_pairs,
    screening_stratum,
)
from retrieval_eval.data import Qrel
from retrieval_eval.metrics import confusion_by_cluster, weighted_kappa
from retrieval_eval.report import compare_labellers, render_compare


@pytest.mark.parametrize(
    "grades, stratum",
    [
        ((2, 2, 2), "consensus-relevant"),
        ((1, 2, 1), "consensus-relevant"),
        ((1, 1, 1), "consensus-partial"),
        ((2, 1, 0), "disputed"),
        ((0, 0, 1), "disputed"),
        ((0, 0, 0), "consensus-irrelevant"),
        ((1,), "consensus-partial"),
    ],
)
def test_stratum_of_a_pair_follows_the_screeners(grades, stratum):
    assert screening_stratum(grades) == stratum


def test_default_allocation_sums_to_n_and_covers_every_stratum():
    for n in (4, 7, 120, 121):
        allocation = default_allocation(n)
        assert sum(allocation.values()) == n and set(allocation) == set(STRATA)
    assert default_allocation(120) == {
        "consensus-relevant": 30,
        "consensus-partial": 20,
        "disputed": 40,
        "consensus-irrelevant": 30,
    }


def screener_grades(queries, docs, name: str, grade_of):
    return [
        Qrel(
            query_id=qid,
            doc_id=did,
            grade=grade_of(int(qid[1:]), int(did[1:])),
            labeller=name,
            text_sha256=doc.text_sha256,
        )
        for qid in queries
        for did, doc in docs.items()
    ]


@pytest.fixture
def screened():
    queries, docs, rankings = pool_world(n_queries=30)
    screeners = {
        "llm:a": screener_grades(queries, docs, "llm:a", lambda q, d: d % 3),
        "llm:b": screener_grades(queries, docs, "llm:b", lambda q, d: (d + q) % 3),
        "llm:c": screener_grades(queries, docs, "llm:c", lambda q, d: int(d % 2 == 1)),
    }
    return queries, docs, rankings, screeners


def test_sample_draws_each_stratum_with_the_weight_of_its_pool_share(screened):
    queries, docs, rankings, screeners = screened
    sample = sample_screened_pairs(
        rankings, docs, screeners, set(queries), depth=12, n=60, seed=1
    )

    assert len(sample.items) == 60 and sample.unscreened == 0
    assert len({i.audit_id for i in sample.items}) == 60
    for name, info in sample.strata.items():
        drawn = [i for i in sample.items if i.stratum == name]
        assert len(drawn) == info.sampled
        assert info.weight == pytest.approx(info.pool / info.sampled)
        # the weights of a stratum add up to its pool: an unbiased count of it
        assert sum(i.weight for i in drawn) == pytest.approx(info.pool)
    assert sum(i.weight for i in sample.items) == pytest.approx(
        sum(info.pool for info in sample.strata.values())
    )
    assert all(i.llm_grade is None for i in sample.items)


def test_strata_hold_exactly_the_pairs_the_screeners_say(screened):
    queries, docs, rankings, screeners = screened
    sample = sample_screened_pairs(
        rankings, docs, screeners, set(queries), depth=12, n=200, seed=1
    )
    grade = {
        name: {(q.query_id, q.doc_id): q.grade for q in qrels}
        for name, qrels in screeners.items()
    }
    for item in sample.items:
        votes = [g[(item.query_id, item.doc_id)] for g in grade.values()]
        assert screening_stratum(votes) == item.stratum


def test_a_small_stratum_is_taken_whole_with_weight_one(screened):
    queries, docs, rankings, screeners = screened
    allocation = dict.fromkeys(STRATA, 10_000)
    sample = sample_screened_pairs(
        rankings, docs, screeners, set(queries), 12, 1, 0, allocation=allocation
    )
    assert all(info.weight == 1.0 for info in sample.strata.values())
    assert len(sample.items) == sum(info.pool for info in sample.strata.values())


def test_sample_is_reproducible_and_seeded(screened):
    queries, docs, rankings, screeners = screened
    args = (rankings, docs, screeners, set(queries), 12, 60)
    first = sample_screened_pairs(*args, seed=3).items
    assert first == sample_screened_pairs(*args, seed=3).items
    assert first != sample_screened_pairs(*args, seed=4).items


def test_pairs_a_screener_did_not_grade_are_left_out_and_counted(screened):
    queries, docs, rankings, screeners = screened
    screeners = dict(screeners)
    screeners["llm:c"] = [q for q in screeners["llm:c"] if q.doc_id != "d0"]
    sample = sample_screened_pairs(rankings, docs, screeners, set(queries), 12, 200, 0)
    assert sample.unscreened == 30  # d0 in each of the 30 queries
    assert "d0" not in {i.doc_id for i in sample.items}


def test_stale_screener_labels_do_not_count(screened):
    queries, docs, rankings, screeners = screened
    stale = [q.model_copy(update={"text_sha256": "old"}) for q in screeners["llm:a"]]
    sample = sample_screened_pairs(
        rankings, docs, {**screeners, "llm:a": stale}, set(queries), 12, 50, 0
    )
    assert sample.items == [] and sample.unscreened > 0


def test_bad_inputs_are_rejected(screened):
    queries, docs, rankings, screeners = screened
    with pytest.raises(ValueError, match="no screener"):
        sample_screened_pairs(rankings, docs, {}, set(queries), 12, 10, 0)
    with pytest.raises(ValueError, match="unknown strata"):
        sample_screened_pairs(
            rankings, docs, screeners, set(queries), 12, 10, 0, allocation={"x": 3}
        )


def test_a_stratified_sample_recovers_pool_counts_that_a_plain_one_misses(screened):
    """The point of the weights: pairs 'truly' graded 2 are rare in the pool, the
    sample over-represents them, and the weighted count still matches the pool."""
    queries, docs, rankings, screeners = screened
    truth = {  # a human who agrees with screener a, except on irrelevant-looking pairs
        (q.query_id, q.doc_id): q.grade for q in screeners["llm:a"]
    }
    sample = sample_screened_pairs(
        rankings, docs, screeners, set(queries), 12, 90, seed=2
    )
    pool_twos = sum(
        truth[(i.query_id, i.doc_id)] == 2
        for i in sample_screened_pairs(
            rankings, docs, screeners, set(queries), 12, 10_000, 0
        ).items
    )
    drawn_twos = [truth[(i.query_id, i.doc_id)] == 2 for i in sample.items]
    unweighted = sum(drawn_twos) / len(drawn_twos)
    weighted = sum(
        w
        for w, t in zip((i.weight for i in sample.items), drawn_twos, strict=True)
        if t
    )
    total = sum(i.weight for i in sample.items)
    pool_share = pool_twos / total
    assert abs(weighted / total - pool_share) < 0.12  # close to the pool's share
    assert unweighted != pytest.approx(pool_share, abs=0.02)  # the raw sample is off


# --- weighted agreement -----------------------------------------------------------


def test_weighted_confusion_and_kappa_match_scikit_learn_sample_weights():
    rng = np.random.default_rng(0)
    first = rng.integers(0, 3, size=300)
    second = np.clip(
        first + rng.integers(-1, 2, size=300) * (rng.random(300) < 0.4), 0, 2
    )
    clusters = rng.integers(0, 12, size=300)
    weights = rng.choice([1.0, 3.5, 20.0], size=300)

    per_cluster = confusion_by_cluster(first, second, clusters, 12, weights)
    assert per_cluster.sum() == pytest.approx(weights.sum())
    assert weighted_kappa(per_cluster.sum(axis=0)) == pytest.approx(
        cohen_kappa_score(first, second, weights="quadratic", sample_weight=weights)
    )
    # without weights nothing changes
    plain = confusion_by_cluster(first, second, clusters, 12)
    assert plain.sum() == 300


def weighted_world(n_queries: int = 30, per_query: int = 6, seed: int = 0):
    rng = np.random.default_rng(seed)
    keys = [
        (f"q{q}", f"d{d}", f"sha{q}{d}")
        for q in range(n_queries)
        for d in range(per_query)
    ]
    grades = {k: int(rng.integers(0, 3)) for k in keys}
    weights = {k: float(rng.choice([1.0, 4.0, 25.0])) for k in keys}
    human = [
        Qrel(query_id=q, doc_id=d, grade=g, labeller="human:r", text_sha256=sha)
        for (q, d, sha), g in grades.items()
    ]
    noisy = []
    for (q, d, sha), g in grades.items():
        flip = rng.random() < 0.25
        noisy.append(
            Qrel(
                query_id=q,
                doc_id=d,
                grade=int(np.clip(g + rng.choice([-1, 1]), 0, 2)) if flip else g,
                labeller="llm:noisy",
                text_sha256=sha,
            )
        )
    return keys, grades, weights, human, {"llm:noisy": noisy}


def test_compare_with_weights_estimates_the_pool_and_keeps_the_raw_kappa():
    keys, grades, weights, human, models = weighted_world()
    result = compare_labellers(human, models, n_boot=200, seed=0, weights=weights)
    row = result.table.iloc[0]

    y_h = [grades[k] for k in keys]
    y_m = [q.grade for q in models["llm:noisy"]]
    w = [weights[k] for k in keys]
    assert result.weighted
    assert row["kappa"] == pytest.approx(
        cohen_kappa_score(y_h, y_m, weights="quadratic", sample_weight=w)
    )
    assert row["kappa_raw"] == pytest.approx(
        cohen_kappa_score(y_h, y_m, weights="quadratic")
    )
    assert row["kappa"] != pytest.approx(row["kappa_raw"], abs=1e-6)
    assert row["kappa_ge1"] == pytest.approx(
        cohen_kappa_score([g >= 1 for g in y_h], [g >= 1 for g in y_m], sample_weight=w)
    )
    assert row["kappa_low"] < row["kappa"] < row["kappa_high"]


def test_compare_uses_only_the_pairs_of_the_weights():
    keys, grades, weights, human, models = weighted_world()
    kept = dict(list(weights.items())[:60])
    result = compare_labellers(human, models, n_boot=50, seed=0, weights=kept)
    assert result.n_human == 60 and result.n_common == 60


def test_unweighted_compare_has_equal_weighted_and_raw_kappas():
    _, _, _, human, models = weighted_world()
    result = compare_labellers(human, models, n_boot=50, seed=0)
    row = result.table.iloc[0]
    assert not result.weighted and row["kappa"] == pytest.approx(row["kappa_raw"])


def test_render_says_which_estimate_the_bar_applies_to():
    _, _, weights, human, models = weighted_world()
    weighted = render_compare(
        compare_labellers(human, models, n_boot=50, seed=0, weights=weights), 50
    )
    assert "pool-weighted" in weighted and "unweighted" in weighted
    plain = render_compare(compare_labellers(human, models, n_boot=50, seed=0), 50)
    assert "pool-weighted" not in plain


def test_render_flags_models_whose_verdict_depends_on_the_weights():
    keys, grades, weights, human, models = weighted_world(seed=2)
    # make the weights extreme so that weighted and raw kappas part ways
    heavy = {k: (500.0 if g == 0 else 1.0) for k, g in grades.items()}
    result = compare_labellers(human, models, n_boot=50, seed=0, weights=heavy)
    table = result.table
    differs = (table["eligible"] != table["eligible_raw"]).any()
    text = render_compare(result, 50)
    assert ("different verdicts on the unweighted sample" in text) == bool(differs)
