"""Stage s07 diversity cap. Seeded k-means plus the in-cluster keep rule.

Spec: docs/specs/pool-curation.md section 10, stage s07, and decisions
D6 and D7. Architecture rule R8 sets the cap. All computation runs on
the CPU in float32 with an explicit seed, and gives byte-for-byte the
same result each time.
"""

import math
from collections.abc import Sequence

import numpy as np

from core.types import FloatArray, IntArray, Vectors
from pool.curation.types import Rejection, StageResult

STAGE = "s07-diversity"


def cluster_count(candidate_count: int, cluster_size_divisor: int) -> int:
    """The cluster count k from decision D6: ceil(n / divisor).

    The output is 1 when candidate_count is at or below the divisor,
    and stays at or below candidate_count.
    """
    if candidate_count < 1:
        raise ValueError(f"candidate_count {candidate_count} is not positive")
    if cluster_size_divisor < 1:
        raise ValueError(f"cluster_size_divisor {cluster_size_divisor} is not positive")
    return min(math.ceil(candidate_count / cluster_size_divisor), candidate_count)


def _squared_distances(vectors: Vectors, centers: Vectors) -> FloatArray:
    """Squared euclidean distances in float32. The output is (n, k)."""
    distances = np.empty((vectors.shape[0], centers.shape[0]), dtype=np.float32)
    for center_index in range(centers.shape[0]):
        difference = vectors - centers[center_index]  # (n, d) float32
        distances[:, center_index] = np.square(difference).sum(axis=1)  # (n,)
    return distances


def _mean_centers(vectors: Vectors, labels: IntArray, counts: IntArray, k: int) -> Vectors:
    """New centers: sum the member rows in float64, then cast to float32."""
    centers = np.empty((k, vectors.shape[1]), dtype=np.float32)
    wide = vectors.astype(np.float64)
    for center_index in range(k):
        members = wide[labels == center_index]  # (m, d) float64
        centers[center_index] = (members.sum(axis=0) / counts[center_index]).astype(np.float32)
    return centers


def seeded_kmeans(vectors: Vectors, k: int, seed: int, max_iterations: int) -> IntArray:
    """Lloyd k-means with explicit seeding. Deterministic on the CPU.

    Initial centers are k different rows, selected with
    numpy.random.default_rng(seed). Each iteration calculates squared
    euclidean distances in float32 and assigns each row to the nearest
    center, lowest center index on equal distances. The center update
    accumulates in float64, then casts to float32. An empty cluster
    makes the loop reseed that center to the row with the greatest
    distance to its own assigned center (lowest row index on equal
    distances) and start the next iteration without a center update.
    The loop stops when assignments do not change, or after
    max_iterations.

    The output is int64 labels of shape (n,).
    """
    if vectors.ndim != 2:
        raise ValueError(f"vectors shape {vectors.shape} is not (n, d)")
    if vectors.dtype != np.float32:
        raise ValueError(f"vectors dtype {vectors.dtype} is not float32")
    n = vectors.shape[0]
    if not 1 <= k <= n:
        raise ValueError(f"k {k} is out of range [1, {n}]")
    if max_iterations < 1:
        raise ValueError(f"max_iterations {max_iterations} is not positive")

    rng = np.random.default_rng(seed)
    centers = vectors[rng.choice(n, size=k, replace=False)]  # (k, d) float32 copy
    labels = np.zeros(n, dtype=np.int64)
    previous: IntArray | None = None
    rows = np.arange(n)
    for _ in range(max_iterations):
        distances = _squared_distances(vectors, centers)  # (n, k) float32
        labels = np.argmin(distances, axis=1).astype(np.int64)  # equal: lowest index
        if previous is not None and np.array_equal(labels, previous):
            break
        previous = labels
        counts = np.bincount(labels, minlength=k)  # (k,)
        empty = np.flatnonzero(counts == 0)
        if empty.size:
            own = distances[rows, labels].astype(np.float64)  # (n,)
            for center_index in empty:
                farthest = int(np.argmax(own))  # equal: lowest row index
                centers[center_index] = vectors[farthest]
                own[farthest] = -np.inf  # one row reseeds at most one center
            continue
        centers = _mean_centers(vectors, labels, counts, k)
    return labels


