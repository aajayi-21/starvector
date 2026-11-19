"""The operator command line: the shell of the command `sv`.

Spec: OC1 (in docs/specs/operator-cli.md) sections 3 to 7. This module
is the imperative shell. It reads the arguments, the environment, and
the store, and it prints. The rules are in the plan module and the
output text is in the view module: each of the two is pure, and this
module holds no rule and no output text of its own that they have.

The sequence of each command: read the arguments, make one frozen
context, then go to one small handler. A handler of a command that
reads prints a view. A handler of a command that changes the store
gives its work to `_run_change`, which asks the question and writes
the two journal records of spec OC1 section 7.
"""

import argparse
import datetime
import os
import pwd
import secrets
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from service import (access, auth, console, index, players, rollover,
                     schedule, signin, store)
from service import operator_plan as plan
from service import operator_view as view
from service.config import ServiceConfig, load_service_config

TOKEN_VARIABLE = "STARVECTOR_OPERATOR_TOKEN"

# The time limit of the one `GET` that `sv status` sends to the public
# server. The spec gives no number: a server on the loopback address
# answers this path from memory, thus a short limit is sufficient.
_STATUS_TIMEOUT_SECONDS = 3.0

# Ruling D2 of spec OC1, in the words of spec S1 R3.
_OPEN_DAY_REFUSAL = (
    "the terminal shows no target and no rank of a day that is open or "
    "closing. Spec S1 R3: nothing shows score information while a day is "
    "open, and that rule names the terminal. No flag changes this.")

# The errors that a handler gives for a refusal that the operator can
# read: a rule of the plan module, a store rule, a config rule, a value
# rule of a function that the handler uses, and a refusal of the results
# index. Each one prints as one line and not as a traceback.
_REFUSALS = (ValueError, index.ResultsIndexError, sqlite3.Error)

# The errors of a journal write: a rule of the journal, and the disk.
_JOURNAL_ERRORS = (store.StoreError, plan.Refusal, OSError)


@dataclass(frozen=True, slots=True)
class Context:
    """The values that each handler reads, made one time for a command.

    command is the row of the command table. root is the store folder.
    login and login_source are the actor of the journal. base_url is
    the loopback address of the public server. The last six fields are
    the values that a test can inject.
    """

    command: plan.Command
    config: ServiceConfig
    config_path: str
    root: Path
    login: str
    login_source: str
    as_json: bool
    assume_yes: bool
    base_url: str
    call: rollover.Call
    ask: Callable[[str], str]
    now: Callable[[], datetime.datetime]
    stdin_is_tty: bool
    stdout_is_tty: bool
    new_id: Callable[[], str]


Handler = Callable[[Context, argparse.Namespace], int]


@dataclass(frozen=True, slots=True)
class Done:
    """What a change gives when it completes.

    value is the JSON output and lines is the text output. facts are
    the machine facts of the `end` record of the journal. day is the
    day of the change when only the change knows it.
    """

    value: object
    lines: Sequence[str]
    facts: Mapping[str, object] = field(default_factory=dict)
    day: str | None = None


class _Stopped(Exception):
    """A change that did not complete, with the outcome and the error
    type for the journal. The text is for the operator, and it does not
    go in the journal."""

    def __init__(self, message: str, outcome: str, error_kind: str,
                 facts: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.error_kind = error_kind
        self.facts = dict(facts or {})


# ---- the argument tree ----


def _shared_flags() -> argparse.ArgumentParser:
    """The flags of each command, for a position after the command.

    Each flag has no default here. Thus a flag that the operator gave
    before the group stays as it is when the command does not give it
    again.
    """
    shared = argparse.ArgumentParser(add_help=False, allow_abbrev=False,
                                     argument_default=argparse.SUPPRESS)
    shared.add_argument("--service-config")
    shared.add_argument("--json", action="store_true")
    shared.add_argument("--yes", action="store_true")
    shared.add_argument("--base-url")
    return shared


def _top_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="service.operator_cli", allow_abbrev=False,
        description="The operator command of the trial server.")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    parser.add_argument("--json", action="store_true",
                        help="print JSON and not text")
    parser.add_argument("--yes", action="store_true",
                        help="answer yes to the question of a command")
    parser.add_argument("--base-url", default=None,
                        help="the loopback address of the public server; "
                             "the default is http://127.0.0.1:<config port>")
    return parser


def _leaf(commands, name: str, shared: argparse.ArgumentParser,
          text: str) -> argparse.ArgumentParser:
    """One command below a group, with the shared flags."""
    return commands.add_parser(name, parents=[shared], allow_abbrev=False,
                               help=text, description=text)


def _group(groups, name: str, shared: argparse.ArgumentParser, text: str, *,
           required: bool = True):
    """One group and the holder of its commands."""
    group = groups.add_parser(name, parents=[shared], allow_abbrev=False,
                              help=text, description=text)
    return group, group.add_subparsers(dest="leaf", required=required)


def _add_day_reads(commands, shared: argparse.ArgumentParser) -> None:
    show = _leaf(commands, "show", shared,
                 "the times of one day and each of its sends")
    show.add_argument("day", nargs="?", default=None,
                      help="a stored day; the default is the latest day")
    send = _leaf(commands, "send", shared, "one stored send")
    send.add_argument("day")
    send.add_argument("player")


def _add_day_moves(commands, shared: argparse.ArgumentParser) -> None:
    _leaf(commands, "open", shared, "open the day that is due")
    for name, text in (("close", "close a day and score each send"),
                       ("reveal", "reveal a closed day")):
        move = _leaf(commands, name, shared, text)
        move.add_argument("day", nargs="?", default=None,
                          help="a stored day; the default is the latest day")


def _add_day_target(commands, shared: argparse.ArgumentParser) -> None:
    flag = "show the target of a closed day that is not revealed"
    target = _leaf(commands, "target", shared,
                   "the image and the credit of the target of a day")
    target.add_argument("day", nargs="?", default=None,
                        help="a stored day; the default is the latest day")
    target.add_argument("--show-target", action="store_true", help=flag)
    target.add_argument("--save", default=None, metavar="PATH",
                        help="write the image to a new file")
    rank = _leaf(commands, "rank", shared,
                 "score one stored send and print the fused sequence")
    rank.add_argument("day")
    rank.add_argument("player")
    rank.add_argument("--show-target", action="store_true", help=flag)
    rank.add_argument("--limit", type=int, default=None,
                      help="the first rows of the sequence, this many")
    quarantine = _leaf(commands, "quarantine", shared,
                       "skip one send that the provider refuses")
    quarantine.add_argument("day")
    quarantine.add_argument("player")
    quarantine.add_argument("--note", required=True)


def _add_modules(groups, commands_of: Mapping[str, object],
                 shared: argparse.ArgumentParser) -> None:
    """The commands of spec OC1 section 3.4. A parser of one has no
    argument and no help flag of its own: each word after the command
    goes to the module with no change."""
    for path, (module, words) in plan.MODULE_COMMANDS.items():
        text = f"as python -m {' '.join((module, *words))}"
        if len(path) == 1:
            groups.add_parser(path[0], add_help=False, allow_abbrev=False,
                              help=text)
            continue
        if path[0] not in commands_of:
            _group_parser, commands_of[path[0]] = _group(
                groups, path[0], shared, f"commands of {module}")
        commands_of[path[0]].add_parser(
            path[1], add_help=False, allow_abbrev=False, help=text)


