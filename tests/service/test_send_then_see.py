"""Send, then see (spec SS1): the sends of a day, as sketches alone.

The gate is the property that no other test holds. A caller with no
send of a day that is not revealed gets one constant refusal, and the
checks before it read no send of a second player. A caller with their
own send in the store gets the sketches of the day, and no text of a
send goes with them.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frozen_fixture import manifest_of
from svc_fixture import (FIXED_CLOCK, build_service_fixture,
                         mixed_wire_record, mint_player,
                         pinned_session_value, plant_session)

from service import auth, limits, notice, players, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-12"
TOKEN = "test-operator-token"
SECRETS = {"alice": "1" * 43, "bru": "2" * 43, "cy": "3" * 43}
REFUSAL = b'{"detail":"sends not shown"}'
SENTINEL = "zq-sentinel"


@pytest.fixture(scope="module")
def pool(tmp_path_factory) -> dict:
    """One development pool for each world of this module. Each world
    reads the pool and writes its own store."""
    return build_service_fixture(tmp_path_factory.mktemp("pool"))


@pytest.fixture(scope="module")
def public_pool(tmp_path_factory) -> dict:
    """A pool with days that a public snapshot can hold: a send of
    this world has the notice (spec R1 section 3)."""
    return build_service_fixture(tmp_path_factory.mktemp("public-pool"),
                                 dev_only=False)


def _send(root: Path, name: str, position: int,
          record: dict | None = None) -> None:
    """One stored send. The position gives the receive time, thus the
    sequence of the sends is the sequence of the positions."""
    store.write_once_json(
        store.submission_path(root, DAY, name),
        {"day": DAY, "player": name, "trial_id": f"{position:032x}",
         "received_at": f"2026-08-12T00:00:{position:02d}+00:00",
         "record": mixed_wire_record() if record is None else record})


def _world(pool: dict, tmp_path: Path, *, senders: tuple[str, ...] = (),
           seed: str = "a" * 32):
    """One open day with three players, and a send of each named one."""
    config = dataclasses.replace(pool["service_config"],
                                 store_root=str(tmp_path / "store"))
    root = Path(config.store_root)
    for name, secret in SECRETS.items():
        mint_player(config, player=name, display_name=name.title(),
                    clock=lambda: FIXED_CLOCK, secret=secret)
        plant_session(root, f"{name}.{secret}")
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed=seed, secret="b" * 64, trial_code="AAAAAA")
    for position, name in enumerate(senders):
        _send(root, name, position)
    return config, root, create_app(config, operator_token=TOKEN)


def _as(app, name: str | None) -> TestClient:
    """A browser with the session of one player, or with no session."""
    client = TestClient(app)
    if name is not None:
        client.cookies.set(
            auth.SESSION_COOKIE,
            pinned_session_value(f"{name}.{SECRETS[name]}"))
    return client


def _sends(client: TestClient, query: str = f"?day={DAY}") -> dict:
    answer = client.get(f"/api/sends{query}")
    assert answer.status_code == 200, answer.content
    assert answer.headers["cache-control"] == "private, no-store"
    return answer.json()


_QUERIES = ("", f"?day={DAY}", f"?day={DAY}&before=0",
            f"?day={DAY}&before=zz", "?day=1999-01-01", "?day=../../etc")


# -- the gate -------------------------------------------------------------


def test_no_session_meets_the_constant_401(pool, tmp_path) -> None:
    bodies = set()
    for index, senders in enumerate(((), ("bru", "cy"))):
        _config, _root, app = _world(pool, tmp_path / str(index),
                                     senders=senders)
        client = _as(app, None)
        for query in _QUERIES:
            answer = client.get(f"/api/sends{query}")
            assert answer.status_code == 401
            bodies.add(answer.content)
    assert bodies == {b'{"detail":"unauthorized"}'}


def test_a_caller_with_no_send_gets_one_constant_refusal(
        pool, tmp_path) -> None:
    """I7 and R3: alice has no send. Her answers are one constant body,
    in a world where the two other players sent and in a world where
    nobody did. A bad cursor does not change it: the gate comes first."""
    answers = set()
    for index, senders in enumerate(((), ("bru", "cy"))):
        _config, _root, app = _world(pool, tmp_path / str(index),
                                     senders=senders)
        client = _as(app, "alice")
        for query in _QUERIES:
            answer = client.get(f"/api/sends{query}")
            answers.add((answer.status_code, answer.content,
                         answer.headers["cache-control"]))
    assert answers == {(404, REFUSAL, "private, no-store")}


def test_the_refusal_reads_no_send_of_a_second_player(
        pool, tmp_path, monkeypatch) -> None:
    """The work before the refusal is the same for each set of sends:
    no read of the day's sends, and no read of a stored send."""
    _config, _root, app = _world(pool, tmp_path, senders=("bru", "cy"))
    client = _as(app, "alice")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the refusal read the sends of the day")

    monkeypatch.setattr(store, "list_submissions", forbidden)
    monkeypatch.setattr(store, "read_json_or_none", forbidden)
    monkeypatch.setattr(store, "count_submissions", forbidden)
    assert client.get(f"/api/sends?day={DAY}").content == REFUSAL


