"""Curation configuration: frozen sections, strict loading, config hash.

Spec: docs/specs/pool-curation.md sections 6 and 9. The committed JSON
file is the full parameter surface of one pipeline run. Loading
validates at the boundary and stops with an error that names the full
JSON path of the problem (R14). The runner passes the loaded object down
as arguments - no code reads global config.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.canonical import JsonValue, canonical_json, sha256_hex

CONFIG_VERSION = 1
SLOT_NAMES: tuple[str, ...] = ("text_coverage", "classifier", "object_size", "encoder")
HASH_SLOT_NAMES: tuple[str, ...] = ("corpus",) + SLOT_NAMES
CORPUS_PROVIDERS: tuple[str, ...] = ("huggingface", "fake")
MODEL_SLOT_PROVIDERS: tuple[str, ...] = ("openrouter", "fake")
ENCODER_SLOT_PROVIDERS: tuple[str, ...] = ("fake",)  # a local encoder comes in a build after this one (U2)
MATERIALIZATION_MODES: tuple[str, ...] = ("wikimedia-thumbnail", "fake")
RESPONSE_FORMAT_MODES: tuple[str, ...] = ("json_schema", "json_object")


class ConfigError(ValueError):
    """The configuration file did not validate."""


@dataclass(frozen=True, slots=True)
class ColumnsSection:
    source_key: str
    claimed_width: str | None
    claimed_height: str | None
    captions: tuple[str, ...]
    attribution: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaterializationSection:
    mode: str
    thumbnail_width: int
    user_agent: str
    max_concurrency: int
    timeout_seconds: float
    retry_limit: int
    fetch_batch_size: int
    max_fetch_bytes: int


@dataclass(frozen=True, slots=True)
class CorpusSection:
    provider: str
    repo_id: str
    revision: str
    config_name: str | None
    split: str
    columns: ColumnsSection
    license_note: str
    max_scan_shards: int | None
    materialization: MaterializationSection


@dataclass(frozen=True, slots=True)
class SamplingSection:
    sample_salt: str
    sample_rate: float


@dataclass(frozen=True, slots=True)
class ExtractionSection:
    budget_bytes: int
    materialize_cap: int | None


@dataclass(frozen=True, slots=True)
class ScreenSection:
    min_short_side: int
    min_aspect: float
    max_aspect: float


@dataclass(frozen=True, slots=True)
class TextSection:
    max_text_coverage: float


@dataclass(frozen=True, slots=True)
class ClassifySection:
    labels: tuple[str, ...]
    keep_label: str
    label_template: str


@dataclass(frozen=True, slots=True)
class ObjectSection:
    min_object_fraction: float


@dataclass(frozen=True, slots=True)
class NeardupSection:
    similarity_threshold: float


@dataclass(frozen=True, slots=True)
class DiversitySection:
    cluster_size_divisor: int
    cluster_cap: int
    kmeans_max_iterations: int


@dataclass(frozen=True, slots=True)
class ReviewSection:
    sample_size: int
    thumbnail_max_side: int


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
    model: str | None                       # slot-level override of default_model
    instruction_template: str | None        # required for openrouter slots
    dimension: int | None                   # required for the fake encoder
    probability_sum_tolerance: float | None  # required for the openrouter classifier


@dataclass(frozen=True, slots=True)
class ProvidersSection:
    openrouter: OpenRouterSection
    text_coverage: SlotSection
    classifier: SlotSection
    object_size: SlotSection
    encoder: SlotSection


@dataclass(frozen=True, slots=True)
class SeedsSection:
    cluster_seed: int
    review_seed: int


@dataclass(frozen=True, slots=True)
class ReleaseSection:
    tag: str
    dev_only: bool


@dataclass(frozen=True, slots=True)
class CurationConfig:
    config_version: int
    corpus: CorpusSection
    sampling: SamplingSection
    extraction: ExtractionSection
    screen: ScreenSection
    text: TextSection
    classify: ClassifySection
    objectsize: ObjectSection
    neardup: NeardupSection
    diversity: DiversitySection
    review: ReviewSection
    providers: ProvidersSection
    seeds: SeedsSection
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


def _parse_columns(node: _Node) -> ColumnsSection:
    section = ColumnsSection(
        source_key=node.str_("source_key"),
        claimed_width=node.opt_str("claimed_width"),
        claimed_height=node.opt_str("claimed_height"),
        captions=node.str_list("captions", allow_empty=True),
        attribution=node.str_list("attribution", allow_empty=True),
    )
    node.finish()
    return section


def _parse_materialization(node: _Node) -> MaterializationSection:
    section = MaterializationSection(
        mode=node.choice("mode", MATERIALIZATION_MODES),
        thumbnail_width=node.int_("thumbnail_width", minimum=1),
        user_agent=node.str_("user_agent"),
        max_concurrency=node.int_("max_concurrency", minimum=1),
        timeout_seconds=node.float_("timeout_seconds", low=0.0, low_open=True),
        retry_limit=node.int_("retry_limit", minimum=0),
        fetch_batch_size=node.int_("fetch_batch_size", minimum=1),
        max_fetch_bytes=node.int_("max_fetch_bytes", minimum=1),
    )
    node.finish()
    return section


def _parse_corpus(node: _Node) -> CorpusSection:
    section = CorpusSection(
        provider=node.choice("provider", CORPUS_PROVIDERS),
        repo_id=node.str_("repo_id"),
        revision=node.str_("revision"),
        config_name=node.opt_str("config_name"),
        split=node.str_("split"),
        columns=_parse_columns(node.child("columns")),
        license_note=node.str_("license_note"),
        max_scan_shards=node.opt_int("max_scan_shards", minimum=1),
        materialization=_parse_materialization(node.child("materialization")),
    )
    node.finish()
    return section


def _parse_classify(node: _Node) -> ClassifySection:
    labels = node.str_list("labels")
    if len(set(labels)) != len(labels):
        raise ConfigError("classify.labels: labels must be unique")
    keep_label = node.str_("keep_label")
    if keep_label not in labels:
        raise ConfigError("classify.keep_label: must be one of classify.labels")
    template = node.str_("label_template")
    if template.count("{label}") != 1:
        raise ConfigError("classify.label_template: must contain {label} exactly one time")
    node.finish()
    return ClassifySection(labels=labels, keep_label=keep_label, label_template=template)


def _parse_slot(node: _Node, slot: str) -> SlotSection:
    allowed = ENCODER_SLOT_PROVIDERS if slot == "encoder" else MODEL_SLOT_PROVIDERS
    section = SlotSection(
        provider=node.choice("provider", allowed),
        model=node.opt_str("model"),
        instruction_template=node.opt_str("instruction_template"),
        dimension=node.opt_int("dimension", minimum=1),
        probability_sum_tolerance=node.opt_float(
            "probability_sum_tolerance", low=0.0, high=1.0, low_open=True
        ),
    )
    node.finish()
    path = f"providers.{slot}"
    if section.provider == "openrouter" and section.instruction_template is None:
        raise ConfigError(f"{path}.instruction_template: required for the openrouter provider")
    if slot == "classifier" and section.provider == "openrouter" \
            and section.probability_sum_tolerance is None:
        raise ConfigError(f"{path}.probability_sum_tolerance: required for the openrouter classifier")
    if slot == "encoder" and section.provider == "fake" and section.dimension is None:
        raise ConfigError(f"{path}.dimension: required for the fake encoder")
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
        text_coverage=_parse_slot(node.child("text_coverage"), "text_coverage"),
        classifier=_parse_slot(node.child("classifier"), "classifier"),
        object_size=_parse_slot(node.child("object_size"), "object_size"),
        encoder=_parse_slot(node.child("encoder"), "encoder"),
    )
    node.finish()
    return section


def parse_curation_config(raw: object, source: str = "config") -> CurationConfig:
    """Parse and validate one raw JSON document into a CurationConfig."""
    root = _Node(raw, source)
    version = root.int_("config_version")
    if version != CONFIG_VERSION:
        raise ConfigError(f"{source}.config_version: expected {CONFIG_VERSION}")

    sampling_node = root.child("sampling")
    sampling = SamplingSection(
        sample_salt=sampling_node.str_("sample_salt"),
        sample_rate=sampling_node.float_("sample_rate", low=0.0, high=1.0, low_open=True),
    )
    sampling_node.finish()

    extraction_node = root.child("extraction")
    extraction = ExtractionSection(
        budget_bytes=extraction_node.int_("budget_bytes", minimum=1),
        materialize_cap=extraction_node.opt_int("materialize_cap", minimum=1),
    )
    extraction_node.finish()

    screen_node = root.child("screen")
    screen = ScreenSection(
        min_short_side=screen_node.int_("min_short_side", minimum=1),
        min_aspect=screen_node.float_("min_aspect", low=0.0, low_open=True),
        max_aspect=screen_node.float_("max_aspect", low=0.0, low_open=True),
    )
    screen_node.finish()
    if screen.min_aspect >= screen.max_aspect:
        raise ConfigError("screen.min_aspect: must be less than screen.max_aspect")

    text_node = root.child("text")
    text = TextSection(max_text_coverage=text_node.float_("max_text_coverage", low=0.0, high=1.0))
    text_node.finish()

    object_node = root.child("objectsize")
    objectsize = ObjectSection(
        min_object_fraction=object_node.float_("min_object_fraction", low=0.0, high=1.0)
    )
    object_node.finish()

    neardup_node = root.child("neardup")
    neardup = NeardupSection(
        similarity_threshold=neardup_node.float_("similarity_threshold", low=0.0, high=1.0,
                                                 low_open=True)
    )
    neardup_node.finish()

    diversity_node = root.child("diversity")
    diversity = DiversitySection(
        cluster_size_divisor=diversity_node.int_("cluster_size_divisor", minimum=1),
        cluster_cap=diversity_node.int_("cluster_cap", minimum=1),
        kmeans_max_iterations=diversity_node.int_("kmeans_max_iterations", minimum=1),
    )
    diversity_node.finish()

    review_node = root.child("review")
    review = ReviewSection(
        sample_size=review_node.int_("sample_size", minimum=1),
        thumbnail_max_side=review_node.int_("thumbnail_max_side", minimum=16),
    )
    review_node.finish()

    seeds_node = root.child("seeds")
    seeds = SeedsSection(
        cluster_seed=seeds_node.int_("cluster_seed"),
        review_seed=seeds_node.int_("review_seed"),
    )
    seeds_node.finish()

    release_node = root.child("release")
    release = ReleaseSection(tag=release_node.str_("tag"), dev_only=release_node.bool_("dev_only"))
    release_node.finish()
    if release.dev_only != release.tag.startswith("dev-"):
        raise ConfigError('release.tag: must start with "dev-" exactly when dev_only is true (R13)')

    config = CurationConfig(
        config_version=version,
        corpus=_parse_corpus(root.child("corpus")),
        sampling=sampling,
        extraction=extraction,
        screen=screen,
        text=text,
        classify=_parse_classify(root.child("classify")),
        objectsize=objectsize,
        neardup=neardup,
        diversity=diversity,
        review=review,
        providers=_parse_providers(root.child("providers")),
        seeds=seeds,
        release=release,
    )
    root.finish()
    return config


def load_curation_config(path: Path) -> CurationConfig:
    """Read, parse, and validate the config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"{path}: cannot read config: {error}") from error
    return parse_curation_config(raw, source=str(path))


