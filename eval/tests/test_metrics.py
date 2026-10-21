import numpy as np
import pytest
from sklearn import metrics as sk

from judge_eval.metrics import (
    bootstrap_draws,
    bootstrap_scores,
    cluster_counts,
    counts_from_labels,
    percentile_ci,
    scores,
)


def test_hand_computed_example():
    # tp=40 fp=10 fn=20 tn=30 -> n=100
    counts = np.array([40, 10, 20, 30])
    s = {k: float(v) for k, v in scores(counts).items()}
    assert s["n"] == 100
    assert s["accuracy"] == pytest.approx(0.70)
    # recall Oui = 40/60, recall Non = 30/40
    assert s["balanced_accuracy"] == pytest.approx((40 / 60 + 30 / 40) / 2)
    # expected agreement = (60*50 + 40*50) / 100^2 = 0.5
    assert s["kappa"] == pytest.approx((0.70 - 0.5) / 0.5)
    assert s["non_precision"] == pytest.approx(30 / 50)
    assert s["non_recall"] == pytest.approx(30 / 40)


@pytest.mark.parametrize("seed", range(5))
def test_matches_scikit_learn(seed):
    rng = np.random.default_rng(seed)
    y_true = rng.random(184) < 0.6
    y_pred = np.where(rng.random(184) < 0.75, y_true, ~y_true)
    s = scores(counts_from_labels(y_true, y_pred))
    assert s["accuracy"] == pytest.approx(sk.accuracy_score(y_true, y_pred))
    assert s["balanced_accuracy"] == pytest.approx(
        sk.balanced_accuracy_score(y_true, y_pred)
    )
    assert s["kappa"] == pytest.approx(sk.cohen_kappa_score(y_true, y_pred))
    assert s["mcc"] == pytest.approx(sk.matthews_corrcoef(y_true, y_pred))
    assert s["macro_f1"] == pytest.approx(sk.f1_score(y_true, y_pred, average="macro"))
    precision, recall, f1, _ = sk.precision_recall_fscore_support(
        y_true, y_pred, labels=[False], zero_division=0
    )
    assert s["non_precision"] == pytest.approx(precision[0])
    assert s["non_recall"] == pytest.approx(recall[0])
    assert s["non_f1"] == pytest.approx(f1[0])


def test_constant_prediction_has_zero_kappa_and_mcc():
    y_true = np.array([True] * 62 + [False] * 38)
    s = scores(counts_from_labels(y_true, np.ones(100, bool)))
    assert s["accuracy"] == pytest.approx(0.62)
    assert s["kappa"] == pytest.approx(0.0)
    assert s["mcc"] == pytest.approx(0.0)
    assert s["non_recall"] == 0.0 and s["non_f1"] == 0.0


def test_scores_accept_batches_of_counts():
    batch = np.array([[[40, 10, 20, 30], [5, 0, 0, 5]]])
    out = scores(batch)
    assert out["accuracy"].shape == (1, 2)
    assert out["accuracy"][0, 1] == pytest.approx(1.0)


def test_cluster_counts_sum_to_overall_counts():
    rng = np.random.default_rng(1)
    y_true = rng.random(60) < 0.5
    y_pred = rng.random(60) < 0.5
    clusters = rng.integers(0, 6, 60)
    per_cluster = cluster_counts(y_true, y_pred, clusters, n_clusters=8)
    assert per_cluster.shape == (8, 4)
    assert (
        per_cluster.sum(axis=0).tolist() == counts_from_labels(y_true, y_pred).tolist()
    )


def test_bootstrap_is_reproducible_and_brackets_the_point_estimate():
    rng = np.random.default_rng(2)
    y_true = rng.random(180) < 0.6
    y_pred = np.where(rng.random(180) < 0.8, y_true, ~y_true)
    clusters = np.repeat(np.arange(18), 10)
    per_cluster = cluster_counts(y_true, y_pred, clusters, 18)

    draws = bootstrap_draws(18, 1000, seed=0)
    assert (draws == bootstrap_draws(18, 1000, seed=0)).all()
    assert not (draws == bootstrap_draws(18, 1000, seed=1)).all()

    boot = bootstrap_scores(per_cluster, draws)
    low, high = percentile_ci(boot["accuracy"])
    point = float(scores(per_cluster.sum(axis=0))["accuracy"])
    assert low < point < high
    assert 0.0 < high - low < 0.3


def test_percentile_ci_ignores_nan_and_handles_all_nan():
    assert percentile_ci(np.array([np.nan, 1.0, 2.0, 3.0]), 0.5) == pytest.approx(
        (1.5, 2.5)
    )
    low, high = percentile_ci(np.array([np.nan, np.nan]))
    assert np.isnan(low) and np.isnan(high)
