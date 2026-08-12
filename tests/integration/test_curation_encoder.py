"""Integration: curation s06/s07 on an openrouter embedding encoder.

The fake corpus drives the funnel and the HTTP boundary is patched
with a deterministic embeddings answer - the provider, its batching,
its response validation, and the two caches run unpatched. The slot
hash must be the embeddings hash, not the chat-slot hash.
"""

import numpy as np

from conftest import find_stage_dir, make_config, run_pipeline

from core.canonical import canonical_json, sha256_hex
from pool.curation.run import _slot_hash
from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                             embedding_config_hash)

DIMENSION = 16

ENCODER_SLOT = {
    "provider": "openrouter", "model": "test/embed",
    "instruction_template": None, "dimension": DIMENSION,
    "probability_sum_tolerance": None,
}


def _fake_post_embeddings(calls):
    def post_embeddings(self, body):
        calls.append(len(body["input"]))
        rows = []
        for index, item in enumerate(body["input"]):
            seed = int(sha256_hex(canonical_json(item))[:8], 16)
            values = np.random.default_rng(seed).normal(size=DIMENSION)
            rows.append({"index": index, "embedding": values.tolist()})
        return {"data": rows}
    return post_embeddings


def test_the_encoder_slot_hash_is_the_embeddings_hash() -> None:
    config = make_config(**{"providers.encoder": dict(ENCODER_SLOT)})
    expected = embedding_config_hash(EmbeddingSlotConfig(
        slot="encoder", model="test/embed", dimension=DIMENSION,
        encoding_format="float", instruction=None))
    assert _slot_hash("encoder", config.providers.encoder,
                      config) == expected
    fake = make_config()
    assert _slot_hash("encoder", fake.providers.encoder, config) != expected


def test_s06_and_s07_run_through_the_patched_boundary(
        tmp_path, monkeypatch) -> None:
    from providers.openrouter.client import OpenRouterClient

    calls: list[int] = []
    # The patched boundary sends nothing and reads no key value.
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-test-key")
    monkeypatch.setattr(OpenRouterClient, "post_embeddings",
                        _fake_post_embeddings(calls))
    config = make_config(**{"providers.encoder": dict(ENCODER_SLOT)})
    report = run_pipeline(config, tmp_path / "data", tmp_path / "releases",
                          through="s07-diversity")
    assert report.halted_at is None

    expected_hash = embedding_config_hash(EmbeddingSlotConfig(
        slot="encoder", model="test/embed", dimension=DIMENSION,
        encoding_format="float", instruction=None))
    import json
    for stage in ("s06-neardup", "s07-diversity"):
        meta = json.loads((find_stage_dir(tmp_path / "data", stage)
                           / "meta.json").read_text())
        assert meta["provider_config_hashes"]["encoder"] == expected_hash

    # The .npy vectors land below the embeddings hash, unit-norm.
    vectors_root = tmp_path / "data" / "cache" / "vectors" \
        / expected_hash[:8]
    stored = sorted(vectors_root.rglob("*.npy"))
    assert stored
    row = np.load(stored[0])
    assert row.shape == (DIMENSION,)
    assert np.isclose(np.linalg.norm(row), 1.0, atol=1e-5)
    assert sum(calls) == len(stored)

    # The second run is warm: no post crosses the boundary.
    calls.clear()
    again = run_pipeline(config, tmp_path / "data", tmp_path / "releases",
                         through="s07-diversity")
    assert again.halted_at is None
    assert calls == []
