"""The protocol integrity gates (spec M1 B10, architecture 22).

Two properties no other test holds.

**Nothing about the open day follows what other players sent.**
Multiplayer adds a path for one player's answer to hold a fact
about a second player's play. I7 forbids score information before
the window closes, and a count of who has sent is score-adjacent:
it says who is in contention.

**No answer length follows the target.** Section 22 asks for this
and no test performed it. Length is the weaker property than
byte-equality and it is the one an outsider measures: a TLS record
length shows where a body does not. It also survives the day-level
randomness that makes the bytes different.
"""

import dataclasses
from pathlib import Path

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import players, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

from fastapi.testclient import TestClient

DAY = "2026-08-12"
TOKEN = "test-operator-token"
ALICE, BRU = "1" * 43, "2" * 43


def _sign_in(client: TestClient, token: str) -> TestClient:
    from service import auth

    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, token)
    return client


def _two_player_world(tmp_path, *, bru_sent: bool):
    """One open day, alice minted, bru minted and sending or not."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    for name, label, secret in (("alice", "Alice", ALICE),
                                ("bru", "Bru", BRU)):
        players.mint_player(config, player=name, display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64, trial_code="AAAAAA")
    if bru_sent:
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, "bru"),
            {"day": DAY, "player": "bru", "trial_id": "b" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    client = TestClient(create_app(config, operator_token=TOKEN))
    return fixture, _sign_in(client, f"alice.{ALICE}")


_OPEN_DAY_PATHS = ("/", "/api/day", "/api/me", "/api/history",
                   "/api/reveal", f"/api/reveal?day={DAY}",
                   f"/api/leaderboard?day={DAY}",
                   f"/api/submission?day={DAY}",
                   "/api/leaderboard/skill", "/api/practice",
                   "/api/avatar/alice", "/api/avatar/bru")


def test_no_open_day_answer_follows_the_other_players_sends(
        tmp_path: Path) -> None:
    """I7: alice cannot read if bru has sent.

    Two worlds equal in each fact but one - bru has sent in the
    first and has not in the second. Alice's bodies must agree
    byte for byte. How many players have sent, and which, is not a
    function that one open-day byte depends on.
    """
    _sent, sent_client = _two_player_world(tmp_path / "sent", bru_sent=True)
    _quiet, quiet_client = _two_player_world(tmp_path / "quiet",
                                             bru_sent=False)
    for path in _OPEN_DAY_PATHS:
        assert sent_client.get(path).content \
            == quiet_client.get(path).content, path


def test_the_reveal_opens_the_board(tmp_path: Path) -> None:
    """The positive control for the test above.

    Without this, the byte-equality test passes when the endpoint
    is simply broken. After the reveal the two worlds must be
    different: bru stands on the first board and not on the second.
    """
    sent, sent_client = _two_player_world(tmp_path / "sent", bru_sent=True)
    quiet, quiet_client = _two_player_world(tmp_path / "quiet",
                                            bru_sent=False)
    for fixture in (sent, quiet):
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, "alice"),
            {"day": DAY, "player": "alice", "trial_id": "a" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
        close_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
        reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    with_bru = sent_client.get(f"/api/leaderboard?day={DAY}").json()
    without = quiet_client.get(f"/api/leaderboard?day={DAY}").json()
    assert {row["player"] for row in with_bru["rows"]} == {"alice", "bru"}
    assert {row["player"] for row in without["rows"]} == {"alice"}


_SEEDS = ("1" * 32, "2" * 32, "3" * 32, "4" * 32)


def _length_walk(fixture, seed: str, tmp_path: Path,
                 index: int) -> tuple[dict[str, int], str]:
    """One world at one pick seed: the length of each answer."""
    config = dataclasses.replace(
        fixture["service_config"],
        store_root=str(tmp_path / f"store-{index}"))
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed=seed, secret="b" * 64, trial_code="AAAAAA")
    record = store.read_day_record(Path(config.store_root), DAY)
    store.write_once_json(
        store.submission_path(Path(config.store_root), DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    client = TestClient(create_app(config))
    paths = ("/", "/api/day", "/api/reveal",
             f"/api/reveal?day={DAY}", f"/api/leaderboard?day={DAY}",
             f"/api/submission?day={DAY}", "/api/history", "/api/me",
             "/api/practice", "/api/leaderboard/skill",
             "/api/avatar/ade",
             f"/image/{fixture['image_ids'][0]}",
             "/join/not-a-token", f"/join/ade.{'s' * 43}")
    return ({path: len(client.get(path).content) for path in paths},
            record.target_id)


def test_no_answer_length_follows_the_target(tmp_path: Path) -> None:
    """Architecture section 22, the test nobody wrote before.

    Four worlds equal in each fact but the day's pick seed, thus
    four different targets. The length of each answer must be one
    value across the four, while the day is open and again after
    the close, which is where the score exists on disk.

    One fixture pool serves the four worlds, each with its own
    store root. The pool, the scoring configuration, and the warm
    tables are read-only and shared, thus the cost is one pool
    build and not four.
    """
    fixture = build_service_fixture(tmp_path)
    walks, targets = [], set()
    for index, seed in enumerate(_SEEDS):
        lengths, target = _length_walk(fixture, seed, tmp_path, index)
        walks.append(lengths)
        targets.add(target)
    # The guard against a test that passes with nothing to compare.
    assert len(targets) >= 2, "the seeds must give different targets"
    for path in walks[0]:
        sizes = {walk[path] for walk in walks}
        assert len(sizes) == 1, f"{path} answered {sorted(sizes)}"


def test_no_answer_length_follows_the_target_after_the_close(
        tmp_path: Path) -> None:
    """The condition where the score is on disk and must not leak."""
    fixture = build_service_fixture(tmp_path)
    walks, targets = [], set()
    for index, seed in enumerate(_SEEDS[:3]):
        config = dataclasses.replace(
            fixture["service_config"],
            store_root=str(tmp_path / f"closed-{index}"))
        open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
                 pick_seed=seed, secret="b" * 64, trial_code="AAAAAA")
        store.write_once_json(
            store.submission_path(Path(config.store_root), DAY, "ade"),
            {"day": DAY, "player": "ade", "trial_id": "f" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
        targets.add(store.read_day_record(
            Path(config.store_root), DAY).target_id)
        close_day(config, clock=lambda: FIXED_CLOCK)
        client = TestClient(create_app(config))
        walks.append({path: len(client.get(path).content)
                      for path in ("/api/day", "/api/reveal",
                                   f"/api/leaderboard?day={DAY}",
                                   f"/api/submission?day={DAY}",
                                   "/api/history", "/api/me",
                                   "/api/leaderboard/skill")})
    assert len(targets) >= 2
    for path in walks[0]:
        sizes = {walk[path] for walk in walks}
        assert len(sizes) == 1, f"{path} answered {sorted(sizes)}"


def test_the_refusal_says_nothing_about_who_is_stored(
        tmp_path: Path) -> None:
    """The enumeration oracle.

    A body or a length that moves with the player name lets
    anybody walk the roster. _resolve_token compares against a
    fixed missing digest before it branches, thus an unknown name
    costs the same single file read and the same fixed-width
    compare as an incorrect secret.
    """
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="alice", display_name="Alice",
                        clock=lambda: FIXED_CLOCK, secret=ALICE)
    client = TestClient(create_app(config, operator_token=TOKEN))
    answers = [client.get(f"/join/{token}", follow_redirects=False)
               for token in (f"alice.{'9' * 43}", f"zzzz.{'9' * 43}",
                             f"bru.{ALICE}", "not-a-token")]
    assert len({answer.content for answer in answers}) == 1
    assert len({len(answer.content) for answer in answers}) == 1
    assert {answer.status_code for answer in answers} == {401}