def _add_schedule_changes(commands, shared: argparse.ArgumentParser) -> None:
    pause = _leaf(commands, "pause", shared, "stop the automatic days")
    pause.add_argument("--note", default="",
                       help="a short text that the schedule shows")
    _leaf(commands, "resume", shared, "start the automatic days again")
    _leaf(commands, "run", shared, "do the steps that are due at this time")


def _add_player_reads(commands, shared: argparse.ArgumentParser) -> None:
    _leaf(commands, "list", shared, "the roster")
    for name, text in (("show", "one account and its devices"),
                       ("history", "the days of one player")):
        _leaf(commands, name, shared, text).add_argument("player")
    avatar = _leaf(commands, "avatar", shared,
                   "write the avatar of a player to a new file")
    avatar.add_argument("player")
    avatar.add_argument("--save", required=True, metavar="PATH")


def _add_player_changes(commands, shared: argparse.ArgumentParser) -> None:
    for name, text in (
            ("recovery-code", "make the operator's recovery code"),
            ("restore", "make a revoked account active, with a code")):
        code = _leaf(commands, name, shared, text)
        code.add_argument("player")
        code.add_argument("--code-to-pipe", action="store_true",
                          help="print the code when the standard output "
                               "is not a terminal")
    for name, text in (("revoke", "revoke an account"),
                       ("avatar-clear", "remove the avatar of a player")):
        _leaf(commands, name, shared, text).add_argument("player")
    signout = _leaf(commands, "signout", shared,
                    "end each device of a player, or one")
    signout.add_argument("player")
    signout.add_argument("--session", default=None, metavar="ID",
                         help="the first characters of one session id")
    _add_describe(commands, shared)
    avatar_set = _leaf(commands, "avatar-set", shared,
                       "replace the avatar of a player")
    avatar_set.add_argument("player")
    avatar_set.add_argument("--file", required=True)
    delete = _leaf(commands, "delete", shared,
                   "show what a deletion removes, or delete with --confirm")
    delete.add_argument("player")
    delete.add_argument("--confirm", default=None, metavar="NAME",
                        help="the username again: this deletes the account")
    _leaf(commands, "prune", shared,
          "remove each expired session and device code")
    _leaf(commands, "claim-names", shared,
          "claim the name of each stored player")


def _add_describe(commands, shared: argparse.ArgumentParser) -> None:
    describe = _leaf(commands, "describe", shared,
                     "set or clear the description of a player")
    describe.add_argument("player")
    source = describe.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", default=None)
    source.add_argument("--text-file", default=None, metavar="F",
                        help="a UTF-8 file; one line end at its end does "
                             "not count")
    source.add_argument("--clear", action="store_true")


def _add_db_reads(commands, shared: argparse.ArgumentParser) -> None:
    _leaf(commands, "status", shared, "the results index and its tables")
    _leaf(commands, "verify", shared, "if the index agrees with the store")
    query = _leaf(commands, "query", shared,
                  "the answer of one read-only SELECT")
    query.add_argument("statement", nargs="?", default=None,
                       help="the statement, or - for the standard input")
    query.add_argument("--file", default=None,
                       help="a file that holds the statement")
    query.add_argument("--csv", action="store_true")
    query.add_argument("--out", default=None, metavar="PATH",
                       help="write the answer to a new file")
    trials = _leaf(commands, "trials", shared, "the revealed trial rows")
    trials.add_argument("--from", dest="from_day", default=None)
    trials.add_argument("--to", dest="to_day", default=None)
    trials.add_argument("--player", default=None)
    _leaf(commands, "build", shared, "build the results index again")


def _add_log(groups, shared: argparse.ArgumentParser) -> None:
    log = groups.add_parser("log", parents=[shared], allow_abbrev=False,
                            help="the operator journal")
    log.add_argument("--since", default=None,
                     help="an ISO 8601 date or time, UTC with no zone")
    log.add_argument("--player", default=None)
    log.add_argument("--day", default=None)
    log.add_argument("--command", dest="named_command", default=None,
                     help="the words of a command, for example "
                          "'players revoke'")
    log.add_argument("--limit", type=int, default=None,
                     help="the newest commands alone, this many")


def _parser() -> argparse.ArgumentParser:
    """The argument tree of spec OC1 section 3."""
    parser = _top_parser()
    shared = _shared_flags()
    groups = parser.add_subparsers(dest="group", required=True)
    for name, text in (("status", "the latest day, the schedule, the "
                                  "players, and the public server"),
                       ("days", "each stored day")):
        groups.add_parser(name, parents=[shared], allow_abbrev=False,
                          help=text, description=text)
    _day, day_commands = _group(groups, "day", shared, "one day")
    _add_day_reads(day_commands, shared)
    _add_day_moves(day_commands, shared)
    _add_day_target(day_commands, shared)
    _schedule_group, schedule_commands = _group(
        groups, "schedule", shared, "the automatic days", required=False)
    _add_schedule_changes(schedule_commands, shared)
    _players, player_commands = _group(groups, "players", shared,
                                       "the players")
    _add_player_reads(player_commands, shared)
    _add_player_changes(player_commands, shared)
    _db, db_commands = _group(groups, "db", shared, "the results index")
    _add_db_reads(db_commands, shared)
    _add_log(groups, shared)
    _add_modules(groups, {"day": day_commands, "db": db_commands}, shared)
    return parser


def _path_of(args: argparse.Namespace) -> tuple[str, ...]:
    """The words of the command, as the command table has them."""
    leaf = getattr(args, "leaf", None)
    return (args.group,) if leaf is None else (args.group, leaf)


# ---- the context ----


def _check_store_owner(root: Path) -> None:
    """Refuse a user that is not the owner of the store folder (spec
    OC1 section 5). The server cannot read a record that a different
    user writes, and a command that reads obeys the same rule."""
    try:
        owner = os.stat(root).st_uid
    except FileNotFoundError:
        raise plan.Refusal(
            f"there is no store folder at {root}. Check --service-config, "
            "and on the server computer start the command as 'sudo sv'."
        ) from None
    if owner != os.geteuid():
        raise plan.Refusal(
            f"the store folder {root} belongs to a different user. Start "
            "the command as 'sudo sv': a record that the wrong user writes "
            "is a record that the server cannot read.")


def _effective_user_name() -> str:
    """The name of the user of this process."""
    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        raise plan.Refusal(
            "the user of this process has no name in the user table, and "
            "the journal needs a login name") from None


