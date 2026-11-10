"""The bake-off table, the calibration report, and the smoke tool, offline."""

import base64
import json
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from providers.fake.encoder import FakeImageEncoder
from providers.voyage.client import VoyageClient, VoyageClientConfig
from tools import voyage_smoke
from validation import bakeoff, neardup_calibration as calibration


def rows(ranks: dict[str, int]) -> list[dict]:
    return [{"pair_key": key, "target_rank": rank} for key, rank in ranks.items()]


def test_mcnemar_is_the_exact_binomial() -> None:
    assert bakeoff.mcnemar_exact_p(0, 0) == 1.0
    assert bakeoff.mcnemar_exact_p(3, 3) == 1.0
    # Six discordant pairs on one side: 2 * (1/2)^6.
    assert bakeoff.mcnemar_exact_p(6, 0) == pytest.approx(0.03125)
    assert bakeoff.mcnemar_exact_p(0, 6) == pytest.approx(0.03125)
    # 2 * (1 + 10 + 45) / 2^10.
    assert bakeoff.mcnemar_exact_p(8, 2) == pytest.approx(0.109375)


def test_the_table_counts_by_pair() -> None:
    table = bakeoff.paired_table(rows({"a": 1, "b": 1, "c": 5, "d": 20}),
                                 rows({"a": 1, "b": 2, "c": 1, "d": 30}))
    assert table.pair_count == 4
    assert table.baseline_first == 0.5
    assert table.candidate_first == 0.5
    assert table.baseline_top_ten == 0.75
    assert table.candidate_top_ten == 0.75
    assert (table.candidate_only, table.baseline_only) == (1, 1)
    assert table.mcnemar_p == 1.0


def test_two_different_pair_sets_are_refused() -> None:
    with pytest.raises(ValueError, match="same pairs"):
        bakeoff.paired_table(rows({"a": 1}), rows({"b": 1}))
    with pytest.raises(ValueError, match="same pairs"):
        bakeoff.paired_table([], [])


def table(baseline: float, candidate: float, p: float) -> bakeoff.PairedTable:
    return bakeoff.PairedTable(200, baseline, candidate, 0.97, 0.97, 0, 0, p)


EQUAL = bakeoff.DecoyParity(((403, 200),), ((403, 200),), 0, 0, 0.66)
BOTH = {"sketch": 0.3, "mixed": 0.2}


def holds(lines: list[bakeoff.RuleLine]) -> dict[str, bool]:
    return {line.name: line.holds for line in lines}


def test_each_rule_line_reads_its_number() -> None:
    clear = bakeoff.rule_lines(table(0.68, 0.66, 0.5), EQUAL, "sketch", BOTH)
    assert all(line.holds for line in clear)
    assert [line.name for line in clear] == [
        "equal decoy counts", "not below the baseline", "first-rank floor",
        "V2 uniform, sketch", "V2 uniform, mixed"]
    below = holds(bakeoff.rule_lines(table(0.68, 0.64, 0.01), EQUAL,
                                     "sketch", BOTH))
    assert below["not below the baseline"] is False
    assert below["first-rank floor"] is True
    floor = holds(bakeoff.rule_lines(table(0.60, 0.62, 1.0), EQUAL,
                                     "sketch", BOTH))
    assert floor["not below the baseline"] is True
    assert floor["first-rank floor"] is False
    uniform = holds(bakeoff.rule_lines(
        table(0.68, 0.70, 1.0), EQUAL, "sketch",
        {"sketch": 0.05, "mixed": 0.2}))
    assert uniform["V2 uniform, sketch"] is False
    assert uniform["V2 uniform, mixed"] is True


def test_a_higher_candidate_clears_the_paired_line_at_a_low_p() -> None:
    lines = holds(bakeoff.rule_lines(table(0.68, 0.75, 0.001), EQUAL,
                                     "sketch", BOTH))
    assert lines["not below the baseline"]


def test_rule_three_without_its_records_does_not_hold() -> None:
    """A report with no V2 record must not read as a clear one."""
    none = holds(bakeoff.rule_lines(table(0.68, 0.70, 1.0), EQUAL,
                                    "sketch", {}))
    assert none["V2 uniform, sketch"] is False
    assert none["V2 uniform, mixed"] is False
    one = holds(bakeoff.rule_lines(table(0.68, 0.70, 1.0), EQUAL,
                                   "sketch", {"sketch": 0.3}))
    assert one["V2 uniform, sketch"] is True
    assert one["V2 uniform, mixed"] is False


def test_the_floor_is_a_sketch_line_alone() -> None:
    text = bakeoff.rule_lines(table(0.265, 0.27, 1.0), EQUAL, "text",
                              {"text": 0.4})
    assert [line.name for line in text] == [
        "equal decoy counts", "not below the baseline", "V2 uniform, text"]
    assert all(line.holds for line in text)
    mixed = bakeoff.rule_lines(table(0.465, 0.47, 1.0), EQUAL, "mixed", BOTH)
    assert [line.name for line in mixed] == ["equal decoy counts"]
    with pytest.raises(ValueError, match="unknown submission mode"):
        bakeoff.rule_lines(table(0.5, 0.5, 1.0), EQUAL, "outline", {})


