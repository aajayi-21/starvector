"""Layer 4 outline channel: sketch shape against pool line drawings.

Implements docs/ARCHITECTURE.md section 12.2 through
docs/specs/scoring-path.md section 10. A channel is a function of
(submission, pool): one number for each pool image, and the target is
not an input (Rule 1). No provider, no file access, no modality
branch.
"""

import numpy as np

from core.types import (EncodedSubmission, FloatArray, OutlineConfig,
                        PoolIndex, PoolScores)

COMPARISON_RULES: tuple[str, ...] = ("center-cosine-v1",)


def outline_scores(sketch_vector: FloatArray, index: PoolIndex,
                   config: OutlineConfig) -> PoolScores:
    """Score one sketch vector against each pool image.

    Rule center-cosine-v1 (D4): subtract the stored pool mean from the
    two sides, then cosine on the centered vectors, then the maximum
    across the six stored rows (full image plus five crops). The mean
    subtraction removes the dominant average direction of the encoder
    space (architecture section 10). Output shape (N,), float32.
    """
    if config.comparison_rule not in COMPARISON_RULES:
        raise ValueError(
            f"unknown comparison_rule: {config.comparison_rule!r}")
    vectors = index.outline_vectors
    if vectors.ndim != 3:
        raise ValueError(f"outline_vectors must be 3-D, got {vectors.shape}")
    dimension = vectors.shape[2]
    if sketch_vector.shape != (dimension,):
        raise ValueError(
            f"sketch_vector must have shape ({dimension},), got "
            f"{sketch_vector.shape}")

    centered_sketch = sketch_vector - index.outline_space_mean   # (d,)
    centered_pool = vectors - index.outline_space_mean           # (N, 6, d)
    sketch_norm = float(np.linalg.norm(centered_sketch))
    pool_norms = np.linalg.norm(centered_pool, axis=2)           # (N, 6)
    if sketch_norm == 0.0 or bool((pool_norms == 0.0).any()):
        # A zero norm after centering means a vector equal to the pool
        # mean. A silent zero or NaN here makes plausible numbers that
        # are incorrect (R14) — thus this raises.
        raise ValueError("zero vector norm after mean subtraction")
    cosines = (centered_pool @ centered_sketch) / (pool_norms * sketch_norm)
    return cosines.max(axis=1).astype(np.float32)                # (N,)


def outline_channel(submission: EncodedSubmission, index: PoolIndex,
                    config: OutlineConfig) -> PoolScores:
    """Run the outline channel on the submission's drawing atom.

    The fusion active set guarantees the channel runs only when one
    encoded drawing atom is in the submission. Zero or two is a broken
    input and raises.
    """
    vectors = [submission.vectors[atom.id] for atom in submission.atoms
               if atom.type == "WHOLE-DRAWING" and atom.id in submission.vectors]
    if len(vectors) != 1:
        raise ValueError(
            "the outline channel needs one encoded WHOLE-DRAWING atom, "
            f"got {len(vectors)}")
    return outline_scores(vectors[0], index, config)
