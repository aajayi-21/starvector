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

from service.beacon import BeaconConfig, parse_beacon_config

CONFIG_VERSION = 1

# The player name becomes a file name below store/days/<day>/, thus
# the shape is pinned tight (S1 section 14a, D6).
_PLAYER_RULE = re.compile(r"^[a-z0-9-]{1,64}$")

_FIELDS = ("config_version", "player", "scoring_config", "data_root",
           "store_root", "port")

# Optional fields parse when given and default when missing, so each
# committed config stays readable (spec S2 ruling 3).
_OPTIONAL_FIELDS = ("closes_at_utc", "signup", "public_data_url",
                    "pick_protocol", "beacon", "pool_roots_dir")

# The pick protocols (spec VP1 section 6). "commit-v1" picks at the open
# and publishes a commitment. "vp1" picks after the close from a beacon
# pulse. A config with no field reads as "commit-v1", thus each earlier
# config keeps its behavior until the owner moves it (ruling D8).
PICK_PROTOCOLS = ("commit-v1", "vp1")

# The sign-up switch (spec A2 section 10.2). A config with no field
# reads as "closed", thus each earlier config keeps its behavior.
SIGNUP_VALUES = ("open", "closed")

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

    signup is "open" or "closed" (spec A2 section 10.2). With "open"
    the server makes accounts and has no fallback identity.

    public_data_url is display-only (spec R1 section 3.1): the address
    of the published snapshots, which the account screen shows.

    pick_protocol "vp1" (spec VP1) needs closes_at_utc, because the
    pulse that picks the target comes from the scheduled close, and a
    beacon block. pool_roots_dir holds the committed pool roots.
    """

    player: str
    scoring_config: str
    data_root: str
    store_root: str
    port: int
    closes_at_utc: str | None = None
    signup: str = "closed"
    public_data_url: str | None = None
    pick_protocol: str = "commit-v1"
    beacon: BeaconConfig | None = None
    pool_roots_dir: str = "configs/pool-roots"


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
    if not _PLAYER_RULE.fullmatch(raw["player"]):
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
            # fullmatch, not match: the dollar sign also matches
            # before a trailing newline, and the value goes into
            # a timestamp string.
            or not _CLOSES_AT_RULE.fullmatch(closes_at_utc)):
        raise ServiceConfigError(
            f"{source}.closes_at_utc: expected \"HH:MM\" (24-hour UTC)")
    signup = raw.get("signup", "closed")
    if signup not in SIGNUP_VALUES:
        raise ServiceConfigError(
            f"{source}.signup: expected one of {list(SIGNUP_VALUES)}")
    public_data_url = raw.get("public_data_url")
    if public_data_url is not None and (
            not isinstance(public_data_url, str)
            or not public_data_url.startswith(("https://", "http://"))):
        raise ServiceConfigError(
            f"{source}.public_data_url: expected an http or https address")
    pick_protocol = raw.get("pick_protocol", "commit-v1")
    if pick_protocol not in PICK_PROTOCOLS:
        raise ServiceConfigError(
            f"{source}.pick_protocol: expected one of {list(PICK_PROTOCOLS)}")
    beacon = None
    if raw.get("beacon") is not None:
        try:
            beacon = parse_beacon_config(raw["beacon"], f"{source}.beacon")
        except ValueError as error:
            raise ServiceConfigError(str(error)) from error
    if pick_protocol == "vp1" and (beacon is None or closes_at_utc is None):
        raise ServiceConfigError(
            f"{source}: pick_protocol \"vp1\" needs a beacon block and "
            "closes_at_utc - the pulse comes from the scheduled close")
    pool_roots_dir = raw.get("pool_roots_dir", "configs/pool-roots")
    if not isinstance(pool_roots_dir, str) or not pool_roots_dir:
        raise ServiceConfigError(
            f"{source}.pool_roots_dir: expected a non-empty string")
    return ServiceConfig(
        player=raw["player"],
        scoring_config=raw["scoring_config"],
        data_root=raw["data_root"],
        store_root=raw["store_root"],
        port=port,
        closes_at_utc=closes_at_utc,
        signup=signup,
        public_data_url=public_data_url,
        pick_protocol=pick_protocol,
        beacon=beacon,
        pool_roots_dir=pool_roots_dir,
    )


def load_service_config(path: Path) -> ServiceConfig:
    """Read, parse, and validate the config file at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ServiceConfigError(
            f"{path}: cannot read config: {error}") from error
    return parse_service_config(raw, source=str(path))
