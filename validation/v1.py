"""The V1 harness: does the style bridge work? (spec P2 section 12).

Builds the union index in memory (D7): the paired photographs go
through the same line-drawer and image-encoder providers and
image-level caches as the pool (Rule 3), near-duplicate grouping runs
again across the union, and the union gets its own commonness table.
Each selected sketch then runs the full scoring path with its paired
photograph as the target. The go or no-go on the bridge is a recorded
human decision on the reported numbers.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np

from core.canonical import JsonValue, sha256_hex
from core.channels.element import match_report
from core.intake import validate_submission
from core.types import PoolIndex
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             fusion_weights, intake_gates, load_scoring_config,
                             outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import (ElementSide, LoadedPreparation, build_pool_index,
                              build_scoring_context, load_pool_index)
from pipeline.score import encode_submission, score_trial
from pool.artifacts import (vector_path, write_bytes_atomic, write_json_pretty,
                            write_jsonl)
from pool.curation.stages.release import membership_hash
from pool.preparation import manifest as mf
from pool.preparation.config import (PreparationConfig,
                                     load_preparation_config)
from pool.preparation.run import wire_slot
from pool.preparation.stages.cap import cap_with_frequencies
from pool.preparation.stages.neardup import neardup_groups
from pool.preparation.stages.normalize import normalize_elements
from pool.preparation.stages.outline import (outline_crop_images,
                                             photo_canonical,
                                             photo_source_token)
from pool.preparation.types import GroupRow
from validation import harness
from validation.splits import select_keys

_PHOTO_ENCODE_CHUNK = 10

# How many photographs go to the describer and the text encoder in one
# batch. The p01 and p04 stages use the same width.
_DESCRIBE_CHUNK = 256


def _check_shared_space(config: ScoringConfig,
                        prep_config: PreparationConfig) -> None:
    """R7: the sketch encoder must fill the p06 vector space.

    The outline channel compares the two, thus a dimension or model
    that does not agree makes each cosine meaningless.
    """
    sketch = config.providers.sketch_encoder
    image = prep_config.providers.image_encoder
    if (sketch.dimension is not None and image.dimension is not None
            and sketch.dimension != image.dimension):
        raise ValueError(
            f"R7: sketch_encoder dimension {sketch.dimension} does not "
            f"agree with the p06 image_encoder dimension {image.dimension}")
    if sketch.provider == "openrouter" and image.provider == "openrouter":
        sketch_model = sketch.model \
            or config.providers.openrouter.default_model
        image_model = image.model \
            or prep_config.providers.openrouter.default_model
        if sketch_model != image_model:
            raise ValueError(
                f"R7: sketch_encoder model {sketch_model!r} does not "
                f"agree with the p06 image_encoder model {image_model!r}")


def build_union_elements(
    loaded: LoadedPreparation, prep_config: PreparationConfig,
    photo_bytes_by_id: dict[str, bytes], union_ids: tuple[str, ...],
    describer, text_encoder,
) -> ElementSide:
    """The element side of the union index (spec P3 section 12, D8).

    The photographs get element lists through the same capability path
    the pool went through (Rule 3): the p01 describer slot with its
    response cache, then the p02 normalization and the p03 cap as pure
    functions. The cap reads the pool's document frequencies, and an
    element the pool does not name takes frequency 1 — it appears in no
    pool image, which is the rarest an element can be.

    Photograph elements the pool does not name append to the element
    bank above the pool vocabulary. pool_frequency and pool_image_count
    do not move, thus an atom's rarity weight is the same number here
    as in a plain-pool trial (R1).
    """
    pool_ids = set(loaded.index.image_ids)
    new_ids = sorted(set(photo_bytes_by_id) - pool_ids)

    responses = []
    for start in range(0, len(new_ids), _DESCRIBE_CHUNK):
        chunk = new_ids[start:start + _DESCRIBE_CHUNK]
        answered = describer.describe_images(
            [photo_bytes_by_id[image_id] for image_id in chunk])
        if len(answered) != len(chunk):
            raise ValueError(
                f"the describer answered {len(answered)} of {len(chunk)} "
                "photographs")
        responses.extend(answered)

    frequency_of = {element: frequency for element, frequency
                    in zip(loaded.index.vocabulary,
                           loaded.index.pool_frequency)}
    capped, _ = cap_with_frequencies(
        new_ids, [normalize_elements(response) for response in responses],
        prep_config.elements.max_elements, frequency_of,
        loaded.index.pool_image_count)

    known = {element: position for position, element
             in enumerate(loaded.index.vocabulary)}
    unknown = sorted({element for sequence in capped for element in sequence
                      if element not in known})
    vectors = [loaded.index.vocabulary_vectors]
    dimension = loaded.index.vocabulary_vectors.shape[1]
    for start in range(0, len(unknown), _DESCRIBE_CHUNK):
        chunk = unknown[start:start + _DESCRIBE_CHUNK]
        rows = text_encoder.encode_texts(chunk)          # (B, d)
        if rows.shape != (len(chunk), dimension):
            raise ValueError(
                f"the text encoder returned shape {rows.shape} for "
                f"{len(chunk)} strings at dimension {dimension}")
        vectors.append(rows.astype(np.float32))
    for position, element in enumerate(unknown):
        known[element] = len(loaded.index.vocabulary) + position

    width = loaded.index.incidence.shape[1]
    incidence = np.full((len(union_ids), width), -1, dtype=np.int32)
    box_table = np.zeros((len(union_ids), width, 4), dtype=np.float32)
    box_mask = np.zeros((len(union_ids), width), dtype=np.bool_)
    pool_position = {image_id: position for position, image_id
                     in enumerate(loaded.index.image_ids)}
    photograph_elements = dict(zip(new_ids, capped))
    for position, image_id in enumerate(union_ids):
        if image_id in pool_position:
            incidence[position] = loaded.index.incidence[
                pool_position[image_id]]
            box_table[position] = loaded.index.box_table[
                pool_position[image_id]]
            box_mask[position] = loaded.index.box_mask[
                pool_position[image_id]]
            continue
        # Photographs hold no boxes: the p07 slot has not run on them,
        # and a placement-active union run must build them first
        # through the same detector path (spec P4 section 7). The
        # slots stay off, thus a photograph does not fire placement.
        elements = photograph_elements[image_id]
        if not elements:
            raise ValueError(
                f"photograph {image_id[:8]}: the describer named no element "
                "that survived normalization")
        if len(elements) > width:
            raise ValueError(
                f"photograph {image_id[:8]}: {len(elements)} elements do not "
                f"fit the incidence width {width}")
        for column, element in enumerate(elements):
            incidence[position, column] = known[element]

    return ElementSide(
        vocabulary=loaded.index.vocabulary + tuple(unknown),
        pool_frequency=loaded.index.pool_frequency,
        pool_image_count=loaded.index.pool_image_count,
        vocabulary_vectors=np.concatenate(vectors, axis=0),
        incidence=incidence,
        element_space_mean=loaded.index.element_space_mean,
        box_table=box_table,
        box_mask=box_mask,
    )


def _match_report_row(pair_key: str, record: JsonValue, image_id: str,
                      context, encoders, union_position: dict[str, int],
                      element) -> dict[str, JsonValue]:
    """One trial's atom-by-atom correspondence row (D12).

    This runs after ranking, with the paired photograph as the chosen
    image: the report is a review instrument and the seed of the
    architecture section 27 player feedback. It is an input to no
    score. The submission is encoded a second time here and is not
    carried out of score_trial, because the Layer 8 contract stays as
    it is and the provider answers the second batch from its cache.
    """
    submission = validate_submission(record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, encoders)
    rows = match_report(encoded, context.index, union_position[image_id],
                        element)
    return {
        "pair_key": pair_key,
        "atoms": [
            {"atom_id": row.atom_id, "atom_text": row.atom_text,
             "element": row.element,
             "weight": harness.quantized(row.weight),
             "similarity": harness.quantized(row.similarity),
             "rarity": harness.quantized(row.rarity)}
            for row in rows
        ],
    }


@dataclass(frozen=True, slots=True)
class V1TrialRow:
    pair_key: str
    p: float
    decoy_count: int
    beaten: int
    tied: int
    target_rank: int
    input_class: str


@dataclass(frozen=True, slots=True)
class V1Report:
    index_id: str
    harness_config_hash: str
    submission_mode: str
    pair_count: int
    first_rank_fraction: float
    top_ten_fraction: float
    mean_trial_score: float
    median_rank: float
    reference_first: float
    reference_top_ten: float
    usage: tuple[tuple[str, tuple[int, int]], ...]
    dataset_bytes_retrieved: int
    record_path: str | None
    trials: tuple[V1TrialRow, ...]


def build_union_index(
    loaded: LoadedPreparation, prep_config: PreparationConfig,
    photo_bytes_by_id: dict[str, bytes], dataset_config_hash: str,
    data_root: Path, line_drawer: object | None, image_encoder: object,
    describer: object, text_encoder: object,
) -> PoolIndex:
    """The V1 union index: pool plus photographs, one path (Rule 3).

    Photographs go through the same providers and image-level caches
    as p05 and p06 — the drawing cache keyed by the drawer hash, the
    vector cache keyed by the combined hash sha256(encoder hash +
    drawer hash). With outline.source = "photo" (spec P2c sections 4
    and 6) the drawer is None, each photograph goes through the same
    canonical render and crop path as stage p06, and the vector cache
    key holds the photograph token in the drawer-hash position.
    Near-duplicate grouping runs again across the union at the
    preparation threshold, and the stored p06 mean stays the
    centering (spec P2 section 12). The element side comes from
    build_union_elements (spec P3 section 12).
    """
    photo_source = prep_config.outline.source == "photo"
    grayscale = prep_config.outline.photo_render == "grayscale"
    encoder_hash = str(getattr(image_encoder, "config_hash"))
    if photo_source:
        drawer_hash = None
        combined_hash = sha256_hex(
            encoder_hash + photo_source_token(prep_config.linedraw.canvas_px,
                                              grayscale))
    else:
        drawer_hash = str(getattr(line_drawer, "config_hash"))
        combined_hash = sha256_hex(encoder_hash + drawer_hash)

    pool_ids = set(loaded.index.image_ids)
    new_ids = sorted(set(photo_bytes_by_id) - pool_ids)

    # Line drawings first, then vectors, in ascending image_id chunks.
    missing_vectors = [image_id for image_id in new_ids
                       if not vector_path(data_root, combined_hash,
                                          image_id).is_file()]
    if not photo_source:
        for image_id in missing_vectors:
            drawing_path = mf.linedraw_path(data_root, drawer_hash, image_id)
            if not drawing_path.is_file():
                drawing = line_drawer.draw_lines(
                    [photo_bytes_by_id[image_id]])[0]
                write_bytes_atomic(drawing_path, drawing)
    for start in range(0, len(missing_vectors), _PHOTO_ENCODE_CHUNK):
        chunk = missing_vectors[start:start + _PHOTO_ENCODE_CHUNK]
        crops: list[bytes] = []
        for image_id in chunk:
            if photo_source:
                source_image = photo_canonical(
                    photo_bytes_by_id[image_id],
                    prep_config.linedraw.canvas_px, grayscale)
            else:
                source_image = mf.linedraw_path(
                    data_root, drawer_hash, image_id).read_bytes()
            crops.extend(outline_crop_images(
                source_image, prep_config.outline.crop_fraction))
        encoded = image_encoder.encode_images(crops)   # (6 * B, d)
        if encoded.shape[0] != len(crops):
            raise ValueError(
                f"image encoder returned {encoded.shape[0]} rows for "
                f"{len(crops)} crops — a miscounted batch must not enter "
                "the shared p06 vector cache")
        for position, image_id in enumerate(chunk):
            rows = np.ascontiguousarray(
                encoded[position * 6:(position + 1) * 6]).astype(np.float32)
            mf.save_npy_atomic(
                vector_path(data_root, combined_hash, image_id), rows)

    union_ids = tuple(sorted(pool_ids | set(photo_bytes_by_id)))
    dimension = loaded.index.outline_vectors.shape[2]
    stacked = np.zeros((len(union_ids), 6, dimension), dtype=np.float32)
    pool_position = {image_id: position for position, image_id
                     in enumerate(loaded.index.image_ids)}
    for position, image_id in enumerate(union_ids):
        if image_id in pool_position:
            stacked[position] = loaded.index.outline_vectors[
                pool_position[image_id]]
        else:
            rows = np.load(vector_path(data_root, combined_hash, image_id))
            if rows.shape != (6, dimension) or rows.dtype != np.float32:
                raise ValueError(
                    f"photograph {image_id[:8]}: cached vectors have shape "
                    f"{rows.shape} dtype {rows.dtype}")
            stacked[position] = rows

    full_rows = np.ascontiguousarray(stacked[:, 0, :])   # (N', d)
    group_rows, _ = neardup_groups(
        list(union_ids), full_rows,
        prep_config.neardup.similarity_threshold)
    union_id = sha256_hex(
        loaded.record.preparation_version_id + dataset_config_hash
        + membership_hash(sorted(photo_bytes_by_id)))
    return build_pool_index(
        index_id=union_id,
        image_ids=union_ids,
        outline_vectors=stacked,
        outline_space_mean=loaded.index.outline_space_mean,
        group_rows=tuple(
            GroupRow(image_id=row.image_id, group_id=row.group_id,
                     member_count=row.member_count)
            for row in group_rows),
        elements=build_union_elements(loaded, prep_config, photo_bytes_by_id,
                                      union_ids, describer, text_encoder),
    )


def run_v1(config: ScoringConfig, *, data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> V1Report:
    """One full V1 run: union index, commonness, trials, record."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    prep_config = load_preparation_config(Path(loaded.record.config_path))
    _check_shared_space(config, prep_config)

    mode = config.validation.submission_mode
    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    keys = harness.pair_keys_of(source)
    fractions = config.commonness.split_fractions
    salt = config.commonness.split_salt
    v1_keys = select_keys(keys, salt, fractions, "v1",
                          config.validation.v1_pair_count)
    synthetic = config.commonness.synthetic
    dataset_count = config.commonness.background_count \
        - (synthetic.count if synthetic else 0)
    background_keys = select_keys(keys, salt, fractions, "background",
                                  dataset_count)
    pairs = harness.pairs_by_key(source, set(v1_keys) | set(background_keys))
    # Pre-flight before the encoder spend: each selected pair (trial
    # and background) must build in this mode and clear the gates.
    harness.check_selected_pairs(pairs, v1_keys + background_keys,
                                 intake_gates(config),
                                 loaded.render.canvas_px, mode)

    # With a photograph-source preparation no drawer is wired (P2c
    # R4) — the row leaves the Rule 3 guard because the slot leaves
    # the photograph path, not because the guard loosens.
    photo_source = prep_config.outline.source == "photo"
    prepared_slots = ("image_encoder", "describer", "text_encoder")
    if not photo_source:
        prepared_slots = ("line_drawer",) + prepared_slots
    wired = {name: providers.get(name) or wire_slot(name, prep_config,
                                                    data_root)
             for name in prepared_slots}
    record_hashes = dict(loaded.record.provider_config_hashes)
    for slot_name in prepared_slots:
        measured = str(getattr(wired[slot_name], "config_hash"))
        if measured != record_hashes[slot_name]:
            raise ValueError(
                f"{slot_name}: wired hash {measured[:8]} does not agree "
                f"with the preparation record {record_hashes[slot_name][:8]} "
                "— the photograph path must equal the pool path (Rule 3)")
    line_drawer = wired.get("line_drawer")
    image_encoder = wired["image_encoder"]

    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(record_hashes, slot_hashes)
    dataset_hash = slot_hashes["sketch_pairs"]
    scoring_hash = scoring_config_hash(config, slot_hashes)
    harness_hash = harness.harness_config_hash("v1", scoring_hash)

    photo_bytes_by_id = {
        sha256_hex(pairs[key].photo_bytes): pairs[key].photo_bytes
        for key in v1_keys}
    drawer_delta = None if photo_source else harness.UsageDelta(line_drawer)
    encoder_delta = harness.UsageDelta(image_encoder)
    describer_delta = harness.UsageDelta(wired["describer"])
    # The union element side encodes its strings through the
    # preparation text_encoder slot, which is a second instance of the
    # same configuration as the scoring slot. Its use is counted apart,
    # so the reported totals cover each string the run encodes (U1).
    union_text_delta = harness.UsageDelta(wired["text_encoder"])
    union_index = build_union_index(
        loaded, prep_config, photo_bytes_by_id, dataset_hash, data_root,
        line_drawer, image_encoder, wired["describer"],
        wired["text_encoder"])

    encoders = harness.wire_encoders(config, data_root, providers)
    sketch_delta = harness.UsageDelta(encoders.sketch)
    text_delta = harness.UsageDelta(encoders.text)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], dataset_hash, generator_hash)
    weights = fusion_weights(config)
    element = element_config(config)
    placement = placement_config(config)

    def background_records() -> list[tuple[str, JsonValue]]:
        rows = [(key, harness.submission_record(pairs[key], mode))
                for key in background_keys]
        # The generator reads the plain pool index — elements, boxes,
        # and the table are pool quantities. The records then score
        # against this run's index like each background record.
        rows.extend(harness.synthetic_background(
            config, loaded.index, placement, data_root,
            providers.get("generalizer")))
        rows.sort(key=lambda entry: entry[0])
        return rows

    tables = ensure_commonness_tables(
        data_root=data_root, index=union_index,
        commonness_hash=commonness_hash, background=background_records,
        gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element,
        placement=placement, encoders=encoders,
        submission_mode=mode, clock=clock)

    context = build_scoring_context(
        index=union_index, gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element,
        placement=placement, weights=weights,
        commonness=tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    union_position = {image_id: position for position, image_id
                      in enumerate(union_index.image_ids)}
    trial_records = {key: harness.submission_record(pairs[key], mode)
                     for key in v1_keys}
    harness.prewarm_records(list(trial_records.values()),
                            intake_gates(config), loaded.render, encoders)
    reports: list[dict[str, JsonValue]] = []
    trials: list[V1TrialRow] = []
    for key in v1_keys:
        pair = pairs[key]
        record = trial_records[key]
        image_id = sha256_hex(pair.photo_bytes)
        trial = score_trial(record, image_id, context, encoders)
        reports.append(_match_report_row(key, record, image_id, context,
                                         encoders, union_position, element))
        # Strict rank: the decoys above the target, plus one. A tied
        # decoy does not push the rank down — p carries the half-credit
        # rule (rare at float32, spec section 12).
        target_rank = trial.decoy_count - trial.beaten - trial.tied + 1
        trials.append(V1TrialRow(
            pair_key=key, p=trial.p, decoy_count=trial.decoy_count,
            beaten=trial.beaten, tied=trial.tied, target_rank=target_rank,
            input_class="vector"))

    count = len(trials)
    first_rank = sum(1 for row in trials if row.target_rank == 1) / count
    top_ten = sum(1 for row in trials if row.target_rank <= 10) / count
    mean_p = sum(row.p for row in trials) / count
    median_rank = float(np.median([row.target_rank for row in trials]))
    reference_first = sum(1.0 / (row.decoy_count + 1)
                          for row in trials) / count
    reference_top_ten = sum(min(1.0, 10.0 / (row.decoy_count + 1))
                            for row in trials) / count
    usage = (
        ("sketch_encoder", (sketch_delta.posts, sketch_delta.cache_hits)),
        ("text_encoder", (text_delta.posts, text_delta.cache_hits)),
        ("union_text_encoder", (union_text_delta.posts,
                                union_text_delta.cache_hits)),
        *(() if drawer_delta is None else
          (("line_drawer", (drawer_delta.posts, drawer_delta.cache_hits)),)),
        ("image_encoder", (encoder_delta.posts, encoder_delta.cache_hits)),
        ("describer", (describer_delta.posts, describer_delta.cache_hits)),
    )

    directory = harness.validation_dir(data_root, "v1", union_index.index_id,
                                       harness_hash)
    write_jsonl(directory / "trials.jsonl", [
        {"pair_key": row.pair_key, "p": harness.quantized(row.p),
         "decoy_count": row.decoy_count, "beaten": row.beaten,
         "tied": row.tied, "target_rank": row.target_rank,
         "input_class": row.input_class}
        for row in trials])
    write_jsonl(directory / "match_reports.jsonl", reports)
    aggregates: dict[str, JsonValue] = {
        "pair_count": count,
        "first_rank_fraction": harness.quantized(first_rank),
        "top_ten_fraction": harness.quantized(top_ten),
        "mean_trial_score": harness.quantized(mean_p),
        "median_rank": harness.quantized(median_rank),
        "reference_first": harness.quantized(reference_first),
        "reference_top_ten": harness.quantized(reference_top_ten),
    }
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v1",
        "submission_mode": mode,
        "index_id": union_index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "commonness_config_hash": commonness_hash,
        "dataset_config_hash": dataset_hash,
        "preparation_version_id": loaded.record.preparation_version_id,
        "provider_usage": {slot: {"posts": posts, "cache_hits": hits}
                           for slot, (posts, hits) in usage},
        "dataset_bytes_retrieved": int(source.bytes_retrieved),
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    record_path = None
    if count == config.validation.v1_pair_count:
        content: dict[str, JsonValue] = {
            "harness": "v1",
            "tag": config.validation.tag,
            "dev_only": config.report.dev_only,
            **aggregates,
            "index_id": union_index.index_id,
            "harness_config_hash": harness_hash,
            "scoring_config_hash": scoring_hash,
            "commonness_config_hash": commonness_hash,
            "dataset_config_hash": dataset_hash,
            "preparation_version_id": loaded.record.preparation_version_id,
            "provider_usage": {slot: {"posts": posts, "cache_hits": hits}
                               for slot, (posts, hits) in usage},
            "dataset_bytes_retrieved": int(source.bytes_retrieved),
            "fusion_weights": dict(config.fusion.weights),
            "fusion_weights_fitted": config.fusion.fit_record is not None,
            "fit_record": config.fusion.fit_record,
            "created_at": clock(),
            "code_version": code_version,
            **harness.VERDICT_TEMPLATE,
        }
        record_path = str(harness.write_harness_record(
            records_root, "v1", config.validation.tag, harness_hash, content))

    return V1Report(
        index_id=union_index.index_id, harness_config_hash=harness_hash,
        submission_mode=mode,
        pair_count=count, first_rank_fraction=first_rank,
        top_ten_fraction=top_ten, mean_trial_score=mean_p,
        median_rank=median_rank, reference_first=reference_first,
        reference_top_ten=reference_top_ten, usage=usage,
        dataset_bytes_retrieved=int(source.bytes_retrieved),
        record_path=record_path, trials=tuple(trials))


def format_report(report: V1Report) -> str:
    """The numbers, one for each line (CLAUDE.md section 11)."""
    lines = [
        f"v1 {report.index_id[:8]}  harness c{report.harness_config_hash[:8]}",
        f"submission_mode={report.submission_mode}",
        f"pairs={report.pair_count}",
        f"first_rank_fraction={report.first_rank_fraction:.4f} "
        f"(reference {report.reference_first:.4f})",
        f"top_ten_fraction={report.top_ten_fraction:.4f} "
        f"(reference {report.reference_top_ten:.4f})",
        f"mean_trial_score={report.mean_trial_score:.4f}",
        f"median_rank={report.median_rank:.1f}",
    ]
    for slot, (posts, hits) in report.usage:
        lines.append(f"{slot}: posts={posts} cache_hits={hits}")
    lines.append(f"dataset_bytes_retrieved={report.dataset_bytes_retrieved}")
    if report.record_path:
        lines.append(f"record={report.record_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v1")
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--records-root", default="validation/records")
    parser.add_argument("--report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        config = load_scoring_config(Path(arguments.config))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    report = run_v1(config, data_root=Path(arguments.data_root),
                    records_root=Path(arguments.records_root))
    if arguments.report:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