def test_a_send_opens_the_sends(pool, tmp_path) -> None:
    """Send, then see, through the server's own send path: 404, the
    send, then 200 with no cache between."""
    _config, _root, app = _world(pool, tmp_path, senders=("bru",))
    client = _as(app, "alice")
    assert client.get(f"/api/sends?day={DAY}").content == REFUSAL
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200
    view = _sends(client)
    assert [entry["player"] for entry in view["entries"]] \
        == ["alice", "bru"]
    assert view["total"] == client.get("/api/day").json()["sends"] == 2
    # A send after that one is in the subsequent answer.
    _send(Path(_config.store_root), "cy", 59)
    assert _sends(client)["total"] == 3


def test_after_the_reveal_a_caller_with_no_send_gets_the_sends(
        pool, tmp_path) -> None:
    config, _root, app = _world(pool, tmp_path, senders=("bru",))
    client = _as(app, "alice")
    assert client.get("/api/sends").content == REFUSAL
    close_day(config, clock=lambda: FIXED_CLOCK)
    # A closed day with no reveal keeps the gate.
    assert client.get(f"/api/sends?day={DAY}").content == REFUSAL
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    for query in ("", f"?day={DAY}"):
        view = _sends(client, query)
        assert [entry["player"] for entry in view["entries"]] == ["bru"]
        assert view["entries"][0]["state"] == "sketch"


# -- the answer -----------------------------------------------------------


def test_the_newest_send_is_first(pool, tmp_path) -> None:
    _config, _root, app = _world(pool, tmp_path,
                                 senders=("cy", "alice", "bru"))
    view = _sends(_as(app, "alice"))
    assert view["day"] == DAY and view["total"] == 3
    assert view["next_before"] is None
    assert [entry["player"] for entry in view["entries"]] \
        == ["bru", "alice", "cy"]
    assert all(entry["named"] and entry["state"] == "sketch"
               for entry in view["entries"])


def test_a_page_stops_at_the_entry_cap(pool, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(limits, "PAGE_ENTRY_CAP", 2)
    _config, _root, app = _world(pool, tmp_path,
                                 senders=("cy", "alice", "bru"))
    client = _as(app, "alice")
    first = _sends(client)
    assert [entry["player"] for entry in first["entries"]] \
        == ["bru", "alice"]
    assert first["next_before"] == 1
    second = _sends(client, f"?day={DAY}&before=1")
    assert [entry["player"] for entry in second["entries"]] == ["cy"]
    assert second["next_before"] is None
    assert second["total"] == 3


def test_a_page_stops_at_the_point_cap_and_keeps_its_first_entry(
        pool, tmp_path, monkeypatch) -> None:
    # The test record has 10 points: two of them are more than 12, and
    # one of them is more than 5.
    _config, _root, app = _world(pool, tmp_path,
                                 senders=("cy", "alice", "bru"))
    client = _as(app, "alice")
    monkeypatch.setattr(limits, "POINT_CAP", 12)
    first = _sends(client)
    assert [entry["player"] for entry in first["entries"]] == ["bru"]
    assert first["next_before"] == 2
    monkeypatch.setattr(limits, "POINT_CAP", 5)
    assert [entry["player"] for entry in
            _sends(client, f"?day={DAY}&before=2")["entries"]] == ["alice"]


def test_the_cursor(pool, tmp_path) -> None:
    _config, _root, app = _world(pool, tmp_path,
                                 senders=("cy", "alice", "bru"))
    client = _as(app, "alice")
    assert _sends(client, f"?day={DAY}&before=3") == _sends(client)
    empty = _sends(client, f"?day={DAY}&before=0")
    assert empty["entries"] == [] and empty["next_before"] is None
    for bad in ("-1", "abc", "4", "1.0", "", " 1", "１"):
        answer = client.get("/api/sends", params={"day": DAY, "before": bad})
        assert answer.status_code == 400, bad
        assert answer.content == b'{"cause":"bad-cursor"}'


def _record_with_text() -> dict:
    """A scoreable record with the sentinel in each text field."""
    return {
        "impressions": [f"{SENTINEL}-word"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6]],
             "group_id": f"{SENTINEL}-group", "color": "#bf616a"},
            {"points": [[0.6, 0.4], [0.9, 0.4]], "group_id": None},
        ],
        "groups": [{"id": f"{SENTINEL}-group", "label": f"{SENTINEL}-label"}],
        "relations": [{"relation": f"{SENTINEL}-relation",
                       "of": [f"{SENTINEL}-group", f"{SENTINEL}-group"]}],
        "pasted_text": f"{SENTINEL}-note",
    }


