"""Tests for the deterministic fake source corpus."""

from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from providers.corpora.fake import FakeCorpus, FakeCorpusConfig, FakeRecordSpec
from providers.protocols import MaterializedImage, MaterializeFailure

ALL_CLASSES = (
    "photo",
    "lowres",
    "lowres_lying",
    "no_metadata",
    "bad_aspect",
    "aspect_boundary",
    "undecodable",
    "fetch_fail",
    "dup_bytes",
    "text_heavy",
    "text_boundary",
    "diagram",
    "logo",
    "map_like",
    "small_object",
    "object_boundary",
    "no_object",
    "neardup_pair",
    "cluster_family",
)

SCAN_BYTES = 100


def _full_config() -> FakeCorpusConfig:
    return FakeCorpusConfig(
        records=tuple(FakeRecordSpec(name, 2) for name in ALL_CLASSES),
        scan_bytes_per_record=SCAN_BYTES,
    )


def _content_class(source_key: str) -> str:
    return source_key.split("/")[-2]


def test_determinism_across_instances():
    corpus_a = FakeCorpus(_full_config())
    corpus_b = FakeCorpus(_full_config())
    records_a = list(corpus_a.iter_records())
    records_b = list(corpus_b.iter_records())
    assert records_a == records_b
    results_a = corpus_a.materialize_many(records_a)
    results_b = corpus_b.materialize_many(records_b)
    assert results_a == results_b


def test_all_classes_reachable():
    corpus = FakeCorpus(_full_config())
    records = list(corpus.iter_records())
    assert len(records) == 2 * len(ALL_CLASSES)
    seen = {_content_class(record.source_key) for record in records}
    assert seen == set(ALL_CLASSES)
    results = corpus.materialize_many(records)
    for record, result in zip(records, results, strict=True):
        if _content_class(record.source_key) == "fetch_fail":
            assert isinstance(result, MaterializeFailure)
        else:
            assert isinstance(result, MaterializedImage)


def test_source_key_scheme_and_claimed_dimensions():
    corpus = FakeCorpus(_full_config())
    records = list(corpus.iter_records())
    by_key = {record.source_key: record for record in records}
    assert "fake://photo/0000" in by_key
    assert "fake://photo/0001" in by_key
    photo = by_key["fake://photo/0000"]
    assert (photo.claimed_width, photo.claimed_height) == (800, 600)
    lying = by_key["fake://lowres_lying/0000"]
    assert (lying.claimed_width, lying.claimed_height) == (800, 600)
    bare = by_key["fake://no_metadata/0000"]
    assert (bare.claimed_width, bare.claimed_height) == (None, None)
    first_pair = by_key["fake://neardup_pair/0000"]
    assert (first_pair.claimed_width, first_pair.claimed_height) == (900, 700)
    second_pair = by_key["fake://neardup_pair/0001"]
    assert (second_pair.claimed_width, second_pair.claimed_height) == (800, 600)


def test_decoded_dimensions_and_dup_bytes():
    corpus = FakeCorpus(_full_config())
    records = list(corpus.iter_records())
    results = corpus.materialize_many(records)
    by_class: dict[str, list[bytes]] = {}
    for record, result in zip(records, results, strict=True):
        if isinstance(result, MaterializedImage):
            by_class.setdefault(_content_class(record.source_key), []).append(
                result.image_bytes
            )
    with Image.open(BytesIO(by_class["photo"][0])) as image:
        assert image.size == (800, 600)
    with Image.open(BytesIO(by_class["lowres_lying"][0])) as image:
        assert image.size == (300, 200)
    with Image.open(BytesIO(by_class["neardup_pair"][0])) as image:
        assert image.size == (900, 700)
    with Image.open(BytesIO(by_class["neardup_pair"][1])) as image:
        assert image.size == (800, 600)
    assert by_class["dup_bytes"][0] == by_class["dup_bytes"][1]
    assert by_class["photo"][0] != by_class["photo"][1]
    with pytest.raises(UnidentifiedImageError):
        Image.open(BytesIO(by_class["undecodable"][0]))


def test_fetch_fail_is_explicit():
    corpus = FakeCorpus(
        FakeCorpusConfig(
            records=(FakeRecordSpec("fetch_fail", 1),), scan_bytes_per_record=SCAN_BYTES
        )
    )
    records = list(corpus.iter_records())
    (result,) = corpus.materialize_many(records)
    assert isinstance(result, MaterializeFailure)
    assert result.source_key == "fake://fetch_fail/0000"
    assert result.reason == "fetch-error"
    assert result.detail == "scripted failure"


def test_byte_counter_scan_and_materialize():
    corpus = FakeCorpus(_full_config())
    assert corpus.bytes_retrieved == 0
    records = list(corpus.iter_records())
    scan_total = SCAN_BYTES * len(records)
    assert corpus.bytes_retrieved == scan_total
    photo_records = [r for r in records if _content_class(r.source_key) == "photo"]
    results = corpus.materialize_many(photo_records)
    payload_total = sum(
        len(r.image_bytes) for r in results if isinstance(r, MaterializedImage)
    )
    assert payload_total > 0
    assert corpus.bytes_retrieved == scan_total + payload_total
    fail_records = [r for r in records if _content_class(r.source_key) == "fetch_fail"]
    corpus.materialize_many(fail_records)
    assert corpus.bytes_retrieved == scan_total + payload_total


def test_identity_and_config_hash_track_config():
    base = FakeCorpus(_full_config())
    same = FakeCorpus(_full_config())
    changed_scan = FakeCorpus(
        FakeCorpusConfig(
            records=_full_config().records, scan_bytes_per_record=SCAN_BYTES + 1
        )
    )
    changed_records = FakeCorpus(
        FakeCorpusConfig(
            records=(FakeRecordSpec("photo", 3),), scan_bytes_per_record=SCAN_BYTES
        )
    )
    assert base.identity == same.identity
    assert base.config_hash == same.config_hash
    assert base.identity != changed_scan.identity
    assert base.identity != changed_records.identity
    assert len({base.config_hash, changed_scan.config_hash, changed_records.config_hash}) == 3
    assert base.identity.provider == "fake"
    assert base.identity.repo_id == "fake-corpus"
    assert base.identity.config_name is None
    assert base.identity.split == "train"
    assert len(base.identity.revision) == 40


def test_materialize_alignment():
    corpus = FakeCorpus(_full_config())
    records = list(corpus.iter_records())
    reordered = list(reversed(records))
    results = corpus.materialize_many(reordered)
    assert len(results) == len(reordered)
    for record, result in zip(reordered, results, strict=True):
        assert result.source_key == record.source_key


def test_unknown_source_key_raises():
    corpus = FakeCorpus(_full_config())
    records = list(corpus.iter_records())
    bogus = records[0]._replace(source_key="fake://photo/9999")
    with pytest.raises(ValueError):
        corpus.materialize_many([bogus])
