"""The operator's player commands (spec M1 section 4, spec BR1
section 4, spec A2 section 10).

Revoke a player, put one back, give a recovery code, claim the names
of the stored players, show the roster, show and end a player's
sessions, and prune the expired sign-in records. Spec MD1 adds the
moderation of a description and an avatar, and the deletion of an
account with a preview and a typed confirmation. The invite is gone
(spec A2 ruling 2): a person makes an account at the sign-up screen,
and this module mints nothing.

This module composes the account moves and the store. It reads no
environment and holds no HTTP shape - the console paths use the same
functions.
"""

import argparse
import datetime
import sys
from collections.abc import Callable
from pathlib import Path

from service import access, auth, names, signin, store
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)


def default_clock() -> str:
    """The current UTC time, in the store's timestamp shape."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def make_player(service_config: ServiceConfig, *, player: str,
                display_name: str | None = None,
                clock: Callable[[], str] = default_clock,
                ) -> store.PlayerRecord:
    """Store one new player record with no credential.

    The dev door and the tests make players with this. Such a player
    has no password and no invite: the door gives it a session, and a
    session can set the first password (spec A2 section 8). The label
    is the name when the caller gives none.

    Raises StoreError for an illegal name, an illegal label, or a
    name that is stored.
    """
    root = Path(service_config.store_root)
    label = player if display_name is None else display_name
    store.check_player_name(player, "player")
    store.check_display_name(label, "display_name")
    record = store.PlayerRecord(
        player=player, display_name=label, token_hash=None,
        created_at=clock(), status="active")
    store.ensure_store(root)
    store.write_player_record(root, record)
    return record


def revoke_player(service_config: ServiceConfig, *,
                  player: str) -> store.PlayerRecord:
    """Stop one player's access.

    The status alone stops each session at its next read, and it
    refuses sign-in and recovery. The session files go too, thus the
    devices of before stay signed out after the player is put back.
    """
    root = Path(service_config.store_root)
    record = store.set_player_status(root, player, expect_status="active",
                                     new_status="revoked")
    store.delete_player_sessions(root, player)
    # A public snapshot shows this player with no username (spec R1
    # section 8). The identifier is made here, one time.
    store.ensure_identifier(root, player, default_clock())
    return record


def operator_code(service_config: ServiceConfig, *, player: str,
                  instant: datetime.datetime) -> tuple[str, str]:
    """The operator's recovery code for one player, and the time from
    which it works (spec A2 section 6.1).

    Raises StoreError for a name with no record and for a revoked
    player: a revoked account gets no recovery, thus a code for it
    opens nothing.
    """
    root = Path(service_config.store_root)
    record = store.read_player_record(root, player)
    if record.status != "active":
        raise store.StoreError(
            f"player {player!r} is {record.status} - a recovery code is "
            "for an active player")
    return signin.issue_operator_code(root, player=player, instant=instant)


def restore_player(service_config: ServiceConfig, *, player: str,
                   instant: datetime.datetime) -> tuple[store.PlayerRecord,
                                                        str, str]:
    """Put a revoked player back, with an operator's recovery code.

    The status moves first and the code follows, thus the answer
    always holds a code that the player can use after its hold. The
    password of before the revoke stays as it was.

    A deleted account cannot come back (spec MD1 section 4.4): its
    record, account, and credentials are gone.
    """
    root = Path(service_config.store_root)
    if store.read_deletion_or_none(root, player) is not None:
        raise store.StoreError(
            f"the account {player!r} is deleted and cannot be restored")
    record = store.set_player_status(root, player, expect_status="revoked",
                                     new_status="active")
    code, usable_at = signin.issue_operator_code(root, player=player,
                                                 instant=instant)
    return record, code, usable_at


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


def _active_record(root: Path, player: str) -> store.PlayerRecord:
    """The stored record of a name, or StoreError for a name with none."""
    record = store.read_player_or_none(root, player)
    if record is None:
        raise store.StoreError(f"no stored player {player!r}")
    return record


def set_description(service_config: ServiceConfig, *, player: str,
                    text: str) -> store.AccountRecord:
    """The operator's edit of a description (spec MD1 section 3).

    The same checks as the player's own edit. The sessions and the
    status do not change. An empty text clears it.
    """
    root = Path(service_config.store_root)
    _active_record(root, player)
    return store.set_account_description(root, player, text,
                                         timestamp=default_clock())


def set_avatar(service_config: ServiceConfig, *, player: str,
               data: bytes) -> store.AccountRecord:
    """The operator's new avatar for a player: the caps of spec A1."""
    root = Path(service_config.store_root)
    _active_record(root, player)
    return store.set_account_avatar(root, player, data,
                                    timestamp=default_clock())


def clear_avatar(service_config: ServiceConfig, *,
                 player: str) -> store.AccountRecord:
    """The operator's removal of an avatar. Legal with no picture too."""
    root = Path(service_config.store_root)
    _active_record(root, player)
    return store.clear_account_avatar(root, player,
                                      timestamp=default_clock())


def deletion_preview(service_config: ServiceConfig, *,
                     player: str) -> dict:
    """What a deletion removes and what it keeps (spec MD1 section 4.4).

    Step one of the operator's deletion. It reads and changes nothing.
    """
    root = Path(service_config.store_root)
    record = _active_record(root, player)
    days = [day for day in store.list_days(root)
            if store.submission_path(root, day, player).is_file()]
    return {
        "player": player,
        "status": record.status,
        "days_played": len(days),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "sessions": len(store.list_sessions(root, player)),
        "has_password": signin.has_password(root, player),
        "identifier": store.read_identifier_or_none(root, player),
        "removes": ["the player record", "the account and the avatar",
                    "the password and each recovery code",
                    "each session and each device code"],
        "keeps": ["each send and trial result, with an anonymous name",
                  "the consent records",
                  "the name, which no one can register again",
                  "each public snapshot published before the deletion, "
                  "with the username in it"],
    }


