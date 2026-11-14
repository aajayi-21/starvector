"""Integration: the four wire additions of spec M1 section 8.

The multi-player daily board, the skill board and its gate, the
mint, and the display name that joins at read time.
"""

import json
from pathlib import Path

from svc_fixture import mint_player
from svc_fixture import (FIXED_CLOCK, build_service_fixture,
                         mixed_wire_record, pinned_session_value,
                         plant_session)

from core import aggregate
from service import auth, players, rollup, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _no_daily_board_floor(monkeypatch):
    """The players of these worlds have no earlier played days, and the
    tests are about the rows of a board. The floor of spec A2 section
    9.5 has its own tests (test_daily_board_floor.py)."""
    from service import rollup as rollup_module

    monkeypatch.setattr(rollup_module, "DAILY_BOARD_FLOOR_DAYS", 0)

DAY = "2026-08-12"
TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CAST = (("ade", "Ade", "1" * 43), ("bru", "Bru Lin", "2" * 43))


def _world(tmp_path, *, cast=CAST, played=CAST):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    tokens = {}
    for name, label, secret in cast:
        _record, token = mint_player(
            config, player=name, display_name=label,
            clock=lambda: FIXED_CLOCK, secret=secret)
        tokens[name] = token
        plant_session(fixture["store"], token)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    for index, (name, _label, _secret) in enumerate(played):
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, name),
            {"day": DAY, "player": name, "trial_id": f"{index}" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    client = TestClient(
        create_app(config, operator_token=TOKEN if cast else None))
    return fixture, client, tokens


def _as(client: TestClient, token: str | None) -> TestClient:
    client.cookies.clear()
    if token is not None:
        client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(token))
    return client


