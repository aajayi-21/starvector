"""Invariants of the two modes (spec IM1 sections 4, 17, and 20).

The instant trial and the daily challenge share one pool and one
scoring configuration, and nothing more. These tests pin that: no
daily answer changes when the store gets instant trials, no module on
the fit side reads an instant record, and a snapshot of a frozen store
holds its instant trials with a clean check.
"""

import dataclasses
import datetime
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from frozen_fixture import (frozen_stores, holds_instant, read_lineage,
                            replay_providers)

from svc_fixture import (FIXED_CLOCK, build_service_fixture, make_vp1,
                         mint_player, mixed_wire_record,
                         pinned_session_value, plant_session)

from service import auth, index, public, rollup, server, store
from service.config import ServiceConfig
from service.day import build_day_scores, close_day, open_day, reveal_day
from service.server import create_app
from tools import check_instant

REPO = Path(__file__).resolve().parents[2]
TOKEN = "test-operator-token"
SECRETS = {"ade": "a" * 43, "bru": "b" * 43}
DAY_ONE, DAY_TWO, DAY_OPEN = "2026-11-20", "2026-11-21", "2026-11-22"
NOW = datetime.datetime(2026, 11, 22, 10, 0, tzinfo=datetime.UTC)

# Each daily answer that a signed-in player reads.
DAILY_PATHS = (
    "/api/day", "/api/me", "/api/history", "/api/days",
    "/api/leaderboard", f"/api/leaderboard?day={DAY_ONE}",
    "/api/leaderboard/skill", "/api/reveal", f"/api/reveal?day={DAY_ONE}",
    f"/api/sends?day={DAY_TWO}", f"/api/sends?day={DAY_OPEN}",
    f"/api/submission?day={DAY_ONE}", f"/api/submission?day={DAY_OPEN}",
    "/api/about",
)


def _send(root: Path, day: str, player: str, words: list[str]) -> None:
    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK,
         "record": {**mixed_wire_record(), "impressions": words}})


def _daily_world(tmp_path: Path, monkeypatch):
    """Two revealed days and one open day, each with sends, and two
    players with sessions. Instant trials are on for accounts."""
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    config = dataclasses.replace(
        fixture["service_config"], pick_protocol="commit-v1",
        instant="accounts", instant_day_cap=400)
    root = Path(config.store_root)
    for name, secret in SECRETS.items():
        mint_player(config, player=name, display_name=name.title(),
                    clock=lambda: FIXED_CLOCK, secret=secret)
        plant_session(root, f"{name}.{secret}")
    for number, day in enumerate((DAY_ONE, DAY_TWO)):
        open_day(config, date=day, clock=lambda: FIXED_CLOCK,
                 pick_seed=str(number + 1) * 32, secret="b" * 64)
        _send(root, day, "ade", ["a tall tower", "cold"])
        _send(root, day, "bru", ["a wide plain"])
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)
    open_day(config, date=DAY_OPEN, clock=lambda: FIXED_CLOCK,
             pick_seed="c" * 32, secret="d" * 64)
    _send(root, DAY_OPEN, "ade", ["a harbor"])
    monkeypatch.setattr(server, "utc_now", lambda: NOW)
    return config, root, create_app(config, operator_token=TOKEN)


def _as(app, name: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(
        f"{name}.{SECRETS[name]}"))
    return client


def _daily_answers(app) -> dict[str, tuple[int, bytes]]:
    found = {}
    for name in SECRETS:
        client = _as(app, name)
        for path in DAILY_PATHS:
            answer = client.get(path)
            found[f"{name} {path}"] = (answer.status_code, answer.content)
    return found


def _daily_files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted((root / "days").rglob("*")) if path.is_file()}


def test_no_daily_answer_changes_with_instant_trials_in_the_store(
        tmp_path, monkeypatch) -> None:
    """Spec IM1 section 4: no rollup, no board, no skill number, and no
    streak reads an instant trial."""
    config, root, app = _daily_world(tmp_path, monkeypatch)
    before = _daily_answers(app)
    files = _daily_files(root)
    fingerprint = index.store_fingerprint(root)
    # Each answer is there: a refusal that stays a refusal is not proof.
    # The latest day is open, and one player has no send of it.
    assert sorted(key for key, (status, _) in before.items()
                  if status != 200) \
        == ["ade /api/reveal", "bru /api/reveal",
            f"bru /api/sends?day={DAY_OPEN}",
            f"bru /api/submission?day={DAY_OPEN}"]

    played = 0
    for name in SECRETS:
        client = _as(app, name)
        for _ in range(3):
            trial = client.post("/api/instant/start").json()
            assert client.post(
                f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
                json=mixed_wire_record()).status_code == 200
            played += 1
    assert app.state.instant.tick() == played
    assert _as(app, "ade").get("/api/instant").json()["record"]["settled"] \
        == 3

    assert _daily_answers(app) == before
    # A new server reads the store with the instant trials in it.
    assert _daily_answers(create_app(config, operator_token=TOKEN)) == before
    # No daily record changed, and the private index does not see an
    # instant trial: its fingerprint reads the daily records alone.
    assert _daily_files(root) == files
    assert index.store_fingerprint(root) == fingerprint