def delete_player(service_config: ServiceConfig, *, player: str,
                  confirm: str | None,
                  deleted_by: str = "operator") -> store.DeletionRecord:
    """Delete an account (spec MD1 section 4).

    The typed copy of the name must equal the name: the operator's
    step two, and the player's typed username. A different value or
    none refuses and deletes nothing.
    """
    root = Path(service_config.store_root)
    if confirm != player:
        raise store.StoreError(
            f"the confirmation does not equal the name {player!r} - nothing "
            "is deleted")
    return store.delete_account(root, player,
                                folded=names.folded_name(player),
                                deleted_by=deleted_by,
                                deleted_at=default_clock())


def player_lines(service_config: ServiceConfig) -> list[str]:
    """One line for each stored player. No secret and no digest."""
    root = Path(service_config.store_root)
    lines = []
    for name in store.list_players(root):
        record = store.read_player_record(root, name)
        lines.append(f"{record.player}  {record.status}  "
                     f"{record.display_name}")
    return lines


def _print_code(player: str, code: str, usable_at: str) -> None:
    """Print the operator's code one time, with the caution that says
    so."""
    print(f"player {player}")
    print(f"recovery code {auth.display_recovery_code(code)}")
    print(f"it works from {usable_at}")
    print("this is the one time the code prints - give it to the "
          "player, then forget it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.players")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    revoke_parser = commands.add_parser("revoke")
    revoke_parser.add_argument("player")
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("player")
    code_parser = commands.add_parser("recovery-code")
    code_parser.add_argument("player")
    commands.add_parser("claim-names")
    commands.add_parser("list")
    sessions_parser = commands.add_parser("sessions")
    sessions_parser.add_argument("player")
    signout_parser = commands.add_parser("signout")
    signout_parser.add_argument("player")
    commands.add_parser("prune")
    describe_parser = commands.add_parser("set-description")
    describe_parser.add_argument("--player", required=True)
    describe_parser.add_argument("--text", required=True)
    clear_parser = commands.add_parser("clear-description")
    clear_parser.add_argument("--player", required=True)
    avatar_parser = commands.add_parser("set-avatar")
    avatar_parser.add_argument("--player", required=True)
    avatar_parser.add_argument("--file", required=True)
    no_avatar_parser = commands.add_parser("clear-avatar")
    no_avatar_parser.add_argument("--player", required=True)
    delete_parser = commands.add_parser(
        "delete", help="preview a deletion, or delete with --confirm NAME")
    delete_parser.add_argument("--player", required=True)
    delete_parser.add_argument("--confirm", default=None,
                               help="the name again, typed: step two")
    arguments = parser.parse_args(argv)
    instant = datetime.datetime.now(datetime.UTC)

    try:
        service_config = load_service_config(Path(arguments.service_config))
        if arguments.command == "revoke":
            record = revoke_player(service_config, player=arguments.player)
            print(f"player {record.player} {record.status}")
        elif arguments.command == "restore":
            record, code, usable_at = restore_player(
                service_config, player=arguments.player, instant=instant)
            print(f"player {record.player} {record.status}")
            _print_code(record.player, code, usable_at)
        elif arguments.command == "recovery-code":
            code, usable_at = operator_code(
                service_config, player=arguments.player, instant=instant)
            _print_code(arguments.player, code, usable_at)
        elif arguments.command == "claim-names":
            claimed = signin.claim_stored_names(
                Path(service_config.store_root), instant)
            print(f"claimed {len(claimed)} name(s): "
                  f"{', '.join(claimed) or 'none - each name has its claim'}")
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
        elif arguments.command in ("set-description", "clear-description"):
            text = arguments.text if arguments.command == "set-description" \
                else ""
            set_description(service_config, player=arguments.player,
                            text=text)
            print(f"player {arguments.player}: description "
                  f"{'set' if text else 'cleared'}")
        elif arguments.command == "set-avatar":
            set_avatar(service_config, player=arguments.player,
                       data=Path(arguments.file).read_bytes())
            print(f"player {arguments.player}: avatar set")
        elif arguments.command == "clear-avatar":
            clear_avatar(service_config, player=arguments.player)
            print(f"player {arguments.player}: avatar removed")
        elif arguments.command == "delete" and arguments.confirm is None:
            preview = deletion_preview(service_config,
                                       player=arguments.player)
            print(f"preview: deleting {preview['player']} removes "
                  f"{'; '.join(preview['removes'])}")
            print(f"it keeps {'; '.join(preview['keeps'])}")
            print(f"days played {preview['days_played']} (one send "
                  f"each), sessions {preview['sessions']}")
            print("the earlier results will show as "
                  f"{preview['identifier'] or 'a new anonymous identifier'}")
            print("nothing changed. To delete, run again with "
                  f"--confirm {preview['player']}")
        elif arguments.command == "delete":
            deleted = delete_player(service_config, player=arguments.player,
                                    confirm=arguments.confirm)
            print(f"player {deleted.player} deleted - the earlier results "
                  f"show as {deleted.identifier}")
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
