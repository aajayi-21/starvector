"""The synthetic submission generator (spec P4 section 8, source B).

Pure functions: pool index in, wire-shape submission out, at a written
degradation level, with the source image kept as the label. The RNG
comes in as an argument and each submission draws from its own seeded
generator, thus a set reproduces byte-for-byte (R12).

The wire shape is the frozen Layer 0 record: sampled and generalized
element strings become impressions rows, and relations become two
labeled stroke groups — a rectangle at each element's box — plus a
relations row naming them. The record then walks the production path
with no special rule for it: the group atoms hold text and strokes,
the rectangle strokes make the WHOLE-DRAWING atom, and Layer 1
assembles the atoms (I5).
"""

from collections.abc import Mapping, Sequence
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import PlacementConfig, PoolIndex
from validation.fitconfig import FitConfig, LevelRow, fit_config_to_json_value

GENERATOR_RULE = "synthetic-v1"

# The relation truth rule: the axis with the larger center distance
# decides, and the sign picks the direction. Written here because the
# generator and the channel must agree on what a relation means.
_HORIZONTAL = ("left-of", "right-of")
_VERTICAL = ("above", "below")


class SyntheticSubmission(NamedTuple):
    """One generated submission with its label kept (section 19)."""

    key: str
    record: JsonValue
    image_id: str
    level: int


def generator_config_hash(config: FitConfig, vocabulary_digest: str,
                          table_digest: str, area_cap: float) -> str:
    """The generator identity (spec P4 section 6).

    Covers the level table, the rule version, the vocabulary content,
    the generalization table content, and the area cap the relation
    sampler reads — each change forks the synthetic-set lineage
    (R11).
    """
    return sha256_hex(canonical_json({
        "rule": GENERATOR_RULE,
        "levels": fit_config_to_json_value(config)["generator"]["levels"],
        "vocabulary_digest": vocabulary_digest,
        "table_digest": table_digest,
        "area_cap": area_cap,
    }))


def _submission_rng(seed: int, position: int) -> np.random.Generator:
    """One seeded generator for each submission, sequence-free."""
    material = sha256_hex(f"{GENERATOR_RULE}:{seed}:{position}")
    return np.random.default_rng(int(material[:16], 16))


def _image_elements(index: PoolIndex, position: int) -> list[int]:
    """The vocabulary entries of one image, in slot sequence."""
    row = index.incidence[position]
    return [int(entry) for entry in row if entry >= 0]


def _located_slots(index: PoolIndex, position: int,
                   placement: PlacementConfig) -> list[int]:
    """The slots with a box a relation can attach to (D3, D4)."""
    kept = []
    row = index.incidence[position]
    for slot, entry in enumerate(row):
        if entry < 0 or not bool(index.box_mask[position, slot]):
            continue
        box = index.box_table[position, slot]
        area = float((box[2] - box[0]) * (box[3] - box[1]))
        if area < placement.area_cap:
            kept.append(slot)
    return kept


def relation_between(box_a: Sequence[float],
                     box_b: Sequence[float]) -> str:
    """The relation the two box centers imply (D3).

    The axis with the larger center distance decides. The canvas y
    axis points down, thus a smaller y is above.
    """
    dx = ((box_b[0] + box_b[2]) - (box_a[0] + box_a[2])) / 2.0
    dy = ((box_b[1] + box_b[3]) - (box_a[1] + box_a[3])) / 2.0
    if abs(dx) >= abs(dy):
        return _HORIZONTAL[0] if dx > 0 else _HORIZONTAL[1]
    return _VERTICAL[0] if dy > 0 else _VERTICAL[1]


def _rectangle_stroke(box: Sequence[float]) -> list[list[float]]:
    """A closed rectangle polyline along one box's edges.

    The perimeter carries the ink the Layer 0 gate counts, and the
    stroke bounding box is the element box itself — which is what the
    placement locating rule reads back (decision 5).
    """
    x_min, y_min, x_max, y_max = (float(v) for v in box)
    return [[x_min, y_min], [x_max, y_min], [x_max, y_max],
            [x_min, y_max], [x_min, y_min]]


def _noise_box(rng: np.random.Generator) -> list[float]:
    """A seeded box for a noise group — the thing is not there."""
    x_min = float(rng.uniform(0.0, 0.7))
    y_min = float(rng.uniform(0.0, 0.7))
    return [x_min, y_min, x_min + float(rng.uniform(0.1, 0.3)),
            y_min + float(rng.uniform(0.1, 0.3))]