def _ask_on_stderr(prompt: str) -> str:
    """The typed answer to a prompt. The prompt goes to the error
    stream, thus the standard output holds the answer of the command
    alone."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()


def _is_terminal(stream: object) -> bool:
    """Is the stream a terminal. A process with a closed stream has
    None there, which is not a terminal."""
    return stream is not None and stream.isatty()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _or(value, default):
    """The injected value, or the default when the caller gave None."""
    return default if value is None else value


def _context(args: argparse.Namespace, command: plan.Command, *,
             call: rollover.Call | None,
             ask: Callable[[str], str] | None,
             now: Callable[[], datetime.datetime] | None,
             environ: Mapping[str, str] | None,
             stdin_is_tty: bool | None, stdout_is_tty: bool | None,
             new_id: Callable[[], str] | None) -> Context:
    """Read the config, check the store owner, and name the actor."""
    environ = _or(environ, os.environ)
    config = load_service_config(Path(args.service_config))
    root = Path(config.store_root)
    _check_store_owner(root)
    login, login_source = plan.actor_of(environ, _effective_user_name())
    base_url = plan.check_loopback(
        args.base_url or f"http://127.0.0.1:{config.port}")
    return Context(
        command=command, config=config, config_path=args.service_config,
        root=root,
        login=login, login_source=login_source, as_json=args.json,
        assume_yes=args.yes, base_url=base_url,
        call=_or(call, rollover.http_call(base_url,
                                          environ.get(TOKEN_VARIABLE))),
        ask=_or(ask, _ask_on_stderr), now=_or(now, _utc_now),
        stdin_is_tty=_or(stdin_is_tty, _is_terminal(sys.stdin)),
        stdout_is_tty=_or(stdout_is_tty, _is_terminal(sys.stdout)),
        new_id=_or(new_id, lambda: secrets.token_hex(8)))


# ---- output and files ----


def _emit(ctx: Context, value: object,
          render: Callable[..., Sequence[str]]) -> None:
    """Print one value: JSON with `--json`, and the text lines of the
    renderer with no flag."""
    if ctx.as_json:
        print(view.to_json(value))
        return
    for line in render(value):
        print(line)


def _write_new_file(path: Path, data: bytes) -> None:
    """Write a new file that its owner alone can read. A path that is
    there refuses: the command replaces no file."""
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise plan.Refusal(
            f"{path} is there. The command writes a new file alone: give a "
            "path that is not in use.") from None
    except OSError as error:
        raise plan.Refusal(f"cannot write {path}: {error.strerror}") from error
    with os.fdopen(handle, "wb") as out:
        out.write(data)


def _read_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise plan.Refusal(f"cannot read {path}: {error.strerror}") from error


# ---- the shared reads of the store ----


def _stored_day(ctx: Context, named: str | None) -> str:
    """The named day when the store has it, or the latest stored day."""
    if named is None:
        latest = store.latest_day(ctx.root)
        if latest is None:
            raise plan.Refusal("the store holds no day")
        return latest
    if named not in store.list_days(ctx.root):
        raise plan.Refusal(f"no stored day {named!r}")
    return named


def _stored_player(ctx: Context, name: str) -> str:
    """The name, when it is legal and the store has its record."""
    store.check_player_name(name, "player")
    if store.read_player_or_none(ctx.root, name) is None:
        raise plan.Refusal(f"no stored player {name!r}")
    return name


def _visibility(ctx: Context, day: str, show_target: bool = False) -> str:
    """The answer of the plan module for one stored day: does an output
    show its target."""
    record = store.read_day_record(ctx.root, day)
    return plan.target_visibility(record.status, record.protocol,
                                  record.target_id is not None, show_target)


def _redacted(ctx: Context, row: Mapping[str, object]) -> dict:
    """One day view, day row, or history row with its target only when
    the day shows it. Each output of a day goes through this function
    before it prints, as text or as JSON."""
    return plan.redact_day(row, _visibility(ctx, str(row["day"])))


def _credits(ctx: Context) -> dict[str, dict[str, str]]:
    """The credit of each pool image, read as the server reads it."""
    from pipeline.config import load_scoring_config
    from pipeline.context import load_preparation_record
    from service import credits

    scoring_config = load_scoring_config(Path(ctx.config.scoring_config))
    record = load_preparation_record(
        Path(scoring_config.input.preparation_record))
    return credits.load_credits(Path(record.pool_release_record_path),
                                Path(ctx.config.data_root))


def _schedule_value(ctx: Context) -> dict:
    return console.schedule_view(
        ctx.root, closes_at_utc=ctx.config.closes_at_utc, instant=ctx.now(),
        lock_held=rollover.lock_is_held(store.rollover_lock_path(ctx.root)))


def _index_target(ctx: Context) -> Path:
    return index.index_path(Path(ctx.config.data_root))


# ---- the commands that read (spec OC1 section 3.1) ----


def _server_answers(ctx: Context) -> bool:
    """Does the public server answer on its loopback address. A server
    that does not answer is a fact of the status and not an error."""
    try:
        answer = ctx.call("GET", "/api/about", None, _STATUS_TIMEOUT_SECONDS)
    except rollover.TransportError:
        return False
    return answer.status == 200


def _status(ctx: Context, _args: argparse.Namespace) -> int:
    rows = console.day_rows(ctx.root, ctx.config.player)
    roster = console.roster_rows(ctx.root, ctx.config.player, ctx.now())
    value = {
        "latest": _redacted(ctx, rows[0]) if rows else None,
        "schedule": _schedule_value(ctx),
        "players": dict(Counter(str(row["status"]) for row in roster)),
        "server_answers": _server_answers(ctx),
    }
    _emit(ctx, value, lambda shown: view.status_lines(
        latest=shown["latest"], schedule=shown["schedule"],
        player_counts=shown["players"],
        server_answers=shown["server_answers"]))
    return plan.EXIT_DONE


def _days(ctx: Context, _args: argparse.Namespace) -> int:
    rows = [_redacted(ctx, row)
            for row in console.day_rows(ctx.root, ctx.config.player)]
    _emit(ctx, {"days": rows}, lambda shown: view.day_rows_lines(
        shown["days"]))
    return plan.EXIT_DONE


def _day_show(ctx: Context, args: argparse.Namespace) -> int:
    day = _stored_day(ctx, args.day)
    # The credit is of the target, and a day that does not show its
    # target does not read the credit table.
    shown = _visibility(ctx, day) == "shown"
    detail = console.day_detail(
        ctx.root, day, closes_at_utc=ctx.config.closes_at_utc,
        credits=_credits(ctx) if shown else {})
    _emit(ctx, _redacted(ctx, detail), view.day_lines)
    return plan.EXIT_DONE


def _day_send(ctx: Context, args: argparse.Namespace) -> int:
    day = _stored_day(ctx, args.day)
    store.check_player_name(args.player, "player")
    stored = store.read_json_or_none(
        store.submission_path(ctx.root, day, args.player))
    if stored is None:
        raise plan.Refusal(f"{args.player} has no stored send on {day}")
    _emit(ctx, stored, view.send_lines)
    return plan.EXIT_DONE


def _schedule(ctx: Context, _args: argparse.Namespace) -> int:
    _emit(ctx, _schedule_value(ctx), view.schedule_lines)
    return plan.EXIT_DONE


def _players_list(ctx: Context, _args: argparse.Namespace) -> int:
    rows = console.roster_rows(ctx.root, ctx.config.player, ctx.now())
    _emit(ctx, {"players": rows}, lambda shown: view.roster_lines(
        shown["players"]))
    return plan.EXIT_DONE


def _players_show(ctx: Context, args: argparse.Namespace) -> int:
    store.check_player_name(args.player, "player")
    _emit(ctx, console.player_detail(ctx.root, args.player, ctx.now()),
          view.player_lines)
    return plan.EXIT_DONE


def _players_history(ctx: Context, args: argparse.Namespace) -> int:
    store.check_player_name(args.player, "player")
    rows = [_redacted(ctx, row)
            for row in console.history_rows(ctx.root, args.player)]
    _emit(ctx, {"player": args.player, "days": rows}, view.history_lines)
    return plan.EXIT_DONE


def _players_avatar(ctx: Context, args: argparse.Namespace) -> int:
    _stored_player(ctx, args.player)
    data = store.read_avatar_or_none(ctx.root, args.player)
    if data is None:
        raise plan.Refusal(f"{args.player} has no avatar")
    _write_new_file(Path(args.save), data)
    value = {"player": args.player, "path": args.save, "bytes": len(data)}
    _emit(ctx, value, lambda shown: [
        f"wrote the avatar of {shown['player']} to "
        f"{view.safe_text(shown['path'])} ({shown['bytes']} bytes)"])
    return plan.EXIT_DONE


def _db_status(ctx: Context, _args: argparse.Namespace) -> int:
    _emit(ctx, index.describe(ctx.root, _index_target(ctx)),
          view.index_lines)
    return plan.EXIT_DONE


def _db_verify(ctx: Context, _args: argparse.Namespace) -> int:
    problems = index.verify(ctx.root, _index_target(ctx))
    _emit(ctx, {"agrees": not problems, "problems": problems},
          view.verify_lines)
    return plan.EXIT_REFUSED if problems else plan.EXIT_DONE


def _statement(args: argparse.Namespace) -> str:
    """The statement of `sv db query`: the argument, the file of
    `--file`, or the standard input for the argument `-`."""
    if (args.statement is None) == (args.file is None):
        raise plan.Refusal(
            "give one statement: as an argument, with --file F, or as - "
            "for the standard input")
    if args.file is not None:
        return _read_file(Path(args.file)).decode("utf-8")
    return sys.stdin.read() if args.statement == "-" else args.statement


def _query_text(ctx: Context, args: argparse.Namespace,
                answer: Mapping[str, object]) -> str:
    """The answer of a query as the text that the command writes."""
    if args.csv:
        # A file and a pipe get the cells as they are. A terminal gets
        # them with each control character as a code.
        return view.to_csv(answer["columns"], answer["rows"],
                           terminal=args.out is None and ctx.stdout_is_tty)
    if ctx.as_json:
        return view.to_json(answer) + "\n"
    return "\n".join(view.query_lines(answer)) + "\n"


def _db_query(ctx: Context, args: argparse.Namespace) -> int:
    if args.csv and ctx.as_json:
        raise plan.Refusal("give --csv or --json, not the two")
    sql = _statement(args)
    target = index.ensure_current(ctx.root, _index_target(ctx))
    answer = index.read_only_query(target, sql)
    text = _query_text(ctx, args, answer)
    if args.out is None:
        sys.stdout.write(text)
        return plan.EXIT_DONE
    _write_new_file(Path(args.out), text.encode("utf-8"))
    print(f"wrote {len(answer['rows'])} rows to {view.safe_text(args.out)}",
          file=sys.stderr)
    return plan.EXIT_DONE


def _db_trials(ctx: Context, args: argparse.Namespace) -> int:
    for label in (args.from_day, args.to_day):
        if label is not None:
            schedule.parse_label(label)
    if args.player is not None:
        store.check_player_name(args.player, "player")
    target = index.ensure_current(ctx.root, _index_target(ctx))
    rows, truncated = index.revealed_trial_rows(
        target, from_day=args.from_day, to_day=args.to_day,
        player=args.player)
    value = {"rows": rows, "count": len(rows), "truncated": truncated,
             "row_cap": index.TRIAL_ROW_CAP}
    _emit(ctx, value, lambda shown: view.trial_lines(shown["rows"],
                                                    shown["truncated"]))
    return plan.EXIT_DONE


# ---- the journal reader ----


def _entry_value(entry: store.OperatorEntry) -> dict[str, object]:
    """One journal record as a plain mapping, for the view and JSON."""
    facts = {key: list(value) if isinstance(value, tuple) else value
             for key, value in entry.facts.items()}
    return {"entry_id": entry.entry_id, "phase": entry.phase, "at": entry.at,
            "login": entry.login, "login_source": entry.login_source,
            "command": entry.command, "player": entry.player,
            "day": entry.day, "outcome": entry.outcome, "facts": facts,
            "error_kind": entry.error_kind}


def _instant(text: str) -> datetime.datetime:
    """An ISO 8601 date or time as an instant. Text with no zone is UTC."""
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise plan.Refusal(
            "--since takes an ISO 8601 date or time, for example "
            "2026-11-19 or 2026-11-19T12:00") from None
    return moment if moment.tzinfo is not None \
        else moment.replace(tzinfo=datetime.UTC)


def _command_agrees(records: Sequence[store.OperatorEntry],
                    args: argparse.Namespace,
                    since: datetime.datetime | None) -> bool:
    """Does one command of the journal agree with each filter. The
    records are the `start` and the `end` of the command, oldest first."""
    if since is not None and _instant(records[0].at) < since:
        return False
    if args.named_command is not None \
            and records[0].command != args.named_command:
        return False
    if args.player is not None \
            and all(record.player != args.player for record in records):
        return False
    return args.day is None \
        or any(record.day == args.day for record in records)


def _log(ctx: Context, args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        raise plan.Refusal("--limit takes a count of 1 or more")
    since = None if args.since is None else _instant(args.since)
    by_command: dict[str, list[store.OperatorEntry]] = {}
    for entry in store.list_operator_entries(ctx.root):
        by_command.setdefault(entry.entry_id, []).append(entry)
    kept = [records for records in by_command.values()
            if _command_agrees(records, args, since)]
    if args.limit is not None:
        kept = kept[-args.limit:]
    entries = [_entry_value(entry) for records in kept for entry in records]
    _emit(ctx, {"entries": entries}, lambda shown: view.journal_lines(
        shown["entries"]))
    return plan.EXIT_DONE


# ---- a change and its journal (spec OC1 sections 6 and 7) ----


def _confirm(ctx: Context, command: plan.Command,
             question: str | None) -> None:
    """Print the question of a change, read the answer, and stop on each
    answer that is not the word `yes`. With no question, or with
    `--yes`, nothing prints.

    The refusal comes before the `start` record: a change that the
    operator declines did not start, and it gets no journal record.
    """
    plan.check_terminal(command, question, ctx.assume_yes, ctx.stdin_is_tty)
    if question is None or ctx.assume_yes:
        return
    print(question, file=sys.stderr)
    try:
        answer = ctx.ask("Type yes to continue: ")
    except EOFError:
        answer = ""
    if not plan.accepts(answer):
        raise plan.Refusal("the answer was not yes. Nothing changed.")


def _journal(ctx: Context, entry_id: str, phase: str, *,
             player: str | None, day: str | None,
             outcome: str | None = None,
             facts: Mapping[str, object] | None = None,
             error_kind: str | None = None) -> None:
    """Write one record of the operator journal."""
    store.write_operator_entry(ctx.root, store.OperatorEntry(
        **plan.journal_fields(
            entry_id=entry_id, phase=phase, at=ctx.now().isoformat(),
            login=ctx.login, login_source=ctx.login_source,
            command=ctx.command, player=player, day=day, outcome=outcome,
            facts=facts, error_kind=error_kind)))


def _end_written(ctx: Context, entry_id: str, **fields: object) -> bool:
    """Write the `end` record, and say if the write completed."""
    try:
        _journal(ctx, entry_id, "end", **fields)
    except _JOURNAL_ERRORS:
        return False
    return True


def _report_stop(ctx: Context, entry_id: str, *, player: str | None,
                 day: str | None, outcome: str, error_kind: str | None,
                 message: str,
                 facts: Mapping[str, object] | None = None) -> int:
    """The end of a change that did not complete: the `end` record, and
    one line for the operator. The message stays out of the journal."""
    written = _end_written(ctx, entry_id, player=player, day=day,
                           outcome=outcome, error_kind=error_kind,
                           facts=facts)
    print(f"{outcome}: {view.safe_text(message)}", file=sys.stderr)
    if not written:
        print("the end record of the journal could not be written",
              file=sys.stderr)
    return plan.EXIT_REFUSED


def _print_done(ctx: Context, done: Done) -> None:
    if ctx.as_json:
        print(view.to_json(done.value))
        return
    for line in done.lines:
        print(line)


def _journaled(ctx: Context, work: Callable[[], Done], *,
               player: str | None = None, day: str | None = None,
               start_facts: Mapping[str, object] | None = None,
               entry_id: str | None = None) -> int:
    """Do one change between its two journal records.

    The `start` record goes in first, and when its write does not
    complete the change does not start. A StoreError or a refusal of
    the plan module gives the outcome of a refusal. Each other error
    gives the outcome of a failure, and an error that is not a known
    one continues to the caller after its `end` record. A change that
    completes with no `end` record gives the exit code 3.

    A day move gives its own identifier, because it sends that
    identifier to the server (spec OC1 section 13).
    """
    entry_id = entry_id or ctx.new_id()
    try:
        _journal(ctx, entry_id, "start", player=player, day=day,
                 facts=start_facts)
    except _JOURNAL_ERRORS as error:
        raise plan.Refusal("the start record of the journal could not be "
                           f"written: {error}. Nothing changed.") from error
    stop = {"player": player, "day": day}
    try:
        done = work()
    except _Stopped as error:
        return _report_stop(ctx, entry_id, **stop, outcome=error.outcome,
                            error_kind=error.error_kind, message=str(error),
                            facts=error.facts)
    except (store.StoreError, plan.Refusal) as error:
        return _report_stop(ctx, entry_id, **stop, outcome="refused",
                            error_kind=plan.error_kind_of(error),
                            message=str(error))
    except _REFUSALS as error:
        return _report_stop(ctx, entry_id, **stop, outcome="failed",
                            error_kind=plan.error_kind_of(error),
                            message=str(error))
    except Exception as error:
        _end_written(ctx, entry_id, **stop, outcome="failed",
                     error_kind=plan.error_kind_of(error))
        raise
    written = _end_written(ctx, entry_id, player=player,
                           day=done.day or day, outcome="done",
                           facts=done.facts)
    _print_done(ctx, done)
    if written:
        return plan.EXIT_DONE
    print("the change completed, and the end record of the journal could "
          "not be written. 'sv log' shows this command with no outcome.",
          file=sys.stderr)
    return plan.EXIT_NO_END_RECORD


def _change(ctx: Context, work: Callable[[], Done], *,
            player: str | None = None, day: str | None = None,
            question_facts: Mapping[str, object] | None = None,
            start_facts: Mapping[str, object] | None = None) -> int:
    """One command that changes the store: the question, then the
    change with its journal records (spec OC1 section 3.2)."""
    named = {key: value for key, value in (("player", player), ("day", day))
             if value is not None}
    question = plan.confirmation_for(ctx.command,
                                     {**named, **(question_facts or {})})
    _confirm(ctx, ctx.command, question)
    return _journaled(ctx, work, player=player, day=day,
                      start_facts=start_facts)


# ---- the player commands (spec OC1 section 3.2) ----


def _check_code_output(ctx: Context, args: argparse.Namespace) -> None:
    """Refuse a recovery code that goes to a pipe (ruling D9).

    The check comes before the question and before the command makes
    the code: a new code replaces the earlier one and starts the notice
    on each device of the player. JSON output obeys the same rule.
    """
    if not plan.code_output_allowed(ctx.stdout_is_tty, args.code_to_pipe):
        raise plan.Refusal(
            "the standard output is not a terminal, and a recovery code "
            "prints one time. Give --code-to-pipe to send it to a pipe. "
            "No code was made.")


def _code_done(player: str, code: str, usable_at: str,
               status: str | None = None) -> Done:
    """The one output of a new recovery code. The code is in no fact."""
    shown = auth.display_recovery_code(code)
    value = {"player": player, "recovery_code": shown, "usable_at": usable_at}
    lines = view.recovery_code_lines(player, shown, usable_at)
    if status is not None:
        value["status"] = status
        lines = [f"player {player} {status}", *lines]
    return Done(value=value, lines=lines)


def _players_recovery_code(ctx: Context, args: argparse.Namespace) -> int:
    _check_code_output(ctx, args)
    player = _stored_player(ctx, args.player)

    def work() -> Done:
        code, usable_at = players.operator_code(
            ctx.config, player=player, instant=ctx.now())
        return _code_done(player, code, usable_at)

    return _change(ctx, work, player=player)


def _players_restore(ctx: Context, args: argparse.Namespace) -> int:
    _check_code_output(ctx, args)
    player = _stored_player(ctx, args.player)

    def work() -> Done:
        record, code, usable_at = players.restore_player(
            ctx.config, player=player, instant=ctx.now())
        return _code_done(player, code, usable_at, record.status)

    return _change(ctx, work, player=player)


def _players_revoke(ctx: Context, args: argparse.Namespace) -> int:
    player = _stored_player(ctx, args.player)

    def work() -> Done:
        record = players.revoke_player(ctx.config, player=player)
        return Done(value={"player": record.player, "status": record.status},
                    lines=[f"player {record.player} {record.status}"])

    return _change(ctx, work, player=player)


def _signout_one(ctx: Context, player: str, prefix: str) -> int:
    """End the one live session that starts with the prefix, as the
    console does with the full identifier."""
    live = [str(row["id"]) for row in
            access.session_rows(ctx.root, player, None, ctx.now())]
    session = plan.match_session(prefix, live)
    facts = {"session": session[:12]}

    def work() -> Done:
        if not store.delete_session(ctx.root, player, session):
            raise store.StoreError("no live session by that id")
        return Done(value={"player": player, "ended": 1},
                    lines=[f"player {player} sessions ended: 1"],
                    facts={**facts, "ended": 1})

    return _change(ctx, work, player=player,
                   question_facts={"session": session}, start_facts=facts)


def _players_signout(ctx: Context, args: argparse.Namespace) -> int:
    player = _stored_player(ctx, args.player)
    if args.session is not None:
        return _signout_one(ctx, player, args.session)

    def work() -> Done:
        ended = players.signout_player(ctx.config, player=player)
        return Done(value={"player": player, "ended": ended},
                    lines=[f"player {player} sessions ended: {ended}"],
                    facts={"ended": ended})

    return _change(ctx, work, player=player)


def _description_text(args: argparse.Namespace) -> str:
    """The new description: empty text for `--clear`."""
    if args.clear:
        return ""
    if args.text is not None:
        return args.text
    text = _read_file(Path(args.text_file)).decode("utf-8")
    # A text file ends with one line end, which is not part of the text.
    for ending in ("\r\n", "\n"):
        if text.endswith(ending):
            return text[:-len(ending)]
    return text


def _players_describe(ctx: Context, args: argparse.Namespace) -> int:
    player = _stored_player(ctx, args.player)
    text = _description_text(args)
    # An illegal text stops here, before the journal: it is not a change.
    store.check_description(text, "description")
    facts = {"field": "description"}

    def work() -> Done:
        account = players.set_description(ctx.config, player=player,
                                          text=text)
        return Done(
            value={"player": player, "description": account.description},
            lines=[f"player {player}: description "
                   f"{'set' if text else 'cleared'}"], facts=facts)

    return _change(ctx, work, player=player, start_facts=facts)


def _avatar_change(ctx: Context, player: str, data: bytes | None) -> int:
    """Replace the avatar with the bytes, or remove it for None."""
    facts = {"field": "avatar"}

    def work() -> Done:
        if data is None:
            account = players.clear_avatar(ctx.config, player=player)
        else:
            account = players.set_avatar(ctx.config, player=player,
                                         data=data)
        return Done(
            value={"player": player, "avatar_hash": account.avatar_hash},
            lines=[f"player {player}: avatar "
                   f"{'removed' if data is None else 'set'}"], facts=facts)

    return _change(ctx, work, player=player, start_facts=facts)


def _players_avatar_set(ctx: Context, args: argparse.Namespace) -> int:
    player = _stored_player(ctx, args.player)
    return _avatar_change(ctx, player, _read_file(Path(args.file)))


def _players_avatar_clear(ctx: Context, args: argparse.Namespace) -> int:
    return _avatar_change(ctx, _stored_player(ctx, args.player), None)


def _players_delete(ctx: Context, args: argparse.Namespace) -> int:
    """The two steps of a deletion (spec MD1 section 4.4). With no
    typed copy of the name the command prints the preview and is a
    read. The flag `--yes` does not replace the typed copy."""
    player = _stored_player(ctx, args.player)
    if args.confirm is None:
        _emit(ctx, players.deletion_preview(ctx.config, player=player),
              view.deletion_preview_lines)
        return plan.EXIT_DONE
    if not plan.deletion_confirmed(player, args.confirm):
        raise plan.Refusal(
            f"--confirm does not equal the name {player!r}. Nothing is "
            "deleted.")

    def work() -> Done:
        deleted = players.delete_player(ctx.config, player=player,
                                        confirm=args.confirm)
        return Done(
            value={"player": player, "deleted": True,
                   "identifier": deleted.identifier},
            lines=[f"player {player} deleted - the earlier results show "
                   f"as {deleted.identifier}"])

    return _change(ctx, work, player=player)


def _players_prune(ctx: Context, _args: argparse.Namespace) -> int:
    def work() -> Done:
        counts = access.prune(ctx.root, ctx.now())
        return Done(value=counts,
                    lines=[f"pruned sessions={counts['sessions']} "
                           f"device_codes={counts['device_codes']}"],
                    facts={"sessions": counts["sessions"],
                           "device_codes": counts["device_codes"]})

    return _change(ctx, work)


def _players_claim_names(ctx: Context, _args: argparse.Namespace) -> int:
    def work() -> Done:
        claimed = signin.claim_stored_names(ctx.root, ctx.now())
        names = ", ".join(claimed) or "none - each name has its claim"
        return Done(value={"claimed": claimed},
                    lines=[f"claimed {len(claimed)} name(s): {names}"])

    return _change(ctx, work)


def _db_build(ctx: Context, _args: argparse.Namespace) -> int:
    """Build the results index again. The index is a cache, thus the
    command asks no question."""
    def work() -> Done:
        target = _index_target(ctx)
        index.build(ctx.root, target)
        described = index.describe(ctx.root, target)
        return Done(value=described, lines=view.index_lines(described))

    return _change(ctx, work)


# ---- the day moves and the schedule (spec OC1 section 4) ----


def _lock_path(ctx: Context) -> Path:
    return store.rollover_lock_path(ctx.root)


def _locked() -> int:
    """The exit of a day move while a rollover holds the lock. Nothing
    started, thus the journal gets no record."""
    print("a rollover is at work and holds the lock. Nothing changed: try "
          "again when it ends.", file=sys.stderr)
    return plan.EXIT_LOCKED


def _locked_change(ctx: Context, work: Callable[[], Done], *,
                   day: str | None = None,
                   question_facts: Mapping[str, object] | None = None,
                   start_facts: Mapping[str, object] | None = None,
                   entry_id: str | None = None) -> int:
    """One day move: the question, then the rollover lock with no wait,
    then the change with its journal records.

    The lock comes after the answer. Thus the time that a person reads
    the question does not stop the rollover of the timer.
    """
    named = {} if day is None else {"day": day}
    question = plan.confirmation_for(ctx.command,
                                     {**named, **(question_facts or {})})
    _confirm(ctx, ctx.command, question)
    handle = rollover.hold_lock(_lock_path(ctx))
    if handle is None:
        return _locked()
    try:
        return _journaled(ctx, work, day=day, start_facts=start_facts,
                          entry_id=entry_id)
    finally:
        os.close(handle)


def _server_refusal(ctx: Context, answer: rollover.Answer) -> _Stopped:
    """The stop of a day move that the server did not do. The words of
    the server go to the operator, and the journal gets the HTTP status
    and the machine cause alone."""
    cause = answer.body.get("cause")
    kind = plan.error_kind_of(None, answer.status,
                              cause if isinstance(cause, str) else None)
    if answer.status == 401:
        return _Stopped(
            "the server refused the operator token. Start the command as "
            f"'sudo sv': it reads {TOKEN_VARIABLE} from the env file of the "
            "server.", "refused", kind)
    detail = answer.body.get("detail") or cause or "no detail"
    outcome = "refused" if 400 <= answer.status < 500 else "failed"
    return _Stopped(f"the server answered HTTP {answer.status}: {detail}",
                    outcome, kind)


def _server_move(ctx: Context, step: str, body: dict | None) -> dict:
    """Send one day move to the public server, and give the body of
    its answer. The server is the one process that moves a day."""
    # The rollover module has the two time limits, and a close is the
    # long one: it encodes each new send through the provider.
    timeout = rollover.CLOSE_TIMEOUT_SECONDS if step == "close" \
        else rollover.STEP_TIMEOUT_SECONDS
    try:
        answer = ctx.call("POST", f"/api/day/{step}", body, timeout)
    except rollover.TransportError as error:
        raise _Stopped(
            f"the server did not answer at {ctx.base_url} ({error}). The "
            "outcome of the move is not known: read 'sv days'.", "failed",
            plan.error_kind_of(error)) from error
    if answer.status != 200:
        raise _server_refusal(ctx, answer)
    return answer.body


def _counts(body: Mapping[str, object],
            keys: Sequence[str]) -> dict[str, int]:
    """The counts of a server answer that are legal journal facts."""
    return {key: body[key] for key in keys
            if isinstance(body.get(key), int)
            and not isinstance(body.get(key), bool) and body[key] >= 0}


def _shown(value: object) -> str:
    """One value of a server answer as safe text."""
    return "-" if value is None else view.safe_text(str(value))


def _day_open(ctx: Context, _args: argparse.Namespace) -> int:
    if rollover.lock_is_held(_lock_path(ctx)):
        return _locked()

    entry_id = ctx.new_id()

    def work() -> Done:
        body = _server_move(ctx, "open", _own_record(entry_id))
        opened = body.get("day")
        lines = [f"day {_shown(opened)} open",
                 f"trial code {_shown(body.get('trial_code'))}"]
        if body.get("commitment") is not None:
            lines.append(f"commitment {_shown(body['commitment'])}")
        return Done(value=body, lines=lines,
                    day=opened if isinstance(opened, str) else None)

    return _locked_change(ctx, work, entry_id=entry_id)


def _day_facts(ctx: Context, day: str) -> dict[str, object]:
    """The facts that the question of a close or a reveal names."""
    return {"status": store.read_day_record(ctx.root, day).status,
            "latest": day == store.latest_day(ctx.root)}


def _own_record(entry_id: str) -> dict:
    """The part of a day move that names the `start` record of this
    command (spec OC1 section 13). The server finds that record in the
    journal and writes no second one for the same move."""
    return {"journal_entry": entry_id}


def _named_body(day: str, entry_id: str) -> dict:
    """The body of a close or a reveal (ruling D1).

    The body names the day each time, also for the latest day. The
    question showed that day, thus the server moves the day that the
    operator accepted and not a newer one that a rollover opened in
    the time between.
    """
    return {"day": day, **_own_record(entry_id)}


def _day_close(ctx: Context, args: argparse.Namespace) -> int:
    if rollover.lock_is_held(_lock_path(ctx)):
        return _locked()
    day = _stored_day(ctx, args.day)
    entry_id = ctx.new_id()

    def work() -> Done:
        body = _server_move(ctx, "close", _named_body(day, entry_id))
        facts = _counts(body, ("trial_rows", "quarantined"))
        counts = "  ".join(f"{key}={value}" for key, value in facts.items())
        return Done(value={"day": day, **body},
                    lines=[f"day {day} closed  {counts}".rstrip()],
                    facts=facts)

    return _locked_change(ctx, work, day=day,
                          question_facts=_day_facts(ctx, day),
                          entry_id=entry_id)


def _day_reveal(ctx: Context, args: argparse.Namespace) -> int:
    if rollover.lock_is_held(_lock_path(ctx)):
        return _locked()
    day = _stored_day(ctx, args.day)
    entry_id = ctx.new_id()

    def work() -> Done:
        body = _server_move(ctx, "reveal", _named_body(day, entry_id))
        return Done(value=body, lines=[f"day {day} revealed"])

    return _locked_change(ctx, work, day=day,
                          question_facts=_day_facts(ctx, day),
                          entry_id=entry_id)


def _set_pause(ctx: Context, paused: bool, note: str) -> int:
    """Write the pause as the pause path of the console does. The note
    is in the control record and not in the journal."""
    # An illegal note stops here, before the journal: it is not a change.
    store.check_rollover_note(note, "note")
    facts = {"paused": paused}

    def work() -> Done:
        store.write_rollover_control(ctx.root, store.RolloverControl(
            paused=paused, changed_at=ctx.now().isoformat(), note=note))
        value = _schedule_value(ctx)
        return Done(value=value, lines=view.schedule_lines(value),
                    facts=facts)

    return _change(ctx, work, start_facts=facts)


def _schedule_pause(ctx: Context, args: argparse.Namespace) -> int:
    return _set_pause(ctx, True, args.note)


def _schedule_resume(ctx: Context, _args: argparse.Namespace) -> int:
    return _set_pause(ctx, False, "")


def _say_on_stderr(line: str) -> None:
    """One line of a rollover. The lines go to the error stream, thus
    the standard output holds the answer of the command alone."""
    print(view.safe_text(line), file=sys.stderr)


def _run_facts(ctx: Context, closes_at_utc: str) -> dict[str, object]:
    """The facts that the question of `sv schedule run` names: the
    steps that are due, the days, and the pause."""
    instant = ctx.now()
    latest = rollover.read_latest(ctx.root)
    steps = rollover.planned_steps(latest, instant, closes_at_utc)
    opens = schedule.next_open_label(latest.label, instant, closes_at_utc) \
        if "open" in steps else None
    return {"steps": steps, "day": latest.label, "opens": opens,
            "paused": store.read_rollover_control(ctx.root).paused}


def _schedule_run(ctx: Context, _args: argparse.Namespace) -> int:
    """Do the steps that are due, with no retry. The command does not
    read the pause (ruling D6), and its question says so."""
    closes_at_utc = ctx.config.closes_at_utc
    if closes_at_utc is None:
        raise plan.Refusal(
            "the automatic days are off: closes_at_utc is not in the server "
            "config, and it is the rollover hour")
    if rollover.lock_is_held(_lock_path(ctx)):
        return _locked()
    facts = _run_facts(ctx, closes_at_utc)
    entry_id = ctx.new_id()

    def work() -> Done:
        # Each move of the run names the record of this command, thus
        # the server writes no record for a step of the run.
        run = rollover.run_and_record(
            root=ctx.root, closes_at_utc=closes_at_utc,
            post=lambda path, timeout: ctx.call(
                "POST", path, _own_record(entry_id), timeout),
            now=ctx.now, source="command-line", retries=0,
            say=_say_on_stderr)
        done = {"steps": run.steps, "retries": 0}
        if run.outcome == "failed":
            raise _Stopped(
                "the rollover did not complete. The run record in "
                "store/rollover/runs holds each line.", "failed",
                "rollover-failed", done)
        value = {"run": console.run_value(run),
                 "schedule": _schedule_value(ctx)}
        return Done(
            value=value, facts=done,
            lines=[f"rollover {run.outcome}: "
                   f"{', '.join(run.steps) or 'no step'}",
                   *view.schedule_lines(value["schedule"])])

    return _locked_change(ctx, work, question_facts=facts,
                          start_facts={"steps": facts["steps"],
                                       "retries": 0},
                          entry_id=entry_id)


# ---- the target, the rank, and the quarantine (spec OC1 section 3.3) ----


def _refuse_path_in_use(path: str | None) -> None:
    """Refuse the path of a new file before the work, when a file is
    there. `_write_new_file` has the same rule at the write."""
    if path is not None and os.path.lexists(path):
        raise plan.Refusal(
            f"{path} is there. The command writes a new file alone: give a "
            "path that is not in use.")


def _end_of_blind_view(ctx: Context, work: Callable[[], Done], *, day: str,
                       player: str | None = None) -> int:
    """Show the target of a closed day that is not revealed: the
    question, and a journal entry for this read (spec OC1 section 7)."""
    # The command table gives a read no question. This one condition
    # has one, thus the terminal guard gets the command as a command
    # with a question.
    _confirm(ctx, replace(ctx.command, confirm="yes"),
             plan.shows_target_question(day))
    return _journaled(ctx, work, player=player, day=day,
                      start_facts={"shows_target": True})


def _has_target_to_show(record: store.DayRecord, show_target: bool) -> bool:
    """Does the day have a target that this output shows.

    The answer is no for a `vp1` day before its pick, which has no
    target. A day that is open or closing refuses with no flag that
    changes it (ruling D2), and a closed day refuses with no
    `--show-target`.
    """
    visibility = plan.target_visibility(
        record.status, record.protocol, record.target_id is not None,
        show_target)
    if visibility in ("shown", "none-yet"):
        return visibility == "shown"
    if not plan.rank_allowed(record.status):
        raise plan.Refusal(_OPEN_DAY_REFUSAL)
    raise plan.Refusal(
        f"{record.day} is closed and not revealed. Give --show-target to "
        "see its target: that ends a blind view of the day, and the "
        "journal records it.")


def _target_done(ctx: Context, args: argparse.Namespace,
                 record: store.DayRecord) -> Done:
    """The target of a day that shows it, and the image file of
    `--save`."""
    from pool.artifacts import load_image_bytes

    credit = _credits(ctx).get(record.target_id)
    value = {"day": record.day, "status": record.status,
             "target_id": record.target_id, "credit": credit}
    lines = view.target_lines(str(record.target_id), credit)
    if args.save is not None:
        data = load_image_bytes(Path(ctx.config.data_root),
                                str(record.target_id))
        _write_new_file(Path(args.save), data)
        value["saved"] = args.save
        lines.append(f"wrote the image to {view.safe_text(args.save)} "
                     f"({len(data)} bytes)")
    return Done(value=value, lines=lines, facts={"shows_target": True})


def _day_target(ctx: Context, args: argparse.Namespace) -> int:
    day = _stored_day(ctx, args.day)
    record = store.read_day_record(ctx.root, day)
    _refuse_path_in_use(args.save)
    if not _has_target_to_show(record, args.show_target):
        # Spec VP1 section 8: no photo is picked, thus the command does
        # not say that one is hidden.
        if args.save is not None:
            raise plan.Refusal("no target until the close: there is no "
                               "image to save")
        _emit(ctx, {"day": day, "status": record.status,
                    plan.VISIBILITY_KEY: "none-yet"},
              lambda _shown: ["no target until the close"])
        return plan.EXIT_DONE
    if plan.shows_target_needs_question(record.status, args.show_target):
        return _end_of_blind_view(
            ctx, lambda: _target_done(ctx, args, record), day=day)
    _print_done(ctx, _target_done(ctx, args, record))
    return plan.EXIT_DONE


def _rankings(ctx: Context, wire: object, target_id: str) -> dict:
    """Score one stored send in this process, as the rankings path of
    the console does (ruling D7). Nothing is stored."""
    from pipeline.config import load_scoring_config
    from service import scoring

    scoring_config = load_scoring_config(Path(ctx.config.scoring_config))
    wired = scoring.wire_for_close(scoring_config, ctx.config.scoring_config,
                                   Path(ctx.config.data_root))
    return scoring.dev_rankings(wire, target_id, wired)


def _day_rank(ctx: Context, args: argparse.Namespace) -> int:
    day = _stored_day(ctx, args.day)
    store.check_player_name(args.player, "player")
    if args.limit is not None and args.limit < 1:
        raise plan.Refusal("--limit takes a count of 1 or more")
    record = store.read_day_record(ctx.root, day)
    if not _has_target_to_show(record, args.show_target):
        raise plan.Refusal("no target until the close: nothing ranks "
                           "before the pick")
    stored = store.read_json_or_none(
        store.submission_path(ctx.root, day, args.player))
    if stored is None:
        raise plan.Refusal(f"{args.player} has no stored send on {day}")

    def work() -> Done:
        value = _rankings(ctx, stored["record"], str(record.target_id))
        return Done(value=value, lines=view.rankings_lines(value, args.limit),
                    facts={"shows_target": True})

    if plan.shows_target_needs_question(record.status, args.show_target):
        return _end_of_blind_view(ctx, work, day=day, player=args.player)
    _print_done(ctx, work())
    return plan.EXIT_DONE


def _day_quarantine(ctx: Context, args: argparse.Namespace) -> int:
    """The operator skip of spec CR1 section 6, with the function of
    the day module. The note is in the quarantine record and not in the
    journal."""
    from service import day as day_module

    day = _stored_day(ctx, args.day)
    store.check_player_name(args.player, "player")

    def work() -> Done:
        record = day_module.quarantine_send(
            ctx.config, date=day, player=args.player, note=args.note)
        return Done(
            value={"day": record.day, "player": record.player,
                   "quarantined": True},
            lines=[f"day {record.day}: the send of {record.player} is "
                   "quarantined - close the day again"],
            facts={"quarantined": 1})

    return _change(ctx, work, player=args.player, day=day)


# ---- the commands that go to a module command (spec OC1 section 3.4) ----


def _module_entry(name: str) -> Callable[[list[str]], int]:
    """The entry function of one module of the plan table."""
    match name:
        case "service.day":
            from service import day as day_module

            return day_module.main
        case "service.index":
            return index.main
        case "service.public":
            from service import public

            return public.main
        case "service.rollup":
            from service import rollup

            return rollup.main
        case "service.pool_keys":
            from service import pool_keys

            return pool_keys.main
        case _:
            raise plan.Refusal(f"no module command {name!r}")


def _module(ctx: Context, args: argparse.Namespace) -> int:
    """Give the arguments to the module command with no change, and
    give its exit code. The module prints text and writes no journal
    record (ruling D8)."""
    if ctx.as_json or "--json" in args.rest:
        raise plan.Refusal(
            f"sv {plan.journal_name(ctx.command)} goes to a module command "
            "that prints text. --json does not work with it.")
    name, argv = plan.module_argv(ctx.command, ctx.config_path, args.rest)
    return _module_entry(name)(argv)


# ---- the dispatch ----


def _handler_for(command: plan.Command) -> Handler:
    """The handler of one command of the table."""
    if command.kind == "module":
        return _module
    match command.path:
        case ("status",):
            return _status
        case ("days",):
            return _days
        case ("day", "show"):
            return _day_show
        case ("day", "send"):
            return _day_send
        case ("schedule",):
            return _schedule
        case ("players", "list"):
            return _players_list
        case ("players", "show"):
            return _players_show
        case ("players", "history"):
            return _players_history
        case ("players", "avatar"):
            return _players_avatar
        case ("db", "status"):
            return _db_status
        case ("db", "verify"):
            return _db_verify
        case ("db", "query"):
            return _db_query
        case ("db", "trials"):
            return _db_trials
        case ("log",):
            return _log
        case ("players", "recovery-code"):
            return _players_recovery_code
        case ("players", "restore"):
            return _players_restore
        case ("players", "revoke"):
            return _players_revoke
        case ("players", "signout"):
            return _players_signout
        case ("players", "describe"):
            return _players_describe
        case ("players", "avatar-set"):
            return _players_avatar_set
        case ("players", "avatar-clear"):
            return _players_avatar_clear
        case ("players", "delete"):
            return _players_delete
        case ("players", "prune"):
            return _players_prune
        case ("players", "claim-names"):
            return _players_claim_names
        case ("db", "build"):
            return _db_build
        case ("day", "open"):
            return _day_open
        case ("day", "close"):
            return _day_close
        case ("day", "reveal"):
            return _day_reveal
        case ("schedule", "pause"):
            return _schedule_pause
        case ("schedule", "resume"):
            return _schedule_resume
        case ("schedule", "run"):
            return _schedule_run
        case ("day", "target"):
            return _day_target
        case ("day", "rank"):
            return _day_rank
        case ("day", "quarantine"):
            return _day_quarantine
        case _:
            raise plan.Refusal(
                f"sv {plan.journal_name(command)} is not built")


def _refused(error: BaseException) -> int:
    """Print one refusal as one safe line, and give its exit code."""
    print(f"refused: {view.safe_text(str(error))}", file=sys.stderr)
    return plan.EXIT_REFUSED


def main(argv: list[str] | None = None, *,
         call: rollover.Call | None = None,
         ask: Callable[[str], str] | None = None,
         now: Callable[[], datetime.datetime] | None = None,
         environ: Mapping[str, str] | None = None,
         stdin_is_tty: bool | None = None,
         stdout_is_tty: bool | None = None,
         new_id: Callable[[], str] | None = None) -> int:
    """Do one operator command, and give its exit code (spec OC1
    section 6).

    Each argument after argv is for the tests, and None is the value of
    the process: the loopback sender with the operator token, the typed
    answer, the UTC clock, the environment, the two terminal checks, and
    a random journal identifier.
    """
    parser = _parser()
    # The tree does not read the words of a module command. A module
    # command gets those words, and each other command refuses them.
    args, unread = parser.parse_known_args(argv)
    args.rest = unread
    try:
        command = plan.command_for(_path_of(args))
        if args.rest and command.kind != "module":
            parser.error(f"unrecognized arguments: {' '.join(args.rest)}")
        ctx = _context(args, command, call=call, ask=ask, now=now,
                       environ=environ, stdin_is_tty=stdin_is_tty,
                       stdout_is_tty=stdout_is_tty, new_id=new_id)
        return _handler_for(command)(ctx, args)
    except _REFUSALS as error:
        return _refused(error)


if __name__ == "__main__":
    raise SystemExit(main())
