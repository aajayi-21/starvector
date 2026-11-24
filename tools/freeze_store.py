"""Make one frozen store for the guard tests of spec SC1.

Spec: docs/specs/store-compatibility.md. A frozen store is a small
trial store, written by the code of one release and kept in the
repository with its pool, its configs, and the vectors that its
encoders gave. The guard tests of the repository read it with the
code of each release after that one.

This tool makes a frozen store one time. It refuses a label that has a
directory: a frozen store is not made again (spec SC1 section 3). When
a release changes what a store can hold, make a new frozen store with a
new label, and keep the earlier ones.

    uv run python -m tools.freeze_store --label 2026-11

The world also holds the instant trials and the guests of spec IM1,
from the second frozen store on (label 2026-11-im1).
"""

import argparse
import dataclasses
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]

# Fixture values. They open nothing: no deployment holds this pepper,
# this password, or this token. The lineage record repeats the first two,
# thus a test can prove that a stored digest reads with the code of today.
FIXTURE_PEPPER = "frozen-store-fixture-pepper"
FIXTURE_PASSWORD = "frozen store fixture password"
OPERATOR_TOKEN = "frozen-store-fixture-operator-token"
ORIGIN = {"origin": "https://testserver"}

# The names of the world that a frozen store does not keep: the pool
# key (a secret of a deployment), the photographs, each cache that the
# code makes again from the store, and the notice file of the store,
# which is not a record.
LEFT_OUT = ("pool-keys", "images", "day-scores", "index", "cache",
            "leaderboards", "skill", "README.md")

DAYS = ("2026-11-01", "2026-11-02", "2026-11-04", "2026-11-05",
        "2026-11-06")

# The cap of all owners on one date, for the instant trials of the
# world (spec IM1 decision D4). The world has six starts.
INSTANT_DAY_CAP = 100


def _clock(day: str, hour: int) -> str:
    return f"{day}T{hour:02d}:00:00+00:00"


