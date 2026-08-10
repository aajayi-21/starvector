"""Fit configuration: the generator, the grid, and the V3–V6 values.

Spec: docs/specs/fuse-and-validate.md sections 8, 10, and 11. The fit
config is a committed JSON file apart from the scoring config: its
values select which labeled pairs and synthetic submissions the fit
and the harnesses read, and none of them changes the score of a given
submission — thus they must not fork scoring_config_hash.
The scoring config points at this file through commonness.synthetic
(the input.preparation_record pattern), and V3 through V6 artifact
keys mix fit_config_hash with scoring_config_hash.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from core.canonical import JsonValue, canonical_json, sha256_hex
from pipeline.config import (RESPONSE_FORMAT_MODES, ConfigError,
                             OpenRouterSection, _Node)

GENERALIZE_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")

FIT_CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class LevelRow:
    """One degradation level (P4 decision D1)."""

    n_atoms: int
    generalize_p: float
    n_noise: int
    relations: int


@dataclass(frozen=True, slots=True)
class GeneratorSection:
    """The level table. The top level is the no-information control."""

    levels: tuple[LevelRow, ...]


@dataclass(frozen=True, slots=True)
class GeneralizeSection:
    """The generalization slot (P4 decision D2)."""

    provider: str
    model: str | None
    instruction_template: str | None


@dataclass(frozen=True, slots=True)
class FitSection:
    """The labeled-pair splits and the grid (D5, D6, D8).

    synthetic_count and synthetic_seed name the source 2 sets: the
    fit half uses synthetic_seed and the holdout half uses
    synthetic_seed + 1, thus the two are disjoint by seed (R12).
    """

    split_salt: str
    fit_count: int
    holdout_count: int
    synthetic_count: int
    synthetic_seed: int
    line_points: int
    simplex_step: float
    signal_line: float
    ablation_line: float


@dataclass(frozen=True, slots=True)
class HarnessSection:
    """The V3 and V6 run sizes and seeds (D10)."""

    v3_trials_for_each_level: int
    v3_seed: int
    v6_trial_count: int
    v6_seed: int
    v6_tier1_widths: tuple[int, ...]
    v6_tier2_widths: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FitConfig:
    config_version: int
    generator: GeneratorSection
    generalize: GeneralizeSection
    openrouter: OpenRouterSection
    fit: FitSection
    harness: HarnessSection
    tag: str


def _parse_levels(raw: object) -> tuple[LevelRow, ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ConfigError(
            "generator.levels: expected a list of two or more levels")
    rows = []
    for position, entry in enumerate(raw):
        node = _Node(entry, f"generator.levels[{position}]")
        row = LevelRow(
            n_atoms=node.int_("n_atoms", minimum=0),
            generalize_p=node.float_("generalize_p", low=0.0, high=1.0),
            n_noise=node.int_("n_noise", minimum=0),
            relations=node.int_("relations", minimum=0),
        )
        node.finish()
        if row.n_atoms + row.n_noise < 1:
            raise ConfigError(
                f"generator.levels[{position}]: a level must hold one atom")
        rows.append(row)
    top = rows[-1]
    if top.n_atoms != 0 or top.relations != 0:
        raise ConfigError(
            "generator.levels: the top level is the no-information control "
            "and must hold noise atoms alone (spec P4 section 8.1)")
    return tuple(rows)


def parse_fit_config(raw: object, source: str = "fit-config") -> FitConfig:
    """Parse and validate one raw JSON document into a FitConfig."""
    root = _Node(raw, source)
    version = root.int_("config_version")
    if version != FIT_CONFIG_VERSION:
        raise ConfigError(
            f"{source}.config_version: expected {FIT_CONFIG_VERSION}")

    generator_node = root.child("generator")
    generator = GeneratorSection(
        levels=_parse_levels(generator_node._take("levels")))
    generator_node.finish()

    generalize_node = root.child("generalize")
    generalize = GeneralizeSection(
        provider=generalize_node.choice("provider", GENERALIZE_PROVIDERS),
        model=generalize_node.opt_str("model"),
        instruction_template=generalize_node.opt_str("instruction_template"),
    )
    generalize_node.finish()
    if generalize.provider == "openrouter":
        if generalize.instruction_template is None:
            raise ConfigError(
                "generalize.instruction_template: required for the "
                "openrouter provider")
        if "{element}" not in generalize.instruction_template:
            raise ConfigError(
                "generalize.instruction_template: must hold {element}")
    elif generalize.instruction_template is not None:
        raise ConfigError(
            "generalize.instruction_template: must be null for the fake "
            "provider")

    openrouter_node = root.child("openrouter")
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

    fit_node = root.child("fit")
    fit = FitSection(
        split_salt=fit_node.str_("split_salt"),
        fit_count=fit_node.int_("fit_count", minimum=1),
        holdout_count=fit_node.int_("holdout_count", minimum=1),
        synthetic_count=fit_node.int_("synthetic_count", minimum=1),
        synthetic_seed=fit_node.any_int("synthetic_seed"),
        line_points=fit_node.int_("line_points", minimum=3),
        simplex_step=fit_node.float_("simplex_step", low=0.0, high=0.5,
                                     low_open=True),
        signal_line=fit_node.float_("signal_line", low=0.5, high=1.0),
        ablation_line=fit_node.float_("ablation_line", low=0.0, high=1.0),
    )
    fit_node.finish()

    harness_node = root.child("harness")
    harness = HarnessSection(
        v3_trials_for_each_level=harness_node.int_(
            "v3_trials_for_each_level", minimum=1),
        v3_seed=harness_node.any_int("v3_seed"),
        v6_trial_count=harness_node.int_("v6_trial_count", minimum=1),
        v6_seed=harness_node.any_int("v6_seed"),
        v6_tier1_widths=_width_tuple(
            harness_node._take("v6_tier1_widths"), "harness.v6_tier1_widths"),
        v6_tier2_widths=_width_tuple(
            harness_node._take("v6_tier2_widths"), "harness.v6_tier2_widths"),
    )
    harness_node.finish()

    tag = root.str_("tag")
    root.finish()
    return FitConfig(config_version=version, generator=generator,
                     generalize=generalize, openrouter=openrouter, fit=fit,
                     harness=harness, tag=tag)


def _width_tuple(raw: object, where: str) -> tuple[int, ...]:
    """Ascending positive shortlist widths, with no two equal."""
    if (not isinstance(raw, list) or not raw
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 1
                   for v in raw)):
        raise ConfigError(f"{where}: expected positive integers")
    widths = tuple(raw)
    if any(widths[i] >= widths[i + 1] for i in range(len(widths) - 1)):
        raise ConfigError(f"{where}: widths must be strictly ascending")
    return widths


def load_fit_config(path: Path) -> FitConfig:
    """Read, parse, and validate the fit config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{path}: cannot read fit config: {error}") from error
    return parse_fit_config(raw, source=str(path))


