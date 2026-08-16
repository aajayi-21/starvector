"""The operator's player commands (spec M1 section 4).

Mint an invite, turn a token, revoke a player, put one back, and
show the roster. The mint answers the invite one time: the store
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

from service import auth, store
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

    The earlier token stops at the next read, and so does each
    cookie that holds it.
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
    return store.set_player_status(root, player, expect_status="active",
                                   new_status="revoked")


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
    arguments = parser.parse_args(argv)

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
    except (ServiceConfigError, store.StoreError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