class _RecordingText:
    """The text encoder of the world, with each answer kept."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.config_hash = inner.config_hash
        self.vectors: dict[str, np.ndarray] = {}
        self.refused: set[str] = set()

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        from providers.protocols import InputRefused

        for text in texts:
            try:
                self.vectors[text] = self._inner.encode_texts([text])[0]
            except InputRefused:
                self.refused.add(text)
        return self._inner.encode_texts(texts)


class _RecordingSketch:
    """The sketch encoder of the world, with each answer kept."""

    def __init__(self, inner: object, key: object) -> None:
        self._inner = inner
        self._key = key
        self.config_hash = inner.config_hash
        self.vectors: dict[str, np.ndarray] = {}

    def encode_images(self, images: Sequence[bytes]) -> np.ndarray:
        rows = self._inner.encode_images(images)
        for image, row in zip(images, rows, strict=True):
            self.vectors[self._key(image)] = row
        return rows


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 86, 199)).save(buffer, format="PNG")
    return buffer.getvalue()


def _send(root: Path, day: str, player: str, number: int,
          record: dict) -> None:
    from service import store

    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": f"{number:032x}",
         "received_at": _clock(day, 12), "record": record})


def _sign_up(app: object, name: str) -> object:
    from fastapi.testclient import TestClient
    from svc_fixture import solved_proof

    client = TestClient(app, base_url="https://testserver", headers=ORIGIN)
    answer = client.post("/api/signup", json={
        "proof": solved_proof(client), "username": name,
        "password": FIXTURE_PASSWORD, "agrees_public": True})
    if answer.status_code != 201:
        raise RuntimeError(f"sign-up of {name}: {answer.status_code} "
                           f"{answer.text}")
    return client


def _records() -> dict[str, dict]:
    """The submission varieties of today: one record for each."""
    from svc_fixture import colored_wire_record, mixed_wire_record

    from providers.fake.text_encoder import REFUSAL_MARKER

    mixed = mixed_wire_record()
    return {
        "mixed": mixed,
        "colored": colored_wire_record(),
        "text": {"impressions": ["a narrow street", "wet stone"],
                 "canvas_strokes": [], "groups": [], "relations": [],
                 "pasted_text": "the air is cold and still"},
        "sketch": {**mixed, "impressions": [], "groups": [],
                   "relations": [],
                   "canvas_strokes": [
                       {"points": stroke["points"], "group_id": None}
                       for stroke in mixed["canvas_strokes"]]},
        "refused": {**mixed,
                    "impressions": [f"{REFUSAL_MARKER} one", "cold air"]},
    }


def _instant_part(root: Path, data: Path, config: object,
                  config_path: str, providers: dict,
                  records: dict[str, dict]) -> None:
    """Write the instant trials and the guests of the world (spec IM1).

    One trial of an account, one of a guest with a withheld response,
    one of a guest that an account claims, one send with no result, and
    one start with no send. The engine writes each record, as the server
    does. The world has no network, thus the beacon is the fake chain.
    """
    from core.intake import validate_submission
    from pipeline.config import load_scoring_config
    from service import (guests, instant, instant_book, instant_store,
                         limits, notice, scoring, settle)
    from service.beacon import make_source
    from service.day import make_trial_code

    wired = scoring.wire_for_close(
        load_scoring_config(Path(config_path)), config_path, data, providers)
    world = settle.instant_world(
        root=root, data_root=data, roots_dir=Path(config.pool_roots_dir),
        day_cap_all=INSTANT_DAY_CAP, source=make_source(config.beacon),
        wired=wired, scoring_config_path=config_path,
        notice=notice.NOTICE_VERSION)
    book = instant_book.InstantBook()
    moment = [datetime.datetime.fromisoformat(_clock(DAYS[4], 13))]

    def now() -> datetime.datetime:
        moment[0] += datetime.timedelta(seconds=7)
        return moment[0]

    def play(owner: object, variety: str | None,
             result: bool = True) -> object:
        cap = limits.instant_day_cap(owner.kind)
        entry = settle.start_trial(world, book, owner, [owner], cap, now(),
                                   make_trial_code)
        if variety is None:
            return entry
        wire = records[variety]
        settle.encode_send(wired, validate_submission(
            wire, wired.context.gates, wired.context.render.canvas_px))
        settle.store_send(world, book, wired, entry, [owner], cap, wire, now)
        if result and settle.settle_due(world, book, lambda: wired,
                                        now().timestamp(), now) != 1:
            raise RuntimeError("an instant trial of the world got no result")
        return entry

    account = instant.Owner(instant.ACCOUNT, "ade")
    play(account, "mixed")
    first, _ = guests.make_guest(root, notice=notice.NOTICE_VERSION,
                                 instant=now())
    held = play(instant.Owner(instant.GUEST, first), "text")
    instant_store.write_withheld(root, instant_store.WithheldTrial(
        date=held.date, trial_id=held.trial_id,
        withheld_at=_clock(DAYS[4], 14),
        note="fixture: a withheld instant response"))
    second, _ = guests.make_guest(root, notice=notice.NOTICE_VERSION,
                                  instant=now())
    play(instant.Owner(instant.GUEST, second), "sketch")
    guests.claim_guest(root, second, "bru", now())
    # The last two have no result: a send that waits for its pulse, and
    # a start with no send.
    play(account, "colored", result=False)
    play(instant.Owner(instant.GUEST, first), None)


def _build_world() -> dict:
    """Write the world below the current directory, with relative paths.

    A deployment runs with relative paths below its working directory,
    and a day record keeps the path of its scoring config as text. The
    tool thus builds the world with the world as its working directory,
    and a test reads it from a copy with the copy as its working
    directory.
    """
    from fastapi.testclient import TestClient
    from frozen_fixture import sketch_key
    from svc_fixture import (QUICK_PROOF, QUICK_PROOF_KEYS,
                             build_service_fixture, make_vp1)

    from pipeline.config import load_scoring_config
    from service import digests, players, public, scoring, store
    from service.day import (CloseHeld, close_day, open_day, quarantine_send,
                             rescore_days, reveal_day)
    from service.server import create_app
    from validation import harness

    fixture = build_service_fixture(
        Path("."), prep_overrides={"linedraw.stroke_color": "rgb"},
        dev_only=False, with_credits=True)
    base = dataclasses.replace(fixture["service_config"], signup="open")
    root = Path(base.store_root)
    data = Path(base.data_root)

    # The second scoring config: the first, with the channel scores in
    # each trial row, as the production config has them.
    document = json.loads(Path(base.scoring_config).read_text(
        encoding="utf-8"))
    document["report"]["channel_scores"] = True
    channels_path = Path("scoring-config-channels.json")
    channels_path.write_text(json.dumps(document, indent=2) + "\n",
                             encoding="utf-8")
    with_channels = dataclasses.replace(base,
                                        scoring_config=str(channels_path))

    text = _RecordingText(fixture["providers"]["text_encoder"])
    sketch = _RecordingSketch(fixture["providers"]["sketch_encoder"],
                              sketch_key)
    providers = {**fixture["providers"], "text_encoder": text,
                 "sketch_encoder": sketch}

    app = create_app(
        base, dev_mode=True, operator_token=OPERATOR_TOKEN,
        digester=digests.Argon2Digester(
            pepper=FIXTURE_PEPPER.encode("utf-8")),
        usual_passwords=frozenset(), proof_keys=QUICK_PROOF_KEYS,
        proof_settings=QUICK_PROOF)
    clients = {name: _sign_up(app, name)
               for name in ("ade", "bru", "cyd", "dee", "eve")}
    clients["ade"].put("/api/account",
                       json={"description": "I sketch what I see first."})
    clients["ade"].put("/api/account/avatar", content=_png())
    clients["dee"].put("/api/account/avatar", content=_png())

    records = _records()
    number = 0

    def play(config: object, day: str, sends: dict[str, str],
             **open_arguments: object) -> None:
        nonlocal number
        open_day(config, date=day, clock=lambda: _clock(day, 0),
                 **open_arguments)
        for player, variety in sends.items():
            number += 1
            _send(root, day, player, number, records[variety])

    def finish(config: object, day: str) -> None:
        close_day(config, providers=providers, clock=lambda: _clock(day, 23))
        reveal_day(config, clock=lambda: _clock(day, 23))

    # Day one: the three modalities, with the first config.
    play(base, DAYS[0], {"ade": "mixed", "bru": "text", "cyd": "sketch",
                         "dee": "mixed"},
         pick_seed="1" * 32, secret="a" * 64)
    store.write_start(root, DAYS[0], "ade", _clock(DAYS[0], 11))
    finish(base, DAYS[0])

    # Day two: strokes with a color, and a response that the operator
    # withholds from the public database.
    play(with_channels, DAYS[1], {"ade": "colored", "bru": "text",
                                  "cyd": "mixed"},
         pick_seed="2" * 32, secret="b" * 64)
    store.write_start(root, DAYS[1], "bru", _clock(DAYS[1], 11))
    finish(with_channels, DAYS[1])
    store.write_withheld(root, store.WithheldRecord(
        day=DAYS[1], player="bru", withheld_at=_clock(DAYS[1], 23),
        note="fixture: a withheld response"))

    # Day three of the calendar has no day record: a day that the
    # server did not open.

    # Day four: one send that the provider refuses. Four sends put the
    # refusal above the guard, thus the operator skips the send.
    play(with_channels, DAYS[2], {"ade": "mixed", "bru": "text",
                                  "cyd": "sketch", "eve": "refused"},
         pick_seed="3" * 32, secret="c" * 64)
    try:
        close_day(with_channels, providers=providers,
                  clock=lambda: _clock(DAYS[2], 23), sleep=lambda _: None)
    except CloseHeld:
        quarantine_send(with_channels, date=DAYS[2], player="eve",
                        note="fixture: the provider refuses this text",
                        providers=providers,
                        clock=lambda: _clock(DAYS[2], 23))
    else:
        raise RuntimeError("the close of the refused send did not hold")
    finish(with_channels, DAYS[2])

    # A second scoring of day one: adjacent rows for the second config.
    rescore_days(base, config_path=str(channels_path), from_date=DAYS[0],
                 to_date=DAYS[0], providers=providers)

    # Two days of the post-close pick: one revealed, one open.
    vp1 = make_vp1({**fixture, "service_config": with_channels}, Path("."))
    vp1_config = vp1["service_config"]

    def before(day: str) -> datetime.datetime:
        return datetime.datetime.fromisoformat(_clock(day, 0)) \
            - datetime.timedelta(hours=12)

    play(vp1_config, DAYS[3], {"ade": "mixed", "bru": "text"},
         now=lambda: before(DAYS[3]))
    finish(vp1_config, DAYS[3])
    play(vp1_config, DAYS[4], {"ade": "colored"},
         now=lambda: before(DAYS[4]))
    store.write_start(root, DAYS[4], "ade", _clock(DAYS[4], 11))

    # The instant trials and the guests (spec IM1), with the config of
    # the channel scores and the pool key of the vp1 world.
    _instant_part(root, data, vp1_config, str(channels_path), providers,
                  records)

    # A revoked player, a deleted account, and the identifiers that a
    # public snapshot shows for them.
    players.revoke_player(vp1_config, player="cyd")
    operator = TestClient(
        app, base_url="https://testserver",
        headers={**ORIGIN, "authorization": f"Bearer {OPERATOR_TOKEN}"})
    answer = operator.post("/api/dev/players/dee/delete",
                           json={"confirm": "dee"})
    if answer.status_code != 200:
        raise RuntimeError(f"deletion: {answer.status_code} {answer.text}")
    # The world has no network, thus its beacon is the fake chain. A
    # public snapshot refuses that chain, and this tool and the guard
    # tests name it as public for the fixture alone.
    chains = public.PUBLIC_CHAINS
    public.PUBLIC_CHAINS = (*chains, "fake")
    try:
        public.write_identifiers(root, datetime.datetime.fromisoformat(
            _clock(DAYS[4], 12)))
    finally:
        public.PUBLIC_CHAINS = chains

    store.write_rollover_control(root, store.RolloverControl(
        paused=False, changed_at=_clock(DAYS[4], 1),
        note="fixture: put back"))
    store.write_rollover_run(root, store.RolloverRun(
        started_at=_clock(DAYS[4], 0), finished_at=_clock(DAYS[4], 0),
        source="timer", outcome="moved", steps=("reveal", "open"),
        detail="fixture"))

    hashes = {}
    for path in (base.scoring_config, str(channels_path)):
        wired = scoring.wire_for_close(load_scoring_config(Path(path)),
                                       path, data, providers)
        hashes[path] = {
            "scoring_config_hash": wired.scoring_hash,
            "commonness_config_hash": wired.commonness_hash,
            "preparation_version_id": wired.preparation_version_id,
        }
    slot_hashes = harness.scoring_provider_hashes(
        load_scoring_config(Path(base.scoring_config)), providers)
    return {
        "configs": hashes, "slot_hashes": slot_hashes,
        "refused_texts": sorted(text.refused),
        "dimension": int(next(iter(text.vectors.values())).shape[0]),
        "text_vectors": text.vectors, "sketch_vectors": sketch.vectors,
        "store_root": str(root), "data_root": str(data),
        "service_configs": {"commit-v1": with_channels, "vp1": vp1_config},
    }


def _keep(directory: str, names: list[str]) -> set[str]:
    return {name for name in names
            if name in LEFT_OUT or name.startswith("skill-board.")
            or name.endswith((".lock", ".tmp"))}


def _commit() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True).stdout.strip()


def freeze(target: Path) -> None:
    """Build one world, and write its frozen store at target."""
    from frozen_fixture import (LINEAGE_NAME, MANIFEST_NAME, REPLAY_NAME,
                                manifest_of, render_manifest, write_replay)

    if target.exists():
        raise SystemExit(
            f"{target} is there: a frozen store is not made again. Use a "
            "new label.")
    with tempfile.TemporaryDirectory() as scratch:
        world = Path(scratch) / "world"
        world.mkdir()
        start = Path.cwd()
        os.chdir(world)
        try:
            built = _build_world()
        finally:
            os.chdir(start)
        shutil.copytree(world, target / "world", ignore=_keep)
    write_replay(target / REPLAY_NAME, built["text_vectors"],
                 built["sketch_vectors"])
    lineage = {
        "note": "A frozen store of spec SC1. Do not change a file here "
                "and do not make this directory again.",
        "made_at_commit": _commit(),
        "store_root": built["store_root"],
        "data_root": built["data_root"],
        "configs": built["configs"],
        "slot_hashes": built["slot_hashes"],
        "dimension": built["dimension"],
        "refused_texts": built["refused_texts"],
        "service_configs": {
            name: {"scoring_config": config.scoring_config,
                   "pick_protocol": config.pick_protocol,
                   "closes_at_utc": config.closes_at_utc,
                   "pool_roots_dir": config.pool_roots_dir}
            for name, config in built["service_configs"].items()},
        "fixture_only": {"password": FIXTURE_PASSWORD,
                         "pepper": FIXTURE_PEPPER},
    }
    (target / LINEAGE_NAME).write_text(
        json.dumps(lineage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (target / MANIFEST_NAME).write_text(
        render_manifest(manifest_of(target)), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """The command line: one label, one frozen store."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--label", required=True,
                        help="the name part after frozen-store-")
    parser.add_argument("--out", type=Path,
                        default=REPO / "tests" / "service" / "fixtures")
    arguments = parser.parse_args(argv)
    sys.path.insert(0, str(REPO / "tests"))
    sys.path.insert(0, str(REPO / "tests" / "service"))
    target = arguments.out / f"frozen-store-{arguments.label}"
    freeze(target)
    print(f"wrote {target}")
    print("run the guard tests, and commit the directory when they "
          "are green: uv run pytest tests/service/test_frozen_store.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