def test_an_entry_holds_the_sketch_and_no_text_of_the_send(
        pool, tmp_path) -> None:
    """Spec SS1 section 5: the sketch alone. The sentinel is in each
    text field of two stored sends, and it is in no answer."""
    _config, root, app = _world(pool, tmp_path, senders=("alice",))
    _send(root, "bru", 1, _record_with_text())
    _send(root, "cy", 2, {**_record_with_text(), "canvas_strokes": []})
    answer = _as(app, "alice").get(f"/api/sends?day={DAY}")
    assert SENTINEL.encode() not in answer.content
    view = answer.json()
    assert set(view) == {"day", "total", "next_before", "entries"}
    for entry in view["entries"]:
        assert set(entry) == {"player", "named", "avatar_hash", "state",
                              "strokes"}
        for stroke in entry["strokes"]:
            assert set(stroke) <= {"points", "color"}
    by_name = {entry["player"]: entry for entry in view["entries"]}
    assert by_name["bru"]["state"] == "sketch"
    assert by_name["bru"]["strokes"] == [
        {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6]], "color": "#bf616a"},
        {"points": [[0.6, 0.4], [0.9, 0.4]]},
    ]
    # A send with no stroke has the mark and no sketch.
    assert by_name["cy"]["state"] == "words-only"
    assert by_name["cy"]["strokes"] == []


# -- moderation -----------------------------------------------------------


def test_a_withheld_send_has_a_mark_and_a_release_shows_the_sketch(
        pool, tmp_path) -> None:
    """Spec SS1 section 9: the operator withholds on an open day, and
    the subsequent answer has no sketch of that send."""
    _config, root, app = _world(pool, tmp_path, senders=("alice", "bru"))
    client = _as(app, "alice")
    assert _sends(client)["entries"][0]["state"] == "sketch"
    store.write_withheld(root, store.WithheldRecord(
        day=DAY, player="bru", withheld_at=FIXED_CLOCK, note="a test"))
    held = _sends(client)["entries"][0]
    assert held["player"] == "bru"
    assert held["state"] == "withheld" and held["strokes"] == []
    assert _sends(client)["total"] == 2
    assert store.remove_withheld(root, DAY, "bru") is True
    assert _sends(client)["entries"][0]["state"] == "sketch"


def test_a_deleted_player_shows_by_the_identifier(pool, tmp_path) -> None:
    """Spec MD1 section 4.2: the send stays, with the anonymous
    identifier and no avatar. No answer holds the username."""
    config, _root, app = _world(pool, tmp_path, senders=("alice", "bru"))
    players.delete_player(config, player="bru", confirm="bru")
    answer = _as(app, "alice").get(f"/api/sends?day={DAY}")
    assert b"bru" not in answer.content
    entry = answer.json()["entries"][0]
    assert entry["player"].startswith("anon-")
    assert entry["named"] is False and entry["avatar_hash"] is None
    assert entry["state"] == "sketch"


def test_a_revoked_player_keeps_the_board_label(pool, tmp_path) -> None:
    config, _root, app = _world(pool, tmp_path, senders=("alice", "bru"))
    players.revoke_player(config, player="bru")
    entry = _sends(_as(app, "alice"))["entries"][0]
    assert entry["player"] == "bru" and entry["named"] is True


# -- the notice -----------------------------------------------------------


