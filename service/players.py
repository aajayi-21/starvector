"""The operator's player commands (spec M1 section 4, spec BR1
section 4).

Mint an invite, turn a token, revoke a player, put one back, show
the roster, show and end a player's sessions, and prune the expired
sign-in records. The mint answers the invite one time: the store
keeps the digest alone, thus a token nobody can find wants a turn
and not a lookup.

This module composes the token module and the store. It reads no
environment and holds no HTTP shape - the endpoint of section 8
uses the same functions.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from service import access, auth, store
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)


def default_clock() -> str:
    """The current UTC time, in the store's timestamp shape."""
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat()


def mint_player(service_config: ServiceConfig, *, player: str,
                display_name: str,
                clock: Callable[[], str] = default_clock,
                secret: str | None = None) -> tuple[store.PlayerRecord, str]:
    """Store one new player record and answer its invite token.

    The token comes back one time. The store keeps the digest, thus
    no read that follows can collect it.

    secret arrives as an argument for the tests that compare two
    worlds as bytes, in the manner of open_day's pick_seed.

    Raises StoreError for an illegal name, an illegal label, or a
    name that is stored.
    """
    root = Path(service_config.store_root)
    store.check_player_name(player, "player")
    store.check_display_name(display_name, "display_name")
    token, digest = auth.mint_token(player, secret=secret)
    record = store.PlayerRecord(
        player=player, display_name=display_name, token_hash=digest,
        created_at=clock(), status="active")
    store.ensure_store(root)
    store.write_player_record(root, record)
    return record, token


def rotate_player(service_config: ServiceConfig, *, player: str,
                  secret: str | None = None
                  ) -> tuple[store.PlayerRecord, str]:
    """Turn one player's invite and answer the new token.

    The earlier invite stops at its next use. The player's sessions
    do not: a session is not the invite (spec BR1 section 4). To end
    them too, run signout_player.
    """
    root = Path(service_config.store_root)
    token, digest = auth.mint_token(player, secret=secret)
    record = store.replace_player_token(root, player,
                                        expect_status="active",
                                        new_token_hash=digest)
    return record, token


def revoke_player(service_config: ServiceConfig, *,
                  player: str) -> store.PlayerRecord:
    """Stop one player's access.

    Two guarded edits, the digest first. The turned-to secret goes
    nowhere, thus a move back to active cannot put the revoked
    invite to use. If the process stops between the two edits, the
    record holds a dead digest and an active status: the credential
    is gone, which is the safe direction.
    """
    root = Path(service_config.store_root)
    _token, digest = auth.mint_token(player)
    store.replace_player_token(root, player, expect_status="active",
                               new_token_hash=digest)
    record = store.set_player_status(root, player, expect_status="active",
                                     new_status="revoked")
    # The status alone stops each session at its next read. The files
    # go too, thus the devices of before stay signed out after the
    # player is put back.
    store.delete_player_sessions(root, player)
    return record


def restore_player(service_config: ServiceConfig, *,
                   player: str) -> tuple[store.PlayerRecord, str]:
    """Put a revoked player back, with a new invite.

    The status moves first and the mint follows, thus the answer
    always carries a token the player can use.
    """
    root = Path(service_config.store_root)
    store.set_player_status(root, player, expect_status="revoked",
                            new_status="active")
    return rotate_player(service_config, player=player)


def signout_player(service_config: ServiceConfig, *, player: str) -> int:
    """End each session of one player, and answer the count ended."""
    root = Path(service_config.store_root)
    store.read_player_record(root, player)
    return store.delete_player_sessions(root, player)


def session_lines(service_config: ServiceConfig, *, player: str,
                  instant) -> list[str]:
    """One line for each live session of one player. No secret."""
    root = Path(service_config.store_root)
    store.read_player_record(root, player)
    rows = access.session_rows(root, player, None, instant)
    return [f"{row['id'][:12]}  {row['created_at']}  {row['label']}"
            for row in rows] or ["no live sessions"]


def player_lines(service_config: ServiceConfig) -> list[str]:
    """One line for each stored player. No secret and no digest."""
    root = Path(service_config.store_root)
    lines = []
    for name in store.list_players(root):
        record = store.read_player_record(root, name)
        lines.append(f"{record.player}  {record.status}  "
                     f"{record.display_name}")
    return lines


def _print_invite(record: store.PlayerRecord, token: str,
                  origin: str | None) -> None:
    """Print the invite one time, with the caution that says so."""
    where = "/join/" + token if origin is None else f"{origin}/join/{token}"
    print(f"player {record.player}  {record.display_name}")
    print(f"invite {where}")
    print("this is the one time the invite prints - send it, then "
          "forget it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.players")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    parser.add_argument("--origin", default=None,
                        help="the site address to put before /join")
    commands = parser.add_subparsers(dest="command", required=True)
    mint_parser = commands.add_parser("mint")
    mint_parser.add_argument("player")
    mint_parser.add_argument("--display-name", default=None)
    rotate_parser = commands.add_parser("rotate")
    rotate_parser.add_argument("player")
    revoke_parser = commands.add_parser("revoke")
    revoke_parser.add_argument("player")
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("player")
    commands.add_parser("list")
    sessions_parser = commands.add_parser("sessions")
    sessions_parser.add_argument("player")
    signout_parser = commands.add_parser("signout")
    signout_parser.add_argument("player")
    commands.add_parser("prune")
    arguments = parser.parse_args(argv)
    import datetime

    instant = datetime.datetime.now(datetime.UTC)

    try:
        service_config = load_service_config(Path(arguments.service_config))
        if arguments.command == "mint":
            # No silent truncation: a long name wants the label
            # said out loud (CLAUDE.md section 3).
            display_name = arguments.display_name or arguments.player
            record, token = mint_player(service_config,
                                        player=arguments.player,
                                        display_name=display_name)
            _print_invite(record, token, arguments.origin)
        elif arguments.command == "rotate":
            record, token = rotate_player(service_config,
                                          player=arguments.player)
            _print_invite(record, token, arguments.origin)
        elif arguments.command == "revoke":
            record = revoke_player(service_config, player=arguments.player)
            print(f"player {record.player} {record.status}")
        elif arguments.command == "restore":
            record, token = restore_player(service_config,
                                           player=arguments.player)
            _print_invite(record, token, arguments.origin)
        elif arguments.command == "list":
            for line in player_lines(service_config):
                print(line)
        elif arguments.command == "sessions":
            for line in session_lines(service_config,
                                      player=arguments.player,
                                      instant=instant):
                print(line)
        elif arguments.command == "signout":
            count = signout_player(service_config, player=arguments.player)
            print(f"player {arguments.player} sessions ended: {count}")
        elif arguments.command == "prune":
            counts = access.prune(Path(service_config.store_root), instant)
            print(f"pruned sessions={counts['sessions']} "
                  f"device_codes={counts['device_codes']}")
    except (ServiceConfigError, store.StoreError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
