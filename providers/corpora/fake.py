"""Deterministic fake source corpus for tests and offline development.

Implements the SourceCorpus protocol of docs/specs/pool-curation.md
section 7. Each content class gives fixtures that one curation stage
accepts or rejects. Pixel content is a seeded numpy gradient plus
rectangles, saved as PNG with tEXt chunks that the fake providers read.
Two instances with the same configuration give the same bytes.
"""

from collections.abc import Iterator, Sequence
from io import BytesIO
from typing import NamedTuple

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.canonical import JsonValue, canonical_json, sha256_hex
from providers.protocols import (
    CorpusIdentity,
    MaterializedImage,
    MaterializeFailure,
    SourceRecord,
)

# Dimensions shared by the photo-like content classes.
_PHOTO_DIMS = (800, 600)


class FakeRecordSpec(NamedTuple):
    """One configured sequence of records of one content class."""

    content_class: str
    count: int


class FakeCorpusConfig(NamedTuple):
    """The full parameter set of one fake corpus."""

    records: tuple[FakeRecordSpec, ...]
    scan_bytes_per_record: int


class _RecordPlan(NamedTuple):
    """The materialization plan for one record."""

    source_key: str
    claimed_width: int | None
    claimed_height: int | None
    kind: str                           # "image", "undecodable", or a scripted failure
    width: int                          # decoded pixel dimensions, PNG records only
    height: int
    chunks: tuple[tuple[str, str], ...]  # sorted tEXt entries
    pixel_key: str                      # seed key for the pixel content


def _seed_from(data: bytes | str) -> int:
    """The output is an integer seed built from the first 8 SHA-256 digest bytes."""
    return int(sha256_hex(data)[:16], 16)


def _photo_chunks(index: int) -> dict[str, str]:
    """The tEXt entries of one photo-like record."""
    return {
        "fake_label": "photograph",
        "fake_text_coverage": "0.01",
        "fake_object_fraction": "0.5",
        "embed_family": f"solo-{index}",
        "embed_jitter": "unique",
    }


def _build_plan(content_class: str, index: int, spec_position: int) -> _RecordPlan:
    """The plan for one record of one content class.

    The index counts records of one class, in ascending sequence. An
    unknown content class raises ValueError.
    """
    source_key = f"fake://{content_class}/{index:04d}"
    claimed: tuple[int | None, int | None] = _PHOTO_DIMS
    dims = _PHOTO_DIMS
    chunks = _photo_chunks(index)
    kind = "image"
    pixel_key = source_key
    match content_class:
        case "photo":
            pass
        case "lowres":
            claimed = (300, 300)
            dims = (300, 300)
            chunks = {}
        case "lowres_lying":
            # Claimed dimensions stay 800x600 - the decoded pixels show less.
            dims = (300, 200)
            chunks = {}
        case "no_metadata":
            claimed = (None, None)
            dims = (700, 700)
        case "bad_aspect":
            claimed = (1600, 600)
            dims = (1600, 600)
            chunks = {}
        case "aspect_boundary":
            claimed = (1024, 512)
            dims = (1024, 512)
        case "undecodable":
            kind = "undecodable"
            chunks = {}
        case "fetch_fail":
            kind = "fetch-fail"
            chunks = {}
        case "dup_bytes":
            # One shared pixel key and one shared chunk set give the
            # same PNG bytes for the full class.
            chunks = _photo_chunks(0)
            chunks["embed_family"] = "solo-dup-bytes"
            pixel_key = "fake://dup_bytes/shared"
        case "text_heavy":
            chunks["fake_text_coverage"] = "0.40"
        case "text_boundary":
            chunks["fake_text_coverage"] = "0.05"
        case "diagram":
            chunks["fake_label"] = "diagram"
        case "logo":
            chunks["fake_label"] = "logo"
        case "map_like":
            chunks["fake_label"] = "map"
        case "small_object":
            chunks["fake_object_fraction"] = "0.10"
        case "object_boundary":
            chunks["fake_object_fraction"] = "0.15"
        case "no_object":
            chunks["fake_object_fraction"] = "0.0"
        case "neardup_pair":
            # The two members of a pair have different pixel areas, and
            # thus the s06 keep rule is observable.
            dims = (900, 700) if index % 2 == 0 else (800, 600)
            claimed = dims
            chunks["embed_family"] = f"neardup-{index // 2}"
            chunks["embed_jitter"] = "dup"
        case "cluster_family":
            # All records of one configured spec share one family.
            chunks["embed_family"] = f"cluster-{spec_position}"
            chunks["embed_jitter"] = "family"
        case _:
            raise ValueError(f"unknown content class: {content_class!r}")
    width, height = dims
    return _RecordPlan(
        source_key=source_key,
        claimed_width=claimed[0],
        claimed_height=claimed[1],
        kind=kind,
        width=width,
        height=height,
        chunks=tuple(sorted(chunks.items())),
        pixel_key=pixel_key,
    )


