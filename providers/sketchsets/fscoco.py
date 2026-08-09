"""FS-COCO sketch-pair adapter (spec P2 decision D1).

FS-COCO ships 10,000 freehand scene sketches as vector stroke files,
each paired with one photograph. The adapter downloads one tar.gz
archive, checks its digest, extracts it, and yields SketchPair records
from the extracted tree. Two pin-at-first-download sentinels keep the
lineage honest: with archive_sha256 or coordinate_extent unpinned, the
adapter raises with the observed value in the message — no
trust-on-first-use. The archive cache is addressed by its own digest,
thus pinning after the first download does not force a second fetch.

Constants marked "check at first download" encode the published
FS-COCO layout, which no network run has confirmed in this repository.
A tree that does not agree with them raises — the adapter does not
guess (R14).
"""

import os
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import canonical_json, canonical_json_pretty, sha256_hex
from core.types import StrokePath
from providers.corpora.transport import ByteMeter, MeteredTransport
from providers.protocols import SketchPair, SketchsetIdentity
from providers.sketchsets.pairs import check_sketch_pair

# Check at first download: one vector sketch row is [x, y, pen_state].
_COLUMN_COUNT = 3

# Check at first download: a pen_state of 1 closes the stroke after
# its row, 0 continues it.
_PEN_STATES = (0.0, 1.0)

# Check at first download: directory names in the extracted tree.
_VECTOR_DIR = "vector_sketches"
_IMAGE_DIR = "images"
_IMAGE_SUFFIX = ".jpg"

_PAIR_KEY_RULE = "user-slash-cocoid-v1"

# v2 (measured 2026-08-08 on the pinned archive): the official raster
# renders are 256 x 256, and 0.34% of vector points land off that
# canvas — digitizer overshoot. Out-of-range points clamp to the edge,
# the rule a drawing canvas applies to a pen that leaves it.
_PARSE_RULE = "npy-columns-v2"

_DOWNLOAD_CHUNK = 1 << 20


class FSCocoConfig(NamedTuple):
    """Frozen parameters for the FS-COCO adapter.

    archive_sha256 and coordinate_extent are None until the first
    download pins them. budget_bytes limits the one archive fetch and
    is not part of the config hash — with the digest pinned, the
    budget cannot change delivered content.
    """

    url: str
    archive_sha256: str | None
    coordinate_extent: tuple[float, float] | None
    budget_bytes: int


def fscoco_config_hash(config: FSCocoConfig) -> str:
    """The adapter hash: content determinants only, no budget."""
    return sha256_hex(canonical_json({
        "provider": "fscoco",
        "url": config.url,
        "archive_sha256": config.archive_sha256,
        "coordinate_extent": (list(config.coordinate_extent)
                              if config.coordinate_extent else None),
        "pair_key_rule": _PAIR_KEY_RULE,
        "parse_rule": _PARSE_RULE,
    }))


def strokes_from_array(array: np.ndarray,
                       extent: tuple[float, float] | None,
                       where: str) -> tuple[StrokePath, ...]:
    """Parse one vector sketch array into unit-square strokes (D2).

    The array must be 2-D with the pinned column count and pen states
    in the pinned value set. Each point normalizes by the pinned
    canvas dimensions and clamps into [0, 1] — 0.34% of source
    points land off the canvas (parse rule v2). When the second
    argument is None, raises with the observed ranges in the message
    so the operator can pin coordinate_extent.
    """
    if array.ndim != 2 or array.shape[1] != _COLUMN_COUNT:
        raise ValueError(
            f"{where}: expected shape (rows, {_COLUMN_COUNT}), got "
            f"{array.shape}")
    if array.shape[0] == 0:
        raise ValueError(f"{where}: the sketch has no rows")
    states = array[:, -1]
    bad_states = sorted(set(float(s) for s in states) - set(_PEN_STATES))
    if bad_states:
        raise ValueError(
            f"{where}: pen_state values {bad_states} are not in "
            f"{list(_PEN_STATES)}")
    if extent is None:
        raise ValueError(
            f"{where}: coordinate_extent is not pinned. Observed x in "
            f"[{float(array[:, 0].min())}, {float(array[:, 0].max())}], "
            f"y in [{float(array[:, 1].min())}, "
            f"{float(array[:, 1].max())}]. Pin coordinate_extent in the "
            "dataset section, then run again.")
    extent_x, extent_y = extent
    strokes: list[StrokePath] = []
    current: list[tuple[float, float]] = []
    for row in array:
        x = min(max(float(row[0]) / extent_x, 0.0), 1.0)
        y = min(max(float(row[1]) / extent_y, 0.0), 1.0)
        current.append((x, y))
        if float(row[-1]) == 1.0:
            strokes.append(tuple(current))
            current = []
    if current:
        strokes.append(tuple(current))
    return tuple(strokes)


def _checked_member_name(name: str) -> None:
    parts = Path(name).parts
    if name.startswith("/") or ".." in parts:
        raise ValueError(f"unsafe archive member: {name!r}")


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_bytes(data)
    os.replace(scratch, path)


