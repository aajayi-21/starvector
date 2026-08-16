"""Integration: the operator plane (spec M1 section 4, item B4).

The bearer on the lifecycle commands and the console, the refusal
that says nothing, the start-time refusal, and the player commands.

The refusal rule these tests pin: the answer to an operator check
that does not agree is the answer that path gives when the
operator plane is not there at all. The dev surfaces have such a
condition - the constant 404 they give with no --dev flag - thus a
bearer that does not agree reproduces it, and no outsider learns
if a deployment runs the flag. The lifecycle commands have no such
condition, thus they answer 401.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture

from service import auth, players, store
from service.config import ServiceConfigError
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"
TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

_DEV_PATHS = ("/dev", "/ui/dev.js", "/api/dev", "/api/dev/days",
              "/api/dev/submission", "/api/dev/rankings", "/history")
_LIFECYCLE = ("/api/day/open", "/api/day/close", "/api/day/reveal")


def _world(tmp_path, *, dev_mode=False, minted=True):
    fixture = build_service_fixture(tmp_path)
    if minted:
        players.mint_player(fixture["service_config"], player="ade",
                            display_name="Ade",
                            clock=lambda: FIXED_CLOCK,
                            secret="1" * 43)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    app = create_app(fixture["service_config"], dev_mode=dev_mode,
                     operator_token=TOKEN if minted else None)
    return fixture, TestClient(app)


def test_the_lifecycle_commands_want_the_bearer(tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    bodies, statuses = set(), set()
    for path in _LIFECYCLE:
        for headers in ({}, {"Authorization": "Bearer nope"},
                        {"Authorization": TOKEN}):
            for _ in range(2):
                answer = client.post(path, headers=headers)
                bodies.add(answer.content)
                statuses.add(answer.status_code)
    assert bodies == {b'{"detail":"unauthorized"}'}
    assert statuses == {401}


def test_the_bearer_opens_the_lifecycle_commands(tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    answer = client.post("/api/day/close", headers=HEADERS)
    assert answer.status_code == 200


def test_a_bearer_of_a_different_length_is_refused_the_same(
        tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    short = client.post("/api/day/close",
                        headers={"Authorization": "Bearer x"})
    long = client.post("/api/day/close",
                       headers={"Authorization": "Bearer " + "x" * 400})
    # Sent as bytes: a client refuses a header str above ASCII, and
    # the server decodes the bytes to a str that compare_digest
    # raises on. constant_time_equal digests first, thus this is a
    # refusal and not a 500.
    odd = client.post("/api/day/close",
                      headers={"Authorization":
                               "Bearer naïve".encode("utf-8")})
    assert short.content == long.content == odd.content
    assert {short.status_code, long.status_code, odd.status_code} == {401}


def test_the_dev_surfaces_answer_the_not_found_body_without_the_bearer(
        tmp_path) -> None:
    """The refusal rule: a refused bearer reads as no --dev flag.

    A 401 here can say 'this deployment runs the dev flag', which
    is the one fact the tunnel and the proxy refusal spend two
    layers hiding.
    """
    _fixture, dev_client = _world(tmp_path, dev_mode=True)
    _off_fixture, off_client = _world(tmp_path / "off", dev_mode=False)
    for path in _DEV_PATHS:
        refused = dev_client.get(path)
        absent = off_client.get(path)
        assert refused.status_code == absent.status_code == 404
        assert refused.content == absent.content


def test_the_bearer_opens_the_console_reads(tmp_path) -> None:
    _fixture, client = _world(tmp_path, dev_mode=True)
    answer = client.get("/api/dev/days", headers=HEADERS)
    assert answer.status_code == 200
    assert answer.json()["days"][0]["day"] == DAY


def test_the_image_surface_falls_back_to_the_gate_without_the_bearer(
        tmp_path) -> None:
    """The one path that is not all-or-nothing.

    Its missing condition is the R3 gate and not a 404, thus a
    caller with no bearer gets the public behavior: revealed
    targets alone.
    """
    fixture, client = _world(tmp_path, dev_mode=True)
    image_id = fixture["image_ids"][0]
    assert client.get(f"/image/{image_id}").status_code == 404
    assert client.get(f"/image/{image_id}",
                      headers=HEADERS).status_code == 200


def test_the_server_refuses_to_start_with_players_and_no_token(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    players.mint_player(fixture["service_config"], player="ade",
                        display_name="Ade", clock=lambda: FIXED_CLOCK,
                        secret="1" * 43)
    with pytest.raises(ServiceConfigError,
                       match="STARVECTOR_OPERATOR_TOKEN"):
        create_app(fixture["service_config"])
    assert create_app(fixture["service_config"],
                      operator_token=TOKEN) is not None


def test_the_fallback_world_wants_no_bearer(tmp_path) -> None:
    """Ruling 7: with no record stored the runbook wants no edit."""
    _fixture, client = _world(tmp_path, minted=False)
    assert client.post("/api/day/close").status_code == 200


def test_main_prints_the_refusal_and_returns_one(tmp_path, capsys) -> None:
    from service import server

    fixture = build_service_fixture(tmp_path)
    players.mint_player(fixture["service_config"], player="ade",
                        display_name="Ade", clock=lambda: FIXED_CLOCK,
                        secret="1" * 43)
    config_path = tmp_path / "service.json"
    config_path.write_text(_config_json(fixture))
    code = server.main(["--service-config", str(config_path)])
    assert code == 1
    assert "refused:" in capsys.readouterr().err


def _config_json(fixture) -> str:
    import json

    config = fixture["service_config"]
    return json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port})


def test_the_player_commands_mint_list_turn_and_revoke(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    root = Path(config.store_root)

    record, token = players.mint_player(config, player="ade",
                                        display_name="Ade",
                                        clock=lambda: FIXED_CLOCK,
                                        secret="1" * 43)
    assert token == f"ade.{'1' * 43}"
    assert record.status == "active"
    assert players.player_lines(config) == ["ade  active  Ade"]

    first_digest = store.read_player_record(root, "ade").token_hash
    _turned, new_token = players.rotate_player(config, player="ade",
                                               secret="2" * 43)
    assert new_token == f"ade.{'2' * 43}"
    assert store.read_player_record(root, "ade").token_hash != first_digest

    revoked = players.revoke_player(config, player="ade")
    assert revoked.status == "revoked"
    # The digest moved too, thus a move back cannot revive it.
    assert not auth.secret_matches(
        "2" * 43, store.read_player_record(root, "ade").token_hash)

    _back, third = players.restore_player(config, player="ade")
    assert store.read_player_record(root, "ade").status == "active"
    assert auth.secret_matches(third.split(".", 1)[1],
                               store.read_player_record(
                                   root, "ade").token_hash)


def test_the_player_listing_prints_no_secret(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    _record, token = players.mint_player(config, player="ade",
                                         display_name="Ade",
                                         clock=lambda: FIXED_CLOCK,
                                         secret="1" * 43)
    secret = token.split(".", 1)[1]
    joined = "\n".join(players.player_lines(config))
    assert secret not in joined
    assert store.read_player_record(
        Path(config.store_root), "ade").token_hash not in joined


def test_the_player_cli_refuses_an_illegal_name(tmp_path, capsys) -> None:
    fixture = build_service_fixture(tmp_path)
    config_path = tmp_path / "service.json"
    config_path.write_text(_config_json(fixture))
    code = players.main(["--service-config", str(config_path),
                         "mint", "A Player"])
    assert code == 1
    assert "refused:" in capsys.readouterr().err


def test_the_player_cli_mints_and_prints_the_invite_one_time(
        tmp_path, capsys) -> None:
    fixture = build_service_fixture(tmp_path)
    config_path = tmp_path / "service.json"
    config_path.write_text(_config_json(fixture))
    code = players.main(["--service-config", str(config_path),
                         "--origin", "https://game.example.com",
                         "mint", "ade", "--display-name", "Ade"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "https://game.example.com/join/ade." in printed
    assert "one time" in printed


def test_the_mint_refuses_a_name_that_is_stored(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK, secret="1" * 43)
    digest = store.read_player_record(Path(config.store_root),
                                      "ade").token_hash
    with pytest.raises(store.StoreError, match="one-write"):
        players.mint_player(config, player="ade", display_name="Other",
                            clock=lambda: FIXED_CLOCK, secret="2" * 43)
    assert store.read_player_record(Path(config.store_root),
                                    "ade").token_hash == digest
