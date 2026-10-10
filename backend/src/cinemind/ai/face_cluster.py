"""Grouping face vectors into people, with constraints. Pure numpy + scikit-learn; no database.

Existing algorithms: scikit-learn's average-linkage agglomerative clustering and HDBSCAN. Ours:
how the constraints go in. Items that must stay together are merged into one point first (their
mean vector). Pairs that must stay apart get a distance so large that average linkage can never
join them below the threshold. HDBSCAN links through chains and can still break such a pair, so
any HDBSCAN group that does is regrouped with the agglomerative method.
"""

# scikit-learn returns untyped arrays.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# pyright: reportArgumentType=false

from collections.abc import Iterable, Sequence
from typing import Any, Literal

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering

Method = Literal["agglomerative", "hdbscan"]
# Larger than any threshold times any group size squared: a pair that must stay apart keeps the
# average distance between two groups above the threshold however large the groups are.
APART = 1e9


def unit(vectors: Any) -> Any:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-9)


def _roots(count: int, together: Iterable[Sequence[int]]) -> list[int]:
    parent = list(range(count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for group in together:
        for other in group[1:]:
            parent[find(other)] = find(group[0])
    return [find(i) for i in range(count)]


def _agglomerative(distance: Any, threshold: float) -> list[int]:
    if len(distance) == 1:
        return [0]
    model = AgglomerativeClustering(
        n_clusters=None, metric="precomputed", linkage="average", distance_threshold=threshold
    )
    return [int(label) for label in model.fit_predict(distance)]


def _hdbscan(distance: Any, threshold: float) -> list[int]:
    if len(distance) < 3:
        return _agglomerative(distance, threshold)
    model = HDBSCAN(min_cluster_size=2, metric="precomputed", allow_single_cluster=True, copy=True)
    labels = [int(label) for label in model.fit_predict(distance.astype(np.float64))]
    following = max(labels, default=-1) + 1
    for i, label in enumerate(labels):  # "noise" points are people seen once: one group each
        if label < 0:
            labels[i] = following
            following += 1
    for label in sorted(set(labels)):
        members = [i for i, value in enumerate(labels) if value == label]
        inside = distance[np.ix_(members, members)]
        if len(members) > 1 and inside.max() >= APART:
            parts = _agglomerative(inside, threshold)
            for member, part in zip(members, parts, strict=True):
                if part:
                    labels[member] = following + part - 1
            following += max(parts)
    return labels


def cluster(
    vectors: Any,
    threshold: float,
    method: Method = "agglomerative",
    apart: Iterable[tuple[int, int]] = (),
    together: Iterable[Sequence[int]] = (),
    weights: Sequence[float] | None = None,
) -> list[int]:
    """A group label for each row of `vectors` (length-normalised). `apart` pairs never share a
    label, each `together` list always does (the caller makes sure the two do not contradict);
    `weights` say how much each row counts in a merged point. Labels are 0..k-1 in order of
    first appearance, so the result does not depend on scikit-learn's numbering."""
    count = len(vectors)
    if count == 0:
        return []
    roots = _roots(count, together)
    order = {root: i for i, root in enumerate(dict.fromkeys(roots))}
    node = [order[root] for root in roots]
    weight = np.ones(count) if weights is None else np.asarray(weights, dtype=np.float64)
    points = np.zeros((len(order), vectors.shape[1]), dtype=np.float64)
    for i in range(count):
        points[node[i]] += vectors[i] * weight[i]
    points = unit(points)
    distance = np.clip(1.0 - points @ points.T, 0.0, 2.0)
    for a, b in apart:
        if node[a] != node[b]:
            distance[node[a], node[b]] = distance[node[b], node[a]] = APART
    np.fill_diagonal(distance, 0.0)
    found = (_hdbscan if method == "hdbscan" else _agglomerative)(distance, threshold)
    renumber: dict[int, int] = {}
    return [renumber.setdefault(found[node[i]], len(renumber)) for i in range(count)]


def centroid_similarity(vectors: Any, labels: Sequence[int]) -> list[float]:
    """For each row, its cosine similarity to the mean vector of its group."""
    labels_array = np.asarray(labels)
    result = [1.0] * len(labels)
    for label in set(labels):
        members = np.flatnonzero(labels_array == label)
        centre = unit(vectors[members].sum(axis=0, keepdims=True))[0]
        for i in members:
            result[int(i)] = round(float(vectors[i] @ centre), 4)
    return result