def _noise_entries(index: PoolIndex, position: int, count: int,
                   rng: np.random.Generator) -> list[int]:
    """Noise atoms: entries drawn from the element lists of other images.

    Raises when no other image holds an entry that is not in this
    image's own elements — the sample loop can then not end, and a
    loud stop beats a hang (CLAUDE.md section 3). The check does not
    touch the RNG, thus the output stays byte-stable.
    """
    entries: list[int] = []
    own = set(_image_elements(index, position))
    image_count = len(index.image_ids)
    if count > 0 and not any(
            other != position
            and any(entry not in own
                    for entry in _image_elements(index, other))
            for other in range(image_count)):
        raise ValueError(
            f"no noise entry is possible for image {position}: no other "
            "image holds an element outside its own list")
    while len(entries) < count:
        other = int(rng.integers(0, image_count))
        if other == position and image_count > 1:
            continue
        candidates = [entry for entry in _image_elements(index, other)
                      if entry not in own]
        if not candidates:
            continue
        entries.append(candidates[int(rng.integers(0, len(candidates)))])
    return entries


def synthetic_submission(index: PoolIndex, position: int, level: LevelRow,
                         table: Mapping[str, str],
                         placement: PlacementConfig,
                         rng: np.random.Generator) -> JsonValue:
    """One wire-shape record from the pool image at position (D1).

    Sample without replacement, generalize each sample with the
    level's probability through the table, add noise atoms from other
    images, and at levels with relations add labeled rectangle groups
    — the box geometry implies their relation. At a level with
    corrupt_relation set, the last relation names a noise group at a
    seeded box — a stated relation about something not there (D3,
    amended 2026-08-10: the flag is config, not a noise-count
    inference).
    """
    own = _image_elements(index, position)
    n_atoms = min(level.n_atoms, len(own))
    picked = [own[int(i)] for i in
              rng.choice(len(own), size=n_atoms, replace=False)] \
        if n_atoms else []
    impressions = []
    for entry in picked:
        text = index.vocabulary[entry]
        if level.generalize_p > 0.0 and rng.random() < level.generalize_p:
            text = table.get(text, text)
        impressions.append(text)
    for entry in _noise_entries(index, position, level.n_noise, rng):
        impressions.append(index.vocabulary[entry])

    strokes: list[JsonValue] = []
    groups: list[JsonValue] = []
    relations: list[JsonValue] = []
    if level.relations > 0:
        located = _located_slots(index, position, placement)
        rng.shuffle(located)
        corrupt_last = level.corrupt_relation

        def add_group(label: str, box: Sequence[float]) -> str:
            group_id = f"g{len(groups) + 1}"
            groups.append({"id": group_id, "label": label})
            strokes.append({"points": _rectangle_stroke(box),
                            "group_id": group_id})
            return group_id

        for number in range(level.relations):
            first_slot = located[2 * number] \
                if 2 * number < len(located) else None
            second_slot = located[2 * number + 1] \
                if 2 * number + 1 < len(located) else None
            if first_slot is None or (second_slot is None
                                      and not corrupt_last):
                break
            box_a = [float(v) for v in index.box_table[position, first_slot]]
            label_a = index.vocabulary[
                int(index.incidence[position, first_slot])]
            last = number == level.relations - 1
            if corrupt_last and (last or second_slot is None):
                noise = _noise_entries(index, position, 1, rng)
                box_b = _noise_box(rng)
                label_b = index.vocabulary[noise[0]]
            else:
                box_b = [float(v)
                         for v in index.box_table[position, second_slot]]
                label_b = index.vocabulary[
                    int(index.incidence[position, second_slot])]
            first_id = add_group(label_a, box_a)
            second_id = add_group(label_b, box_b)
            relations.append({
                "relation": relation_between(box_a, box_b),
                "of": [first_id, second_id],
            })

    return {
        "impressions": impressions,
        "canvas_strokes": strokes,
        "groups": groups,
        "relations": relations,
        "pasted_text": None,
    }


def synthetic_set(index: PoolIndex, config: FitConfig,
                  table: Mapping[str, str], placement: PlacementConfig,
                  seed: int, count: int,
                  level_index: int | None = None,
                  ) -> tuple[SyntheticSubmission, ...]:
    """A labeled synthetic set, byte-stable for one seed (R12).

    The source image and the level come from each submission's own
    seeded generator — a modulo cycle correlates the two, because
    the level count divides the dev image count. Keys sort by their
    zero-filled number, thus a set arrives in ascending key sequence.
    """
    levels = config.generator.levels
    rows = []
    for number in range(count):
        rng = _submission_rng(seed, number)
        position = int(rng.integers(0, len(index.image_ids)))
        chosen = level_index if level_index is not None \
            else int(rng.integers(0, len(levels)))
        record = synthetic_submission(index, position, levels[chosen],
                                      table, placement, rng)
        rows.append(SyntheticSubmission(
            key=f"synthetic://{seed}/{number:06d}",
            record=record,
            image_id=index.image_ids[position],
            level=chosen,
        ))
    return tuple(rows)
