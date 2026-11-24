"""The instant trials in the public results database (spec IM1 13).

One world of a production pool holds each condition that a snapshot
must handle: an account, a guest, a guest that an account claimed, a
withheld response, a send with no result, and a deleted account. The
fake beacon stands in for drand: the build keeps a trial of it out of
a published snapshot, and this world has no network.
"""

import dataclasses
import datetime
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (QUICK_PROOF, QUICK_PROOF_KEYS, QuickDigester,
                         build_service_fixture, make_vp1, mixed_wire_record)

from service import instant_store, public
from service.server import create_app
from tools import check_instant

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}
NOW = datetime.datetime(2026, 12, 4, 12, 0, tzinfo=datetime.UTC)
WITHHELD_MARKER = "zzprivate street address"


def _wire(words: list[str], strokes: bool = True) -> dict:
    record = mixed_wire_record()
    record["impressions"] = words
    if not strokes:
        record.update(canvas_strokes=[], groups=[], relations=[])
    return record


def _proof(client, path: str) -> str:
    import altcha

    challenge = altcha.Challenge.from_dict(client.get(path).json())
    return altcha.Payload(
        challenge, altcha.solve_challenge(challenge)).to_base64()


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=ORIGIN)


def _guest(app) -> tuple[TestClient, str]:
    client = _client(app)
    made = client.post("/api/guest", json={
        "proof": _proof(client, "/api/guest/challenge"),
        "agrees_public": True})
    assert made.status_code == 201, made.text
    return client, made.json()["owner"]


def _sign_up(client, name: str) -> None:
    made = client.post("/api/signup", json={
        "username": name, "password": GOOD, "agrees_public": True,
        "proof": _proof(client, "/api/signup/challenge")})
    assert made.status_code == 201, made.text


def _play(client, app, wire: dict, settle: bool = True) -> dict:
    trial = client.post("/api/instant/start").json()
    sent = client.post(
        f"/api/instant/{trial['date']}/{trial['trial_id']}/send", json=wire)
    assert sent.status_code == 200, sent.text
    if settle:
        assert app.state.instant.tick() == 1
    return trial


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setattr(public, "PUBLIC_CHAINS", ("drand-quicknet", "fake"))
    base = tmp_path_factory.mktemp("public-instant")
    fixture = make_vp1(build_service_fixture(base / "prod", dev_only=False,
                                             with_credits=True), base)
    config = dataclasses.replace(
        fixture["service_config"], signup="open", instant="open",
        instant_day_cap=400)
    app = create_app(config, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset(),
                     proof_keys=QUICK_PROOF_KEYS, proof_settings=QUICK_PROOF)
    root = Path(config.store_root)
    trials = {}
    opal = _client(app)
    _sign_up(opal, "opal")
    trials["opal-1"] = _play(opal, app, _wire(["a red bridge"]))
    trials["opal-2"] = _play(opal, app, _wire(["mist"], strokes=False))
    guest, guest_id = _guest(app)
    trials["guest"] = _play(guest, app, _wire(["a quiet lake"]))
    claimed, claimed_id = _guest(app)
    trials["claimed"] = _play(claimed, app, _wire(["tall grass"]))
    _sign_up(claimed, "ruby")
    held, _ = _guest(app)
    trials["withheld"] = _play(held, app, _wire([WITHHELD_MARKER]))
    instant_store.write_withheld(root, instant_store.WithheldTrial(
        date=trials["withheld"]["date"],
        trial_id=trials["withheld"]["trial_id"],
        withheld_at=NOW.isoformat(), note="an address"))
    gone = _client(app)
    _sign_up(gone, "zed")
    trials["gone"] = _play(gone, app, _wire(["a harbor"]))
    assert gone.post("/api/account/delete", json={
        "username": "zed", "password": GOOD}).status_code == 200
    trials["pending"] = _play(guest, app, _wire(["no result"]),
                              settle=False)
    yield {"config": config, "root": root, "base": base, "app": app,
           "trials": trials, "guest": guest_id, "claimed": claimed_id}
    patch.undo()


def _build(world, name: str = "out") -> Path:
    out = world["base"] / name
    public.build(world["root"], Path(world["config"].data_root), out,
                 snapshot_date="2026-12-04", built_at=NOW.isoformat(),
                 version="test")
    return out


def _open(directory: Path) -> sqlite3.Connection:
    return sqlite3.connect(directory / "starvector-public-2026-12-04.sqlite")