def fit_config_to_json_value(config: FitConfig) -> dict[str, JsonValue]:
    """The JSON document for a fit config. The inverse of parsing."""
    return {
        "config_version": config.config_version,
        "generator": {
            "levels": [
                {"n_atoms": row.n_atoms, "generalize_p": row.generalize_p,
                 "n_noise": row.n_noise, "relations": row.relations}
                for row in config.generator.levels
            ],
        },
        "generalize": {
            "provider": config.generalize.provider,
            "model": config.generalize.model,
            "instruction_template": config.generalize.instruction_template,
        },
        "openrouter": {
            "default_model": config.openrouter.default_model,
            "max_concurrency": config.openrouter.max_concurrency,
            "requests_per_second": config.openrouter.requests_per_second,
            "timeout_seconds": config.openrouter.timeout_seconds,
            "retry_limit": config.openrouter.retry_limit,
            "response_format_mode": config.openrouter.response_format_mode,
        },
        "fit": {
            "split_salt": config.fit.split_salt,
            "fit_count": config.fit.fit_count,
            "holdout_count": config.fit.holdout_count,
            "synthetic_count": config.fit.synthetic_count,
            "synthetic_seed": config.fit.synthetic_seed,
            "line_points": config.fit.line_points,
            "simplex_step": config.fit.simplex_step,
            "signal_line": config.fit.signal_line,
            "ablation_line": config.fit.ablation_line,
        },
        "harness": {
            "v3_trials_for_each_level": config.harness.v3_trials_for_each_level,
            "v3_seed": config.harness.v3_seed,
            "v6_trial_count": config.harness.v6_trial_count,
            "v6_seed": config.harness.v6_seed,
            "v6_tier1_widths": list(config.harness.v6_tier1_widths),
            "v6_tier2_widths": list(config.harness.v6_tier2_widths),
        },
        "tag": config.tag,
    }


def fit_config_hash(config: FitConfig) -> str:
    """The hash that keys the fit-side artifacts (spec P4 section 6)."""
    return sha256_hex(canonical_json(fit_config_to_json_value(config)))


def generalize_slot_hash(config: FitConfig) -> str:
    """The generalization slot hash, computed without wiring."""
    if config.generalize.provider == "openrouter":
        from providers.openrouter.generalize import (GENERALIZE_MAX_TOKENS,
                                                     GeneralizeSlotConfig,
                                                     generalize_config_hash)

        return generalize_config_hash(GeneralizeSlotConfig(
            slot="generalizer",
            model=config.generalize.model or config.openrouter.default_model,
            template=config.generalize.instruction_template or "",
            temperature=0.0,
            seed=0,
            max_tokens=GENERALIZE_MAX_TOKENS,
            reasoning_enabled=False,
            response_format_mode=config.openrouter.response_format_mode,
        ))
    from providers.fake.generalize import FakeGeneralizer

    return FakeGeneralizer().config_hash


def wire_generalizer(config: FitConfig, data_root: Path):
    """Build the generalizer instance for this config."""
    if config.generalize.provider == "openrouter":
        import os

        from providers.openrouter.client import (OpenRouterClient,
                                                 OpenRouterClientConfig)
        from providers.openrouter.generalize import (GENERALIZE_MAX_TOKENS,
                                                     GeneralizeSlotConfig,
                                                     OpenRouterGeneralizer)

        section = config.openrouter
        client = OpenRouterClient(
            OpenRouterClientConfig(
                max_concurrency=section.max_concurrency,
                requests_per_second=section.requests_per_second,
                timeout_seconds=section.timeout_seconds,
                retry_limit=section.retry_limit,
            ),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        )
        return OpenRouterGeneralizer(
            GeneralizeSlotConfig(
                slot="generalizer",
                model=config.generalize.model
                or config.openrouter.default_model,
                template=config.generalize.instruction_template or "",
                temperature=0.0,
                seed=0,
                max_tokens=GENERALIZE_MAX_TOKENS,
                reasoning_enabled=False,
                response_format_mode=config.openrouter.response_format_mode,
            ),
            client,
            data_root / "cache" / "openrouter",
        )
    from providers.fake.generalize import FakeGeneralizer

    return FakeGeneralizer()
