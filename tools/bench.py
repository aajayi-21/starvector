"""The P5 bench tool: local-stage timings on a synthetic pool.

Spec P5 item B7 (R6: measured, not asserted). Builds a synthetic
pool index at a given count and dimension, one section 18 submission
shape (8 text atoms plus one drawing), warm fake encoders, and times
each local stage - render, encode, the channels, normalization,
fusion, ranking - at the median across passes. The numbers land in a
committed record with the machine noted, and the ruling-3 verdict on
the 50 ms line is the owner's: a shortfall on this machine is a
recorded result and a standing item for the production phase, not an
inline failure. Dev-only, not in CI.
"""

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from core.canonical import canonical_json, sha256_hex
from core.channels.element import (element_atoms, matched_scores,
                                   rarity_weights, shortlist_groups,
                                   similarity_table, soft_matches,
                                   tier1_scores)
from core.channels.element import element_channel
from core.channels.outline import outline_pool_cache, outline_scores
from core.fusion import fuse
from core.intake import render_submission_strokes
from core.normalize import commonness_correct, standardize
from core.ranking import decoy_set, rank
from core.types import (Atom, ElementConfig, EncodedSubmission, PoolIndex,
                        RenderParams)

BUDGET_MS = 50.0
ATOM_COUNT = 8
ELEMENTS_FOR_EACH_IMAGE = 20
WEIGHTS = {"element": 0.45, "outline": 0.55}


def build_synthetic_index(count: int, dimension: int,
                          vocabulary_count: int, seed: int) -> PoolIndex:
    """One synthetic pool index with the residency cache filled.

    Seeded unit-norm float32 arrays, full incidence rows (the
    heaviest one-group batch), singleton near-duplicate groups, and
    pool frequencies from the incidence tally clamped to one - a
    zero-frequency entry stops rarity_weights, and the clamp shapes
    timing alone, not the scores' meaning.
    """
    rng = np.random.default_rng(seed)

    def unit_rows(shape: tuple[int, ...]) -> np.ndarray:
        rows = rng.standard_normal(shape).astype(np.float32)
        norms = np.linalg.norm(rows, axis=-1, keepdims=True)
        return (rows / norms).astype(np.float32)

    outline_vectors = unit_rows((count, 6, dimension))
    outline_space_mean = (outline_vectors.mean(axis=(0, 1)) * 0.5
                          ).astype(np.float32)
    vocabulary_vectors = unit_rows((vocabulary_count, dimension))
    element_space_mean = (vocabulary_vectors.mean(axis=0) * 0.5
                          ).astype(np.float32)
    incidence = np.stack([
        rng.choice(vocabulary_count, size=ELEMENTS_FOR_EACH_IMAGE,
                   replace=False)
        for _ in range(count)]).astype(np.int32)
    tally = np.bincount(incidence.reshape(-1), minlength=vocabulary_count)
    frequency = tuple(int(max(value, 1)) for value in tally)
    image_ids = tuple(f"{number:064x}" for number in range(count))
    centered, norms = outline_pool_cache(outline_vectors, outline_space_mean)
    return PoolIndex(
        index_id="b" * 64,
        image_ids=image_ids,
        outline_vectors=outline_vectors,
        outline_space_mean=outline_space_mean,
        group_ids=image_ids,
        pool_image_count=count,
        vocabulary=tuple(f"element {n}" for n in range(vocabulary_count)),
        pool_frequency=frequency,
        vocabulary_vectors=vocabulary_vectors,
        incidence=incidence,
        element_space_mean=element_space_mean,
        box_table=np.zeros((count, ELEMENTS_FOR_EACH_IMAGE, 4),
                           dtype=np.float32),
        box_mask=np.zeros((count, ELEMENTS_FOR_EACH_IMAGE), dtype=bool),
        outline_centered=centered,
        outline_norms=norms,
    )


def _submission(dimension: int, seed: int) -> EncodedSubmission:
    """The section 18 shape: 8 text atoms plus one drawing atom."""
    rng = np.random.default_rng(seed + 1)
    atoms = [Atom(id=f"a{n}", type="DESCRIPTION", subtype=None,
                  text=f"impression {n}", strokes=None, refers_to=None,
                  relation=None)
             for n in range(1, ATOM_COUNT + 1)]
    strokes = tuple(
        tuple((float(x) / 12.0 + 0.05 * n, 0.1 + 0.08 * n)
              for x in range(10))
        for n in range(1, 3))
    atoms.append(Atom(id="a9", type="WHOLE-DRAWING", subtype=None,
                      text=None, strokes=strokes, refers_to=None,
                      relation=None))
    vectors = {}
    for atom in atoms:
        row = rng.standard_normal(dimension).astype(np.float32)
        vectors[atom.id] = row / np.float32(np.linalg.norm(row))
    return EncodedSubmission(atoms=tuple(atoms), vectors=vectors)


def _timed(step, repeat: int) -> tuple[float, object]:
    """The median wall time of one step across passes, in ms."""
    value = step()
    times = []
    for _ in range(repeat):
        start = time.perf_counter_ns()
        value = step()
        times.append((time.perf_counter_ns() - start) / 1e6)
    return float(statistics.median(times)), value


