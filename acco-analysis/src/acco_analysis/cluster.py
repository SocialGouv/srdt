"""Stage 3: group the heat passages that say the same kind of thing.

Passages are embedded with Albert (bge-m3) and clustered with k-means (default, every
passage gets a group) or HDBSCAN (groups only where the points are dense, the rest is
noise, -1). On this corpus heat clauses form a continuum, not separate groups: HDBSCAN
leaves about 70% as noise or makes one giant group, so k-means is the default and its
stability is reported with the result. Stability: the same clustering on random 80%
subsets, compared with the full one (adjusted Rand index on the points they share).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score

from acco_analysis.relevance import excerpt

EMBED_CHARS = 1500


@dataclass(frozen=True)
class Params:
    method: str = "kmeans"  # or "hdbscan"
    k: int = 15  # kmeans
    components: int = 20  # hdbscan: PCA dimensions
    min_cluster_size: int = 15  # hdbscan
    min_samples: int = 3  # hdbscan
    selection: str = "leaf"  # hdbscan: "leaf" gives finer groups than "eom"
    seed: int = 0


DEFAULT = Params()


def passage_text(passage: dict[str, Any]) -> str:
    heading = passage["heading"]
    body = excerpt(passage["text"], EMBED_CHARS)
    return f"{heading}\n{body}" if heading else body


def normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def cluster(vectors: np.ndarray, params: Params = DEFAULT) -> np.ndarray:
    """One label per row (-1 for noise, hdbscan only). Labels are ordered by
    decreasing size."""
    x = normalise(vectors)
    if params.method == "kmeans":
        model = KMeans(
            params.k,
            n_init=10,  # type: ignore[arg-type]
            random_state=params.seed,
        )
        return _by_size(model.fit_predict(x))
    if params.method != "hdbscan":
        raise ValueError(f"unknown clustering method {params.method!r}")
    components = min(params.components, x.shape[0] - 1, x.shape[1])
    reduced = PCA(components, random_state=params.seed).fit_transform(x)
    labels = HDBSCAN(
        min_cluster_size=params.min_cluster_size,
        min_samples=params.min_samples,
        cluster_selection_method=params.selection,  # type: ignore[arg-type]
        copy=True,  # type: ignore[arg-type]
    ).fit_predict(reduced)
    return _by_size(labels)


def _by_size(labels: np.ndarray) -> np.ndarray:
    ids, counts = np.unique(labels[labels >= 0], return_counts=True)
    rank = {int(i): n for n, i in enumerate(ids[np.argsort(-counts, kind="stable")])}
    return np.array([rank.get(int(label), -1) for label in labels])


def stability(
    vectors: np.ndarray,
    full: np.ndarray,
    params: Params = DEFAULT,
    runs: int = 5,
    share: float = 0.8,
) -> list[float]:
    """Adjusted Rand index, per subset, between the clustering of the subset and the
    labels of the full run on the same points (noise counts as one group)."""
    scores = []
    for run in range(runs):
        rng = np.random.default_rng(100 + run)
        keep = np.sort(rng.choice(len(vectors), int(len(vectors) * share), False))
        sub = cluster(vectors[keep], Params(**{**params.__dict__, "seed": run + 1}))
        scores.append(float(adjusted_rand_score(full[keep], sub)))
    return scores


def nearest(vectors: np.ndarray, members: np.ndarray, n: int) -> list[int]:
    """Indices (into `vectors`) of the `n` members closest to the cluster centroid."""
    x = normalise(vectors)
    centroid = normalise(x[members].mean(axis=0, keepdims=True))[0]
    order = np.argsort(-(x[members] @ centroid), kind="stable")
    return [int(members[i]) for i in order[:n]]
