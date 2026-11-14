"""The public results database (spec R1 sections 5 to 10).

One world holds each condition that a snapshot must handle: two
revealed days of a production pool, an open day with a response, a
revealed day of a development pool, a withheld response, a revoked
player, an account text, a credential, a start record, and a second
scoring of one trial. The tests build a snapshot and read it.
"""

import dataclasses
import datetime
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         mixed_wire_record)

from service import players, public, signin, store
from service.day import close_day, day_commitment, open_day, reveal_day

DAY_ONE, DAY_TWO, DAY_OPEN, DAY_DEV = ("2026-12-01", "2026-12-02",
                                       "2026-12-03", "2026-11-20")
NOW = datetime.datetime(2026, 12, 4, 12, 0, tzinfo=datetime.UTC)
WITHHELD_MARKER = "a private street address"
ACCOUNT_MARKER = "account text that is not for a dataset"
PASSWORD = "marker-password-AAAA"
GONE = "zed-revoked"


def _wire(impressions: list[str], pasted: str | None = None) -> dict:
    return {**mixed_wire_record(), "impressions": impressions,
            "pasted_text": pasted}


def _send(root: Path, day: str, player: str, wire: dict,
          received_at: str = FIXED_CLOCK) -> None:
    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": received_at, "record": wire})