def _slot_to_json(slot: SlotSection) -> dict[str, JsonValue]:
    return {
        "provider": slot.provider,
        "model": slot.model,
        "instruction_template": slot.instruction_template,
        "dimension": slot.dimension,
        "probability_sum_tolerance": slot.probability_sum_tolerance,
    }


def config_to_json_value(config: CurationConfig) -> dict[str, JsonValue]:
    """The JSON document for a config. The inverse of parsing."""
    corpus = config.corpus
    providers = config.providers
    return {
        "config_version": config.config_version,
        "corpus": {
            "provider": corpus.provider,
            "repo_id": corpus.repo_id,
            "revision": corpus.revision,
            "config_name": corpus.config_name,
            "split": corpus.split,
            "columns": {
                "source_key": corpus.columns.source_key,
                "claimed_width": corpus.columns.claimed_width,
                "claimed_height": corpus.columns.claimed_height,
                "captions": list(corpus.columns.captions),
                "attribution": list(corpus.columns.attribution),
            },
            "license_note": corpus.license_note,
            "max_scan_shards": corpus.max_scan_shards,
            "materialization": {
                "mode": corpus.materialization.mode,
                "thumbnail_width": corpus.materialization.thumbnail_width,
                "user_agent": corpus.materialization.user_agent,
                "max_concurrency": corpus.materialization.max_concurrency,
                "timeout_seconds": corpus.materialization.timeout_seconds,
                "retry_limit": corpus.materialization.retry_limit,
                "fetch_batch_size": corpus.materialization.fetch_batch_size,
                "max_fetch_bytes": corpus.materialization.max_fetch_bytes,
            },
        },
        "sampling": {
            "sample_salt": config.sampling.sample_salt,
            "sample_rate": config.sampling.sample_rate,
        },
        "extraction": {
            "budget_bytes": config.extraction.budget_bytes,
            "materialize_cap": config.extraction.materialize_cap,
        },
        "screen": {
            "min_short_side": config.screen.min_short_side,
            "min_aspect": config.screen.min_aspect,
            "max_aspect": config.screen.max_aspect,
        },
        "text": {"max_text_coverage": config.text.max_text_coverage},
        "classify": {
            "labels": list(config.classify.labels),
            "keep_label": config.classify.keep_label,
            "label_template": config.classify.label_template,
        },
        "objectsize": {"min_object_fraction": config.objectsize.min_object_fraction},
        "neardup": {"similarity_threshold": config.neardup.similarity_threshold},
        "diversity": {
            "cluster_size_divisor": config.diversity.cluster_size_divisor,
            "cluster_cap": config.diversity.cluster_cap,
            "kmeans_max_iterations": config.diversity.kmeans_max_iterations,
        },
        "review": {
            "sample_size": config.review.sample_size,
            "thumbnail_max_side": config.review.thumbnail_max_side,
        },
        "providers": {
            "openrouter": {
                "default_model": providers.openrouter.default_model,
                "max_concurrency": providers.openrouter.max_concurrency,
                "requests_per_second": providers.openrouter.requests_per_second,
                "timeout_seconds": providers.openrouter.timeout_seconds,
                "retry_limit": providers.openrouter.retry_limit,
                "response_format_mode": providers.openrouter.response_format_mode,
            },
            "text_coverage": _slot_to_json(providers.text_coverage),
            "classifier": _slot_to_json(providers.classifier),
            "object_size": _slot_to_json(providers.object_size),
            "encoder": _slot_to_json(providers.encoder),
        },
        "seeds": {
            "cluster_seed": config.seeds.cluster_seed,
            "review_seed": config.seeds.review_seed,
        },
        "release": {"tag": config.release.tag, "dev_only": config.release.dev_only},
    }


def curation_config_hash(config: CurationConfig, provider_config_hashes: Mapping[str, str]) -> str:
    """The hash that keys the artifact tree (spec section 6).

    The document contains the full config plus the config_hash of each
    wired provider, so a provider code change moves the tree.
    """
    if set(provider_config_hashes) != set(HASH_SLOT_NAMES):
        raise ValueError(f"provider_config_hashes must have keys {list(HASH_SLOT_NAMES)}")
    document: dict[str, JsonValue] = {
        "config": config_to_json_value(config),
        "provider_config_hashes": {k: provider_config_hashes[k] for k in HASH_SLOT_NAMES},
    }
    return sha256_hex(canonical_json(document))
