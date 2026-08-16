"""Integration: the four wire additions of spec M1 section 8.

The multi-player daily board, the skill board and its gate, the
mint, and the display name that joins at read time.
"""

import json
from pathlib import Path

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import auth, players, rollup, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

from fastapi.testclient import TestClient

DAY = "2026-08-12"
TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CAST = (("ade", "Ade", "1" * 43), ("bru", "Bru Lin", "2" * 43))


def _world(tmp_path, *, cast=CAST, played=CAST):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    tokens = {}
    for name, label, secret in cast:
        _record, token = players.mint_player(
            config, player=name, display_name=label,
            clock=lambda: FIXED_CLOCK, secret=secret)
        tokens[name] = token
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
        client.cookies.set(auth.SESSION_COOKIE, token)
    return client


def test_the_daily_board_serves_each_player(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    body = _as(client, tokens["ade"]).get(f"/api/leaderboard?day={DAY}")
    assert body.status_code == 200
    rows = body.json()["rows"]
    assert len(rows) == 2
    assert {row["player"] for row in rows} == {"ade", "bru"}
    # The board label attaches at read time.
    labels = {row["player"]: row["display_name"] for row in rows}
    assert labels == {"ade": "Ade", "bru": "Bru Lin"}
    # Sorted by the trial score down.
    scores = [row["p"] for row in rows]
    assert scores == sorted(scores, reverse=True)
    for row in rows:
        assert set(row) == {"player", "display_name", "p", "target_rank",
                            "decoy_count", "streak"}


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


def test_an_edited_label_wants_no_new_assembly(tmp_path) -> None:
    """The artifact holds the store key, thus the label attaches."""
    fixture, client, tokens = _world(tmp_path)
    root = Path(fixture["service_config"].store_root)
    before = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").json()
    assert before["rows"][0]["display_name"] in ("Ade", "Bru Lin")
    # The board file does not move. The record does.
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(root, DAY)
    board_path = rollup.leaderboard_path(
        data_root, DAY, record.scoring_config_hash)
    stamp = board_path.read_bytes()
    moved = store.read_player_record(root, "bru")
    from dataclasses import replace

    from pool.artifacts import write_json_pretty
    write_json_pretty(store.player_record_path(root, "bru"),
                      {"player": moved.player, "display_name": "Renamed",
                       "token_hash": moved.token_hash,
                       "created_at": moved.created_at,
                       "status": moved.status})
    after = _as(client, tokens["ade"]).get(
        f"/api/leaderboard?day={DAY}").json()
    labels = {row["player"]: row["display_name"] for row in after["rows"]}
    assert labels["bru"] == "Renamed"
    assert board_path.read_bytes() == stamp


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
    assert body["display_name"] == "Bru Lin"


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


def test_the_skill_board_answers_the_constant_before_any_reveal(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
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
        players.mint_player(config, player=name, display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
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


def test_the_mint_endpoint_answers_the_invite_one_time(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    client = TestClient(create_app(config, operator_token=TOKEN))
    answer = client.post("/api/players", headers=HEADERS,
                         json={"player": "cyd", "display_name": "Cyd"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["player"] == "cyd"
    assert body["display_name"] == "Cyd"
    assert body["join_path"] == f"/join/{body['token']}"
    # The token signs the new player in. The store keeps its
    # digest alone.
    joined = client.get(body["join_path"], follow_redirects=False)
    assert joined.status_code == 302
    secret = body["token"].split(".", 1)[1]
    for path in Path(config.store_root).rglob("*.json"):
        assert secret not in path.read_text()


def test_the_mint_endpoint_wants_the_bearer_in_each_world(
        tmp_path) -> None:
    """The switch that turns access control on is not open.

    _operator_ok is open in the world with no player record. The
    mint uses the bearer alone, thus nobody can make the first
    player and close the door around themselves.
    """
    empty = build_service_fixture(tmp_path / "empty")
    client = TestClient(create_app(empty["service_config"]))
    bodies = {client.post("/api/players",
                          json={"player": "cyd"}).content
              for _ in range(2)}
    assert bodies == {b'{"detail":"unauthorized"}'}

    fixture = build_service_fixture(tmp_path / "held")
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    held = TestClient(create_app(config, operator_token=TOKEN))
    assert held.post("/api/players",
                     json={"player": "cyd"}).status_code == 401
    assert held.post("/api/players", headers={"Authorization": "Bearer x"},
                     json={"player": "cyd"}).status_code == 401


def test_the_mint_endpoint_refuses_a_bad_shape(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    client = TestClient(create_app(config, operator_token=TOKEN))
    for body, cause in (({"player": "A Player"}, "bad-player"),
                        ({"player": "cyd", "display_name": " x"},
                         "bad-display-name"),
                        ({"player": "ade"}, "already-minted")):
        answer = client.post("/api/players", headers=HEADERS, json=body)
        assert answer.json()["cause"] == cause
    assert client.post("/api/players", headers=HEADERS,
                       content=b"[]").json()["cause"] == "bad-shape"


def test_the_mint_endpoint_does_not_move_a_stored_digest(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    root = Path(config.store_root)
    digest = store.read_player_record(root, "ade").token_hash
    client = TestClient(create_app(config, operator_token=TOKEN))
    assert client.post("/api/players", headers=HEADERS,
                       json={"player": "ade"}).status_code == 409
    assert store.read_player_record(root, "ade").token_hash == digest


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
    client.get(f"/join/{tokens['bru']}", follow_redirects=False)
    assert snapshot() == before
