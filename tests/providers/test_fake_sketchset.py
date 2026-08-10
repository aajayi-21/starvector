"""Tests for the fake sketch-pair source."""

import pytest

from pipeline.config import SplitFractionsSection
from providers.fake import markers
from providers.fake.chunks import read_fake_chunks
from providers.sketchsets.fake import (FakeSketchPairSource,
                                       FakeSketchsetConfig)
from validation.splits import split_of


def _pairs(count: int = 8, families: tuple[str, ...] = ()):
    source = FakeSketchPairSource(
        FakeSketchsetConfig(pair_count=count, neardup_families=families))
    return source, list(source.iter_pairs())


def test_two_instances_give_equal_pairs() -> None:
    _, first = _pairs()
    _, second = _pairs()
    assert first == second


def test_pair_keys_ascend_and_strokes_carry_the_marker() -> None:
    _, pairs = _pairs(count=4)
    keys = [pair.pair_key for pair in pairs]
    assert keys == sorted(keys)
    for position, pair in enumerate(pairs):
        assert pair.sketch_strokes[0] == ((0.0, markers.SYNC_Y),
                                          (1.0, markers.SYNC_Y))
        # Content strokes stay above the marker band.
        for stroke in pair.sketch_strokes:
            if stroke[0][1] < markers.SYNC_Y:
                assert all(y <= markers.CONTENT_MAX_Y for _, y in stroke)
        chunks = read_fake_chunks(pair.photo_bytes)
        assert chunks["embed_family"] == markers.family_name(position)
        assert chunks["embed_jitter"] == "dup"


def test_neardup_families_override_the_photo_chunk() -> None:
    _, pairs = _pairs(count=3, families=("fam-a", "fam-b"))
    chunks = [read_fake_chunks(pair.photo_bytes)["embed_family"]
              for pair in pairs]
    assert chunks == ["fam-a", "fam-b", markers.family_name(2)]


def test_a_pair_count_above_the_bit_range_raises() -> None:
    with pytest.raises(ValueError, match="pair_count"):
        FakeSketchsetConfig(pair_count=129)


def test_bytes_retrieved_grows_with_iteration() -> None:
    source, pairs = _pairs(count=3)
    assert source.bytes_retrieved == sum(len(pair.photo_bytes)
                                         for pair in pairs)


def test_the_default_salt_populates_the_three_splits() -> None:
    _, pairs = _pairs(count=24)
    fractions = SplitFractionsSection(background=0.5, v1=0.25, v2=0.25)
    names = {split_of("test-salt", pair.pair_key, fractions)
             for pair in pairs}
    assert names == {"background", "v1", "v2"}


def test_each_photograph_carries_its_scripted_element_list() -> None:
    import json

    from providers.fake.describer import FakeVlmDescriber

    _, pairs = _pairs(count=3)
    for position, pair in enumerate(pairs):
        scripted = json.loads(read_fake_chunks(pair.photo_bytes)
                              ["fake_elements"])
        assert scripted["objects"][0] == f"tower {position:04d}"
    responses = FakeVlmDescriber().describe_images(
        [pair.photo_bytes for pair in pairs])
    assert responses[1].setting == "harbor 0001"


def test_the_description_names_the_photograph_elements_and_one_more() -> None:
    from core.atoms import split_pasted_text
    from pool.preparation.stages.normalize import normalize_elements

    from providers.fake.describer import FakeVlmDescriber

    _, pairs = _pairs(count=2)
    pair = pairs[1]
    fragments = split_pasted_text(pair.text)
    elements = normalize_elements(
        FakeVlmDescriber().describe_images([pair.photo_bytes])[0])
    # The frozen paste rule gives one atom for each named word group,
    # and the element strings are p02 fixed points, thus three of the
    # four atoms are accurately an element of this photograph.
    assert len(fragments) == 4
    assert sum(1 for text in fragments if text in elements) == 3
    assert "drift 0001" in fragments


def test_the_config_hash_covers_the_scripted_structure() -> None:
    plain = FakeSketchPairSource(FakeSketchsetConfig(pair_count=8))
    scripted = FakeSketchPairSource(FakeSketchsetConfig(
        pair_count=8, neardup_families=("fam-a",)))
    assert plain.config_hash != scripted.config_hash
    assert len(plain.config_hash) == 64
