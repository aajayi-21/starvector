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
from core.types import PoolIndex
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_table)
from pipeline.config import (ConfigError, ScoringConfig, fusion_weights,
                             intake_gates, load_scoring_config,
                             outline_config, scoring_config_hash)
from pipeline.context import (LoadedPreparation, build_pool_index,
                              build_scoring_context, load_pool_index)
from pipeline.score import score_trial
from pool.artifacts import (vector_path, write_bytes_atomic, write_json_pretty,
                            write_jsonl)
from pool.curation.stages.release import membership_hash
from pool.preparation import manifest as mf
from pool.preparation.config import (PreparationConfig,
                                     load_preparation_config)
from pool.preparation.run import wire_slot
from pool.preparation.stages.neardup import neardup_groups
from pool.preparation.stages.outline import outline_crop_images
from pool.preparation.types import GroupRow
from providers.protocols import SketchPair
from validation import harness
from validation.splits import select_keys

_PHOTO_ENCODE_CHUNK = 10


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
    data_root: Path, line_drawer: object, image_encoder: object,
) -> PoolIndex:
    """The V1 union index: pool plus photographs, one path (Rule 3).

    Photographs go through the same providers and image-level caches
    as p05 and p06 — the drawing cache keyed by the drawer hash, the
    vector cache keyed by the combined hash sha256(encoder hash +
    drawer hash). Near-duplicate grouping runs again across the union
    at the preparation threshold, and the stored p06 mean stays the
    centering (spec section 12).
    """
    drawer_hash = str(getattr(line_drawer, "config_hash"))
    encoder_hash = str(getattr(image_encoder, "config_hash"))
    combined_hash = sha256_hex(encoder_hash + drawer_hash)

    pool_ids = set(loaded.index.image_ids)
    new_ids = sorted(set(photo_bytes_by_id) - pool_ids)

    # Line drawings first, then vectors, in ascending image_id chunks.
    missing_vectors = [image_id for image_id in new_ids
                       if not vector_path(data_root, combined_hash,
                                          image_id).is_file()]
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
            drawing_path = mf.linedraw_path(data_root, drawer_hash, image_id)
            crops.extend(outline_crop_images(
                drawing_path.read_bytes(),
                prep_config.outline.crop_fraction))
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

    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    keys = harness.pair_keys_of(source)
    fractions = config.commonness.split_fractions
    salt = config.commonness.split_salt
    v1_keys = select_keys(keys, salt, fractions, "v1",
                          config.validation.v1_pair_count)
    background_keys = select_keys(keys, salt, fractions, "background",
                                  config.commonness.background_count)
    pairs = harness.pairs_by_key(source, set(v1_keys) | set(background_keys))
    # Pre-flight before the encoder spend: each selected sketch (trial
    # and background) must clear the Layer 0 gates.
    harness.check_selected_pairs(pairs, v1_keys + background_keys,
                                 intake_gates(config),
                                 loaded.render.canvas_px)

    line_drawer = providers.get("line_drawer") or wire_slot(
        "line_drawer", prep_config, data_root)
    image_encoder = providers.get("image_encoder") or wire_slot(
        "image_encoder", prep_config, data_root)
    record_hashes = dict(loaded.record.provider_config_hashes)
    for slot_name, provider in (("line_drawer", line_drawer),
                                ("image_encoder", image_encoder)):
        measured = str(getattr(provider, "config_hash"))
        if measured != record_hashes[slot_name]:
            raise ValueError(
                f"{slot_name}: wired hash {measured[:8]} does not agree "
                f"with the preparation record {record_hashes[slot_name][:8]} "
                "— the photograph path must equal the pool path (Rule 3)")

    slot_hashes = harness.scoring_provider_hashes(config, providers)
    dataset_hash = slot_hashes["sketch_pairs"]
    scoring_hash = scoring_config_hash(config, slot_hashes)
    harness_hash = harness.harness_config_hash("v1", scoring_hash)

    photo_bytes_by_id = {
        sha256_hex(pairs[key].photo_bytes): pairs[key].photo_bytes
        for key in v1_keys}
    drawer_delta = harness.UsageDelta(line_drawer)
    encoder_delta = harness.UsageDelta(image_encoder)
    union_index = build_union_index(
        loaded, prep_config, photo_bytes_by_id, dataset_hash, data_root,
        line_drawer, image_encoder)

    sketch_encoder = providers.get("sketch_encoder") \
        or harness.wire_sketch_encoder(config, data_root)
    sketch_delta = harness.UsageDelta(sketch_encoder)
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"], dataset_hash)

    def background_pairs() -> list[SketchPair]:
        rows = [pairs[key] for key in background_keys]
        rows.sort(key=lambda pair: pair.pair_key)
        return rows

    table = ensure_commonness_table(
        data_root=data_root, index=union_index,
        commonness_hash=commonness_hash, background=background_pairs,
        render=loaded.render, outline=outline_config(config),
        encoder=sketch_encoder, clock=clock)

    context = build_scoring_context(
        index=union_index, gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), weights=fusion_weights(config),
        commonness={"outline": table.table},
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    trials: list[V1TrialRow] = []
    for key in v1_keys:
        pair = pairs[key]
        record = harness.submission_record_from_strokes(pair.sketch_strokes)
        trial = score_trial(record, sha256_hex(pair.photo_bytes), context,
                            sketch_encoder)
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
        ("line_drawer", (drawer_delta.posts, drawer_delta.cache_hits)),
        ("image_encoder", (encoder_delta.posts, encoder_delta.cache_hits)),
    )

    directory = harness.validation_dir(data_root, "v1", union_index.index_id,
                                       harness_hash)
    write_jsonl(directory / "trials.jsonl", [
        {"pair_key": row.pair_key, "p": harness.quantized(row.p),
         "decoy_count": row.decoy_count, "beaten": row.beaten,
         "tied": row.tied, "target_rank": row.target_rank,
         "input_class": row.input_class}
        for row in trials])
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
            "created_at": clock(),
            "code_version": code_version,
            **harness.VERDICT_TEMPLATE,
        }
        record_path = str(harness.write_harness_record(
            records_root, "v1", config.validation.tag, harness_hash, content))

    return V1Report(
        index_id=union_index.index_id, harness_config_hash=harness_hash,
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