def test_the_boards_and_the_index_have_no_instant_row(
        tmp_path, monkeypatch) -> None:
    config, root, app = _daily_world(tmp_path, monkeypatch)
    rollup.assemble(config)
    boards = {path.name: path.read_bytes() for path in sorted(
        Path(config.data_root).rglob("*.json"))
        if "leaderboards" in path.parts or "skill" in path.parts}
    target = tmp_path / "before.sqlite"
    index.build(root, target)

    client = _as(app, "ade")
    trial = client.post("/api/instant/start").json()
    client.post(f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
                json=mixed_wire_record())
    assert app.state.instant.tick() == 1

    rollup.assemble(config)
    again = {path.name: path.read_bytes() for path in sorted(
        Path(config.data_root).rglob("*.json"))
        if "leaderboards" in path.parts or "skill" in path.parts}
    assert again == boards and boards
    after = tmp_path / "after.sqlite"
    index.build(root, after)

    def rows(path: Path) -> dict:
        with sqlite3.connect(path) as db:
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name != 'meta' ORDER BY name")]
            return {table: db.execute(
                f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in tables}

    assert rows(after) == rows(target)
    assert trial["trial_id"].encode() not in after.read_bytes()


_FIT_SIDE = ("core", "pipeline", "pool", "providers", "validation")
_INSTANT_NAMES = ("instant_store", "instant_book", "store/instant",
                  '"instant"', "'instant'", "service.instant",
                  "service.settle", "service.guests")


def test_no_fit_side_module_names_an_instant_record() -> None:
    """Rule I6 (spec IM1 section 17): an instant trial is a live player
    trial, and no code that fits a weight reads one."""
    offenders = []
    for package in _FIT_SIDE:
        for path in sorted((REPO / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for name in _INSTANT_NAMES:
                if name in text:
                    offenders.append(f"{path.relative_to(REPO)}: {name}")
    assert offenders == []


def test_the_instant_modules_read_no_day_record() -> None:
    """Spec IM1 section 4: no instant path reads a day record. The
    modules of the instant trial name no reader of a day."""
    readers = ("read_day_record", "list_days", "latest_day",
               "list_submissions", "submission_path", "trial_row_path")
    offenders = []
    for name in ("instant.py", "instant_store.py", "instant_book.py",
                 "settle.py", "guests.py"):
        text = (REPO / "service" / name).read_text(encoding="utf-8")
        offenders += [f"{name}: {reader}" for reader in readers
                      if reader in text]
    assert offenders == []


@pytest.mark.parametrize(
    "frozen", [path for path in frozen_stores() if holds_instant(path)],
    ids=lambda path: path.name)
def test_a_snapshot_of_a_frozen_store_holds_its_instant_trials(
        frozen, tmp_path, monkeypatch) -> None:
    copy = tmp_path / "world"
    shutil.copytree(frozen / "world", copy)
    monkeypatch.chdir(copy)
    monkeypatch.setattr(public, "PUBLIC_CHAINS",
                        (*public.PUBLIC_CHAINS, "fake"))
    lineage = read_lineage(frozen)
    # The day-score files are a cache that a frozen store does not keep.
    build_day_scores(
        ServiceConfig(player="ade",
                      scoring_config=sorted(lineage["configs"])[0],
                      data_root=lineage["data_root"],
                      store_root=lineage["store_root"], port=8399),
        providers=replay_providers(frozen))
    out = tmp_path / "public"
    database = public.build(
        Path(lineage["store_root"]), Path(lineage["data_root"]), out,
        snapshot_date="2027-01-01",
        built_at="2027-01-01T12:00:00+00:00", version="invariant-test")
    assert public.check(out) == []
    with sqlite3.connect(database) as db:
        owners = dict(db.execute(
            "SELECT owner, kind FROM instant_owners"))
        chain = db.execute(
            "SELECT COUNT(*), SUM(settled) FROM instant_chain").fetchone()
        withheld = db.execute(
            "SELECT COUNT(*) FROM instant_submissions WHERE withheld = 1"
        ).fetchone()[0]
    # An account, a guest, and the account that claimed a guest.
    assert sorted(owners.values()) == ["account", "account", "guest"]
    assert set(owners) >= {"ade", "bru"}
    assert chain == (4, 3) and withheld == 1
    assert check_instant.main(["--database", str(database)]) == 0