def test_a_send_of_notice_version_1_waits_for_the_reveal(
        public_pool, tmp_path) -> None:
    """Spec SS1 section 10: version 1 said `after each day closes`. On a
    server that publishes, a send of a player with version 1 alone does
    not go to a second player before the reveal of its day."""
    config, root, app = _world(public_pool, tmp_path,
                               senders=("alice", "bru", "cy"))
    store.write_consent(root, "alice", notice.NOTICE_VERSION, "t")
    store.write_consent(root, "bru", 1, "t")
    store.write_consent(root, "cy", notice.NOTICE_VERSION, "t")
    client = _as(app, "alice")
    by_name = {entry["player"]: entry for entry in _sends(client)["entries"]}
    assert by_name["bru"]["state"] == "after-reveal"
    assert by_name["bru"]["strokes"] == []
    assert by_name["cy"]["state"] == "sketch"
    assert by_name["alice"]["state"] == "sketch"
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    after = {entry["player"]: entry for entry in _sends(client)["entries"]}
    assert after["bru"]["state"] == "sketch" and after["bru"]["strokes"]


def test_a_server_that_does_not_publish_has_no_notice_rule(
        pool, tmp_path) -> None:
    _config, _root, app = _world(pool, tmp_path, senders=("alice", "bru"))
    assert all(entry["state"] == "sketch"
               for entry in _sends(_as(app, "alice"))["entries"])


# -- integrity ------------------------------------------------------------

# The player paths of an open day, apart from the sends of the day.
_OTHER_PATHS = ("/api/day", "/api/me", "/api/history", "/api/reveal",
                f"/api/reveal?day={DAY}", f"/api/leaderboard?day={DAY}",
                f"/api/submission?day={DAY}", "/api/leaderboard/skill",
                "/api/practice", "/api/avatar/alice", "/api/avatar/bru")


def test_a_caller_with_a_send_sees_the_sends_and_no_other_answer_moves(
        pool, tmp_path) -> None:
    """Two worlds: alice sent in the two, and bru sent in the first.
    The sends of the day show bru in the first world alone. Each other
    answer agrees byte for byte, apart from the `sends` total (spec H1
    D5): the change of this spec is one path wide."""
    _c1, _r1, with_bru = _world(pool, tmp_path / "sent",
                                senders=("alice", "bru"))
    _c2, _r2, without = _world(pool, tmp_path / "quiet", senders=("alice",))
    sent, quiet = _as(with_bru, "alice"), _as(without, "alice")
    assert [entry["player"] for entry in _sends(sent)["entries"]] \
        == ["bru", "alice"]
    assert [entry["player"] for entry in _sends(quiet)["entries"]] \
        == ["alice"]
    for path in _OTHER_PATHS:
        first, second = sent.get(path), quiet.get(path)
        if path == "/api/day":
            one, two = first.json(), second.json()
            assert one.pop("sends") == two.pop("sends") + 1
            assert one == two
        else:
            assert first.content == second.content, path


_SEEDS = ("1" * 32, "2" * 32, "3" * 32)


def test_the_sends_do_not_follow_the_target(pool, tmp_path) -> None:
    """R3: worlds equal in each fact but the pick seed. The bytes of
    the sends are one value, while the day is open and after the close,
    where the scores are on disk."""
    open_bodies, closed_bodies, targets = set(), set(), set()
    for index, seed in enumerate(_SEEDS):
        config, root, app = _world(pool, tmp_path / str(index),
                                   senders=("alice", "bru"), seed=seed)
        client = _as(app, "alice")
        targets.add(store.read_day_record(root, DAY).target_id)
        open_bodies.add(client.get(f"/api/sends?day={DAY}").content)
        close_day(config, clock=lambda: FIXED_CLOCK)
        closed_bodies.add(client.get(f"/api/sends?day={DAY}").content)
    assert len(targets) >= 2, "the seeds must give different targets"
    assert len(open_bodies) == 1 and open_bodies == closed_bodies


def test_a_read_writes_no_file(pool, tmp_path) -> None:
    """I4: the sends of a day are a read of the store."""
    _config, root, app = _world(pool, tmp_path,
                                senders=("alice", "bru", "cy"))
    store.write_withheld(root, store.WithheldRecord(
        day=DAY, player="cy", withheld_at=FIXED_CLOCK, note="a test"))
    before = manifest_of(root)
    for name in ("alice", "bru", None):
        client = _as(app, name)
        for query in _QUERIES:
            client.get(f"/api/sends{query}")
    assert manifest_of(root) == before


def test_the_answer_is_json_of_the_stored_points(pool, tmp_path) -> None:
    """The points go out as the store has them: no rounding and no new
    number."""
    _config, _root, app = _world(pool, tmp_path, senders=("alice",))
    strokes = _sends(_as(app, "alice"))["entries"][0]["strokes"]
    assert json.dumps(strokes) == json.dumps(
        [{"points": stroke["points"]}
         for stroke in mixed_wire_record()["canvas_strokes"]])
