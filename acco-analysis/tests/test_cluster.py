import numpy as np
from sklearn.metrics import adjusted_rand_score

from acco_analysis import cluster as clustering
from acco_analysis.label import pick


def blobs(per: int = 60, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    centres = np.eye(4, 64) * 5
    x = np.vstack([c + rng.normal(0, 0.3, (per, 64)) for c in centres])
    return x, np.repeat(np.arange(4), per)


def test_hdbscan_clusters_are_found_and_ordered_by_size():
    x, truth = blobs()
    # a smaller blob last
    x, truth = x[:-30], truth[:-30]
    labels = clustering.cluster(
        x, clustering.Params(method="hdbscan", components=10, min_cluster_size=10)
    )
    assert adjusted_rand_score(truth, labels) > 0.95
    sizes = [int((labels == c).sum()) for c in range(labels.max() + 1)]
    assert sizes == sorted(sizes, reverse=True)


def test_kmeans_assigns_every_point():
    x, truth = blobs()
    labels = clustering.cluster(x, clustering.Params(k=4))
    assert -1 not in labels and adjusted_rand_score(truth, labels) > 0.95
    sizes = np.bincount(labels)
    assert list(sizes) == sorted(sizes, reverse=True)


def test_unknown_method():
    import pytest

    with pytest.raises(ValueError, match="method"):
        clustering.cluster(blobs()[0], clustering.Params(method="spectral"))


def test_scattered_points_are_noise_not_forced_into_a_cluster():
    x, _ = blobs()
    noise = np.random.default_rng(1).normal(0, 3, (10, 64))
    labels = clustering.cluster(
        np.vstack([x, noise]),
        clustering.Params(
            method="hdbscan", components=10, min_cluster_size=20, min_samples=10
        ),
    )
    # HDBSCAN may attach a few of them to a blob: most are noise, the blobs are intact
    assert (labels[-10:] == -1).sum() >= 5
    assert len(set(labels[:-10][labels[:-10] >= 0])) == 4


def test_stability_of_well_separated_clusters():
    x, _ = blobs()
    params = clustering.Params(method="hdbscan", components=10, min_cluster_size=10)
    full = clustering.cluster(x, params)
    scores = clustering.stability(x, full, params, runs=3)
    assert len(scores) == 3 and min(scores) > 0.9


def test_nearest_and_pick():
    x, _ = blobs(per=30)
    members = np.arange(30)  # the first blob
    close = clustering.nearest(x, members, 5)
    assert len(close) == 5 and set(close) <= set(members.tolist())
    chosen = pick(x, members)
    assert len(chosen) == len(set(chosen)) == 16
