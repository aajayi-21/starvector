"""Tests for the deterministic fake encoder, classifier, and estimators."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from providers.corpora.fake import FakeCorpus, FakeCorpusConfig, FakeRecordSpec
from providers.fake.classifier import FakeZeroShotImageClassifier
from providers.fake.encoder import FakeImageEncoder
from providers.fake.estimators import FakeSalientObjectEstimator, FakeTextCoverageEstimator
from providers.protocols import MaterializedImage

DIMENSION = 256

LABELS = (
    "photograph",
    "diagram",
    "chart",
    "logo",
    "map",
    "screenshot",
    "coat of arms",
    "line drawing",
)

CORPUS_CONFIG = FakeCorpusConfig(
    records=(
        FakeRecordSpec("photo", 2),
        FakeRecordSpec("lowres", 1),
        FakeRecordSpec("diagram", 1),
        FakeRecordSpec("text_heavy", 1),
        FakeRecordSpec("small_object", 1),
        FakeRecordSpec("no_object", 1),
        FakeRecordSpec("neardup_pair", 2),
        FakeRecordSpec("cluster_family", 2),
    ),
    scan_bytes_per_record=10,
)


@pytest.fixture(scope="module")
def images() -> dict[str, list[bytes]]:
    corpus = FakeCorpus(CORPUS_CONFIG)
    records = list(corpus.iter_records())
    results = corpus.materialize_many(records)
    grouped: dict[str, list[bytes]] = {}
    for record, result in zip(records, results, strict=True):
        assert isinstance(result, MaterializedImage)
        content_class = record.source_key.split("/")[-2]
        grouped.setdefault(content_class, []).append(result.image_bytes)
    return grouped


def _png_with_chunks(chunks: dict[str, str]) -> bytes:
    info = PngInfo()
    for chunk_key, chunk_value in chunks.items():
        info.add_text(chunk_key, chunk_value)
    buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def test_encoder_shape_dtype_unit_norms(images):
    encoder = FakeImageEncoder(DIMENSION)
    batch = images["photo"] + images["lowres"] + images["cluster_family"]
    vectors = encoder.encode_images(batch)
    assert vectors.shape == (len(batch), DIMENSION)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_encoder_determinism(images):
    batch = images["photo"] + images["neardup_pair"]
    vectors_a = FakeImageEncoder(DIMENSION).encode_images(batch)
    vectors_b = FakeImageEncoder(DIMENSION).encode_images(batch)
    assert np.array_equal(vectors_a, vectors_b)


def test_encoder_dup_pair_cosine(images):
    vectors = FakeImageEncoder(DIMENSION).encode_images(images["neardup_pair"])
    cosine = float(vectors[0] @ vectors[1])
    assert cosine >= 0.98


def test_encoder_family_pair_cosine(images):
    vectors = FakeImageEncoder(DIMENSION).encode_images(images["cluster_family"])
    cosine = float(vectors[0] @ vectors[1])
    assert 0.5 < cosine < 0.95


def test_encoder_chunk_free_fallback(images):
    vectors = FakeImageEncoder(DIMENSION).encode_images(images["lowres"])
    assert vectors.shape == (1, DIMENSION)
    assert np.isclose(float(np.linalg.norm(vectors[0])), 1.0, atol=1e-5)


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), color=(120, 60, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_encoder_accepts_jpeg_bytes():
    # JPEG has no text-chunk attribute in Pillow. The encoder must use
    # the bytes-seeded rule for JPEG bytes, because the live corpus
    # supplies JPEG images.
    jpeg = _jpeg_bytes()
    vectors_a = FakeImageEncoder(DIMENSION).encode_images([jpeg])
    vectors_b = FakeImageEncoder(DIMENSION).encode_images([jpeg])
    assert vectors_a.shape == (1, DIMENSION)
    assert np.isclose(float(np.linalg.norm(vectors_a[0])), 1.0, atol=1e-5)
    assert np.array_equal(vectors_a, vectors_b)


def test_classifier_jpeg_bytes_raise():
    # The scripted classifier keeps its missing-chunk error for
    # unscripted images.
    with pytest.raises(ValueError, match="fake_label chunk is missing"):
        FakeZeroShotImageClassifier().classify([_jpeg_bytes()], LABELS)


def test_encoder_unrelated_images_are_not_near_duplicates(images):
    vectors = FakeImageEncoder(DIMENSION).encode_images(images["photo"])
    assert float(vectors[0] @ vectors[1]) < 0.95


def test_classifier_winner_and_row_sums(images):
    classifier = FakeZeroShotImageClassifier()
    batch = images["photo"] + images["diagram"]
    matrix = classifier.classify(batch, LABELS)
    assert matrix.shape == (len(batch), len(LABELS))
    assert matrix.dtype == np.float32
    assert np.allclose(matrix.sum(axis=1), 1.0, atol=1e-5)
    assert matrix[0, LABELS.index("photograph")] == pytest.approx(0.9)
    assert matrix[1, LABELS.index("photograph")] == pytest.approx(0.9)
    assert matrix[2, LABELS.index("diagram")] == pytest.approx(0.9)
    assert matrix[0, LABELS.index("logo")] == pytest.approx(0.1 / (len(LABELS) - 1))


def test_classifier_missing_chunk_raises(images):
    with pytest.raises(ValueError):
        FakeZeroShotImageClassifier().classify(images["lowres"], LABELS)


def test_classifier_unknown_label_raises(images):
    with pytest.raises(ValueError):
        FakeZeroShotImageClassifier().classify(images["diagram"], ("photograph", "logo"))


def test_estimators_scripted_values(images):
    batch = (
        images["photo"][:1]
        + images["text_heavy"]
        + images["small_object"]
        + images["no_object"]
    )
    coverage = FakeTextCoverageEstimator().estimate_text_coverage(batch)
    fractions = FakeSalientObjectEstimator().estimate_salient_object_fraction(batch)
    assert coverage.dtype == np.float32
    assert coverage.shape == (4,)
    assert coverage == pytest.approx([0.01, 0.40, 0.01, 0.01])
    assert fractions.dtype == np.float32
    assert fractions.shape == (4,)
    assert fractions == pytest.approx([0.5, 0.5, 0.10, 0.0])


def test_estimators_missing_chunk_raises(images):
    with pytest.raises(ValueError):
        FakeTextCoverageEstimator().estimate_text_coverage(images["lowres"])
    with pytest.raises(ValueError):
        FakeSalientObjectEstimator().estimate_salient_object_fraction(images["lowres"])


def test_estimators_out_of_range_raises():
    bad_text = _png_with_chunks({"fake_text_coverage": "1.5"})
    with pytest.raises(ValueError):
        FakeTextCoverageEstimator().estimate_text_coverage([bad_text])
    bad_object = _png_with_chunks({"fake_object_fraction": "-0.2"})
    with pytest.raises(ValueError):
        FakeSalientObjectEstimator().estimate_salient_object_fraction([bad_object])


def test_config_hashes_are_different_across_fakes():
    hashes = {
        FakeImageEncoder(DIMENSION).config_hash,
        FakeZeroShotImageClassifier().config_hash,
        FakeTextCoverageEstimator().config_hash,
        FakeSalientObjectEstimator().config_hash,
    }
    assert len(hashes) == 4
    assert all(len(value) == 64 for value in hashes)
    assert FakeImageEncoder(128).config_hash != FakeImageEncoder(256).config_hash
