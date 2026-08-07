"""Preparation configuration: frozen sections, strict loading, config hash.

Spec: docs/specs/pool-preparation.md sections 6 and 9. The committed
JSON file is the full parameter surface of one pipeline run. Loading
validates at the boundary and stops with an error that names the full
JSON path of the problem (R14). The runner passes the loaded object down
as arguments - no code reads global config.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.canonical import JsonValue, canonical_json, sha256_hex

SLOT_NAMES: tuple[str, ...] = (
    "describer",
    "text_encoder",
    "image_encoder",
    "line_drawer",
    "element_boxes",
)
DESCRIBER_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")
ENCODER_PROVIDERS: tuple[str, ...] = ("openrouter", "local", "fake")
LINE_DRAWER_PROVIDERS: tuple[str, ...] = ("local", "fake")
BOXES_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")
RESPONSE_FORMAT_MODES: tuple[str, ...] = ("json_schema", "json_object")
CONFIG_VERSION = 1
NORMALIZE_RULES: tuple[str, ...] = ("d7-v1",)
BACKGROUNDS: tuple[str, ...] = ("white",)
CROP_GRIDS: tuple[str, ...] = ("center-corners",)
DEVICES: tuple[str, ...] = ("auto", "cuda", "xpu", "cpu")


class ConfigError(ValueError):
    """The configuration file did not validate."""


@dataclass(frozen=True, slots=True)
class InputSection:
    release_record: str


@dataclass(frozen=True, slots=True)
class ElementCountsSection:
    """The D2 field-count contract of the R2 schema, one count for each field."""

    objects: int
    materials: int
    colors: int
    shapes: int
    scale: int
    setting: int
    ambience: int


@dataclass(frozen=True, slots=True)
class ElementsSection:
    counts: ElementCountsSection
    max_elements: int
    normalize_rule: str


@dataclass(frozen=True, slots=True)
class LinedrawSection:
    binarize_threshold: float
    min_segment_px: int
    canvas_px: int
    line_width_px: int
    background: str
    antialias: bool


@dataclass(frozen=True, slots=True)
class OutlineSection:
    crop_fraction: float
    crop_grid: str


@dataclass(frozen=True, slots=True)
class NeardupSection:
    similarity_threshold: float


@dataclass(frozen=True, slots=True)
class OpenRouterSection:
    default_model: str
    max_concurrency: int
    requests_per_second: float
    timeout_seconds: float
    retry_limit: int
    response_format_mode: str


@dataclass(frozen=True, slots=True)
class SlotSection:
    provider: str
    model: str | None                # slot-level override of default_model
    instruction_template: str | None
    dimension: int | None


@dataclass(frozen=True, slots=True)
class ProvidersSection:
    openrouter: OpenRouterSection
    describer: SlotSection
    text_encoder: SlotSection
    image_encoder: SlotSection
    line_drawer: SlotSection
    element_boxes: SlotSection


@dataclass(frozen=True, slots=True)
class RuntimeSection:
    """Machine-local execution values. Not part of the config hash.

    The device selects where the local providers run. It changes no
    artifact identity: the same config on a CUDA machine and an XPU
    machine addresses the same tree, and the determinism scope stays
    one machine and environment (spec section 14).
    """

    device: str


@dataclass(frozen=True, slots=True)
class ReleaseSection:
    tag: str
    dev_only: bool


@dataclass(frozen=True, slots=True)
class PreparationConfig:
    config_version: int
    input: InputSection
    elements: ElementsSection
    linedraw: LinedrawSection
    outline: OutlineSection
    neardup: NeardupSection
    providers: ProvidersSection
    runtime: RuntimeSection
    release: ReleaseSection


class _Node:
    """One JSON object in strict validation.

    The `_take` helper removes one known field. The `finish` helper rejects
    fields that stay - an unknown field is an error, not a warning (R14).
    """

    def __init__(self, raw: object, path: str) -> None:
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: expected an object")
        self._raw = dict(raw)
        self._path = path

    def child(self, key: str) -> "_Node":
        return _Node(self._take(key), f"{self._path}.{key}")

    def _take(self, key: str) -> object:
        if key not in self._raw:
            raise ConfigError(f"{self._path}.{key}: missing field")
        return self._raw.pop(key)

    def str_(self, key: str) -> str:
        value = self._take(key)
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{self._path}.{key}: expected a non-empty string")
        return value

    def opt_str(self, key: str) -> str | None:
        value = self._take(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{self._path}.{key}: expected a non-empty string or null")
        return value

    def int_(self, key: str, minimum: int | None = None) -> int:
        value = self._take(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{self._path}.{key}: expected an integer")
        if minimum is not None and value < minimum:
            raise ConfigError(f"{self._path}.{key}: must be at least {minimum}")
        return value

    def opt_int(self, key: str, minimum: int | None = None) -> int | None:
        if self._raw.get(key) is None and key in self._raw:
            self._raw.pop(key)
            return None
        return self.int_(key, minimum)

    def float_(self, key: str, low: float | None = None, high: float | None = None,
               low_open: bool = False) -> float:
        value = self._take(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{self._path}.{key}: expected a number")
        value = float(value)
        if low is not None and (value < low or (low_open and value == low)):
            raise ConfigError(f"{self._path}.{key}: out of range")
        if high is not None and value > high:
            raise ConfigError(f"{self._path}.{key}: out of range")
        return value

    def opt_float(self, key: str, low: float | None = None, high: float | None = None,
                  low_open: bool = False) -> float | None:
        if self._raw.get(key) is None and key in self._raw:
            self._raw.pop(key)
            return None
        return self.float_(key, low, high, low_open)

    def bool_(self, key: str) -> bool:
        value = self._take(key)
        if not isinstance(value, bool):
            raise ConfigError(f"{self._path}.{key}: expected a boolean")
        return value

    def str_list(self, key: str, allow_empty: bool = False) -> tuple[str, ...]:
        value = self._take(key)
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ConfigError(f"{self._path}.{key}: expected a list of non-empty strings")
        if not value and not allow_empty:
            raise ConfigError(f"{self._path}.{key}: must not be empty")
        return tuple(value)

    def choice(self, key: str, allowed: tuple[str, ...]) -> str:
        value = self.str_(key)
        if value not in allowed:
            raise ConfigError(f"{self._path}.{key}: expected one of {list(allowed)}")
        return value

    def finish(self) -> None:
        if self._raw:
            names = ", ".join(sorted(self._raw))
            raise ConfigError(f"{self._path}: unknown field(s): {names}")


_SLOT_PROVIDERS: dict[str, tuple[str, ...]] = {
    "describer": DESCRIBER_PROVIDERS,
    "text_encoder": ENCODER_PROVIDERS,
    "image_encoder": ENCODER_PROVIDERS,
    "line_drawer": LINE_DRAWER_PROVIDERS,
    "element_boxes": BOXES_PROVIDERS,
}


def _parse_slot(node: _Node, slot: str) -> SlotSection:
    section = SlotSection(
        provider=node.choice("provider", _SLOT_PROVIDERS[slot]),
        model=node.opt_str("model"),
        instruction_template=node.opt_str("instruction_template"),
        dimension=node.opt_int("dimension", minimum=1),
    )
    node.finish()
    path = f"providers.{slot}"
    if slot in ("describer", "element_boxes"):
        if section.provider == "openrouter" and section.instruction_template is None:
            raise ConfigError(
                f"{path}.instruction_template: required for the openrouter provider"
            )
    if slot in ("text_encoder", "image_encoder"):
        if section.provider in ("openrouter", "fake") and section.dimension is None:
            raise ConfigError(
                f"{path}.dimension: required for the {section.provider} provider"
            )
        if section.provider in ("openrouter", "local") and section.model is None:
            raise ConfigError(
                f"{path}.model: required for the {section.provider} provider"
            )
    if slot == "line_drawer" and section.provider == "local" and section.model is None:
        raise ConfigError(f"{path}.model: required for the local provider")
    return section


def _parse_providers(node: _Node) -> ProvidersSection:
    openrouter_node = node.child("openrouter")
    openrouter = OpenRouterSection(
        default_model=openrouter_node.str_("default_model"),
        max_concurrency=openrouter_node.int_("max_concurrency", minimum=1),
        requests_per_second=openrouter_node.float_("requests_per_second", low=0.0, low_open=True),
        timeout_seconds=openrouter_node.float_("timeout_seconds", low=0.0, low_open=True),
        retry_limit=openrouter_node.int_("retry_limit", minimum=0),
        response_format_mode=openrouter_node.choice("response_format_mode", RESPONSE_FORMAT_MODES),
    )
    openrouter_node.finish()
    section = ProvidersSection(
        openrouter=openrouter,
        describer=_parse_slot(node.child("describer"), "describer"),
        text_encoder=_parse_slot(node.child("text_encoder"), "text_encoder"),
        image_encoder=_parse_slot(node.child("image_encoder"), "image_encoder"),
        line_drawer=_parse_slot(node.child("line_drawer"), "line_drawer"),
        element_boxes=_parse_slot(node.child("element_boxes"), "element_boxes"),
    )
    node.finish()
    return section


def parse_preparation_config(raw: object, source: str = "config") -> PreparationConfig:
    """Parse and validate one raw JSON document into a PreparationConfig."""
    root = _Node(raw, source)

    version = root.int_("config_version")
    if version != CONFIG_VERSION:
        raise ConfigError(f"{source}.config_version: expected {CONFIG_VERSION}")

    input_node = root.child("input")
    input_section = InputSection(release_record=input_node.str_("release_record"))
    input_node.finish()

    elements_node = root.child("elements")
    counts_node = elements_node.child("counts")
    counts = ElementCountsSection(
        objects=counts_node.int_("objects", minimum=1),
        materials=counts_node.int_("materials", minimum=1),
        colors=counts_node.int_("colors", minimum=1),
        shapes=counts_node.int_("shapes", minimum=1),
        scale=counts_node.int_("scale", minimum=1),
        setting=counts_node.int_("setting", minimum=1),
        ambience=counts_node.int_("ambience", minimum=1),
    )
    counts_node.finish()
    elements = ElementsSection(
        counts=counts,
        max_elements=elements_node.int_("max_elements", minimum=1),
        normalize_rule=elements_node.choice("normalize_rule", NORMALIZE_RULES),
    )
    elements_node.finish()

    linedraw_node = root.child("linedraw")
    linedraw = LinedrawSection(
        binarize_threshold=linedraw_node.float_("binarize_threshold", low=0.0, high=1.0),
        min_segment_px=linedraw_node.int_("min_segment_px", minimum=0),
        canvas_px=linedraw_node.int_("canvas_px", minimum=1),
        line_width_px=linedraw_node.int_("line_width_px", minimum=1),
        background=linedraw_node.choice("background", BACKGROUNDS),
        antialias=linedraw_node.bool_("antialias"),
    )
    linedraw_node.finish()

    outline_node = root.child("outline")
    outline = OutlineSection(
        crop_fraction=outline_node.float_("crop_fraction", low=0.0, high=1.0, low_open=True),
        crop_grid=outline_node.choice("crop_grid", CROP_GRIDS),
    )
    outline_node.finish()

    neardup_node = root.child("neardup")
    neardup = NeardupSection(
        similarity_threshold=neardup_node.float_("similarity_threshold", low=0.0, high=1.0,
                                                 low_open=True)
    )
    neardup_node.finish()

    providers = _parse_providers(root.child("providers"))

    runtime_node = root.child("runtime")
    runtime = RuntimeSection(device=runtime_node.choice("device", DEVICES))
    runtime_node.finish()

    release_node = root.child("release")
    release = ReleaseSection(tag=release_node.str_("tag"), dev_only=release_node.bool_("dev_only"))
    release_node.finish()
    if release.dev_only != release.tag.startswith("dev-"):
        raise ConfigError('release.tag: must start with "dev-" exactly when dev_only is true (R15)')

    config = PreparationConfig(
        config_version=version,
        input=input_section,
        elements=elements,
        linedraw=linedraw,
        outline=outline,
        neardup=neardup,
        providers=providers,
        runtime=runtime,
        release=release,
    )
    root.finish()
    return config


def load_preparation_config(path: Path) -> PreparationConfig:
    """Read, parse, and validate the config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{path}: cannot read config: {error}") from error
    return parse_preparation_config(raw, source=str(path))


