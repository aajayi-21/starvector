"""A vp1 day in the public database and the reader's check (spec VP1 §7)."""

import datetime
import json
import sqlite3
from pathlib import Path

import pytest
from svc_fixture import (FIXED_CLOCK, build_service_fixture, make_vp1,
                         mixed_wire_record)

from service import players, public, store
from service.day import close_day, open_day, reveal_day
from tools import check_day

DAY = "2026-12-01"
NOW = datetime.datetime(2026, 12, 4, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    # The fake chain stands in for drand here: the build refuses it in a
    # published snapshot (the test below), and this world has no network.
    patch = pytest.MonkeyPatch()
    patch.setattr(public, "PUBLIC_CHAINS", ("drand-quicknet", "fake"))
    base = tmp_path_factory.mktemp("vp1-public")
    fixture = make_vp1(build_service_fixture(base / "prod", dev_only=False,
                                             with_credits=True), base)
    config = fixture["service_config"]
    root = Path(config.store_root)
    players.make_player(config, player="ade", clock=lambda: FIXED_CLOCK)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             now=lambda: NOW - datetime.timedelta(days=4))
    store.write_once_json(
        store.submission_path(root, DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    out = base / "out"
    public.build(root, Path(config.data_root), out,
                 snapshot_date="2026-12-04", built_at=NOW.isoformat(),
                 version="test")
    yield out / "starvector-public-2026-12-04.sqlite", root
    patch.undo()


def test_the_build_refuses_a_day_of_the_fake_beacon(built,
                                                    monkeypatch) -> None:
    _, root = built
    monkeypatch.setattr(public, "PUBLIC_CHAINS", ("drand-quicknet",))
    with pytest.raises(public.PublicBuildError, match="not a public beacon"):
        public.public_days(root)


def test_the_snapshot_holds_the_pick_and_passes_the_check(built) -> None:
    database, root = built
    record = store.read_day_record(root, DAY)
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT protocol, commitment, secret, randomness, target_index, "
            "beacon_round FROM days WHERE day = ?", (DAY,)).fetchone()
    assert row == ("vp1", None, None, record.pick_seed, record.target_index,
                   record.beacon_round)
    assert public.check(database.parent) == []
    assert check_day.main(["--database", str(database)]) == 0


@pytest.mark.parametrize("column,value", [
    ("randomness", "0" * 64),
    ("target_index", 0),
    ("target_salt", "1" * 64),
    ("target_proof", json.dumps(["R:" + "2" * 64])),
])
def test_a_changed_pick_fails_the_check(built, tmp_path, column, value):
    database, root = built
    record = store.read_day_record(root, DAY)
    if column == "target_index" and record.target_index == 0:
        value = 1
    copy = tmp_path / database.name
    copy.write_bytes(database.read_bytes())
    with sqlite3.connect(copy) as db:
        db.execute(f"UPDATE days SET {column} = ?", (value,))
    assert check_day.main(["--database", str(copy)]) == 1
