"""Ranking metrics per query, their query-level bootstrap, and label agreement.

Conventions:
- A document is *relevant at threshold t* if its grade is >= t (t=1 "useful at all",
  t=2 "answers directly"). A document without a label counts as not relevant, so the
  scores are lower bounds when the pool is shallow: `judged@k` says by how much.
- A query with no relevant document at threshold t has undefined recall, precision,
  MRR and nDCG (NaN): it is left out of that metric's mean, never counted as 0. The
  report shows how many queries each mean is over.
- The bootstrap resamples whole queries, with draws shared by every variant so that
  differences between variants are paired.
"""

import math
from collections.abc import Sequence

import numpy as np

from judge_eval.metrics import bootstrap_draws, percentile_ci  # noqa: F401  (re-export)
from retrieval_eval.data import GRADES

Grades = dict[str, int]  # doc_id -> grade, for one query


def _gains(grades: Grades) -> list[float]:
    return sorted((2**g - 1 for g in grades.values() if g > 0), reverse=True)


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(rank + 2) for rank, g in enumerate(gains))


def recall_at_k(ranking: Sequence[str], grades: Grades, k: int, t: int) -> float:
    relevant = {d for d, g in grades.items() if g >= t}
    if not relevant:
        return math.nan
    return len(relevant.intersection(ranking[:k])) / len(relevant)


def precision_at_k(ranking: Sequence[str], grades: Grades, k: int, t: int) -> float:
    """Over k, whatever the ranking length: a short list is penalised."""
    if not any(g >= t for g in grades.values()):
        return math.nan
    return sum(grades.get(d, 0) >= t for d in ranking[:k]) / k


def mrr_at_k(ranking: Sequence[str], grades: Grades, k: int, t: int) -> float:
    if not any(g >= t for g in grades.values()):
        return math.nan
    for rank, doc_id in enumerate(ranking[:k], start=1):
        if grades.get(doc_id, 0) >= t:
            return 1 / rank
    return 0.0


def ndcg_at_k(ranking: Sequence[str], grades: Grades, k: int) -> float:
    """Gain 2**grade - 1; the ideal ranking is the query's labelled documents."""
    ideal = _dcg(_gains(grades)[:k])
    if ideal == 0:
        return math.nan
    return _dcg([2 ** grades.get(d, 0) - 1 for d in ranking[:k]]) / ideal


def judged_at_k(ranking: Sequence[str], grades: Grades, k: int) -> float:
    """Share of the top k that has a label (k, not the list length, is the divisor)."""
    return sum(d in grades for d in ranking[:k]) / k


def query_metrics(
    ranking: Sequence[str], grades: Grades, ks: Sequence[int]
) -> dict[str, float]:
    """Every reported metric for one query, keyed like `recall@10(>=1)`."""
    out: dict[str, float] = {}
    for k in ks:
        for t in (1, 2):
            out[f"recall@{k}(>={t})"] = recall_at_k(ranking, grades, k, t)
            out[f"precision@{k}(>={t})"] = precision_at_k(ranking, grades, k, t)
        out[f"ndcg@{k}"] = ndcg_at_k(ranking, grades, k)
        out[f"judged@{k}"] = judged_at_k(ranking, grades, k)
    top = max(ks)
    for t in (1, 2):
        out[f"mrr(>={t})"] = mrr_at_k(ranking, grades, top, t)
    return out


def bootstrap_mean(values: np.ndarray, draws: np.ndarray) -> np.ndarray:
    """Mean of `values` over each resample of clusters; NaN entries are skipped.

    `values` is (n_clusters,), `draws` (n_boot, n_clusters). A resample with no
    defined value gives NaN."""
    defined = ~np.isnan(values)
    picked_defined = defined[draws]
    total = np.where(defined, values, 0.0)[draws].sum(axis=1)
    count = picked_defined.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def mean_with_ci(
    values: np.ndarray, draws: np.ndarray, level: float = 0.95
) -> tuple[float, float, float, int]:
    """(mean, low, high, n defined) of a per-query metric."""
    defined = ~np.isnan(values)
    if not defined.any():
        return (math.nan, math.nan, math.nan, 0)
    low, high = percentile_ci(bootstrap_mean(values, draws), level)
    return (float(values[defined].mean()), low, high, int(defined.sum()))


def paired_difference(
    a: np.ndarray, b: np.ndarray, draws: np.ndarray, level: float = 0.95
) -> tuple[float, float, float, float]:
    """(mean a - mean b, low, high, P(a > b)) over the queries defined for both."""
    diff = np.where(np.isnan(a) | np.isnan(b), np.nan, a - b)
    if np.isnan(diff).all():
        return (math.nan, math.nan, math.nan, math.nan)
    boot = bootstrap_mean(diff, draws)
    low, high = percentile_ci(boot, level)
    finite = boot[np.isfinite(boot)]
    return (
        float(np.nanmean(diff)),
        low,
        high,
        float((finite > 0).mean()) if finite.size else math.nan,
    )


# --- agreement between two labellers (grades 0/1/2) -------------------------


def confusion_by_cluster(
    first: Sequence[int],
    second: Sequence[int],
    clusters: Sequence[int],
    n_clusters: int,
    weights: Sequence[float] | None = None,
) -> np.ndarray:
    """Per-cluster confusion matrices, shape (n_clusters, 3, 3): rows are `first`.

    `weights` gives each pair the number of pool pairs it stands for, when the pairs
    were drawn with unequal probabilities (a stratified sample): the matrices then
    estimate the pool's."""
    out = np.zeros((n_clusters, len(GRADES), len(GRADES)))
    for i, (a, b, c) in enumerate(zip(first, second, clusters, strict=True)):
        out[c, a, b] += 1 if weights is None else weights[i]
    return out


def weighted_kappa(confusion: np.ndarray, weights: str = "quadratic") -> np.ndarray:
    """Cohen's kappa of (..., 3, 3) confusion matrices; NaN when chance agreement is
    total (e.g. both labellers constant)."""
    n_classes = confusion.shape[-1]
    index = np.arange(n_classes)
    distance = np.abs(index[:, None] - index[None, :])
    penalty = distance**2 if weights == "quadratic" else distance
    penalty = penalty / penalty.max()
    total = confusion.sum(axis=(-2, -1))
    rows = confusion.sum(axis=-1)
    cols = confusion.sum(axis=-2)
    with np.errstate(invalid="ignore", divide="ignore"):
        expected = rows[..., :, None] * cols[..., None, :] / total[..., None, None]
        observed = (penalty * confusion).sum(axis=(-2, -1))
        chance = (penalty * expected).sum(axis=(-2, -1))
        return np.where(chance > 0, 1 - observed / chance, np.nan)


def exact_agreement(confusion: np.ndarray) -> np.ndarray:
    total = confusion.sum(axis=(-2, -1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.trace(confusion, axis1=-2, axis2=-1) / total


def binarise(confusion: np.ndarray, threshold: int) -> np.ndarray:
    """Collapse (..., 3, 3) to (..., 2, 2): grade >= threshold or not."""
    low, high = slice(0, threshold), slice(threshold, None)
    out = np.zeros((*confusion.shape[:-2], 2, 2))
    for i, rows in enumerate((low, high)):
        for j, cols in enumerate((low, high)):
            out[..., i, j] = confusion[..., rows, :][..., cols].sum(axis=(-2, -1))
    return out
