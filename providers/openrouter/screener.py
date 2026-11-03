"""One OpenRouter POST for the s03, s04, and s05 screens.

Spec: docs/specs/production-pool.md section 5a and build item B7. The
image is about 1,800 of the 1,850 prompt tokens of each screen, thus one
answer with all the fields costs about one third of three answers. The
three stage protocols do not move: this one provider fills the three
slots and the person-role slot from one cached response. Text, label,
and object thresholds stay in the stage rules.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import FloatArray
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError
from providers.openrouter.resolve import (chat_request_body,
                                          checked_response_format_mode,
                                          default_clock, json_payload,
                                          resolve_chat)
from providers.openrouter.slots import (_LABEL_PLACEHOLDER, _choice_row,
                                        _fraction_value)

PERSON_ROLES: tuple[str, ...] = ("none", "in_scene", "main_subject")
_PERSON_MAIN = "main_subject"
_TEXT_KEY = "text_area_fraction"
_OBJECT_KEY = "largest_object_fraction"
_PERSON_KEY = "person_role"


class ScreenerSlotConfig(NamedTuple):
    """The full parameter set of the screener. Each field enters the hash.

    labels is the closed set of s04, in label sequence. input_canvas_px
    is the long side of the image the POST holds, or None for the
    materialized bytes.
    """

    slot: str
    model: str
    template: str
    labels: tuple[str, ...]
    temperature: float
    seed: int
    max_tokens: int
    reasoning_enabled: bool
    response_format_mode: str
    input_canvas_px: int | None


class ScreenAnswer(NamedTuple):
    """The one parsed answer for one image."""

    text_fraction: float
    label_row: tuple[float, ...]
    object_fraction: float
    person_role: str


def screener_config_hash(config: ScreenerSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config."""
    document = dict(config._asdict())
    document["labels"] = list(config.labels)
    return sha256_hex(canonical_json(document))


def _screen_schema(labels: tuple[str, ...]) -> dict[str, JsonValue]:
    fraction = {"type": "number", "minimum": 0, "maximum": 1}
    return {
        "type": "object",
        "properties": {
            _TEXT_KEY: fraction,
            "label": {"type": "string", "enum": list(labels)},
            "confidence": fraction,
            _OBJECT_KEY: fraction,
            _PERSON_KEY: {"type": "string", "enum": list(PERSON_ROLES)},
        },
        "required": [_TEXT_KEY, "label", "confidence", _OBJECT_KEY, _PERSON_KEY],
        "additionalProperties": False,
    }


def _screen_answer(payload: Mapping[str, object],
                   labels: tuple[str, ...]) -> ScreenAnswer:
    """One validated answer. A missing or out-of-set field raises (R14)."""
    role = payload.get(_PERSON_KEY)
    if not isinstance(role, str) or role not in PERSON_ROLES:
        raise OpenRouterResponseError(f"person_role is not in the set: {role!r}")
    return ScreenAnswer(
        text_fraction=_fraction_value(payload, _TEXT_KEY),
        label_row=_choice_row(payload, labels),
        object_fraction=_fraction_value(payload, _OBJECT_KEY),
        person_role=role,
    )


class OpenRouterScreener:
    """TextCoverageEstimator, ZeroShotImageClassifier,
    SalientObjectEstimator, and PersonRoleEstimator from one response.

    The cache key is the hash of the materialized bytes. Each stage reads
    the entry that the first stage stored, thus only the first stage of
    an image makes a POST. prepare is the input render, injected at
    wiring because providers do not import pool code.
    """

    def __init__(
        self,
        slot_config: ScreenerSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        prepare: Callable[[bytes], bytes] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        checked_response_format_mode(slot_config.response_format_mode)
        if _LABEL_PLACEHOLDER not in slot_config.template:
            raise ValueError(
                f"screener template must contain {_LABEL_PLACEHOLDER!r}")
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._prepare = prepare
        self._clock = clock if clock is not None else default_clock
        self._config_hash = screener_config_hash(slot_config)
        self._cache_hit_count = 0
        quoted = '"' + '", "'.join(slot_config.labels) + '"'
        self._instruction = slot_config.template.replace(_LABEL_PLACEHOLDER, quoted)
        self._schema = _screen_schema(slot_config.labels)

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def cache_hit_count(self) -> int:
        return self._cache_hit_count

    @property
    def post_count(self) -> int:
        return self._client.post_count

    def _answers(self, images: Sequence[bytes]) -> list[ScreenAnswer]:
        keys = [sha256_hex(image) for image in images]

        def body_at(index: int) -> dict[str, JsonValue]:
            image = images[index]
            prepared = self._prepare(image) if self._prepare is not None else image
            return chat_request_body(self._slot_config, self._instruction,
                                     prepared, self._schema)

        def parse(response_body: object) -> ScreenAnswer:
            return _screen_answer(json_payload(response_body),
                                  self._slot_config.labels)

        values, hits = resolve_chat(
            keys, keys, body_at, parse, self._config_hash,
            self._slot_config.model, self._client, self._cache_root, self._clock)
        self._cache_hit_count += hits
        return values

    def estimate_text_coverage(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        return np.asarray([answer.text_fraction for answer in self._answers(images)],
                          dtype=np.float32)

    def estimate_salient_object_fraction(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        return np.asarray([answer.object_fraction for answer in self._answers(images)],
                          dtype=np.float32)

    def classify(self, images: Sequence[bytes], labels: Sequence[str]) -> FloatArray:
        """The output is float32 (B, L) in label sequence. Each row sums to 1.

        The labels are part of the one instruction, thus a different set
        here is a wiring fault and raises.
        """
        if tuple(labels) != self._slot_config.labels:
            raise ValueError(
                f"the screener holds the labels {self._slot_config.labels}, "
                f"not {tuple(labels)}")
        rows = [answer.label_row for answer in self._answers(images)]
        if not rows:
            return np.zeros((0, len(labels)), dtype=np.float32)
        return np.asarray(rows, dtype=np.float32)

    def person_is_main_subject(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), 1.0 for the main_subject role."""
        return np.asarray(
            [float(answer.person_role == _PERSON_MAIN)
             for answer in self._answers(images)], dtype=np.float32)
