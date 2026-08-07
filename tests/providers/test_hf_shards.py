"""The deterministic shard subset rule for the scan bound (U1)."""

import hashlib

from providers.corpora.huggingface import select_shards

SHARDS = tuple(f"data/train-{i:05d}-of-00330.parquet" for i in range(20))


def test_selection_is_deterministic_and_input_sequence_free():
    forward = select_shards(SHARDS, 5)
    backward = select_shards(tuple(reversed(SHARDS)), 5)
    assert forward == backward
    assert len(forward) == 5


def test_selection_matches_longhand_hash_ranking():
    ranked = sorted(SHARDS, key=lambda p: (hashlib.sha256(p.encode()).hexdigest(), p))
    assert select_shards(SHARDS, 3) == tuple(ranked[:3])
    assert select_shards(SHARDS, None) == tuple(ranked)


def test_smaller_subset_is_a_prefix_of_a_larger_one():
    assert select_shards(SHARDS, 2) == select_shards(SHARDS, 4)[:2]


def test_subset_larger_than_input_gives_all():
    assert len(select_shards(SHARDS, 500)) == len(SHARDS)