def _play(config, root: Path, day: str, sends: dict[str, dict],
          reveal: bool = True) -> None:
    open_day(config, date=day, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    for player, wire in sends.items():
        _send(root, day, player, wire)
    if reveal:
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("public-world")
    fixture = build_service_fixture(base / "prod", dev_only=False,
                                    with_credits=True)
    config = fixture["service_config"]
    root = Path(config.store_root)
    for name in ("ade", "bru", GONE):
        players.make_player(config, player=name, clock=lambda: FIXED_CLOCK)

    # A revealed day of a development pool, in the same store.
    dev = build_service_fixture(base / "dev")
    _play(dev["service_config"], Path(dev["service_config"].store_root),
          DAY_DEV, {"ade": _wire(["a development response"])})
    shutil.copytree(
        store.day_dir(Path(dev["service_config"].store_root), DAY_DEV),
        store.day_dir(root, DAY_DEV))

    _play(config, root, DAY_ONE, {
        "ade": _wire(["mountains", "a lake"], pasted="cold and still"),
        "bru": _wire(["a narrow street"]),
        GONE: _wire(["a tall tower"])})
    _play(config, root, DAY_TWO, {
        "ade": _wire(["an open field"]),
        "bru": _wire([WITHHELD_MARKER])})
    _play(config, root, DAY_OPEN, {"ade": _wire(["not public"])},
          reveal=False)

    # A start for one response, 90 seconds before its send.
    sent = datetime.datetime.fromisoformat(FIXED_CLOCK)
    store.write_start(root, DAY_ONE, "ade",
                      (sent - datetime.timedelta(seconds=90)).isoformat())
    store.write_start(root, DAY_OPEN, "ade", sent.isoformat())
    # A second scoring of one trial: a row that is not pinned.
    pinned = store.trial_row_path(root, DAY_ONE, "ade")
    second = json.loads(pinned.read_text())
    second["scoring_config_hash"] = "e" * 64
    second["p"] = 0.123456
    (pinned.parent / f"ade.{'e' * 8}.json").write_text(json.dumps(second))
    # An account text, a credential, a withheld response, a revoke.
    store.set_account_description(root, "ade", ACCOUNT_MARKER,
                                  timestamp=FIXED_CLOCK)
    signin.set_password(root, player="ade", current_password=None,
                        password=PASSWORD, digester=QuickDigester(),
                        usual=frozenset(), instant=NOW)
    store.write_withheld(root, store.WithheldRecord(
        day=DAY_TWO, player="bru", withheld_at=NOW.isoformat(),
        note="names a home address"))
    players.revoke_player(config, player=GONE)
    return {"fixture": fixture, "config": config, "root": root,
            "data": Path(config.data_root), "base": base}


def _build(world, name: str = "out") -> Path:
    out = world["base"] / name
    public.build(world["root"], world["data"], out,
                 snapshot_date="2026-12-04", built_at=NOW.isoformat(),
                 version="test")
    return out


def _open(directory: Path) -> sqlite3.Connection:
    return sqlite3.connect(directory / "starvector-public-2026-12-04.sqlite")


def test_the_snapshot_holds_the_revealed_production_days_alone(world) -> None:
    out = _build(world)
    with _open(out) as db:
        assert [row[0] for row in db.execute(
            "SELECT day FROM days ORDER BY day")] == [DAY_ONE, DAY_TWO]
        for table in ("submissions", "trials", "impressions", "strokes",
                      "trial_atoms"):
            days = {row[0] for row in db.execute(
                f"SELECT DISTINCT day FROM {table}")}
            assert days <= {DAY_ONE, DAY_TWO}, table
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] \
            == 5
        # The pinned row alone: the second scoring is not in the file.
        assert db.execute(
            "SELECT COUNT(*) FROM trials WHERE day = ? AND player = 'ade'",
            (DAY_ONE,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM trials WHERE p = 0.123456"
                          ).fetchone()[0] == 0
        pools = {row[0] for row in db.execute("SELECT pool_label FROM days")}
        assert pools == {"prod-direct-pool"}
    assert public.check(out) == []


def test_each_fence_holds_in_the_bytes_of_the_file(world) -> None:
    out = _build(world)
    raw = (out / "starvector-public-2026-12-04.sqlite").read_bytes()
    root = world["root"]
    credential = store.read_credential_or_none(root, "ade")
    secrets = [PASSWORD, credential.password_digest,
               credential.recovery_digest, ACCOUNT_MARKER, WITHHELD_MARKER,
               "names a home address", GONE, "not public",
               "a development response", "a" * 32]
    for secret in secrets:
        assert secret.encode("utf-8") not in raw, secret
    # The pool stays closed: no image that was not a target is named.
    with _open(out) as db:
        targets = {row[0] for row in db.execute(
            "SELECT target_id FROM targets")}
    assert len(targets) >= 1
    for image_id in world["fixture"]["image_ids"]:
        if image_id not in targets:
            assert image_id.encode("utf-8") not in raw


def test_the_rows_agree_with_the_store(world) -> None:
    out = _build(world)
    root = world["root"]
    with _open(out) as db:
        row = db.execute(
            "SELECT received_at, started_at, seconds_from_start, "
            "impression_count, has_pasted_text, withheld, pasted_text, "
            "record_json FROM submissions WHERE day = ? AND player = 'ade'",
            (DAY_ONE,)).fetchone()
        stored = json.loads(store.submission_path(
            root, DAY_ONE, "ade").read_text())
        assert row[0] == stored["received_at"]
        assert row[2] == 90.0
        assert (row[3], row[4], row[5]) == (2, 1, 0)
        assert row[6] == "cold and still"
        assert json.loads(row[7]) == stored["record"]
        # A response with no start record has no time from it.
        assert db.execute(
            "SELECT started_at, seconds_from_start FROM submissions "
            "WHERE day = ? AND player = 'bru'", (DAY_ONE,)).fetchone() \
            == (None, None)
        # The row tables hold the same data as the raw record.
        assert [r[0] for r in db.execute(
            "SELECT text FROM impressions WHERE day = ? AND player = 'ade' "
            "ORDER BY position", (DAY_ONE,))] == ["mountains", "a lake"]
        strokes = db.execute(
            "SELECT position, group_id, point_count, points_json FROM "
            "strokes WHERE day = ? AND player = 'ade' ORDER BY position",
            (DAY_ONE,)).fetchall()
        wire = stored["record"]
        assert len(strokes) == len(wire["canvas_strokes"])
        for position, group_id, point_count, points in strokes:
            source = wire["canvas_strokes"][position]
            assert group_id == source.get("group_id")
            assert json.loads(points) == source["points"]
            assert point_count == len(source["points"])
        assert db.execute(
            "SELECT COUNT(*) FROM groups WHERE day = ? AND player = 'ade'",
            (DAY_ONE,)).fetchone()[0] == len(wire["groups"])
        relation = db.execute(
            "SELECT relation, first_group, second_group FROM relations "
            "WHERE day = ? AND player = 'ade'", (DAY_ONE,)).fetchone()
        assert relation == (wire["relations"][0]["relation"],
                            *wire["relations"][0]["of"])
        trial = db.execute(
            "SELECT p, target_rank, decoy_count, beaten, tied FROM trials "
            "WHERE day = ? AND player = 'ade'", (DAY_ONE,)).fetchone()
        pinned = json.loads(store.trial_row_path(
            root, DAY_ONE, "ade").read_text())
        assert trial == (pinned["p"], pinned["target_rank"],
                         pinned["decoy_count"], pinned["beaten"],
                         pinned["tied"])
        day = db.execute(
            "SELECT target_id, secret, commitment, pool_image_count, "
            "player_count FROM days WHERE day = ?", (DAY_ONE,)).fetchone()
        assert day_commitment(day[0], day[1]) == day[2]
        assert (day[3], day[4]) == (40, 3)
        page = db.execute("SELECT source, page FROM targets WHERE "
                          "target_id = ?", (day[0],)).fetchone()
        assert page[0] == "Wikimedia Commons"
        assert page[1].startswith("https://commons.wikimedia.org/wiki/File:")
        config = db.execute("SELECT path, config_json, weights_json FROM "
                            "configs").fetchone()
        assert json.loads(config[1])["fusion"]["weights"] \
            == json.loads(config[2])
        meta = dict(db.execute("SELECT key, value FROM meta"))
        assert meta["schema_version"] == "1"
        assert meta["license"] == "CC BY 4.0"
        assert meta["day_count"] == "2" and meta["withheld_count"] == "1"
        assert meta["first_day"] == DAY_ONE and meta["last_day"] == DAY_TWO


def test_a_withheld_response_keeps_its_scores_and_no_text(world) -> None:
    out = _build(world)
    with _open(out) as db:
        row = db.execute(
            "SELECT withheld, record_json, pasted_text, impression_count, "
            "stroke_count FROM submissions WHERE day = ? AND player = 'bru'",
            (DAY_TWO,)).fetchone()
        assert row[0] == 1 and row[1] is None and row[2] is None
        assert row[3] == 1 and row[4] > 0
        for table in ("impressions", "strokes", "groups", "relations"):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE day = ? AND "
                "player = 'bru'", (DAY_TWO,)).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM trials WHERE day = ? AND player = 'bru'",
            (DAY_TWO,)).fetchone()[0] == 1
        atoms = db.execute(
            "SELECT atom_text FROM trial_atoms WHERE day = ? AND "
            "player = 'bru'", (DAY_TWO,)).fetchall()
        assert atoms and all(text is None for (text,) in atoms)
        # The response of the same player on a different day is complete.
        assert db.execute(
            "SELECT withheld FROM submissions WHERE day = ? AND "
            "player = 'bru'", (DAY_ONE,)).fetchone()[0] == 0