def test_the_snapshot_is_clean_and_holds_the_settled_trials(world) -> None:
    out = _build(world)
    assert public.check(out) == []
    trials = world["trials"]
    with _open(out) as db:
        found = {row[0] for row in db.execute(
            "SELECT trial_id FROM instant_trials")}
        meta = dict(db.execute("SELECT key, value FROM meta"))
    assert found == {trials[name]["trial_id"] for name in trials
                     if name != "pending"}
    assert meta["schema_version"] == "5"
    assert meta["instant_trial_count"] == "6"
    assert meta["instant_send_count"] == "7"
    assert meta["instant_withheld_count"] == "1"
    # No daily table holds an instant trial.
    with _open(out) as db:
        for table in ("days", "submissions", "trials", "players"):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_the_owners_are_accounts_guests_and_anonymous_ones(world) -> None:
    with _open(_build(world)) as db:
        owners = {row[0]: row[1:] for row in db.execute(
            "SELECT owner, kind, named, trial_count FROM instant_owners")}
        claimed = db.execute(
            "SELECT owner FROM instant_trials WHERE trial_id = ?",
            (world["trials"]["claimed"]["trial_id"],)).fetchone()[0]
    assert owners["opal"] == ("account", 1, 2)
    # The trial of a claimed guest is a trial of the account.
    assert claimed == "ruby" and owners["ruby"] == ("account", 1, 1)
    assert world["claimed"] not in owners
    assert owners[world["guest"]] == ("guest", 0, 1)
    anonymous = [name for name in owners if name.startswith("anon-")]
    assert len(anonymous) == 1
    assert owners[anonymous[0]] == ("account", 0, 1)
    assert "zed" not in owners


def test_the_rows_agree_with_the_store(world) -> None:
    trial = world["trials"]["opal-1"]
    send = instant_store.read_send_or_none(
        world["root"], trial["date"], trial["trial_id"])
    result = instant_store.read_result_or_none(
        world["root"], trial["date"], trial["trial_id"])
    with _open(_build(world)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM instant_trials WHERE trial_id = ?",
                         (trial["trial_id"],)).fetchone()
        response = db.execute(
            "SELECT * FROM instant_submissions WHERE trial_id = ?",
            (trial["trial_id"],)).fetchone()
        words = [found[0] for found in db.execute(
            "SELECT text FROM instant_impressions WHERE trial_id = ? "
            "ORDER BY position", (trial["trial_id"],))]
        strokes = db.execute(
            "SELECT COUNT(*) FROM instant_strokes WHERE trial_id = ?",
            (trial["trial_id"],)).fetchone()[0]
        atoms = db.execute(
            "SELECT COUNT(*) FROM instant_trial_atoms WHERE trial_id = ?",
            (trial["trial_id"],)).fetchone()[0]
        target = db.execute("SELECT page FROM targets WHERE target_id = ?",
                            (result.target_id,)).fetchone()
    assert row["owner"] == "opal" and row["date"] == trial["date"]
    assert row["trial_code"] == trial["trial_code"]
    assert row["target_id"] == result.target_id
    assert row["p"] == result.row["p"]
    assert row["nonce"] == result.nonce
    assert row["commitment"] == send.commitment
    assert row["send_digest"] == send.send_digest
    assert row["chain_position"] == send.chain_position
    assert json.loads(row["target_proof"]) == list(result.target_proof)
    assert row["round_time"] > row["received_at"][:19]
    assert json.loads(response["record_json"]) == send.record
    assert words == ["a red bridge"] and strokes == 2
    assert atoms == len(result.row["report"])
    assert target is not None


def test_the_chain_holds_each_send_of_the_store(world) -> None:
    with _open(_build(world)) as db:
        rows = db.execute(
            "SELECT chain_position, trial_id, settled FROM instant_chain "
            "ORDER BY chain_position").fetchall()
    assert [row[0] for row in rows] == list(range(7))
    pending = world["trials"]["pending"]["trial_id"]
    assert {row[1]: row[2] for row in rows}[pending] == 0
    assert sum(row[2] for row in rows) == 6


def test_a_withheld_response_keeps_its_scores_and_no_text(world) -> None:
    out = _build(world)
    trial_id = world["trials"]["withheld"]["trial_id"]
    database = out / "starvector-public-2026-12-04.sqlite"
    assert WITHHELD_MARKER.encode() not in database.read_bytes()
    with _open(out) as db:
        response = db.execute(
            "SELECT withheld, record_json, pasted_text, impression_count "
            "FROM instant_submissions WHERE trial_id = ?",
            (trial_id,)).fetchone()
        score = db.execute(
            "SELECT p FROM instant_trials WHERE trial_id = ?",
            (trial_id,)).fetchone()
        texts = db.execute(
            "SELECT COUNT(*) FROM instant_trial_atoms WHERE trial_id = ? "
            "AND atom_text IS NOT NULL", (trial_id,)).fetchone()[0]
        parts = db.execute(
            "SELECT COUNT(*) FROM instant_impressions WHERE trial_id = ?",
            (trial_id,)).fetchone()[0]
    assert response == (1, None, None, 1)
    assert score is not None and texts == 0 and parts == 0


def test_no_credential_and_no_secret_of_a_guest_is_in_the_file(
        world) -> None:
    raw = (_build(world) / "starvector-public-2026-12-04.sqlite").read_bytes()
    for text in public._FORBIDDEN_TEXT:
        assert text.encode() not in raw
    # The identifier of a claimed guest is not in the file.
    assert world["claimed"].encode() not in raw


def test_a_trial_of_a_beacon_that_is_not_public_stays_out(
        world, monkeypatch) -> None:
    monkeypatch.setattr(public, "PUBLIC_CHAINS", ("drand-quicknet",))
    out = _build(world, "no-fake")
    with _open(out) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM instant_trials").fetchone()[0] == 0
        # The chain stays full: its rows hold digests alone.
        assert db.execute(
            "SELECT COUNT(*), SUM(settled) FROM instant_chain"
        ).fetchone() == (7, 0)
    assert public.check(out) == []


