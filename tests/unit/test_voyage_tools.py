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


def test_each_rule_line_reads_its_number() -> None:
    clear = bakeoff.rule_lines(table(0.68, 0.66, 0.5), {"sym": 0.3, "mixed": 0.2})
    assert all(line.holds for line in clear)
    below = bakeoff.rule_lines(table(0.68, 0.64, 0.01), {})
    assert [line.holds for line in below] == [False, True]
    floor = bakeoff.rule_lines(table(0.60, 0.62, 1.0), {})
    assert [line.holds for line in floor] == [True, False]
    uniform = bakeoff.rule_lines(table(0.68, 0.70, 1.0), {"sym": 0.05})
    assert uniform[-1].holds is False


def test_a_higher_candidate_clears_the_paired_line_at_a_low_p() -> None:
    lines = bakeoff.rule_lines(table(0.68, 0.75, 0.001), {})
    assert lines[0].holds


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