def test_a_revoked_player_shows_by_one_identifier(world) -> None:
    out = _build(world)
    identifier = store.read_identifier_or_none(world["root"], GONE)
    with _open(out) as db:
        rows = db.execute("SELECT player, named, first_day, trial_count "
                          "FROM players ORDER BY player").fetchall()
        assert (identifier, 0, DAY_ONE, 1) in rows
        assert ("ade", 1, DAY_ONE, 2) in rows
        assert {row[0] for row in rows} == {"ade", "bru", identifier}
        assert db.execute(
            "SELECT COUNT(*) FROM trials WHERE player = ?",
            (identifier,)).fetchone()[0] == 1
    second = _build(world, "again")
    with _open(second) as db:
        assert db.execute("SELECT player FROM players WHERE named = 0"
                          ).fetchone()[0] == identifier


def test_two_builds_of_one_store_give_equal_rows(world) -> None:
    first, second = _build(world, "one"), _build(world, "two")

    def rows(directory: Path) -> dict:
        with _open(directory) as db:
            return {table: db.execute(
                f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in public._TABLES if table != "meta"}

    assert rows(first) == rows(second)


def test_a_player_with_no_identifier_record_stops_the_build(
        world, tmp_path) -> None:
    root = tmp_path / "store"
    shutil.copytree(world["root"], root)
    store.identifier_path(root, GONE).unlink()
    with pytest.raises(public.PublicBuildError, match="identifiers"):
        public.build(root, world["data"], tmp_path / "out",
                     snapshot_date="2026-12-04", built_at=NOW.isoformat())
    assert not list((tmp_path / "out").glob("*.sqlite"))
    assert public.write_identifiers(root, NOW) == [GONE]
    assert public.write_identifiers(root, NOW) == []
    public.build(root, world["data"], tmp_path / "out",
                 snapshot_date="2026-12-04", built_at=NOW.isoformat())
    # A player that is put back shows by the username again.
    store.set_player_status(root, GONE, expect_status="revoked",
                            new_status="active")
    public.build(root, world["data"], tmp_path / "back",
                 snapshot_date="2026-12-04", built_at=NOW.isoformat())
    with _open(tmp_path / "back") as db:
        assert db.execute("SELECT named FROM players WHERE player = ?",
                          (GONE,)).fetchone()[0] == 1


def test_a_changed_target_stops_the_build(world, tmp_path) -> None:
    root = tmp_path / "store"
    shutil.copytree(world["root"], root)
    path = store.day_record_path(root, DAY_ONE)
    raw = json.loads(path.read_text())
    other = next(image for image in world["fixture"]["image_ids"]
                 if image != raw["target_id"])
    raw["target_id"] = other
    path.write_text(json.dumps(raw))
    with pytest.raises(public.PublicBuildError, match="commitment"):
        public.build(root, world["data"], tmp_path / "out",
                     snapshot_date="2026-12-04", built_at=NOW.isoformat())


def test_a_target_with_no_source_page_stops_the_build(world,
                                                      tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(public.PublicBuildError, match="source page"):
        public.build(world["root"], data, tmp_path / "out",
                     snapshot_date="2026-12-04", built_at=NOW.isoformat())


def test_the_check_finds_each_planted_fault(world, tmp_path) -> None:
    def planted(statement: str, *arguments) -> list[str]:
        out = tmp_path / f"case-{len(list(tmp_path.iterdir()))}"
        shutil.copytree(_build(world, "for-check"), out)
        target = out / "starvector-public-2026-12-04.sqlite"
        db = sqlite3.connect(target)
        db.execute(statement, arguments)
        db.commit()
        db.close()
        return public.check(out)

    # The file changed after the build, thus its digest does not agree.
    faults = planted("UPDATE days SET pool_label = 'dev-wit-002'")
    assert any("digest" in fault for fault in faults)
    assert any("development pool" in fault for fault in faults)
    faults = planted("UPDATE submissions SET record_json = '{}' "
                     "WHERE withheld = 1")
    assert any("withheld response has its text" in fault for fault in faults)
    faults = planted("UPDATE trial_atoms SET atom_text = 'x' WHERE player "
                     "= 'bru' AND day = ?", DAY_TWO)
    assert any("trial_atoms" in fault for fault in faults)
    faults = planted("UPDATE days SET secret = ? WHERE day = ?", "c" * 64,
                     DAY_ONE)
    assert any("commitment" in fault for fault in faults)
    faults = planted("INSERT INTO meta VALUES ('note', ?)",
                     "$argon2id$v=19$m=19456")
    assert any("$argon2" in fault for fault in faults)
    faults = planted("INSERT INTO submissions VALUES ('2026-12-03', 'ade', "
                     "'t', NULL, NULL, 0, 0, 0, 0, 0, 0, NULL, '{}')")
    assert any("not in days" in fault for fault in faults)
    faults = planted("UPDATE players SET named = 1 WHERE named = 0")
    assert any("named" in fault for fault in faults)
    faults = planted("DELETE FROM impressions WHERE day = ?", DAY_ONE)
    assert any("impression_count" in fault for fault in faults)


def test_the_snapshot_directory_has_its_five_files(world) -> None:
    out = _build(world, "files")
    names = sorted(path.name for path in out.iterdir())
    assert names == ["LICENSE.txt", "README.md", "SHA256SUMS",
                     "release.json", "starvector-public-2026-12-04.sqlite"]
    release = json.loads((out / "release.json").read_text())
    assert release["day_count"] == 2 and release["withheld_count"] == 1
    assert release["rows"]["trials"] == 5
    assert release["schema_version"] == public.SCHEMA_VERSION
    assert "CC BY 4.0" in (out / "LICENSE.txt").read_text()
    readme = (out / "README.md").read_text()
    assert "Do not tune a scorer on this data" in readme
    assert "2026-12-04" in readme
    lines = public.summary_lines(out)
    assert f"withheld 1 on {DAY_TWO}" in lines
    assert "players with no username 1" in lines


def test_each_example_of_the_readme_runs(world) -> None:
    out = _build(world, "examples")
    with _open(out) as db:
        for _question, query in public.README_EXAMPLES:
            db.execute(query).fetchall()
        assert db.execute(public.README_EXAMPLES[0][1]).fetchone() \
            == (2, 3, 5)
    readme = (out / "README.md").read_text()
    for _question, query in public.README_EXAMPLES:
        assert query in readme


def test_the_command_line_builds_checks_and_withholds(
        world, tmp_path, capsys) -> None:
    root = tmp_path / "store"
    shutil.copytree(world["root"], root)
    config = dataclasses.replace(world["config"], store_root=str(root))
    config_path = tmp_path / "service.json"
    config_path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}))
    base = ["--service-config", str(config_path)]
    out = tmp_path / "out"
    assert public.main([*base, "build", "--out", str(out),
                        "--date", "2026-12-04"]) == 0
    printed = capsys.readouterr().out
    assert "rows trials 5" in printed and "publish it by hand" in printed
    assert public.main([*base, "check", str(out)]) == 0
    assert "check: no fault" in capsys.readouterr().out

    assert public.main([*base, "withhold", DAY_ONE, "ade",
                        "--note", "a telephone number"]) == 0
    assert public.main([*base, "withhold", DAY_ONE, "nobody",
                        "--note", "x"]) == 1
    assert public.main([*base, "withheld"]) == 0
    listed = capsys.readouterr().out
    assert f"{DAY_ONE}  ade" in listed and "a telephone number" in listed
    assert public.main([*base, "build", "--out", str(tmp_path / "two"),
                        "--date", "2026-12-04"]) == 0
    with _open(tmp_path / "two") as db:
        assert db.execute("SELECT COUNT(*) FROM submissions WHERE withheld "
                          "= 1").fetchone()[0] == 2
    assert public.main([*base, "release", DAY_ONE, "ade"]) == 0
    assert public.main([*base, "release", DAY_ONE, "ade"]) == 0
    assert "was not withheld" in capsys.readouterr().out
    assert public.main([*base, "identifiers"]) == 0
    assert public.main([*base, "build", "--out", str(tmp_path / "bad"),
                        "--date", "the-fourth"]) == 1
    assert "refused:" in capsys.readouterr().err


def test_the_build_writes_nothing_to_the_store(world) -> None:
    def snapshot() -> dict:
        return {str(path): path.read_bytes()
                for path in world["root"].rglob("*") if path.is_file()}

    before = snapshot()
    _build(world, "pure")
    assert snapshot() == before


def test_a_store_with_no_public_day_builds_an_empty_snapshot(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    _play(config, Path(config.store_root), DAY_DEV,
          {"ade": _wire(["a development response"])})
    out = tmp_path / "out"
    public.build(Path(config.store_root), Path(config.data_root), out,
                 snapshot_date="2026-12-04", built_at=NOW.isoformat())
    with _open(out) as db:
        assert db.execute("SELECT COUNT(*) FROM days").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM submissions"
                          ).fetchone()[0] == 0
    assert public.check(out) == []
