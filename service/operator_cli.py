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
from dataclasses import dataclass
from pathlib import Path

from service import console, index, rollover, schedule, store
from service import operator_plan as plan
from service import operator_view as view
from service.config import ServiceConfig, load_service_config

TOKEN_VARIABLE = "STARVECTOR_OPERATOR_TOKEN"

# The time limit of the one `GET` that `sv status` sends to the public
# server. The spec gives no number: a server on the loopback address
# answers this path from memory, thus a short limit is sufficient.
_STATUS_TIMEOUT_SECONDS = 3.0

# The errors that a handler gives for a refusal that the operator can
# read: a rule of the plan module, a store rule, a config rule, a value
# rule of a function that the handler uses, and a refusal of the results
# index. Each one prints as one line and not as a traceback.
_REFUSALS = (ValueError, index.ResultsIndexError, sqlite3.Error)


@dataclass(frozen=True, slots=True)
class Context:
    """The values that each handler reads, made one time for a command.

    root is the store folder. login and login_source are the actor of
    the journal. base_url is the loopback address of the public server.
    The last six fields are the values that a test can inject.
    """

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


def _add_player_reads(commands, shared: argparse.ArgumentParser) -> None:
    _leaf(commands, "list", shared, "the roster")
    for name, text in (("show", "one account and its devices"),
                       ("history", "the days of one player")):
        _leaf(commands, name, shared, text).add_argument("player")
    avatar = _leaf(commands, "avatar", shared,
                   "write the avatar of a player to a new file")
    avatar.add_argument("player")
    avatar.add_argument("--save", required=True, metavar="PATH")


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
    _group(groups, "schedule", shared, "the automatic days", required=False)
    _players, player_commands = _group(groups, "players", shared,
                                       "the players")
    _add_player_reads(player_commands, shared)
    _db, db_commands = _group(groups, "db", shared, "the results index")
    _add_db_reads(db_commands, shared)
    _add_log(groups, shared)
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


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _or(value, default):
    """The injected value, or the default when the caller gave None."""
    return default if value is None else value


def _context(args: argparse.Namespace, *, call: rollover.Call | None,
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
        config=config, config_path=args.service_config, root=root,
        login=login, login_source=login_source, as_json=args.json,
        assume_yes=args.yes, base_url=base_url,
        call=_or(call, rollover.http_call(base_url,
                                          environ.get(TOKEN_VARIABLE))),
        ask=_or(ask, _ask_on_stderr), now=_or(now, _utc_now),
        stdin_is_tty=_or(stdin_is_tty, sys.stdin.isatty()),
        stdout_is_tty=_or(stdout_is_tty, sys.stdout.isatty()),
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
    store.check_player_name(args.player, "player")
    if store.read_player_or_none(ctx.root, args.player) is None:
        raise plan.Refusal(f"no stored player {args.player!r}")
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


# ---- the dispatch ----


def _handler_for(command: plan.Command) -> Handler:
    """The handler of one command of the table."""
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
    args = parser.parse_args(argv)
    try:
        command = plan.command_for(_path_of(args))
        ctx = _context(args, call=call, ask=ask, now=now, environ=environ,
                       stdin_is_tty=stdin_is_tty,
                       stdout_is_tty=stdout_is_tty, new_id=new_id)
        return _handler_for(command)(ctx, args)
    except _REFUSALS as error:
        return _refused(error)


if __name__ == "__main__":
    raise SystemExit(main())
