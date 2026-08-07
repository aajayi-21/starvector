"""Stage p08 near-duplicate grouping. Pure graph logic on arrays.

Spec: docs/specs/pool-preparation.md section 10, stage p08, and
decision D9. Architecture rule R10 sets the threshold, and Layer 8
removes the target's full group from the decoy set. The runner loads
the full-image outline vectors - this module only groups.
"""

from collections import Counter
from collections.abc import Sequence

import numpy as np

from core.types import Vectors
from pool.preparation.types import GroupRow


def neardup_groups(
    image_ids: Sequence[str],
    vectors: Vectors,
    similarity_threshold: float,
) -> tuple[tuple[GroupRow, ...], tuple[tuple[int, int], ...]]:
    """Group one aligned image set with connected components (D9).

    The graph has one edge for each pair with cosine similarity at or
    above the threshold. The similarity values have float32
    precision. The threshold gets the same precision, and thus a
    cosine equal to the float32 value of the threshold makes an edge.
    The groups are the connected components, not cliques. group_id is
    the smallest member image_id - stable and content-derived.

    Arguments:
        image_ids: N unique image identifiers, ascending.
        vectors: float32 (N, d), unit-norm full-image rows, aligned
            with image_ids.
        similarity_threshold: the R10 limit from the stage config.

    The output is a pair: N GroupRow records in ascending image_id
    sequence, and the histogram of group member counts as sorted
    (member_count, group_count) pairs.
    """
    count = len(image_ids)
    ids = list(image_ids)
    if any(ids[index] >= ids[index + 1] for index in range(count - 1)):
        raise ValueError("image_ids must be strictly ascending")
    if vectors.ndim != 2 or vectors.shape[0] != count:
        raise ValueError(f"vectors shape {vectors.shape} does not agree with {count} images")
    if vectors.dtype != np.float32:
        raise ValueError(f"vectors dtype {vectors.dtype} is not float32")
    if count == 0:
        return (), ()

    threshold = float(np.float32(similarity_threshold))
    similarities = vectors @ vectors.T  # (N, N) float32

    # Union-find across pairs i < j in ascending sequence. The pair
    # sequence cannot change the components - it is pinned for
    # determinism of the walk only (spec section 14).
    parent = list(range(count))

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    above = np.argwhere(np.triu(similarities >= threshold, k=1))  # (E, 2) pairs i < j
    for i, j in above.tolist():
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[max(root_i, root_j)] = min(root_i, root_j)

    members: dict[int, list[int]] = {}
    for index in range(count):
        members.setdefault(find(index), []).append(index)

    group_of: dict[int, tuple[str, int]] = {}
    for member_rows in members.values():
        # Ascending ids make the smallest row index the smallest id.
        group_id = ids[min(member_rows)]
        for member in member_rows:
            group_of[member] = (group_id, len(member_rows))

    rows = tuple(
        GroupRow(image_id=ids[index], group_id=group_of[index][0],
                 member_count=group_of[index][1])
        for index in range(count)
    )
    histogram = tuple(sorted(Counter(len(m) for m in members.values()).items()))
    return rows, histogram
