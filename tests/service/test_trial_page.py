"""Integration: the public page of one instant trial (spec IM1 10).

A world of a production pool, because a development pool has no public
page. The clock is the wall clock: the guest tests read the proof
library.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (QUICK_PROOF, QUICK_PROOF_KEYS, QuickDigester,
                         build_service_fixture, make_vp1)

from service import instant_store, public
from service.server import create_app
from tools import check_instant

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}
# A text that must be in no public answer: each text field of a record.
SECRET_WORDS = "zzsentinel words of the player"
PUBLIC_HEADERS = {"cache-control": "no-store", "x-robots-tag": "noindex"}


def _record(strokes: bool = True) -> dict:
    drawn = [
        {"points": [[0.2, 0.2], [0.5, 0.6], [0.8, 0.3], [0.2, 0.2]],
         "group_id": "zzsentinel-group", "color": "#81a1c1"},
        {"points": [[0.3, 0.7], [0.6, 0.8], [0.7, 0.5], [0.3, 0.7]],
         "group_id": "zzsentinel-group"},
    ]
    return {"impressions": [SECRET_WORDS, "zzsentinel second row"],
            "canvas_strokes": drawn if strokes else [],
            "groups": [{"id": "zzsentinel-group",
                        "label": "zzsentinel label"}] if strokes else [],
            "relations": [], "pasted_text": "zzsentinel notes"}


def _world(tmp_path: Path, *, dev_only: bool = False):
    fixture = make_vp1(build_service_fixture(tmp_path, dev_only=dev_only),
                       tmp_path)
    config = dataclasses.replace(
        fixture["service_config"], signup="open", instant="open",
        instant_day_cap=400)
    app = create_app(config, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset(),
                     proof_keys=QUICK_PROOF_KEYS, proof_settings=QUICK_PROOF)
    return fixture, config, app


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=ORIGIN)


def _proof(client, path: str) -> str:
    import altcha

    challenge = altcha.Challenge.from_dict(client.get(path).json())
    solution = altcha.solve_challenge(challenge)
    return altcha.Payload(challenge, solution).to_base64()


def _guest(app) -> tuple[TestClient, str]:
    client = _client(app)
    made = client.post("/api/guest", json={
        "proof": _proof(client, "/api/guest/challenge"),
        "agrees_public": True})
    assert made.status_code == 201, made.text
    return client, made.json()["owner"]


def _account(app, name: str) -> TestClient:
    client = _client(app)
    made = client.post("/api/signup", json={
        "username": name, "password": GOOD, "agrees_public": True,
        "proof": _proof(client, "/api/signup/challenge")})
    assert made.status_code == 201, made.text
    return client


def _play(client, app, record: dict | None = None,
          settle: bool = True) -> dict:
    trial = client.post("/api/instant/start").json()
    sent = client.post(
        f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
        json=record or _record())
    assert sent.status_code == 200, sent.text
    if settle:
        assert app.state.instant.tick() == 1
    return trial


def _page(app, trial: dict):
    return _client(app).get(
        f"/api/trial/{trial['date']}/{trial['trial_id']}")


def test_each_reader_gets_a_settled_trial_with_no_identity(
        tmp_path) -> None:
    fixture, _, app = _world(tmp_path)
    client, guest = _guest(app)
    trial = _play(client, app)
    page = _page(app, trial)
    assert page.status_code == 200
    for name, value in PUBLIC_HEADERS.items():
        assert page.headers[name] == value
    body = page.json()
    assert body["owner"] == guest and body["kind"] == "guest"
    assert body["named"] is False and body["avatar_hash"] is None
    assert body["state"] == "sketch"
    assert body["words"] == 2
    assert body["target_id"] in fixture["image_ids"]
    assert set(body["trial"]) == {"p", "decoy_count", "beaten", "tied",
                                  "target_rank"}
    assert body["record"] == {"position": 1, "sent": 1, "settled": 1,
                              "mean_p": body["trial"]["p"],
                              "hit_number": body["record"]["hit_number"]}
    # The owner of the trial gets the same pick.
    mine = client.get(
        f"/api/instant/{trial['date']}/{trial['trial_id']}").json()
    assert mine["pick"] == body["pick"]


def test_the_page_holds_the_sketch_alone(tmp_path) -> None:
    """Ruling 2 of spec SS1: a second person gets no word of a send."""
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    page = _page(app, _play(client, app))
    assert "zzsentinel" not in page.text
    strokes = page.json()["strokes"]
    assert [sorted(stroke) for stroke in strokes] == [
        ["color", "points"], ["points"]]
    assert strokes[0]["points"][0] == [0.2, 0.2]


def test_a_send_of_words_alone_has_the_words_only_mark(tmp_path) -> None:
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    body = _page(app, _play(client, app, _record(strokes=False))).json()
    assert body["state"] == "words-only"
    assert body["strokes"] == [] and body["words"] == 2
    assert "zzsentinel" not in json.dumps(body)


def test_one_constant_404_for_each_trial_that_is_not_public(
        tmp_path) -> None:
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    pending = _play(client, app, settle=False)
    started = client.post("/api/instant/start")
    assert started.status_code == 200
    missing = [pending, started.json(),
               {"date": pending["date"], "trial_id": "f" * 32},
               {"date": "2020-01-01", "trial_id": pending["trial_id"]},
               {"date": "not-a-date", "trial_id": "not-a-trial"}]
    bodies = set()
    for trial in missing:
        page = _page(app, trial)
        assert page.status_code == 404
        assert page.headers["x-robots-tag"] == "noindex"
        bodies.add(page.content)
    assert bodies == {b'{"detail":"not found"}'}
    # The result makes the page.
    assert app.state.instant.tick() == 1
    assert _page(app, pending).status_code == 200


def test_a_development_pool_has_no_public_page(tmp_path) -> None:
    _, _, app = _world(tmp_path, dev_only=True)
    client, _ = _guest(app)
    trial = _play(client, app)
    page = _page(app, trial)
    assert page.status_code == 404
    assert page.content == b'{"detail":"not found"}'
    # The owner reads the trial as before.
    assert client.get(
        f"/api/instant/{trial['date']}/{trial['trial_id']}"
    ).json()["status"] == "settled"


def test_the_record_is_live_and_holds_each_trial_of_the_owner(
        tmp_path) -> None:
    """The defense against a selected result: the page of one trial
    shows the count and the mean of all the trials of its owner."""
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    first = _play(client, app)
    assert _page(app, first).json()["record"]["sent"] == 1
    scores = [_page(app, first).json()["trial"]["p"]]
    for _ in range(2):
        scores.append(_page(app, _play(client, app)).json()["trial"]["p"])
    waiting = _play(client, app, settle=False)
    record = _page(app, first).json()["record"]
    assert record["position"] == 1
    assert record["sent"] == 4 and record["settled"] == 3
    assert record["mean_p"] == pytest.approx(sum(scores) / 3, abs=1e-6)
    # A second guest has its own record.
    other, _ = _guest(app)
    assert app.state.instant.tick() == 1
    assert _page(app, _play(other, app)).json()["record"]["sent"] == 1
    assert _page(app, waiting).json()["record"]["position"] == 4


def test_a_claimed_trial_shows_the_account(tmp_path) -> None:
    _, _, app = _world(tmp_path)
    client, guest = _guest(app)
    trial = _play(client, app)
    assert _page(app, trial).json()["owner"] == guest
    made = client.post("/api/signup", json={
        "username": "opal", "password": GOOD, "agrees_public": True,
        "proof": _proof(client, "/api/signup/challenge")})
    assert made.status_code == 201
    second = _play(client, app)
    for shown in (trial, second):
        body = _page(app, shown).json()
        assert body["owner"] == "opal" and body["kind"] == "account"
        assert body["named"] is True
        assert body["record"]["sent"] == 2
    assert _page(app, second).json()["record"]["position"] == 2
    assert guest not in _page(app, trial).text


def test_a_deleted_account_shows_its_anonymous_identifier(
        tmp_path) -> None:
    _, _, app = _world(tmp_path)
    client = _account(app, "opal")
    trial = _play(client, app)
    assert _page(app, trial).json()["owner"] == "opal"
    gone = client.post("/api/account/delete", json={
        "username": "opal", "password": GOOD})
    assert gone.status_code == 200, gone.text
    body = _page(app, trial).json()
    assert body["owner"].startswith("anon-") and body["named"] is False
    assert "opal" not in json.dumps(body)
    assert body["record"]["sent"] == 1


def test_the_operator_withholds_and_puts_back_a_response(
        tmp_path, capsys) -> None:
    fixture, config, app = _world(tmp_path)
    client, _ = _guest(app)
    trial = _play(client, app)
    config_path = tmp_path / "service.json"
    config_path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}), encoding="utf-8")
    base = ["--service-config", str(config_path)]
    before = _page(app, trial).json()
    assert public.main(base + ["withhold-instant", trial["date"],
                               trial["trial_id"], "--note",
                               "a name in it"]) == 0
    held = _page(app, trial).json()
    assert held["state"] == "withheld" and held["strokes"] == []
    # The score, the target, and the pick stay.
    for name in ("trial", "target_id", "pick", "record"):
        assert held[name] == before[name]
    assert public.main(base + ["withheld"]) == 0
    assert f"instant {trial['date']}  {trial['trial_id']}" \
        in capsys.readouterr().out
    assert public.main(base + ["release-instant", trial["date"],
                               trial["trial_id"]]) == 0
    assert _page(app, trial).json() == before
    # The stored send did not change.
    assert instant_store.read_send_or_none(
        fixture["store"], trial["date"], trial["trial_id"]) is not None
    assert public.main(base + ["withhold-instant", trial["date"],
                               "f" * 32, "--note", "none"]) == 1


def test_the_check_of_a_reader_passes_on_the_page_answer(
        tmp_path) -> None:
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    trial = _play(client, app)
    saved = tmp_path / "trial.json"
    saved.write_text(_page(app, trial).text, encoding="utf-8")
    assert _page(app, trial).json()["check"] \
        == "uv run python tools/check_instant.py --trial trial.json"
    assert check_instant.main(["--trial", str(saved)]) == 0
    # The answer of the owner checks too.
    saved.write_text(client.get(
        f"/api/instant/{trial['date']}/{trial['trial_id']}").text,
        encoding="utf-8")
    assert check_instant.main(["--trial", str(saved)]) == 0


@pytest.mark.parametrize("change, words", [
    (lambda value: value.update(target_id="image-not-the-target"),
     "pool root"),
    (lambda value: value["pick"].update(nonce="ef" * 32), "commitment"),
    (lambda value: value["pick"].update(send_digest="00" * 32), "position"),
    (lambda value: value["pick"].update(target_index=(
        value["pick"]["target_index"] + 1) % value["pick"]["pool_count"]),
     "position"),
    (lambda value: value.update(received_at="2999-01-01T00:00:00+00:00"),
     "not after the send"),
])
def test_the_check_finds_a_changed_answer(tmp_path, capsys, change,
                                          words: str) -> None:
    _, _, app = _world(tmp_path)
    client, _ = _guest(app)
    value = _page(app, _play(client, app)).json()
    change(value)
    saved = tmp_path / "trial.json"
    saved.write_text(json.dumps(value), encoding="utf-8")
    assert check_instant.main(["--trial", str(saved)]) == 1
    assert words in capsys.readouterr().out


def test_the_page_does_not_follow_the_target_of_the_open_day(
        tmp_path) -> None:
    """Rule I7: the public path reads no day record."""
    import inspect

    from service import server

    source = inspect.getsource(server.create_app)
    start = source.index('@app.get("/api/trial/{date}/{trial_id}")')
    body = source[start:source.index('@app.get("/api/day")', start)]
    assert "read_day_record" not in body and "list_days" not in body