def decoy_rows(values: dict[str, tuple[int, int]]) -> list[dict]:
    return [{"pair_key": key, "target_rank": rank, "decoy_count": decoys}
            for key, (rank, decoys) in values.items()]


def test_decoy_parity_counts_each_direction() -> None:
    baseline = decoy_rows({"a": (1, 403), "b": (1, 403), "c": (4, 402),
                           "d": (9, 403)})
    candidate = decoy_rows({"a": (1, 401), "b": (1, 403), "c": (1, 403),
                            "d": (2, 400)})
    parity = bakeoff.decoy_parity(baseline, candidate)
    assert parity.baseline_counts == ((402, 1), (403, 3))
    assert parity.candidate_counts == ((400, 1), (401, 1), (403, 2))
    assert (parity.candidate_fewer, parity.candidate_more) == (2, 1)
    # Three first ranks, and the one on a fewer-decoy pair does not count.
    assert parity.conservative_first == 0.5
    lines = holds(bakeoff.rule_lines(table(0.5, 0.75, 1.0), parity,
                                     "sketch", BOTH))
    assert lines["equal decoy counts"] is False
    same = bakeoff.decoy_parity(baseline, baseline)
    assert (same.candidate_fewer, same.candidate_more) == (0, 0)
    assert same.conservative_first == 0.5


def write_run(root: Path, name: str, harness_name: str, mode: str,
              preparation: str, ranks: dict[str, tuple[int, int]] | None,
              **fields: object) -> Path:
    """One record with its run directory, as the harness writes them."""
    index_id = (name + "-index").ljust(64, "0")
    harness_hash = (name + "-hash").ljust(64, "1")
    record = {"harness": harness_name, "index_id": index_id,
              "harness_config_hash": harness_hash,
              "preparation_version_id": preparation,
              "scoring_config_hash": "scoring-" + preparation, **fields}
    directory = (root / "data" / "validation" / harness_name
                 / index_id[:8] / harness_hash[:8])
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(json.dumps(
        {"harness_config_hash": harness_hash, "submission_mode": mode}))
    if ranks is not None:
        (directory / "trials.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in decoy_rows(ranks)))
        (directory / "match_reports.jsonl").write_text("")
        first = sum(rank == 1 for rank, _ in ranks.values()) / len(ranks)
        record.setdefault("first_rank_fraction", first)
    path = root / f"{name}.json"
    path.write_text(json.dumps(record))
    return path


RANKS = {"a": (1, 403), "b": (1, 403), "c": (5, 403), "d": (20, 403)}


def run_bakeoff(root: Path, *arguments: str | Path) -> int:
    return bakeoff.main([*map(str, arguments), "--data-root",
                         str(root / "data")])


def test_the_tool_reads_the_candidate_records(tmp_path: Path, capsys) -> None:
    base = write_run(tmp_path, "base", "v1", "sketch", "prep-a", RANKS)
    cand = write_run(tmp_path, "cand", "v1", "sketch", "prep-b",
                     {**RANKS, "c": (1, 403)})
    sketch = write_run(tmp_path, "v2s", "v2", "sketch", "prep-b", None,
                       ks_significance=0.3)
    mixed = write_run(tmp_path, "v2m", "v2", "mixed", "prep-b", None,
                      ks_significance=0.2)
    assert run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand,
                       "--v2", sketch, "--v2", mixed) == 0
    printed = capsys.readouterr().out
    assert "submission mode       sketch" in printed
    assert "decoy counts          candidate 403 x4" in printed
    assert "FAILS" not in printed
    # With no V2 record the report holds two lines that do not hold.
    assert run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand) == 0
    assert capsys.readouterr().out.count(
        "no V2 record of this mode was given") == 2


