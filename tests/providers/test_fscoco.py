"""Offline tests for the FS-COCO adapter: parse, digests, tree walk.

No network: the tests cover the pure parse functions, the archive
digest check against a scratch tar.gz, and iter_pairs on a
hand-built extracted tree with its meta marker written.
"""

import hashlib
import tarfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

from providers.sketchsets.fscoco import (FSCocoConfig, FSCocoSketchPairSource,
                                         _checked_member_name,
                                         fscoco_config_hash,
                                         strokes_from_array)

EXTENT = (10.0, 10.0)


def _config(**overrides) -> FSCocoConfig:
    values = {
        "url": "https://example.org/fscoco.tar.gz",
        "archive_sha256": "0" * 64,
        "coordinate_extent": EXTENT,
        "budget_bytes": 10_000_000,
    }
    values.update(overrides)
    return FSCocoConfig(**values)


def test_strokes_split_at_pen_up_rows() -> None:
    array = np.asarray([
        [0.0, 0.0, 0.0],
        [5.0, 5.0, 1.0],
        [2.0, 8.0, 0.0],
        [9.0, 9.0, 1.0],
    ])
    strokes = strokes_from_array(array, EXTENT, "u/1")
    assert strokes == (
        ((0.0, 0.0), (0.5, 0.5)),
        ((0.2, 0.8), (0.9, 0.9)),
    )


def test_a_trailing_open_stroke_closes_at_the_end() -> None:
    array = np.asarray([[0.0, 0.0, 0.0], [5.0, 5.0, 0.0]])
    strokes = strokes_from_array(array, EXTENT, "u/1")
    assert strokes == (((0.0, 0.0), (0.5, 0.5)),)


def test_a_bad_column_count_raises() -> None:
    with pytest.raises(ValueError, match=r"expected shape \(rows, 3\)"):
        strokes_from_array(np.zeros((4, 2)), EXTENT, "u/1")


def test_a_bad_pen_state_raises() -> None:
    array = np.asarray([[0.0, 0.0, 2.0]])
    with pytest.raises(ValueError, match="pen_state values"):
        strokes_from_array(array, EXTENT, "u/1")


def test_an_unpinned_extent_raises_with_the_observed_ranges() -> None:
    array = np.asarray([[3.0, 4.0, 1.0]])
    with pytest.raises(ValueError, match=r"Observed x in \[3.0, 3.0\]"):
        strokes_from_array(array, None, "u/1")


def test_a_point_off_the_pinned_extent_clamps_to_the_edge() -> None:
    # Parse rule v2: the source data crosses the canvas edge on a
    # small fraction of points, and they clamp — the drawing-canvas
    # rule. A negative value clamps to zero.
    array = np.asarray([[11.0, -2.0, 0.0], [5.0, 5.0, 1.0]])
    strokes = strokes_from_array(array, EXTENT, "u/1")
    assert strokes == (((1.0, 0.0), (0.5, 0.5)),)


def test_unsafe_archive_members_raise() -> None:
    with pytest.raises(ValueError, match="unsafe archive member"):
        _checked_member_name("/etc/passwd")
    with pytest.raises(ValueError, match="unsafe archive member"):
        _checked_member_name("a/../b")
    _checked_member_name("fscoco/vector_sketches/u1/1.npy")


def test_the_hash_covers_content_determinants_and_no_budget() -> None:
    base = fscoco_config_hash(_config())
    assert len(base) == 64
    assert fscoco_config_hash(_config(url="https://example.org/b.tar.gz")) \
        != base
    assert fscoco_config_hash(_config(archive_sha256="1" * 64)) != base
    assert fscoco_config_hash(_config(coordinate_extent=(20.0, 20.0))) \
        != base
    assert fscoco_config_hash(_config(budget_bytes=1)) == base


def _write_tree(data_root: Path, config: FSCocoConfig) -> None:
    """A materialized tree with its meta marker: no download runs."""
    root = (data_root / "sketchsets" / "trees"
            / (config.archive_sha256 or "")[:16])
    for user, name, rows in (
        ("u1", "0001", [[0.0, 0.0, 0.0], [5.0, 5.0, 1.0]]),
        ("u1", "0002", [[1.0, 1.0, 1.0], [2.0, 2.0, 1.0]]),
        ("u2", "0009", [[3.0, 3.0, 0.0], [4.0, 4.0, 1.0]]),
    ):
        sketch_path = root / "tree" / "fscoco" / "vector_sketches" / user \
            / f"{name}.npy"
        sketch_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(sketch_path, np.asarray(rows))
        photo_path = root / "tree" / "fscoco" / "images" / user \
            / f"{name}.jpg"
        photo_path.parent.mkdir(parents=True, exist_ok=True)
        photo_path.write_bytes(b"jpeg-bytes-" + name.encode())
    (root / "meta.json").write_text("{}\n", encoding="utf-8")


def test_iter_pairs_walks_the_tree_in_ascending_sequence(
        tmp_path: Path) -> None:
    config = _config()
    _write_tree(tmp_path, config)
    source = FSCocoSketchPairSource(config, tmp_path)
    pairs = list(source.iter_pairs())
    assert [pair.pair_key for pair in pairs] == [
        "u1/0001", "u1/0002", "u2/0009"]
    assert pairs[0].sketch_strokes == (((0.0, 0.0), (0.5, 0.5)),)
    # Two pen-up rows give two one-point strokes — dots are permitted.
    assert pairs[1].sketch_strokes == (((0.1, 0.1),), ((0.2, 0.2),))
    assert pairs[0].photo_bytes == b"jpeg-bytes-0001"
    assert source.bytes_retrieved == 0


def test_a_missing_photograph_raises(tmp_path: Path) -> None:
    config = _config()
    _write_tree(tmp_path, config)
    source = FSCocoSketchPairSource(config, tmp_path)
    root = tmp_path / "sketchsets" / "trees" / config.archive_sha256[:16]
    (root / "tree" / "fscoco" / "images" / "u1" / "0002.jpg").unlink()
    with pytest.raises(ValueError, match="photograph missing"):
        list(source.iter_pairs())


def test_a_pinned_archive_extracts_without_a_download(
        tmp_path: Path) -> None:
    payload = BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for user, name, rows in (("u1", "0001",
                                  [[0.0, 0.0, 0.0], [5.0, 5.0, 1.0]]),):
            sketch = BytesIO()
            np.save(sketch, np.asarray(rows))
            info = tarfile.TarInfo(
                f"fscoco/vector_sketches/{user}/{name}.npy")
            info.size = len(sketch.getvalue())
            archive.addfile(info, BytesIO(sketch.getvalue()))
            photo = b"jpeg-bytes"
            info = tarfile.TarInfo(f"fscoco/images/{user}/{name}.jpg")
            info.size = len(photo)
            archive.addfile(info, BytesIO(photo))
    archive_bytes = payload.getvalue()
    digest = hashlib.sha256(archive_bytes).hexdigest()

    config = _config(archive_sha256=digest)
    archive_path = tmp_path / "sketchsets" / "archives" \
        / f"{digest}.tar.gz"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)

    source = FSCocoSketchPairSource(config, tmp_path)
    pairs = list(source.iter_pairs())
    assert [pair.pair_key for pair in pairs] == ["u1/0001"]
    assert source.bytes_retrieved == 0