def run_bench(count: int, dimension: int, vocabulary_count: int,
              seed: int, repeat: int, clock=None) -> dict:
    """One bench run: the record document, numbers and no verdict."""
    from validation.harness import default_clock, quantized

    index = build_synthetic_index(count, dimension, vocabulary_count, seed)
    submission = _submission(dimension, seed)
    config = ElementConfig(comparison_rule="element-center-cosine-v1",
                           matching_rule="sinkhorn-slack-v1",
                           epsilon=0.1, sinkhorn_iterations=20,
                           tier2_count=500, alpha=1.0)
    from core.types import OutlineConfig
    outline_config = OutlineConfig(comparison_rule="center-cosine-v1")
    render = RenderParams(canvas_px=512, line_width_px=3)
    rng = np.random.default_rng(seed + 2)
    commonness = {name: rng.standard_normal(count).astype(np.float32) * 0.1
                  for name in WEIGHTS}
    target = index.image_ids[0]
    drawing = [atom for atom in submission.atoms
               if atom.type == "WHOLE-DRAWING"][0]
    sketch_vector = submission.vectors[drawing.id]

    stage_ms: dict[str, float] = {}
    stage_ms["render"], _ = _timed(
        lambda: render_submission_strokes(drawing.strokes, None, render),
        repeat)
    atom_vectors = np.stack(
        [submission.vectors[a.id] for a in element_atoms(submission)])
    stage_ms["similarity_table"], similarity = _timed(
        lambda: similarity_table(atom_vectors, index.vocabulary_vectors,
                                 index.element_space_mean), repeat)
    rarity = rarity_weights(similarity, index.pool_frequency, count)

    def tier1_step():
        scores = tier1_scores(similarity, rarity, index.incidence)
        return scores, np.argsort(-scores,
                                  kind="stable")[:config.tier2_count]

    stage_ms["tier1"], (tier1, shortlist) = _timed(tier1_step, repeat)

    def tier2_step():
        scores = tier1.copy()
        for positions, columns in shortlist_groups(shortlist,
                                                   index.incidence):
            tables = similarity[:, columns].transpose(1, 0, 2)
            plans = soft_matches(tables, config)
            scores[positions] = matched_scores(tables, plans, rarity)
        return scores.astype(np.float32)

    stage_ms["tier2"], element_raw = _timed(tier2_step, repeat)
    stage_ms["element_total"], _ = _timed(
        lambda: element_channel(submission, index, config), repeat)
    stage_ms["outline"], outline_raw = _timed(
        lambda: outline_scores(sketch_vector, index, outline_config),
        repeat)
    raw = {"element": element_raw, "outline": outline_raw}
    stage_ms["normalize"], corrected = _timed(
        lambda: {name: standardize(commonness_correct(raw[name],
                                                      commonness[name]))
                 for name in raw}, repeat)
    stage_ms["fuse"], fused = _timed(
        lambda: fuse(corrected, WEIGHTS), repeat)
    stage_ms["rank"], _ = _timed(
        lambda: rank(fused, target, decoy_set(index, target), index),
        repeat)

    def local_total_step():
        element = element_channel(submission, index, config)
        outline = outline_scores(sketch_vector, index, outline_config)
        both = {"element": element, "outline": outline}
        scored = {name: standardize(commonness_correct(both[name],
                                                       commonness[name]))
                  for name in both}
        return rank(fuse(scored, WEIGHTS), target,
                    decoy_set(index, target), index)

    stage_ms["local_total"], _ = _timed(local_total_step, repeat)

    resident = sum(int(array.nbytes) for array in (
        index.outline_vectors, index.outline_centered, index.outline_norms,
        index.vocabulary_vectors, index.incidence))
    cpu = platform.processor() or ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "tool": "bench",
        "dev_only": True,
        "created_at": (clock or default_clock)(),
        "machine": {"platform": platform.platform(), "cpu": cpu,
                    "cpu_count": int(platform.os.cpu_count() or 0)},
        "count": count,
        "dimension": dimension,
        "vocabulary_count": vocabulary_count,
        "elements_for_each_image": ELEMENTS_FOR_EACH_IMAGE,
        "atom_count": ATOM_COUNT,
        "repeat": repeat,
        "seed": seed,
        "weights": dict(WEIGHTS),
        "encoders": "fake",
        "stage_ms": {name: quantized(value)
                     for name, value in stage_ms.items()},
        "budget_ms": BUDGET_MS,
        "resident_bytes": resident,
        "notes": "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.bench")
    parser.add_argument("--count", type=int, default=204)
    parser.add_argument("--dimension", type=int, default=3072)
    parser.add_argument("--vocabulary", type=int, default=1379)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--records-root", default="validation/records")
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    record = run_bench(arguments.count, arguments.dimension,
                       arguments.vocabulary, arguments.seed,
                       arguments.repeat)
    print(json.dumps(record, indent=1, sort_keys=True))
    if arguments.write:
        name = f"bench-{arguments.count}-" \
            f"{sha256_hex(canonical_json(record))[:8]}.json"
        path = Path(arguments.records_root) / name
        path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
        print(f"record={path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