def test_the_check_of_a_reader_passes_on_the_file(world, capsys) -> None:
    database = _build(world) / "starvector-public-2026-12-04.sqlite"
    assert check_instant.main(["--database", str(database)]) == 0
    assert "6 instant trial(s) checked, 0 fault(s)" in capsys.readouterr().out


def test_the_checks_find_each_planted_fault(world, tmp_path) -> None:
    def planted(statement: str, *arguments) -> tuple[list[str], int]:
        directory = tmp_path / f"planted-{len(list(tmp_path.iterdir()))}"
        shutil.copytree(_build(world), directory)
        database = directory / "starvector-public-2026-12-04.sqlite"
        with sqlite3.connect(database) as db:
            db.execute(statement, arguments)
        faults = [fault for fault in public.check(directory)
                  if "digest of starvector" not in fault]
        return faults, check_instant.main(["--database", str(database)])

    trial_id = world["trials"]["opal-1"]["trial_id"]
    withheld = world["trials"]["withheld"]["trial_id"]
    cases = [
        ("UPDATE instant_trials SET nonce = ? WHERE trial_id = ?",
         ("ef" * 32, trial_id), "commitment", 1),
        ("UPDATE instant_trials SET target_index = target_index + 1 "
         "WHERE trial_id = ?", (trial_id,), "position", 1),
        ("UPDATE instant_trials SET send_digest = ? WHERE trial_id = ?",
         ("00" * 32, trial_id), "position", 1),
        ("DELETE FROM instant_chain WHERE chain_position = 2", (),
         "instant_chain", 1),
        ("UPDATE instant_chain SET received_at = '2026-01-01T00:00:00+00:00'"
         " WHERE chain_position = 3", (), "instant_chain", 1),
        ("UPDATE instant_submissions SET record_json = '{}' "
         "WHERE trial_id = ?", (withheld,), "withheld", 0),
        ("DELETE FROM instant_impressions WHERE trial_id = ?", (trial_id,),
         "instant_impressions", 0),
        ("UPDATE instant_owners SET named = 1 WHERE kind = 'guest'", (),
         "instant_owners", 0),
        ("UPDATE instant_trials SET owner = 'nobody' WHERE trial_id = ?",
         (trial_id,), "instant_owners", 0),
        ("UPDATE instant_trials SET pool_label = 'dev-pool' "
         "WHERE trial_id = ?", (trial_id,), "development pool", 0),
        ("INSERT INTO targets VALUES ('image-extra', 's', 't', 'p')", (),
         "not a target", 0),
    ]
    for statement, arguments, words, tool in cases:
        faults, code = planted(statement, *arguments)
        assert any(words in fault for fault in faults), (statement, faults)
        assert code == tool, statement


def test_a_changed_send_in_the_store_stops_the_build(world,
                                                     tmp_path) -> None:
    copy = tmp_path / "store"
    shutil.copytree(world["root"], copy)
    trial = world["trials"]["guest"]
    path = copy / "instant" / trial["date"] / trial["trial_id"] / "send.json"
    path.unlink()
    with pytest.raises(public.PublicBuildError, match="chain"):
        public.build(copy, Path(world["config"].data_root), tmp_path / "out",
                     snapshot_date="2026-12-04", built_at=NOW.isoformat())


def test_each_example_of_the_readme_runs(world) -> None:
    out = _build(world)
    readme = (out / "README.md").read_text()
    assert "instant_trials" in readme and "instant_chain" in readme
    with _open(out) as db:
        for _question, query in public.README_EXAMPLES:
            db.execute(query).fetchall()
        summary = dict((row[0], row[2]) for row in db.execute(
            "SELECT s.owner, o.kind, s.trial_count FROM "
            "instant_owner_summary AS s JOIN instant_owners AS o "
            "ON o.owner = s.owner"))
    assert summary["opal"] == 2


def test_the_build_writes_nothing_to_the_store(world) -> None:
    def snapshot() -> dict:
        return {str(path.relative_to(world["root"])): path.read_bytes()
                for path in sorted(world["root"].rglob("*"))
                if path.is_file()}

    before = snapshot()
    _build(world, "again")
    assert snapshot() == before


def test_the_summary_names_the_instant_counts(world) -> None:
    lines = public.summary_lines(_build(world))
    assert "instant trials 6 of 7 sends, withheld 1" in lines
    assert "instant owners that are guests 2" in lines


def test_a_development_pool_has_no_instant_trial_in_a_snapshot(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public, "PUBLIC_CHAINS", ("drand-quicknet", "fake"))
    fixture = make_vp1(build_service_fixture(tmp_path / "dev"), tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 instant="accounts", instant_day_cap=400)
    app = create_app(config)
    _play(TestClient(app), app, _wire(["a development trial"]))
    root = Path(config.store_root)
    assert public.public_instant(root) == []
    assert len(public.instant_sends(root)) == 1