def _render_png(
    width: int, height: int, pixel_key: str, chunks: tuple[tuple[str, str], ...]
) -> bytes:
    """One deterministic PNG: a seeded gradient plus seeded rectangles."""
    rng = np.random.default_rng(_seed_from(pixel_key))
    ramp_x = np.linspace(0.0, 255.0, num=width)
    ramp_y = np.linspace(0.0, 255.0, num=height)
    red = np.broadcast_to(ramp_x, (height, width))
    green = np.broadcast_to(ramp_y[:, None], (height, width))
    blue = np.full((height, width), float(rng.integers(0, 256)))
    pixels = np.stack([red, green, blue], axis=2).astype(np.uint8)  # (height, width, 3)
    for _ in range(4):
        x0 = int(rng.integers(0, width))
        y0 = int(rng.integers(0, height))
        x1 = int(rng.integers(x0, width)) + 1
        y1 = int(rng.integers(y0, height)) + 1
        pixels[y0:y1, x0:x1] = rng.integers(0, 256, size=3, dtype=np.uint8)
    info = PngInfo()
    for chunk_key, chunk_value in chunks:
        info.add_text(chunk_key, chunk_value)
    buffer = BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def _undecodable_bytes(pixel_key: str) -> bytes:
    """Seeded random-looking bytes that no image decoder accepts."""
    rng = np.random.default_rng(_seed_from(pixel_key))
    payload = rng.integers(0, 256, size=512, dtype=np.uint8).tobytes()
    # The ASCII prefix makes sure the bytes align with no image signature.
    return b"not-an-image:" + payload


def _config_json(config: FakeCorpusConfig) -> dict[str, JsonValue]:
    """The canonical JSON document for one fake corpus configuration."""
    return {
        "records": [
            {"content_class": spec.content_class, "count": spec.count}
            for spec in config.records
        ],
        "scan_bytes_per_record": config.scan_bytes_per_record,
    }


class FakeCorpus:
    """Fake corpus that makes scripted PNG fixtures.

    The record sequence follows the configured specs. The source key
    scheme is "fake://{content_class}/{index:04d}", and the index
    counts records of one class. A monotone byte counter covers the
    metadata scan and the materialized payloads (U1).
    """

    def __init__(self, config: FakeCorpusConfig) -> None:
        plans: list[_RecordPlan] = []
        class_counters: dict[str, int] = {}
        for spec_position, spec in enumerate(config.records):
            for _ in range(spec.count):
                index = class_counters.get(spec.content_class, 0)
                class_counters[spec.content_class] = index + 1
                plans.append(_build_plan(spec.content_class, index, spec_position))
        self._config = config
        self._plans = tuple(plans)
        self._plan_by_key = {plan.source_key: plan for plan in plans}
        self._bytes_retrieved = 0

    @property
    def identity(self) -> CorpusIdentity:
        """The pinned identity. The revision comes from the configuration."""
        revision = sha256_hex(canonical_json(_config_json(self._config)))[:40]
        return CorpusIdentity(
            provider="fake",
            repo_id="fake-corpus",
            revision=revision,
            config_name=None,
            split="train",
        )

    @property
    def config_hash(self) -> str:
        """Stable hash of the configuration, with a provider marker."""
        document: dict[str, JsonValue] = {"provider": "fake-corpus"}
        document.update(_config_json(self._config))
        return sha256_hex(canonical_json(document))

    @property
    def bytes_retrieved(self) -> int:
        """Monotone count of bytes this corpus supplied (U1)."""
        return self._bytes_retrieved

    def iter_records(self) -> Iterator[SourceRecord]:
        """Iterate the configured records in a fixed sequence.

        Each yielded record adds scan_bytes_per_record to the byte
        counter.
        """
        for plan in self._plans:
            self._bytes_retrieved += self._config.scan_bytes_per_record
            yield SourceRecord(
                source_key=plan.source_key,
                claimed_width=plan.claimed_width,
                claimed_height=plan.claimed_height,
                captions=(f"Fake caption for {plan.source_key}",),
                attribution={"license": "fake", "source_key": plan.source_key},
            )

    def materialize_many(
        self, records: Sequence[SourceRecord]
    ) -> list[MaterializedImage | MaterializeFailure]:
        """Materialize each record. Results align with the input index.

        A fetch_fail record gives a MaterializeFailure. All other
        records give a MaterializedImage, and the byte counter increases
        by the byte count of each payload. An unknown source key raises
        ValueError.
        """
        results: list[MaterializedImage | MaterializeFailure] = []
        for record in records:
            plan = self._plan_by_key.get(record.source_key)
            if plan is None:
                raise ValueError(f"unknown source_key: {record.source_key!r}")
            if plan.kind == "fetch-fail":
                results.append(
                    MaterializeFailure(plan.source_key, "fetch-error", "scripted failure")
                )
                continue
            if plan.kind == "undecodable":
                image_bytes = _undecodable_bytes(plan.pixel_key)
            else:
                image_bytes = _render_png(
                    plan.width, plan.height, plan.pixel_key, plan.chunks
                )
            self._bytes_retrieved += len(image_bytes)
            results.append(
                MaterializedImage(plan.source_key, image_bytes, "fake://generated")
            )
        return results
