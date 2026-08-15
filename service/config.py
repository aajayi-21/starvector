"""The server configuration: one small strict document.

Spec: S1 (in docs/specs/) sections 9 and 14a. The committed JSON file
names the player, the scoring config, the two roots, and the port.
Loading validates at the boundary and stops with the JSON path of the
problem named (the pipeline/config.py pattern, compressed to five
fields).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

CONFIG_VERSION = 1

# The player name becomes a file name below store/days/<day>/, thus
# the shape is pinned tight (S1 section 14a, D6).
_PLAYER_RULE = re.compile(r"^[a-z0-9-]{1,64}$")

_FIELDS = ("config_version", "player", "scoring_config", "data_root",
           "store_root", "port")

# Optional fields parse when given and default when missing, so each
# committed config stays readable (spec S2 ruling 3).
_OPTIONAL_FIELDS = ("closes_at_utc",)

# The display close time: "HH:MM", 24-hour, UTC.
_CLOSES_AT_RULE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ServiceConfigError(ValueError):
    """The server configuration file did not validate."""


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """The values the server and the day commands read.

    closes_at_utc is display-only (spec S2 ruling 3): the day view
    computes closes_at from it for an open day. It does not enter
    the stored day record, and closing stays the operator's action.
    """

    player: str
    scoring_config: str
    data_root: str
    store_root: str
    port: int
    closes_at_utc: str | None = None


def parse_service_config(raw: object, source: str) -> ServiceConfig:
    """Parse and validate one raw JSON document into a ServiceConfig."""
    if not isinstance(raw, dict):
        raise ServiceConfigError(f"{source}: expected an object")
    unknown = sorted(set(raw) - set(_FIELDS) - set(_OPTIONAL_FIELDS))
    missing = sorted(set(_FIELDS) - set(raw))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            parts.append(f"missing field(s): {', '.join(missing)}")
        raise ServiceConfigError(f"{source}: {'; '.join(parts)}")
    if raw["config_version"] != CONFIG_VERSION:
        raise ServiceConfigError(
            f"{source}.config_version: expected {CONFIG_VERSION}")
    for name in ("player", "scoring_config", "data_root", "store_root"):
        value = raw[name]
        if not isinstance(value, str) or not value:
            raise ServiceConfigError(
                f"{source}.{name}: expected a non-empty string")
    if not _PLAYER_RULE.match(raw["player"]):
        raise ServiceConfigError(
            f"{source}.player: must agree with [a-z0-9-]{{1,64}} - the "
            "name becomes a file name in the store")
    port = raw["port"]
    if not isinstance(port, int) or isinstance(port, bool) \
            or not 1 <= port <= 65535:
        raise ServiceConfigError(
            f"{source}.port: expected an integer in [1, 65535]")
    closes_at_utc = raw.get("closes_at_utc")
    if closes_at_utc is not None and (
            not isinstance(closes_at_utc, str)
            or not _CLOSES_AT_RULE.match(closes_at_utc)):
        raise ServiceConfigError(
            f"{source}.closes_at_utc: expected \"HH:MM\" (24-hour UTC)")
    return ServiceConfig(
        player=raw["player"],
        scoring_config=raw["scoring_config"],
        data_root=raw["data_root"],
        store_root=raw["store_root"],
        port=port,
        closes_at_utc=closes_at_utc,
    )


def load_service_config(path: Path) -> ServiceConfig:
    """Read, parse, and validate the config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ServiceConfigError(
            f"{path}: cannot read config: {error}") from error
    return parse_service_config(raw, source=str(path))
