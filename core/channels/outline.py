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


def outline_pool_cache(outline_vectors: FloatArray,
                       outline_space_mean: FloatArray,
                       ) -> tuple[FloatArray, FloatArray]:
    """Center the pool matrix and get its norms, one time (P5 R2).

    The same expressions the channel runs, calculated at index build
    - the values are byte-equal by construction, and at a 20,000
    image pool the cache removes about one second from each channel
    step. The cache doubles the resident outline storage. The
    zero-norm check stays with the channel (R14): an index with an
    outline side that does not score must build, as before the
    cache.
    """
    centered = outline_vectors - outline_space_mean          # (N, 6, d)
    norms = np.linalg.norm(centered, axis=2)                 # (N, 6)
    return centered, norms


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
    if not np.isfinite(sketch_vector).all():
        raise ValueError("sketch_vector holds a non-finite value")

    centered_sketch = sketch_vector - index.outline_space_mean   # (d,)
    if index.outline_centered is None or index.outline_norms is None:
        centered_pool = vectors - index.outline_space_mean       # (N, 6, d)
        pool_norms = np.linalg.norm(centered_pool, axis=2)       # (N, 6)
    else:
        centered_pool = index.outline_centered
        pool_norms = index.outline_norms
    sketch_norm = float(np.linalg.norm(centered_sketch))
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
