"""Agreement metrics between a judge and the human labels.

Everything is computed from confusion counts so the cluster bootstrap can resample
whole questions with one vectorised sum. "Oui" is the positive class (True). The
"Non" class is reported separately because flagging bad answers is the use case
that matters.
"""

import numpy as np

# Last axis of every counts array: true positives, false positives, false
# negatives, true negatives (positive = "Oui").
TP, FP, FN, TN = range(4)

SCORE_NAMES = (
    "n",
    "accuracy",
    "balanced_accuracy",
    "kappa",
    "mcc",
    "macro_f1",
    "non_precision",
    "non_recall",
    "non_f1",
)


def _ratio(num: np.ndarray, den: np.ndarray, *, empty: float) -> np.ndarray:
    """num / den, with `empty` wherever den is 0 (no warning)."""
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    out = np.full(np.broadcast(num, den).shape, empty, dtype=float)
    np.divide(num, den, out=out, where=den != 0)
    return out


def counts_from_labels(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    y_true, y_pred = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    return np.array(
        [
            np.sum(y_true & y_pred),
            np.sum(~y_true & y_pred),
            np.sum(y_true & ~y_pred),
            np.sum(~y_true & ~y_pred),
        ]
    )


def cluster_counts(
    y_true: np.ndarray, y_pred: np.ndarray, clusters: np.ndarray, n_clusters: int
) -> np.ndarray:
    """Confusion counts per cluster (question), shape (n_clusters, 4)."""
    y_true, y_pred = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    clusters = np.asarray(clusters, int)
    cells = (y_true & y_pred, ~y_true & y_pred, y_true & ~y_pred, ~y_true & ~y_pred)
    return np.stack(
        [np.bincount(clusters[cell], minlength=n_clusters) for cell in cells], axis=-1
    )


def scores(counts: np.ndarray) -> dict[str, np.ndarray]:
    """All scores from counts of shape (..., 4); returns arrays of shape (...)."""
    c = np.asarray(counts, dtype=float)
    tp, fp, fn, tn = c[..., TP], c[..., FP], c[..., FN], c[..., TN]
    n = tp + fp + fn + tn

    accuracy = _ratio(tp + tn, n, empty=np.nan)
    recall_oui = _ratio(tp, tp + fn, empty=np.nan)
    recall_non = _ratio(tn, tn + fp, empty=np.nan)
    # A class absent from the truth is ignored, as sklearn does.
    recalls = np.stack([recall_oui, recall_non])
    present = np.isfinite(recalls)
    balanced = _ratio(
        np.where(present, recalls, 0).sum(axis=0), present.sum(axis=0), empty=np.nan
    )

    expected = _ratio(
        (tp + fn) * (tp + fp) + (tn + fp) * (tn + fn), n * n, empty=np.nan
    )
    kappa = _ratio(accuracy - expected, 1 - expected, empty=np.nan)

    mcc = _ratio(
        tp * tn - fp * fn,
        np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)),
        empty=0.0,
    )

    def f1(precision: np.ndarray, recall: np.ndarray) -> np.ndarray:
        return _ratio(2 * precision * recall, precision + recall, empty=0.0)

    precision_oui = _ratio(tp, tp + fp, empty=0.0)
    precision_non = _ratio(tn, tn + fn, empty=0.0)
    f1_oui = f1(precision_oui, np.nan_to_num(recall_oui))
    f1_non = f1(precision_non, np.nan_to_num(recall_non))

    return {
        "n": n,
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "kappa": kappa,
        "mcc": mcc,
        "macro_f1": (f1_oui + f1_non) / 2,
        "non_precision": precision_non,
        "non_recall": np.nan_to_num(recall_non),
        "non_f1": f1_non,
    }


def bootstrap_draws(n_clusters: int, n_boot: int, seed: int) -> np.ndarray:
    """Cluster indices for each bootstrap draw, shape (n_boot, n_clusters).

    Generate once and reuse for every judge so that differences between judges
    are paired (same resampled questions).
    """
    rng = np.random.default_rng(seed)
    return rng.integers(0, n_clusters, size=(n_boot, n_clusters))


def bootstrap_scores(
    per_cluster: np.ndarray, draws: np.ndarray
) -> dict[str, np.ndarray]:
    """Scores for each resample; per_cluster has shape (n_clusters, 4)."""
    return scores(per_cluster[draws].sum(axis=1))


def percentile_ci(values: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return (np.nan, np.nan)
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(finite, [tail, 100 - tail])
    return float(low), float(high)