def test_the_daily_board_serves_each_player(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    body = _as(client, tokens["ade"]).get(f"/api/leaderboard?day={DAY}")
    assert body.status_code == 200
    rows = body.json()["rows"]
    assert len(rows) == 2
    assert {row["player"] for row in rows} == {"ade", "bru"}
    # The board label is the username (spec A2 ruling 3).
    labels = {row["player"]: row["display_name"] for row in rows}
    assert labels == {"ade": "ade", "bru": "bru"}
    # Sorted by the trial score down.
    scores = [row["p"] for row in rows]
    assert scores == sorted(scores, reverse=True)
    for row in rows:
        assert set(row) == {"player", "display_name", "avatar_hash", "p",
                            "target_rank", "decoy_count", "streak", "public"}


def _stored_target_ranks(fixture) -> dict[str, int]:
    """The rank of the target in the set of images, for each player."""
    root = Path(fixture["service_config"].store_root)
    ranks = {}
    for name, _label, _secret in CAST:
        row = store.read_json_or_none(
            store.trial_row_path(root, DAY, name))
        ranks[name] = row["target_rank"]
    return ranks


def test_the_board_says_the_target_rank_and_not_the_position(
        tmp_path) -> None:
    """The two ranks count different things (spec M1 B9).

    target_rank is the position of the target in the set of images
    and it is what the reveal card prints with the decoy count.
    The board position is the position in the set of players. A
    board that carries one alone makes the reader answer with the
    other.
    """
    fixture, client, tokens = _world(tmp_path)
    wanted = _stored_target_ranks(fixture)
    rows = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").json()["rows"]
    served = {row["player"]: row["target_rank"] for row in rows}
    assert served == wanted
    # The guard against a test that cannot tell the two apart.
    positions = {row["player"]: index + 1
                 for index, row in enumerate(rows)}
    assert any(served[name] != positions[name] for name in served)


def test_a_board_from_before_the_target_rank_is_rebuilt(tmp_path) -> None:
    """A stale artifact is met and not trusted.

    The trial rows are permanent and hold the number, thus the
    reader assembles the rows again. To answer the board position
    with the name of the target rank is the fault this stops.
    """
    fixture, client, tokens = _world(tmp_path)
    wanted = _stored_target_ranks(fixture)
    root = Path(fixture["service_config"].store_root)
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(root, DAY)
    board_path = rollup.leaderboard_path(
        data_root, DAY, record.scoring_config_hash)
    stale = json.loads(board_path.read_text())
    for row in stale["rows"]:
        del row["target_rank"]
    board_path.write_text(json.dumps(stale))
    rows = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").json()["rows"]
    assert {row["player"]: row["target_rank"] for row in rows} == wanted


def test_the_board_with_no_day_names_the_newest_revealed(tmp_path) -> None:
    """The leaderboard screen wants that day and cannot name it.

    The reveal reads the latest day, which is the open one for most
    of each day, and the history reads the days that one caller
    played. A newer open day must not hide the newest revealed
    board.
    """
    fixture, client, tokens = _world(tmp_path)
    named = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").content
    assert _as(client, tokens["ade"]).get(
        "/api/leaderboard").content == named
    open_day(fixture["service_config"], date="2026-08-13",
             clock=lambda: FIXED_CLOCK, pick_seed="c" * 32,
             secret="d" * 64)
    assert _as(client, tokens["ade"]).get(
        "/api/leaderboard").content == named


def test_the_board_label_is_the_username_and_not_the_record_label(
        tmp_path) -> None:
    """Ruling 3 of spec A2: each board shows the username. The display
    name of a record from before that spec shows on no board."""
    _fixture, client, tokens = _world(tmp_path)
    board = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").json()
    labels = {row["player"]: row["display_name"] for row in board["rows"]}
    assert labels == {"ade": "ade", "bru": "bru"}


def test_a_name_with_no_record_falls_back_to_its_key(tmp_path) -> None:
    """The world of ruling 7: the configured player has no record."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    client = TestClient(create_app(config))
    rows = client.get(f"/api/leaderboard?day={DAY}").json()["rows"]
    assert rows[0]["display_name"] == "ade"
    assert client.get("/api/me").json()["display_name"] == "ade"


def test_the_me_surface_carries_the_display_name(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    body = _as(client, tokens["bru"]).get("/api/me").json()
    assert body["player"] == "bru"
    # The one name of a player is the username (spec A2 ruling 3).
    assert body["display_name"] == "bru"


def test_the_skill_board_gates_itself(tmp_path) -> None:
    """One revealed day is below the trial floor for everybody."""
    _fixture, client, tokens = _world(tmp_path)
    body = _as(client, tokens["ade"]).get("/api/leaderboard/skill")
    assert body.status_code == 200
    view = body.json()
    assert view["active"] is False
    assert view["eligible_count"] == 0
    assert view["provisional"] is True
    assert view["rows"] == []
    # The gated body holds the two floors, thus a screen holds no
    # number the wire does not give it.
    assert view["eligibility_floor"] == 30
    assert view["fit_floor"] == 30


def test_the_skill_board_keeps_the_configuration_off_the_wire(
        tmp_path) -> None:
    """The artifact keys the cache. A player wants none of it."""
    _fixture, client, tokens = _world(tmp_path)
    view = _as(client, tokens["ade"]).get("/api/leaderboard/skill").json()
    for name in ("scoring_config_hash", "preparation_version_id",
                 "rank_seed"):
        assert name not in view


# Each field SkillBoardView declares without a question mark. A
# body that drops one makes a screen that trusts the type read a
# missing value, and the gated board is where that happens.
_REQUIRED = ("active", "player_count", "eligible_count",
             "degenerate_count", "eligibility_floor", "recomputed_floor",
             "fit_floor", "provisional", "rows", "baseline_band",
             "population", "variation", "discovery")


def test_each_gated_body_is_a_complete_view(tmp_path) -> None:
    """The two gated paths each answer each declared field.

    One path serves the constant, when no reveal wrote an artifact.
    The other serves an artifact that is gated on its own count.
    A screen renders the same words for the two, thus the two hold
    the same fields.
    """
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    plant_session(fixture["store"], f"ade.{'1' * 43}")
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    constant = TestClient(create_app(config, operator_token=TOKEN))
    _as(constant, f"ade.{'1' * 43}")
    bodies = [constant.get("/api/leaderboard/skill").json()]

    _played, client, tokens = _world(tmp_path / "played")
    bodies.append(
        _as(client, tokens["ade"]).get("/api/leaderboard/skill").json())

    for view in bodies:
        assert view["active"] is False
        for name in _REQUIRED:
            assert name in view, name
        # The floors travel from the module that owns them.
        assert view["eligibility_floor"] == aggregate.ELIGIBLE_TRIAL_FLOOR
        assert view["fit_floor"] == aggregate.FIT_PLAYER_FLOOR


def test_the_standing_monitors_stay_operator_only(tmp_path) -> None:
    """Ruling 5 of 2026-08-15 publishes the discovery claim alone.

    The baseline check and the stopping monitor hold no
    player-facing copy, thus they stay in the artifact where the
    operator reads them.
    """
    fixture, client, tokens = _world(tmp_path)
    root = Path(fixture["service_config"].store_root)
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(root, DAY)
    stored = json.loads(rollup.skill_board_path(
        data_root, record.scoring_config_hash).read_text())
    # The guard against a test that passes on a missing field.
    assert "baseline" in stored and "stopping_monitor" in stored
    view = _as(client, tokens["ade"]).get("/api/leaderboard/skill").json()
    assert "baseline" not in view
    assert "stopping_monitor" not in view
    assert "discovery" in view


def test_the_me_surface_holds_no_flag_that_cannot_vary(tmp_path) -> None:
    """Ruling 3 of spec M1 removed the public flag.

    Ruling 4 removed the opt-out, thus the field was correct for
    each player forever, and a value that cannot change is a claim
    that waits for a reader to trust it.
    """
    _fixture, client, tokens = _world(tmp_path)
    body = _as(client, tokens["ade"]).get("/api/me").json()
    assert set(body) == {"player", "display_name", "streak", "reminder",
                         "description", "avatar_hash", "has_password",
                         "operator_code", "notice"}
    # The pool of this world is a development pool, thus no send needs
    # the agreement (spec R1 section 3.3).
    assert body["notice"] == {"version": 1, "agreed": False,
                              "required": False}
    # A player of before spec A2 has no password and no operator's code.
    assert body["has_password"] is False
    assert body["operator_code"] is None


def test_the_skill_board_answers_the_constant_before_any_reveal(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    plant_session(fixture["store"], f"ade.{'1' * 43}")
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    client = TestClient(create_app(config, operator_token=TOKEN))
    _as(client, f"ade.{'1' * 43}")
    bodies = {client.get("/api/leaderboard/skill").content
              for _ in range(2)}
    assert len(bodies) == 1
    assert json.loads(bodies.pop())["active"] is False


def test_the_daily_board_refuses_before_the_reveal(tmp_path) -> None:
    """Growing the board to many players does not open R3."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    for name, label, secret in CAST:
        mint_player(config, player=name, display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
        plant_session(fixture["store"], f"{name}.{secret}")
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    for index, (name, _label, _secret) in enumerate(CAST):
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, name),
            {"day": DAY, "player": name, "trial_id": f"{index}" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    client = TestClient(create_app(config, operator_token=TOKEN))
    _as(client, f"ade.{'1' * 43}")
    bodies = set()
    for _ in range(2):
        answer = client.get(f"/api/leaderboard?day={DAY}")
        assert answer.status_code == 404
        bodies.add(answer.content)
    close_day(config, clock=lambda: FIXED_CLOCK)
    for _ in range(2):
        bodies.add(client.get(f"/api/leaderboard?day={DAY}").content)
    assert bodies == {b'{"detail":"not revealed"}'}


def test_the_mint_path_is_gone(tmp_path) -> None:
    """Ruling 2 of spec A2: the operator mints no player. A person
    makes an account at the sign-up path, and the POST of before
    answers as a path that is not there, with the bearer and with
    none."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    client = TestClient(create_app(config, operator_token=TOKEN))
    for headers in (HEADERS, {}):
        answer = client.post("/api/players", headers=headers,
                             json={"player": "cyd", "display_name": "Cyd"})
        assert answer.status_code in (404, 405)
    assert store.list_players(Path(config.store_root)) == ("ade",)


def test_the_new_surfaces_leave_the_store_byte_equal(tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    root = Path(fixture["service_config"].store_root)

    def snapshot() -> dict:
        return {str(path.relative_to(root)): path.read_bytes()
                for path in sorted(root.rglob("*")) if path.is_file()}

    _as(client, tokens["ade"])
    before = snapshot()
    for path in (f"/api/leaderboard?day={DAY}", "/api/leaderboard/skill",
                 "/api/me", "/api/history", f"/api/submission?day={DAY}"):
        client.get(path)
    # The invite gate writes one session deliberately (spec BR1), thus
    # it is not a read. test_player_access pins what it writes.
    assert snapshot() == before
