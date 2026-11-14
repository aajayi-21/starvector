"""The shared server test fixture: pool, tables, configs, fakes.

Builds the hand-built pool artifacts, stores image bytes for the reveal
source, writes a mixed-mode scoring config and a server config to
disk, and prebuilds the commonness tables warm with fake providers -
thus the day commands run offline against a warm lineage, as the
live server does.
"""

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (element_config, intake_gates, outline_config,
                             parse_scoring_config, placement_config)
from pipeline.context import load_pool_index
from pipeline.score import Encoders
from pool.artifacts import image_path, write_bytes_atomic
from service.config import ServiceConfig
from validation import harness

FIXED_CLOCK = "2026-08-12T00:00:00+00:00"


def _png_bytes(seed: int) -> bytes:
    buffer = BytesIO()
    color = ((seed * 37) % 256, (seed * 91) % 256, 40)
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def build_service_fixture(root: Path, count: int = 40,
                          prep_overrides: dict | None = None,
                          dev_only: bool = True,
                          with_credits: bool = False) -> dict:
    """One warm offline server world below root. Output keys:
    service_config, providers, store, data, scoring_config_path,
    image_ids. prep_overrides reaches the preparation config - the
    spec C1 tests build an rgb world with
    {"linedraw.stroke_color": "rgb"}. With dev_only off, the world is
    the world of a production pool: its days can be in a public snapshot (spec
    R1). with_credits writes a pool release record and its manifest,
    thus each image has a source page.
    """
    from conftest import (build_direct_prepared_pool, scoring_config_dict,
                          scoring_fakes)

    release_path = root / "pool-release.json"
    prepared = build_direct_prepared_pool(
        root / "pool", count, overrides=prep_overrides, dev_only=dev_only,
        release_record_path=str(release_path) if with_credits
        else "unused.json")
    data = prepared["data"]
    if with_credits:
        release_path.write_text(json.dumps(
            {"corpus_id": "c" * 64, "curation_config_hash": "d" * 64}),
            encoding="utf-8")
        manifest = (data / "curation" / ("c" * 8) / ("d" * 8) / "s09-release"
                    / "manifest.jsonl")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(
            json.dumps({"image_id": image_id, "source_key":
                        "https://upload.wikimedia.org/wikipedia/commons/"
                        f"a/ab/Test_photo_{position}.jpg"}) + "\n"
            for position, image_id in enumerate(prepared["image_ids"])),
            encoding="utf-8")
    for position, image_id in enumerate(prepared["image_ids"]):
        write_bytes_atomic(image_path(data, image_id), _png_bytes(position))

    document = scoring_config_dict(
        prepared["prep_record_path"],
        **{"validation.submission_mode": "mixed",
           "commonness.dataset.fake_pair_count": 24,
           "commonness.background_count": 6,
           "report.dev_only": dev_only,
           "validation.tag": "dev-service-test" if dev_only
           else "prod-service-test"})
    scoring_config_path = root / "scoring-config.json"
    scoring_config_path.write_text(json.dumps(document, indent=2) + "\n",
                                   encoding="utf-8")
    config = parse_scoring_config(document, str(scoring_config_path))
    providers = scoring_fakes(pair_count=24)

    loaded = load_pool_index(prepared["prep_record_path"], data,
                             dev_only=dev_only)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"], None)
    encoders = Encoders(sketch=providers["sketch_encoder"],
                        text=providers["text_encoder"])

    def background():
        return harness.full_background(
            config, providers["sketch_pairs"], "mixed", loaded.index,
            placement_config(config), data)

    ensure_commonness_tables(
        data_root=data, index=loaded.index,
        commonness_hash=commonness_hash, background=background,
        gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement_config(config), encoders=encoders,
        submission_mode="mixed", clock=lambda: FIXED_CLOCK)

    service_config = ServiceConfig(
        player="ade", scoring_config=str(scoring_config_path),
        data_root=str(data), store_root=str(root / "store"), port=8399)
    return {
        "service_config": service_config,
        "providers": providers,
        "store": root / "store",
        "data": data,
        "scoring_config_path": str(scoring_config_path),
        "image_ids": prepared["image_ids"],
    }


def colored_wire_record() -> dict:
    """The mixed record with a color on each stroke (spec C1)."""
    record = mixed_wire_record()
    record["canvas_strokes"][0]["color"] = "#1a73e8"
    record["canvas_strokes"][1]["color"] = "#c5221f"
    return record


def mixed_wire_record() -> dict:
    """One complete mixed submission: impressions, strokes, a
    group, a relation."""
    return {
        "impressions": ["tall vertical structure", "cold and exposed"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": "g2"},
        ],
        "groups": [{"id": "g1", "label": "tower"},
                   {"id": "g2", "label": "sea"}],
        "relations": [{"relation": "left-of", "of": ["g1", "g2"]}],
        "pasted_text": None,
    }


def pinned_session_value(token: str) -> str:
    """The session cookie value a test world pins for an invite token.

    A pure function of the token, thus a helper that signs a client
    in needs no store path. plant_session writes the matching
    record. The secret is a digest prefix: 43 characters from the
    URL-safe alphabet, the session secret's shape.
    """
    from core.canonical import sha256_hex
    from service import auth

    parsed = auth.parse_token(token)
    if parsed is None:
        raise ValueError(f"not an invite token: {token!r}")
    player, _secret = parsed
    value, _digest = auth.mint_session(
        player, secret=sha256_hex(f"test-session:{token}")[:43])
    return value


def plant_session(store_root: Path, token: str) -> str:
    """Write the session record pinned_session_value names, one time.

    The creation time is the wall clock, thus the session stays in
    its fixed life for each run of the suite. A world plants its
    sessions at setup, before a test takes a byte snapshot.
    """
    import datetime

    from service import auth, store

    value = pinned_session_value(token)
    player, secret = auth.parse_token(value)
    digest = auth.token_hash(secret)
    if store.read_session_or_none(store_root, player, digest) is None:
        store.write_session_record(store_root, digest, store.SessionRecord(
            player=player, label="Test device",
            created_at=datetime.datetime.now(datetime.UTC).isoformat()))
    return value


class QuickDigester:
    """A password digester with no slow work, for the tests (spec A2
    build item B2). The interface is the deployed digester's.

    The digest text names its own parameter number, thus a test can
    make a digest that reads as stale.
    """

    def __init__(self, level: int = 2) -> None:
        self.level = level
        self.absent_count = 0

    def digest(self, password: str) -> str:
        from core.canonical import sha256_hex

        return f"quick${self.level}${sha256_hex('quick:' + password)}"

    def agrees(self, password: str, stored: str) -> bool:
        from core.canonical import sha256_hex

        parts = stored.split("$")
        if len(parts) != 3 or parts[0] != "quick":
            raise ValueError("a stored password digest is not quick text")
        return parts[2] == sha256_hex("quick:" + password)

    def stale(self, stored: str) -> bool:
        return stored.split("$")[1] != str(self.level)

    def absent(self, password: str) -> None:
        self.absent_count += 1


def mint_player(service_config, *, player: str, display_name: str,
                clock=None, secret: str | None = None):
    """One stored player and a token-shaped seed for plant_session.

    The invite is gone (spec A2 ruling 2), and the tests of before it
    signed a client in with the session that an invite token pins.
    This helper keeps that shape: the record has no credential, and
    the second output names the player and a secret for
    pinned_session_value. It opens nothing on the server.
    """
    from service import players

    more = {} if clock is None else {"clock": clock}
    record = players.make_player(service_config, player=player,
                                 display_name=display_name, **more)
    return record, f"{player}.{secret or 's' * 43}"