def _slot_to_json(slot: SlotSection) -> dict[str, JsonValue]:
    return {
        "provider": slot.provider,
        "model": slot.model,
        "instruction_template": slot.instruction_template,
        "dimension": slot.dimension,
    }


def config_to_json_value(config: PreparationConfig) -> dict[str, JsonValue]:
    """The JSON document for a config. The inverse of parsing."""
    counts = config.elements.counts
    providers = config.providers
    return {
        "config_version": config.config_version,
        "input": {"release_record": config.input.release_record},
        "elements": {
            "counts": {
                "objects": counts.objects,
                "materials": counts.materials,
                "colors": counts.colors,
                "shapes": counts.shapes,
                "scale": counts.scale,
                "setting": counts.setting,
                "ambience": counts.ambience,
            },
            "max_elements": config.elements.max_elements,
            "normalize_rule": config.elements.normalize_rule,
        },
        "linedraw": {
            "binarize_threshold": config.linedraw.binarize_threshold,
            "min_segment_px": config.linedraw.min_segment_px,
            "canvas_px": config.linedraw.canvas_px,
            "line_width_px": config.linedraw.line_width_px,
            "background": config.linedraw.background,
            "antialias": config.linedraw.antialias,
        },
        "outline": {
            "crop_fraction": config.outline.crop_fraction,
            "crop_grid": config.outline.crop_grid,
        },
        "neardup": {"similarity_threshold": config.neardup.similarity_threshold},
        "providers": {
            "openrouter": {
                "default_model": providers.openrouter.default_model,
                "max_concurrency": providers.openrouter.max_concurrency,
                "requests_per_second": providers.openrouter.requests_per_second,
                "timeout_seconds": providers.openrouter.timeout_seconds,
                "retry_limit": providers.openrouter.retry_limit,
                "response_format_mode": providers.openrouter.response_format_mode,
            },
            "describer": _slot_to_json(providers.describer),
            "text_encoder": _slot_to_json(providers.text_encoder),
            "image_encoder": _slot_to_json(providers.image_encoder),
            "line_drawer": _slot_to_json(providers.line_drawer),
            "element_boxes": _slot_to_json(providers.element_boxes),
        },
        "runtime": {"device": config.runtime.device},
        "release": {"tag": config.release.tag, "dev_only": config.release.dev_only},
    }


def preparation_config_hash(
    config: PreparationConfig, provider_config_hashes: Mapping[str, str]
) -> str:
    """The hash that keys the pool artifact tree (spec section 6).

    The document contains the full config plus the config_hash of each
    wired provider slot, so a provider code change moves the tree. The
    runtime section is removed first: the device is machine-local and
    must not fork the artifact lineage (spec section 9).
    """
    if set(provider_config_hashes) != set(SLOT_NAMES):
        raise ValueError(f"provider_config_hashes must have keys {list(SLOT_NAMES)}")
    config_document = config_to_json_value(config)
    del config_document["runtime"]
    document: dict[str, JsonValue] = {
        "config": config_document,
        "provider_config_hashes": {k: provider_config_hashes[k] for k in SLOT_NAMES},
    }
    return sha256_hex(canonical_json(document))
