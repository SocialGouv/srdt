import math

import numpy as np
import pytest
from sklearn.metrics import cohen_kappa_score

from retrieval_eval.metrics import (
    binarise,
    bootstrap_draws,
    bootstrap_mean,
    confusion_by_cluster,
    exact_agreement,
    judged_at_k,
    mean_with_ci,
    mrr_at_k,
    ndcg_at_k,
    paired_difference,
    precision_at_k,
    query_metrics,
    recall_at_k,
    weighted_kappa,
)

GRADES = {"a": 2, "b": 1, "c": 0, "d": 2}  # relevant at >=1: a, b, d; at >=2: a, d
RANKING = ["c", "a", "x", "b"]  # x is unlabelled


def test_recall():
    assert recall_at_k(RANKING, GRADES, 2, 1) == pytest.approx(1 / 3)  # a
    assert recall_at_k(RANKING, GRADES, 4, 1) == pytest.approx(2 / 3)  # a, b
    assert recall_at_k(RANKING, GRADES, 4, 2) == pytest.approx(1 / 2)  # a of a, d


def test_precision_counts_unlabelled_as_not_relevant_and_divides_by_k():
    assert precision_at_k(RANKING, GRADES, 4, 1) == pytest.approx(2 / 4)
    assert precision_at_k(["a"], GRADES, 4, 1) == pytest.approx(1 / 4)  # short list


def test_mrr():
    assert mrr_at_k(RANKING, GRADES, 4, 1) == pytest.approx(1 / 2)
    assert mrr_at_k(RANKING, GRADES, 1, 1) == 0.0  # nothing relevant in the top 1
    assert mrr_at_k(["c", "x", "b"], {"b": 1, "c": 0}, 10, 2) != mrr_at_k(
        ["c", "x", "b"], {"b": 1, "c": 0}, 10, 1
    )


def test_ndcg_is_one_for_the_ideal_ranking_and_hand_computed_otherwise():
    assert ndcg_at_k(["a", "d", "b", "c"], GRADES, 4) == pytest.approx(1.0)
    # gains 2**g-1: a=3, b=1, d=3. ideal = 3 + 3/log2(3) + 1/2
    ideal = 3 + 3 / math.log2(3) + 1 / 2
    got = 0 + 3 / math.log2(3) + 0 + 1 / math.log2(5)  # c, a, x, b
    assert ndcg_at_k(RANKING, GRADES, 4) == pytest.approx(got / ideal)


def test_undefined_without_a_relevant_document():
    none = {"a": 0, "b": 0}
    only_one = {"a": 1}
    for value in (
        recall_at_k(["a"], none, 5, 1),
        precision_at_k(["a"], none, 5, 1),
        mrr_at_k(["a"], none, 5, 1),
        ndcg_at_k(["a"], none, 5),
        recall_at_k(["a"], only_one, 5, 2),  # no grade-2 document
    ):
        assert math.isnan(value)


def test_judged_at_k():
    assert judged_at_k(RANKING, GRADES, 4) == pytest.approx(3 / 4)
    assert judged_at_k(["x"], GRADES, 4) == 0


def test_query_metrics_keys():
    keys = set(query_metrics(RANKING, GRADES, [5, 10]))
    assert {
        "recall@5(>=1)",
        "precision@10(>=2)",
        "ndcg@5",
        "judged@10",
        "mrr(>=1)",
        "mrr(>=2)",
    } <= keys


# --- bootstrap ---------------------------------------------------------------


def test_bootstrap_mean_skips_undefined_queries():
    values = np.array([1.0, np.nan, 0.0])
    draws = np.array([[0, 1, 1], [1, 1, 1], [0, 2, 2]])
    result = bootstrap_mean(values, draws)
    assert result[0] == 1.0  # only query 0 is defined in the draw
    assert math.isnan(result[1])  # nothing defined
    assert result[2] == pytest.approx(1 / 3)


def test_mean_with_ci_brackets_the_mean_and_counts_defined_queries():
    rng = np.random.default_rng(0)
    values = rng.uniform(size=60)
    values[:5] = np.nan
    draws = bootstrap_draws(60, 500, seed=1)
    mean, low, high, n = mean_with_ci(values, draws)
    assert n == 55
    assert low < mean < high
    assert mean == pytest.approx(np.nanmean(values))


def test_mean_with_ci_all_undefined():
    mean, low, high, n = mean_with_ci(np.full(4, np.nan), bootstrap_draws(4, 10, 0))
    assert n == 0 and math.isnan(mean) and math.isnan(low)


def test_paired_difference_uses_the_same_queries_and_detects_a_better_variant():
    rng = np.random.default_rng(0)
    b = rng.uniform(0.2, 0.6, size=80)
    a = b + 0.2
    a[0] = np.nan  # undefined for a: dropped from the pair
    draws = bootstrap_draws(80, 1000, seed=2)
    delta, low, high, p_a_better = paired_difference(a, b, draws)
    assert delta == pytest.approx(0.2)
    assert low > 0 and high > low
    assert p_a_better == 1.0


def test_draws_are_reproducible():
    assert (bootstrap_draws(10, 5, 3) == bootstrap_draws(10, 5, 3)).all()


# --- agreement ---------------------------------------------------------------


def _random_grades(seed: int, n: int = 200):
    rng = np.random.default_rng(seed)
    first = rng.integers(0, 3, size=n)
    noise = rng.integers(-1, 2, size=n)
    second = np.clip(first + noise * (rng.random(n) < 0.4), 0, 2)
    return first, second.astype(int), rng.integers(0, 10, size=n)


@pytest.mark.parametrize("weights", ["quadratic", "linear"])
def test_weighted_kappa_matches_sklearn(weights):
    first, second, clusters = _random_grades(0)
    confusion = confusion_by_cluster(first, second, clusters, 10)
    assert weighted_kappa(confusion.sum(axis=0), weights) == pytest.approx(
        cohen_kappa_score(first, second, weights=weights)
    )


def test_kappa_is_vectorised_over_resamples():
    first, second, clusters = _random_grades(1)
    per_cluster = confusion_by_cluster(first, second, clusters, 10)
    draws = bootstrap_draws(10, 7, seed=0)
    batch = weighted_kappa(per_cluster[draws].sum(axis=1))
    assert batch.shape == (7,)
    assert batch[3] == pytest.approx(weighted_kappa(per_cluster[draws[3]].sum(axis=0)))


def test_kappa_and_agreement_edge_cases():
    same = confusion_by_cluster([0, 1, 2, 1], [0, 1, 2, 1], [0, 0, 1, 1], 2).sum(axis=0)
    assert weighted_kappa(same) == pytest.approx(1.0)
    assert exact_agreement(same) == 1.0
    constant = confusion_by_cluster([1, 1], [1, 1], [0, 0], 1).sum(axis=0)
    assert math.isnan(weighted_kappa(constant))


def test_binarise_collapses_to_useful_or_not():
    first, second, clusters = _random_grades(2)
    confusion = confusion_by_cluster(first, second, clusters, 10)
    for threshold in (1, 2):
        binary = binarise(confusion, threshold)
        assert binary.shape == (10, 2, 2)
        assert binary.sum() == confusion.sum()
        assert weighted_kappa(binary.sum(axis=0)) == pytest.approx(
            cohen_kappa_score(first >= threshold, second >= threshold)
        )