class FSCocoSketchPairSource:
    """SketchPairSource for one pinned FS-COCO archive."""

    def __init__(self, config: FSCocoConfig, data_root: Path) -> None:
        self._config = config
        self._data_root = data_root
        self._meter = ByteMeter()

    @property
    def identity(self) -> SketchsetIdentity:
        return SketchsetIdentity(
            provider="fscoco", name="fscoco",
            revision=self._config.archive_sha256 or "unpinned")

    @property
    def config_hash(self) -> str:
        return fscoco_config_hash(self._config)

    @property
    def bytes_retrieved(self) -> int:
        return self._meter.total

    def _tree_root(self, digest: str) -> Path:
        # Keyed by the archive digest: the tree content depends on the
        # archive alone, thus pinning coordinate_extent afterward does
        # not extract again and leaves no orphan tree.
        return self._data_root / "sketchsets" / "trees" / digest[:16]

    def _archive_path(self, digest: str) -> Path:
        return (self._data_root / "sketchsets" / "archives"
                / f"{digest}.tar.gz")

    def iter_pairs(self) -> Iterator[SketchPair]:
        """Yield each pair from the extracted tree, ascending pair_key."""
        digest = self._ensure_materialized()
        vector_root = self._vector_root(digest)
        image_root = vector_root.parent / _IMAGE_DIR
        entries: list[tuple[str, Path, Path]] = []
        for user_dir in sorted(vector_root.iterdir()):
            if not user_dir.is_dir():
                raise ValueError(
                    f"unexpected file in {_VECTOR_DIR}: {user_dir.name}")
            for sketch_path in sorted(user_dir.glob("*.npy")):
                pair_key = f"{user_dir.name}/{sketch_path.stem}"
                photo_path = (image_root / user_dir.name
                              / (sketch_path.stem + _IMAGE_SUFFIX))
                if not photo_path.is_file():
                    raise ValueError(
                        f"{pair_key}: photograph missing at {photo_path}")
                entries.append((pair_key, sketch_path, photo_path))
        # The walk sequence approximates pair_key sequence but a stem
        # with a dot can reorder — sort by pair_key, the contract.
        entries.sort(key=lambda entry: entry[0])
        for pair_key, sketch_path, photo_path in entries:
            array = np.load(sketch_path, allow_pickle=False)
            strokes = strokes_from_array(
                array, self._config.coordinate_extent, pair_key)
            pair = SketchPair(
                pair_key=pair_key,
                photo_bytes=photo_path.read_bytes(),
                sketch_strokes=strokes,
                sketch_bytes=None,
                category=None)
            check_sketch_pair(pair)
            yield pair

    def _vector_root(self, digest: str) -> Path:
        tree = self._tree_root(digest) / "tree"
        candidates = sorted(p for p in tree.rglob(_VECTOR_DIR) if p.is_dir())
        if len(candidates) != 1:
            raise ValueError(
                f"expected one {_VECTOR_DIR} directory in the extracted "
                f"tree, found {len(candidates)}")
        return candidates[0]

    def _ensure_materialized(self) -> str:
        """Download, check, and extract one time. Offline afterward.

        Returns the archive digest that keys the tree.
        """
        digest = self._config.archive_sha256
        if digest is not None \
                and (self._tree_root(digest) / "meta.json").is_file():
            return digest
        if digest is None or not self._archive_path(digest).is_file():
            observed = self._download_archive()
            if digest is None:
                raise ValueError(
                    "archive_sha256 is not pinned. The downloaded archive "
                    f"has digest {observed}. Pin archive_sha256 in the "
                    "dataset section, then run again.")
            if observed != digest:
                raise ValueError(
                    f"archive digest mismatch: pinned {digest}, "
                    f"observed {observed}")
        self._extract_archive(self._archive_path(digest), digest)
        meta = {
            "url": self._config.url,
            "archive_sha256": digest,
            "bytes_retrieved": self._meter.total,
            "pair_key_rule": _PAIR_KEY_RULE,
            "parse_rule": _PARSE_RULE,
        }
        _write_bytes_atomic(
            self._tree_root(digest) / "meta.json",
            (canonical_json_pretty(meta) + "\n").encode("utf-8"))
        return digest

    def _download_archive(self) -> str:
        """Fetch the archive with byte accounting (U1). Returns its digest.

        Streams to a scratch file — the archive is multi-GB and must
        not sit in memory.
        """
        import hashlib

        import httpx

        budget = self._config.budget_bytes
        hasher = hashlib.sha256()
        scratch = (self._data_root / "sketchsets" / "archives"
                   / "download.tmp")
        scratch.parent.mkdir(parents=True, exist_ok=True)
        transport = MeteredTransport(httpx.HTTPTransport(), self._meter)
        with httpx.Client(transport=transport, follow_redirects=True,
                          timeout=300.0) as client:
            with client.stream("GET", self._config.url) as response:
                response.raise_for_status()
                with open(scratch, "wb") as sink:
                    for chunk in response.iter_bytes(_DOWNLOAD_CHUNK):
                        if self._meter.total > budget:
                            raise ValueError(
                                f"budget_bytes {budget} passed during the "
                                "archive download — raise the budget or "
                                "use a smaller source")
                        hasher.update(chunk)
                        sink.write(chunk)
        digest = hasher.hexdigest()
        os.replace(scratch, self._archive_path(digest))
        return digest

    def _extract_archive(self, archive_path: Path, digest: str) -> None:
        tree = self._tree_root(digest) / "tree"
        tree.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                _checked_member_name(member.name)
            archive.extractall(tree, filter="data")