def _keep_positions(member_vectors: Vectors, cluster_cap: int) -> list[int]:
    """D7 keep rule for one cluster with more members than the cap.

    The medoid is the member with the greatest summed cosine
    similarity to its cluster members, smallest position on equal
    sums. Farthest-point traversal then grows the kept set: the next
    member is the one with the greatest minimum distance (1.0 minus
    the float64 cosine similarity) to the kept set, smallest position
    on equal distances. The output is the kept positions in the member
    array, in traversal sequence.
    """
    similarity = (member_vectors @ member_vectors.T).astype(np.float64)  # (m, m)
    summed = similarity.sum(axis=1)  # (m,)
    medoid = int(np.argmax(summed))  # equal sums: smallest position
    minimum_distance = 1.0 - similarity[:, medoid]  # (m,) float64
    minimum_distance[medoid] = -np.inf
    kept = [medoid]
    while len(kept) < cluster_cap:
        farthest = int(np.argmax(minimum_distance))  # equal: smallest position
        kept.append(farthest)
        np.minimum(minimum_distance, 1.0 - similarity[:, farthest], out=minimum_distance)
        minimum_distance[farthest] = -np.inf
    return kept


def diversity_decisions(
    image_ids: Sequence[str],
    vectors: Vectors,
    cluster_seed: int,
    cluster_size_divisor: int,
    cluster_cap: int,
    kmeans_max_iterations: int,
) -> StageResult[str]:
    """Apply the R8 cluster cap to one aligned candidate set.

    Clusters come from seeded_kmeans with k = cluster_count(n,
    cluster_size_divisor). A cluster with more than cluster_cap
    members keeps the D7 selection from the medoid plus farthest-point
    traversal, and its other members become rejections with cause
    "diversity-cap" and the cluster identifier recorded with them. The
    ascending image_ids make the smallest row index and the smallest
    image_id agree, which the equal-value rules rely on.

    Arguments:
        image_ids: N image identifiers, sorted ascending.
        vectors: float32 (N, d), unit-norm rows, aligned with image_ids.
        cluster_seed: seed for the k-means initialization.
        cluster_size_divisor: the D6 granularity value.
        cluster_cap: the R8 maximum cluster membership.
        kmeans_max_iterations: iteration limit for seeded_kmeans.

    The output holds survivors and rejections, sorted by ascending
    image_id.
    """
    count = len(image_ids)
    if vectors.ndim != 2 or vectors.shape[0] != count:
        raise ValueError(f"vectors shape {vectors.shape} does not match {count} candidates")
    if vectors.dtype != np.float32:
        raise ValueError(f"vectors dtype {vectors.dtype} is not float32")
    ids = list(image_ids)
    if ids != sorted(ids):
        raise ValueError("image_ids must be sorted ascending")
    if cluster_cap < 1:
        raise ValueError(f"cluster_cap {cluster_cap} is not positive")
    if count == 0:
        return StageResult(survivors=(), rejections=())

    k = cluster_count(count, cluster_size_divisor)
    labels = seeded_kmeans(vectors, k, cluster_seed, kmeans_max_iterations)

    survivors: list[str] = []
    rejections: list[Rejection] = []
    for cluster_index in range(k):
        members = np.flatnonzero(labels == cluster_index)  # ascending rows
        if members.size <= cluster_cap:
            survivors.extend(ids[row] for row in members)
            continue
        kept_positions = set(_keep_positions(vectors[members], cluster_cap))
        for position, row in enumerate(members):
            if position in kept_positions:
                survivors.append(ids[row])
            else:
                rejections.append(
                    Rejection(
                        key=ids[row],
                        stage=STAGE,
                        reason="diversity-cap",
                        measured=None,
                        detail=f"cluster-{cluster_index}",
                    )
                )
    survivors.sort()
    rejections.sort(key=lambda rejection: rejection.key)
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
