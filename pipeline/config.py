"""Scoring configuration: frozen sections, strict loading, config hash.

Spec: docs/specs/scoring-path.md sections 6 and 9. The committed JSON
file is the full parameter surface of the scoring path and the
harnesses. Loading validates at the boundary and stops with an error
that names the full JSON path of the problem (R14). There is no render
section — the canonical render values come from the preparation config
through the context loader (R2), and a render field here is an
unknown-field error by construction.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import (ElementConfig, IntakeGates, OutlineConfig,
                        PlacementConfig)

SCORING_SLOT_NAMES: tuple[str, ...] = ("sketch_encoder", "sketch_pairs",
                                       "text_encoder")
BUILT_CHANNELS: tuple[str, ...] = ("outline", "element", "placement")
COMPARISON_RULES: tuple[str, ...] = ("center-cosine-v1",)
ELEMENT_COMPARISON_RULES: tuple[str, ...] = ("element-center-cosine-v1",)
MATCHING_RULES: tuple[str, ...] = ("sinkhorn-slack-v1",)
CHECK_RULES: tuple[str, ...] = ("axis-ramp-v1",)
RELATION_VOCABULARY: tuple[str, ...] = ("left-of", "right-of", "above",
                                        "below")
SKETCH_ENCODER_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")
TEXT_ENCODER_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")
SKETCH_PAIR_PROVIDERS: tuple[str, ...] = ("fscoco", "fake")
RESPONSE_FORMAT_MODES: tuple[str, ...] = ("json_schema", "json_object")
SUBMISSION_MODES: tuple[str, ...] = ("sketch", "text", "mixed")
DEVICES: tuple[str, ...] = ("auto", "cuda", "xpu", "cpu")
CONFIG_VERSION = 1

# The alpha value the element channel implements (P3 decision D10).
BUILT_ALPHA = 1.0


class ConfigError(ValueError):
    """The configuration file did not validate."""


@dataclass(frozen=True, slots=True)
class InputSection:
    preparation_record: str


@dataclass(frozen=True, slots=True)
class IntakeSection:
    """The R3 gate values (decision D3)."""

    min_ink_pixels: int
    min_strokes_whole_drawing: int
    max_text_length: int
    max_atoms: int


@dataclass(frozen=True, slots=True)
class OutlineChannelSection:
    comparison_rule: str


@dataclass(frozen=True, slots=True)
class ElementChannelSection:
    """The element channel values (P3 decisions D2, D3, D4, D10)."""

    comparison_rule: str
    matching_rule: str
    epsilon: float
    sinkhorn_iterations: int
    tier2_count: int
    alpha: float


@dataclass(frozen=True, slots=True)
class PlacementChannelSection:
    """The placement channel values (P4 decision D4)."""

    check_rule: str
    relation_vocabulary: tuple[str, ...]
    area_cap: float
    margin: float


@dataclass(frozen=True, slots=True)
class ChannelsSection:
    outline: OutlineChannelSection
    element: ElementChannelSection
    placement: PlacementChannelSection


@dataclass(frozen=True, slots=True)
class FusionSection:
    """The weight table (P2 D12), as sorted pairs, with provenance.

    fit_record names the committed fit record — these weights are its
    winner (P4 decision D7). Null means unfitted — the weights
    are provisional and each harness record says so. The freeze
    updates the two fields together.
    """

    weights: tuple[tuple[str, float], ...]
    fit_record: str | None


@dataclass(frozen=True, slots=True)
class DatasetSection:
    """One SketchPairSource selection (decision D1).

    The fscoco provider reads url, archive_sha256, coordinate_extent,
    and budget_bytes. The fake provider reads fake_pair_count and
    fake_neardup_families. Fields of the other provider must be null.
    archive_sha256 and coordinate_extent are the pin-at-first-download
    sentinels — null until the first download records them.
    """

    provider: str
    url: str | None
    archive_sha256: str | None
    coordinate_extent: tuple[float, float] | None
    budget_bytes: int | None
    fake_pair_count: int | None
    fake_neardup_families: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class SplitFractionsSection:
    """The D8 ranges: background, then v1, then v2."""

    background: float
    v1: float
    v2: float


@dataclass(frozen=True, slots=True)
class SyntheticSection:
    """The source B half of the background (P4 decision D11).

    fit_config names the file that holds the generator level table and
    the generalization slot — the path resolution follows the
    input.preparation_record pattern. count synthetic submissions go
    into the background, built from the seed.
    """

    fit_config: str
    count: int
    seed: int


@dataclass(frozen=True, slots=True)
class CommonnessSection:
    dataset: DatasetSection
    split_salt: str
    background_count: int
    split_fractions: SplitFractionsSection
    synthetic: SyntheticSection | None


@dataclass(frozen=True, slots=True)
class ValidationSection:
    """The harness values. submission_mode is P3 decision D7."""

    v1_pair_count: int
    v2_trial_count: int
    v2_target_seed: int
    submission_mode: str
    tag: str


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
    model: str | None
    instruction_template: str | None
    dimension: int | None


@dataclass(frozen=True, slots=True)
class ProvidersSection:
    openrouter: OpenRouterSection
    sketch_encoder: SlotSection
    text_encoder: SlotSection


@dataclass(frozen=True, slots=True)
class RuntimeSection:
    """Machine-local execution values. Not part of the config hash."""

    device: str


@dataclass(frozen=True, slots=True)
class ReportSection:
    dev_only: bool


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    config_version: int
    input: InputSection
    intake: IntakeSection
    channels: ChannelsSection
    fusion: FusionSection
    commonness: CommonnessSection
    validation: ValidationSection
    providers: ProvidersSection
    runtime: RuntimeSection
    report: ReportSection


class _Node:
    """One JSON object in strict validation (the P1a/P1b pattern).

    The `_take` helper removes one known field. The `finish` helper
    rejects fields that stay — an unknown field is an error (R14).
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

    def any_int(self, key: str) -> int:
        value = self._take(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{self._path}.{key}: expected an integer")
        return value

    def float_(self, key: str, low: float | None = None, high: float | None = None,
               low_open: bool = False) -> float:
        value = self._take(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{self._path}.{key}: expected a number")
        value = float(value)
        if not math.isfinite(value):
            raise ConfigError(f"{self._path}.{key}: expected a finite number")
        if low is not None and (value < low or (low_open and value == low)):
            raise ConfigError(f"{self._path}.{key}: out of range")
        if high is not None and value > high:
            raise ConfigError(f"{self._path}.{key}: out of range")
        return value

    def bool_(self, key: str) -> bool:
        value = self._take(key)
        if not isinstance(value, bool):
            raise ConfigError(f"{self._path}.{key}: expected a boolean")
        return value

    def opt_str_list(self, key: str) -> tuple[str, ...] | None:
        value = self._take(key)
        if value is None:
            return None
        if not isinstance(value, list) or not all(
                isinstance(v, str) and v for v in value):
            raise ConfigError(
                f"{self._path}.{key}: expected a list of non-empty strings "
                "or null")
        return tuple(value)

    def opt_float_pair(self, key: str) -> tuple[float, float] | None:
        value = self._take(key)
        if value is None:
            return None
        if (not isinstance(value, list) or len(value) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(float(v)) or float(v) <= 0.0
                       for v in value)):
            raise ConfigError(
                f"{self._path}.{key}: expected two positive numbers or null")
        return (float(value[0]), float(value[1]))

    def weight_table(self, key: str) -> tuple[tuple[str, float], ...]:
        value = self._take(key)
        if not isinstance(value, dict) or not value:
            raise ConfigError(f"{self._path}.{key}: expected a non-empty object")
        pairs = []
        for name in sorted(value):
            weight = value[name]
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ConfigError(f"{self._path}.{key}.{name}: expected a number")
            if not math.isfinite(float(weight)):
                raise ConfigError(
                    f"{self._path}.{key}.{name}: expected a finite number")
            if float(weight) <= 0.0:
                raise ConfigError(
                    f"{self._path}.{key}.{name}: must be positive — a zero "
                    "weight is channel deactivation by config")
            pairs.append((name, float(weight)))
        return tuple(pairs)

    def choice(self, key: str, allowed: tuple[str, ...]) -> str:
        value = self.str_(key)
        if value not in allowed:
            raise ConfigError(f"{self._path}.{key}: expected one of {list(allowed)}")
        return value

    def finish(self) -> None:
        if self._raw:
            names = ", ".join(sorted(self._raw))
            raise ConfigError(f"{self._path}: unknown field(s): {names}")


def _parse_dataset(node: _Node) -> DatasetSection:
    section = DatasetSection(
        provider=node.choice("provider", SKETCH_PAIR_PROVIDERS),
        url=node.opt_str("url"),
        archive_sha256=node.opt_str("archive_sha256"),
        coordinate_extent=node.opt_float_pair("coordinate_extent"),
        budget_bytes=node.opt_int("budget_bytes", minimum=1),
        fake_pair_count=node.opt_int("fake_pair_count", minimum=1),
        fake_neardup_families=node.opt_str_list("fake_neardup_families"),
    )
    node.finish()
    path = "commonness.dataset"
    if section.provider == "fscoco":
        if section.url is None:
            raise ConfigError(f"{path}.url: required for the fscoco provider")
        if section.budget_bytes is None:
            raise ConfigError(
                f"{path}.budget_bytes: required for the fscoco provider")
        if (section.fake_pair_count is not None
                or section.fake_neardup_families is not None):
            raise ConfigError(
                f"{path}: fake_* fields must be null for the fscoco provider")
    if section.provider == "fake":
        if section.fake_pair_count is None:
            raise ConfigError(
                f"{path}.fake_pair_count: required for the fake provider")
        for name, value in (("url", section.url),
                            ("archive_sha256", section.archive_sha256),
                            ("coordinate_extent", section.coordinate_extent),
                            ("budget_bytes", section.budget_bytes)):
            if value is not None:
                raise ConfigError(
                    f"{path}.{name}: must be null for the fake provider")
    return section


def _parse_encoder_slot(node: _Node, path: str,
                        providers: tuple[str, ...],
                        allow_instruction: bool = False) -> SlotSection:
    section = SlotSection(
        provider=node.choice("provider", providers),
        model=node.opt_str("model"),
        instruction_template=node.opt_str("instruction_template"),
        dimension=node.opt_int("dimension", minimum=1),
    )
    node.finish()
    # The sketch slot reads the field as its joint-embedding
    # instruction (spec P2c section 9a). The text slot keeps the
    # must-be-null rule — an ignored field is a silent thinning of
    # the config (P2c R7).
    if section.instruction_template is not None and not allow_instruction:
        raise ConfigError(
            f"{path}.instruction_template: must be null — the slot has no "
            "instruction")
    if section.dimension is None:
        raise ConfigError(
            f"{path}.dimension: required for the {section.provider} provider")
    if section.provider == "openrouter" and section.model is None:
        raise ConfigError(f"{path}.model: required for the openrouter provider")
    return section


def parse_scoring_config(raw: object, source: str = "config") -> ScoringConfig:
    """Parse and validate one raw JSON document into a ScoringConfig."""
    root = _Node(raw, source)

    version = root.int_("config_version")
    if version != CONFIG_VERSION:
        raise ConfigError(f"{source}.config_version: expected {CONFIG_VERSION}")

    input_node = root.child("input")
    input_section = InputSection(
        preparation_record=input_node.str_("preparation_record"))
    input_node.finish()

    intake_node = root.child("intake")
    intake = IntakeSection(
        min_ink_pixels=intake_node.int_("min_ink_pixels", minimum=0),
        min_strokes_whole_drawing=intake_node.int_(
            "min_strokes_whole_drawing", minimum=1),
        max_text_length=intake_node.int_("max_text_length", minimum=1),
        max_atoms=intake_node.int_("max_atoms", minimum=1),
    )
    intake_node.finish()

    channels_node = root.child("channels")
    outline_node = channels_node.child("outline")
    outline = OutlineChannelSection(
        comparison_rule=outline_node.choice("comparison_rule",
                                            COMPARISON_RULES))
    outline_node.finish()
    element_node = channels_node.child("element")
    element = ElementChannelSection(
        comparison_rule=element_node.choice("comparison_rule",
                                            ELEMENT_COMPARISON_RULES),
        matching_rule=element_node.choice("matching_rule", MATCHING_RULES),
        epsilon=element_node.float_("epsilon", low=0.0, low_open=True),
        sinkhorn_iterations=element_node.int_("sinkhorn_iterations",
                                              minimum=1),
        tier2_count=element_node.int_("tier2_count", minimum=1),
        alpha=element_node.float_("alpha", low=0.0, high=1.0),
    )
    element_node.finish()
    if element.alpha != BUILT_ALPHA:
        raise ConfigError(
            f"channels.element.alpha: expected {BUILT_ALPHA} — the "
            "sketch-vector path behind lower values is not built (D10)")
    placement_node = channels_node.child("placement")
    vocabulary = placement_node.opt_str_list("relation_vocabulary")
    if not vocabulary:
        raise ConfigError(
            "channels.placement.relation_vocabulary: expected a non-empty "
            "list")
    placement = PlacementChannelSection(
        check_rule=placement_node.choice("check_rule", CHECK_RULES),
        relation_vocabulary=vocabulary,
        area_cap=placement_node.float_("area_cap", low=0.0, high=1.0,
                                       low_open=True),
        margin=placement_node.float_("margin", low=0.0, high=1.0,
                                     low_open=True),
    )
    placement_node.finish()
    unknown_relations = sorted(set(placement.relation_vocabulary)
                               - set(RELATION_VOCABULARY))
    if unknown_relations:
        raise ConfigError(
            "channels.placement.relation_vocabulary: no check rule for "
            f"{unknown_relations}")
    channels = ChannelsSection(outline=outline, element=element,
                               placement=placement)
    channels_node.finish()

    fusion_node = root.child("fusion")
    fusion = FusionSection(weights=fusion_node.weight_table("weights"),
                           fit_record=fusion_node.opt_str("fit_record"))
    fusion_node.finish()
    for name, _ in fusion.weights:
        if name not in BUILT_CHANNELS:
            raise ConfigError(
                f"fusion.weights.{name}: not a built channel "
                f"{list(BUILT_CHANNELS)}")

    commonness_node = root.child("commonness")
    dataset = _parse_dataset(commonness_node.child("dataset"))
    fractions_node = commonness_node.child("split_fractions")
    fractions = SplitFractionsSection(
        background=fractions_node.float_("background", low=0.0, high=1.0,
                                         low_open=True),
        v1=fractions_node.float_("v1", low=0.0, high=1.0, low_open=True),
        v2=fractions_node.float_("v2", low=0.0, high=1.0, low_open=True),
    )
    fractions_node.finish()
    if fractions.background + fractions.v1 + fractions.v2 > 1.0:
        raise ConfigError(
            "commonness.split_fractions: the three fractions sum above 1.0")
    synthetic_raw = commonness_node._take("synthetic")
    synthetic: SyntheticSection | None = None
    if synthetic_raw is not None:
        synthetic_node = _Node(synthetic_raw, "commonness.synthetic")
        synthetic = SyntheticSection(
            fit_config=synthetic_node.str_("fit_config"),
            count=synthetic_node.int_("count", minimum=1),
            seed=synthetic_node.any_int("seed"),
        )
        synthetic_node.finish()
    commonness = CommonnessSection(
        dataset=dataset,
        split_salt=commonness_node.str_("split_salt"),
        background_count=commonness_node.int_("background_count", minimum=1),
        split_fractions=fractions,
        synthetic=synthetic,
    )
    commonness_node.finish()
    if synthetic is not None and synthetic.count >= commonness.background_count:
        raise ConfigError(
            "commonness.synthetic.count: must be below background_count — "
            "source A stays in the background as the check (D11)")

    validation_node = root.child("validation")
    validation = ValidationSection(
        v1_pair_count=validation_node.int_("v1_pair_count", minimum=1),
        v2_trial_count=validation_node.int_("v2_trial_count", minimum=1),
        v2_target_seed=validation_node.any_int("v2_target_seed"),
        submission_mode=validation_node.choice("submission_mode",
                                               SUBMISSION_MODES),
        tag=validation_node.str_("tag"),
    )
    validation_node.finish()

    providers_node = root.child("providers")
    openrouter_node = providers_node.child("openrouter")
    openrouter = OpenRouterSection(
        default_model=openrouter_node.str_("default_model"),
        max_concurrency=openrouter_node.int_("max_concurrency", minimum=1),
        requests_per_second=openrouter_node.float_(
            "requests_per_second", low=0.0, low_open=True),
        timeout_seconds=openrouter_node.float_(
            "timeout_seconds", low=0.0, low_open=True),
        retry_limit=openrouter_node.int_("retry_limit", minimum=0),
        response_format_mode=openrouter_node.choice(
            "response_format_mode", RESPONSE_FORMAT_MODES),
    )
    openrouter_node.finish()
    providers = ProvidersSection(
        openrouter=openrouter,
        sketch_encoder=_parse_encoder_slot(
            providers_node.child("sketch_encoder"),
            "providers.sketch_encoder", SKETCH_ENCODER_PROVIDERS,
            allow_instruction=True),
        text_encoder=_parse_encoder_slot(
            providers_node.child("text_encoder"),
            "providers.text_encoder", TEXT_ENCODER_PROVIDERS),
    )
    providers_node.finish()

    runtime_node = root.child("runtime")
    runtime = RuntimeSection(device=runtime_node.choice("device", DEVICES))
    runtime_node.finish()

    report_node = root.child("report")
    report = ReportSection(dev_only=report_node.bool_("dev_only"))
    report_node.finish()
    if report.dev_only != validation.tag.startswith("dev-"):
        raise ConfigError(
            'validation.tag: must start with "dev-" exactly when dev_only '
            "is true (R15)")

    config = ScoringConfig(
        config_version=version,
        input=input_section,
        intake=intake,
        channels=channels,
        fusion=fusion,
        commonness=commonness,
        validation=validation,
        providers=providers,
        runtime=runtime,
        report=report,
    )
    root.finish()
    return config


def load_scoring_config(path: Path) -> ScoringConfig:
    """Read, parse, and validate the config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{path}: cannot read config: {error}") from error
    return parse_scoring_config(raw, source=str(path))


def config_to_json_value(config: ScoringConfig) -> dict[str, JsonValue]:
    """The JSON document for a config. The inverse of parsing."""
    dataset = config.commonness.dataset
    fractions = config.commonness.split_fractions
    synthetic = config.commonness.synthetic
    encoder = config.providers.sketch_encoder
    text_encoder = config.providers.text_encoder
    element = config.channels.element
    placement = config.channels.placement
    openrouter = config.providers.openrouter
    return {
        "config_version": config.config_version,
        "input": {"preparation_record": config.input.preparation_record},
        "intake": {
            "min_ink_pixels": config.intake.min_ink_pixels,
            "min_strokes_whole_drawing":
                config.intake.min_strokes_whole_drawing,
            "max_text_length": config.intake.max_text_length,
            "max_atoms": config.intake.max_atoms,
        },
        "channels": {
            "outline": {
                "comparison_rule": config.channels.outline.comparison_rule,
            },
            "element": {
                "comparison_rule": element.comparison_rule,
                "matching_rule": element.matching_rule,
                "epsilon": element.epsilon,
                "sinkhorn_iterations": element.sinkhorn_iterations,
                "tier2_count": element.tier2_count,
                "alpha": element.alpha,
            },
            "placement": {
                "check_rule": placement.check_rule,
                "relation_vocabulary": list(placement.relation_vocabulary),
                "area_cap": placement.area_cap,
                "margin": placement.margin,
            },
        },
        "fusion": {"weights": dict(config.fusion.weights),
                   "fit_record": config.fusion.fit_record},
        "commonness": {
            "dataset": {
                "provider": dataset.provider,
                "url": dataset.url,
                "archive_sha256": dataset.archive_sha256,
                "coordinate_extent": (list(dataset.coordinate_extent)
                                      if dataset.coordinate_extent else None),
                "budget_bytes": dataset.budget_bytes,
                "fake_pair_count": dataset.fake_pair_count,
                "fake_neardup_families": (
                    list(dataset.fake_neardup_families)
                    if dataset.fake_neardup_families is not None else None),
            },
            "split_salt": config.commonness.split_salt,
            "background_count": config.commonness.background_count,
            "split_fractions": {
                "background": fractions.background,
                "v1": fractions.v1,
                "v2": fractions.v2,
            },
            "synthetic": (None if synthetic is None else {
                "fit_config": synthetic.fit_config,
                "count": synthetic.count,
                "seed": synthetic.seed,
            }),
        },
        "validation": {
            "v1_pair_count": config.validation.v1_pair_count,
            "v2_trial_count": config.validation.v2_trial_count,
            "v2_target_seed": config.validation.v2_target_seed,
            "submission_mode": config.validation.submission_mode,
            "tag": config.validation.tag,
        },
        "providers": {
            "openrouter": {
                "default_model": openrouter.default_model,
                "max_concurrency": openrouter.max_concurrency,
                "requests_per_second": openrouter.requests_per_second,
                "timeout_seconds": openrouter.timeout_seconds,
                "retry_limit": openrouter.retry_limit,
                "response_format_mode": openrouter.response_format_mode,
            },
            "sketch_encoder": {
                "provider": encoder.provider,
                "model": encoder.model,
                "instruction_template": encoder.instruction_template,
                "dimension": encoder.dimension,
            },
            "text_encoder": {
                "provider": text_encoder.provider,
                "model": text_encoder.model,
                "instruction_template": text_encoder.instruction_template,
                "dimension": text_encoder.dimension,
            },
        },
        "runtime": {"device": config.runtime.device},
        "report": {"dev_only": config.report.dev_only},
    }


def scoring_config_hash(
    config: ScoringConfig, provider_config_hashes: Mapping[str, str]
) -> str:
    """The hash that keys each scoring-side artifact (spec section 6).

    The document contains the full config plus the config_hash of each
    wired slot. The runtime section is removed first: the device is
    machine-local and must not fork the artifact lineage.
    """
    if set(provider_config_hashes) != set(SCORING_SLOT_NAMES):
        raise ValueError(
            f"provider_config_hashes must have keys {list(SCORING_SLOT_NAMES)}")
    config_document = config_to_json_value(config)
    del config_document["runtime"]
    # fit_record is provenance: it names the weights' source and moves
    # no score, thus it stays out of the artifact key — a label
    # correction after the freeze must not fork each artifact
    # directory (ruling 2026-08-10).
    config_document["fusion"] = {
        "weights": config_document["fusion"]["weights"]}
    document: dict[str, JsonValue] = {
        "config": config_document,
        "provider_config_hashes": {
            k: provider_config_hashes[k] for k in SCORING_SLOT_NAMES},
    }
    return sha256_hex(canonical_json(document))


def intake_gates(config: ScoringConfig) -> IntakeGates:
    """The core gate record for this config."""
    return IntakeGates(
        min_ink_pixels=config.intake.min_ink_pixels,
        min_strokes_whole_drawing=config.intake.min_strokes_whole_drawing,
        max_text_length=config.intake.max_text_length,
        max_atoms=config.intake.max_atoms,
    )


def outline_config(config: ScoringConfig) -> OutlineConfig:
    """The core outline channel record for this config."""
    return OutlineConfig(
        comparison_rule=config.channels.outline.comparison_rule)


def element_config(config: ScoringConfig) -> ElementConfig:
    """The core element channel record for this config."""
    section = config.channels.element
    return ElementConfig(
        comparison_rule=section.comparison_rule,
        matching_rule=section.matching_rule,
        epsilon=section.epsilon,
        sinkhorn_iterations=section.sinkhorn_iterations,
        tier2_count=section.tier2_count,
        alpha=section.alpha,
    )


def placement_config(config: ScoringConfig) -> PlacementConfig:
    """The core placement channel record for this config."""
    section = config.channels.placement
    return PlacementConfig(
        check_rule=section.check_rule,
        relation_vocabulary=section.relation_vocabulary,
        area_cap=section.area_cap,
        margin=section.margin,
    )


def fusion_weights(config: ScoringConfig) -> dict[str, float]:
    """The weight table as a mapping (decision D12)."""
    return dict(config.fusion.weights)