def test_evidence_of_a_different_run_is_refused(tmp_path: Path) -> None:
    base = write_run(tmp_path, "base", "v1", "sketch", "prep-a", RANKS)
    cand = write_run(tmp_path, "cand", "v1", "sketch", "prep-b", RANKS)
    foreign = write_run(tmp_path, "v2a", "v2", "sketch", "prep-a", None,
                        ks_significance=0.3)
    with pytest.raises(ValueError, match="not the candidate's"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand,
                    "--v2", foreign)
    twice = write_run(tmp_path, "v2b", "v2", "sketch", "prep-b", None,
                      ks_significance=0.3)
    again = write_run(tmp_path, "v2c", "v2", "sketch", "prep-b", None,
                      ks_significance=0.4)
    with pytest.raises(ValueError, match="second V2 record"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand,
                    "--v2", twice, "--v2", again)
    moved = write_run(tmp_path, "v2d", "v2", "sketch", "prep-b", None,
                      ks_significance=0.3, scoring_config_hash="other")
    with pytest.raises(ValueError, match="different scoring config hash"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand,
                    "--v2", moved)
    with pytest.raises(ValueError, match="not a v2 record"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", cand,
                    "--v2", cand)
    text = write_run(tmp_path, "text", "v1", "text", "prep-b", RANKS)
    with pytest.raises(ValueError, match="different submission modes"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", text)


def test_moved_trial_rows_are_refused(tmp_path: Path) -> None:
    base = write_run(tmp_path, "base", "v1", "sketch", "prep-a", RANKS)
    stale = write_run(tmp_path, "cand", "v1", "sketch", "prep-b", RANKS,
                      first_rank_fraction=0.75)
    with pytest.raises(ValueError, match="rows moved after the record"):
        run_bakeoff(tmp_path, "--baseline", base, "--candidate", stale)


def test_similarity_quantiles_skip_a_sketch_run() -> None:
    assert bakeoff.similarity_quantiles([{"atoms": []}]) is None
    reports = [{"atoms": [{"similarity": value / 10}]} for value in range(10)]
    quantiles = bakeoff.similarity_quantiles(reports)
    assert quantiles is not None
    assert quantiles["p50"] == 0.5
    assert quantiles["max"] == 0.9


def photo(shade: int = 40) -> bytes:
    pixels = np.random.default_rng(shade).integers(0, 255, (64, 96, 3), dtype=np.uint8)
    buffer = BytesIO()
    Image.fromarray(pixels, "RGB").save(buffer, "PNG")
    return buffer.getvalue()


def test_the_variants_are_new_decodable_images() -> None:
    source = photo()
    variants = calibration.duplicate_variants(source)
    assert tuple(variants) == calibration.VARIANT_NAMES
    assert len({*variants.values(), source}) == 5
    sizes = {name: Image.open(BytesIO(data)).size for name, data in variants.items()}
    assert sizes["jpeg"] == (96, 64)
    assert sizes["brightness"] == (96, 64)
    assert sizes["crop"][0] < 96
    assert sizes["resize"] == (67, 45)


def test_the_margin_is_positive_when_one_threshold_separates() -> None:
    sources = np.eye(3, dtype=np.float32)
    near = np.eye(3, dtype=np.float32) * 0.99
    near[:, 2] += 0.01
    report = calibration.space_report(
        "hash", sources, {"jpeg": near / np.linalg.norm(near, axis=1, keepdims=True)})
    assert report.pool_pairs["max"] == 0.0
    assert report.margin > 0.9
    assert report.source_count == 3


def test_a_single_source_is_refused() -> None:
    with pytest.raises(ValueError, match="two sources"):
        calibration.space_report("hash", np.eye(1, dtype=np.float32), {})


def test_calibration_runs_end_to_end_on_a_fake_encoder() -> None:
    encoder = FakeImageEncoder(dimension=16)
    report = calibration.calibrate_space(
        encoder.config_hash, encoder.encode_images,
        [photo(1), photo(2), photo(3)], canvas_px=64)
    assert set(report.variants) == set(calibration.VARIANT_NAMES)
    assert report.encoder_hash == encoder.config_hash


def test_the_sample_is_seeded_and_ascending() -> None:
    ids = [f"{index:03d}" for index in range(50)]
    first = calibration.sampled_ids(ids, 10, 7)
    assert first == calibration.sampled_ids(list(reversed(ids)), 10, 7)
    assert first == sorted(first)
    assert calibration.sampled_ids(ids, 500, 7) == ids


def smoke_client(row: list[float]) -> VoyageClient:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        encoded = base64.b64encode(np.asarray(row, dtype="<f4").tobytes()).decode()
        return httpx.Response(200, json={
            "data": [{"index": index, "embedding": encoded}
                     for index in range(len(body["inputs"]))],
            "usage": {"image_pixels": 4096, "text_tokens": 3, "total_tokens": 10},
        })

    return VoyageClient(
        VoyageClientConfig(10**9, 10**12, 5.0, 0), "test-key",
        transport=httpx.MockTransport(handle))


def test_the_smoke_stores_and_then_reads_a_canary(tmp_path: Path) -> None:
    canary = tmp_path / "canary.json"
    first = voyage_smoke.run_smoke(smoke_client([1.0, 0.0]), "m", 2, canary)
    assert first.canary_cosine is None
    assert first.repeat_cosine == pytest.approx(1.0)
    assert first.posts == 4
    assert first.image_pixels == 4096 * 4
    second = voyage_smoke.run_smoke(smoke_client([1.0, 0.0]), "m", 2, canary)
    assert second.canary_cosine == pytest.approx(1.0)
    moved = voyage_smoke.run_smoke(smoke_client([0.0, 1.0]), "m", 2, canary)
    assert moved.canary_cosine == pytest.approx(0.0)
    assert "against the stored canary" in voyage_smoke.format_report(moved)
