"""Layer 6 fusion: weighted average across the active channels.

Implements docs/ARCHITECTURE.md section 14 through
docs/specs/scoring-path.md section 10 (decision D5). The active set
comes from the atom types through the routing table — no code
branches on modality (Rule 5). The division by the sum of the active
weights is what makes a missing modality safe.
"""

from collections.abc import Mapping, Sequence

import numpy as np

from core.types import Atom, AtomType, ChannelName, PoolScores, Weights


class NoActiveChannels(ValueError):
    """The submission carries no signal a built channel reads."""


def active_channels(atoms: Sequence[Atom],
                    routing: Mapping[AtomType, tuple[ChannelName, ...]],
                    ) -> frozenset[ChannelName]:
    """The channels the submission activates, from its atom types.

    The union of the routing entries across atoms. Pure data lookup —
    this is the full mechanism by which text-only, sketch-only, and
    mixed submissions work without a branch (Rule 5).
    """
    names: set[ChannelName] = set()
    for atom in atoms:
        names.update(routing[atom.type])
    return frozenset(names)


def fuse(scores: Mapping[ChannelName, PoolScores],
         weights: Weights) -> PoolScores:
    """The fixed weighted average of architecture section 14.

    fused = sum of weight_c * scores_c, across the active channels,
    divided by the sum of the active weights. An empty score table
    raises NoActiveChannels — to score a submission with no active
    channel is to invent a number. A channel without a configured
    weight raises: that is a configuration bug, not a skip.
    """
    if not scores:
        raise NoActiveChannels(
            "no active channels: no built channel reads this submission")
    names = sorted(scores)
    length: int | None = None
    total: np.ndarray | None = None
    denominator = 0.0
    for name in names:
        if name not in weights:
            raise ValueError(f"channel {name!r} has no configured weight")
        channel_scores = scores[name]
        if channel_scores.ndim != 1:
            raise ValueError(
                f"channel {name!r} scores must be 1-D, got shape "
                f"{channel_scores.shape}")
        if length is None:
            length = channel_scores.shape[0]
            total = np.zeros(length, dtype=np.float64)
        elif channel_scores.shape[0] != length:
            raise ValueError(
                f"channel {name!r} has length {channel_scores.shape[0]}, "
                f"expected {length}")
        assert total is not None
        total += weights[name] * channel_scores.astype(np.float64)
        denominator += weights[name]
    if denominator == 0.0:
        raise ValueError("the sum of the active weights is zero")
    assert total is not None
    return (total / denominator).astype(np.float32)   # (N,)
