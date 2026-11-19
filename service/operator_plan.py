"""The rules of the operator command line: commands, questions, guards.

Spec: OC1 (in docs/specs/operator-cli.md) sections 3, 4, 5, 6, and 7.
This module holds the command table, the text of each question, the
guards that refuse a command, and the fields of a journal entry. Each
function is pure: it reads no file, no environment, and no clock, and
it prints nothing. The shell of the command gives each value as an
argument and does the work that a function here permits.

A guard that stops a command raises `Refusal`. A guard that answers a
question about a command gives a `bool`.
"""

import copy
import re
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

# The exit codes of spec OC1 section 6.
EXIT_DONE = 0
EXIT_REFUSED = 1
EXIT_LOCKED = 2
EXIT_NO_END_RECORD = 3

KINDS: tuple[str, ...] = ("read", "change", "module")
TRANSPORTS: tuple[str, ...] = ("store", "server", "module")
CONFIRMS: tuple[str, ...] = ("none", "yes", "typed-name")
DAY_STATUSES: tuple[str, ...] = ("open", "closing", "closed", "revealed")
PROTOCOLS: tuple[str, ...] = ("commit-v1", "vp1")
VISIBILITIES: tuple[str, ...] = ("shown", "hidden", "none-yet", "refused")

# The key that `redact_day` adds to a view. The renderers of the output
# module read the same key, and a test compares the two names.
VISIBILITY_KEY = "target_visibility"

# The keys that `redact_day` removes from a day view, a day row, and a
# history row when the target does not show. `target_id`, `credit`, and
# `trial` are in the views of the console module today. The other keys
# are the fields of the stored day record that give the target: no view
# holds them today, and a view that gets one does not show it.
TARGET_KEYS: tuple[str, ...] = (
    "target_id", "credit", "secret", "pick_seed", "target_index",
    "target_salt", "target_proof", "trial")
# The keys that `redact_day` removes from each row of `sends`. `trial`
# holds the trial score and the rank of the target for that send.
SEND_TARGET_KEYS: tuple[str, ...] = ("trial",)

# The shortest start of a session identifier that `match_session` reads.
SESSION_PREFIX_MIN = 6

LOGIN_VARIABLE = "STARVECTOR_OPERATOR_LOGIN"
LOGIN_SOURCE_VARIABLE = "STARVECTOR_OPERATOR_LOGIN_SOURCE"
# The sources that the script of spec OC1 section 5 can name.
SCRIPT_LOGIN_SOURCES: tuple[str, ...] = ("login-uid", "sudo-user")
EFFECTIVE_USER_SOURCE = "effective-user"
LOGIN_SOURCES: tuple[str, ...] = (*SCRIPT_LOGIN_SOURCES,
                                  EFFECTIVE_USER_SOURCE)
_LOGIN_RULE = re.compile(r"[A-Za-z0-9._-]{1,64}")

# The journal rules of spec OC1 section 7. The store has the same rules,
# and a test compares the two.
PHASES: tuple[str, ...] = ("start", "end")
OUTCOMES: tuple[str, ...] = ("done", "refused", "failed")
FACT_KEYS: tuple[str, ...] = (
    "steps", "trial_rows", "quarantined", "ended", "field", "paused",
    "exit_code", "session", "sessions", "device_codes", "agrees",
    "shows_target", "retries")
_FACT_RULE = re.compile(r"[A-Za-z0-9 _.:,/-]{0,80}")
_ERROR_RULE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_CAUSE_RULE = re.compile(r"[A-Za-z0-9_-]{1,40}")
# The cause that `error_kind_of` writes for a cause with illegal text.
OTHER_CAUSE = "other"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class Refusal(ValueError):
    """A command that a rule stops. The text is for the operator."""


@dataclass(frozen=True, slots=True)
class Command:
    """One command of spec OC1 section 3.

    path holds the words after `sv`. The three fields after it hold one
    of KINDS, one of TRANSPORTS, and one of CONFIRMS, in that sequence.
    covers holds the pairs of an HTTP method and a path template of the
    server that this command does the work of.
    """

    path: tuple[str, ...]
    kind: str
    transport: str
    confirm: str
    covers: tuple[tuple[str, str], ...]


def _read(words: str, *covers: tuple[str, str]) -> Command:
    return Command(tuple(words.split()), "read", "store", "none", covers)


def _change(words: str, confirm: str, *covers: tuple[str, str],
            transport: str = "store") -> Command:
    return Command(tuple(words.split()), "change", transport, confirm,
                   covers)


def _module(words: str) -> Command:
    return Command(tuple(words.split()), "module", "module", "none", ())


_PLAYER = "/api/dev/players/{name}"

COMMANDS: tuple[Command, ...] = (
    # Spec OC1 section 3.1: the commands that read.
    _read("status"),
    _read("days", ("GET", "/api/dev/days"), ("GET", "/api/dev")),
    _read("day show", ("GET", "/api/dev/day")),
    _read("day send", ("GET", "/api/dev/submission")),
    _read("schedule", ("GET", "/api/dev/schedule")),
    _read("players list", ("GET", "/api/dev/players")),
    _read("players show", ("GET", _PLAYER)),
    _read("players history", ("GET", "/api/dev/history")),
    _read("players avatar", ("GET", _PLAYER + "/avatar")),
    _read("db status", ("GET", "/api/dev/index")),
    _read("db verify", ("POST", "/api/dev/index/verify")),
    _read("db query", ("POST", "/api/dev/index/query")),
    _read("db trials", ("GET", "/api/ops/trials")),
    _read("log"),
    # Spec OC1 section 3.2: the commands that change.
    _change("day open", "none", ("POST", "/api/day/open"),
            transport="server"),
    _change("day close", "yes", ("POST", "/api/day/close"),
            ("POST", "/api/dev/day/close"), transport="server"),
    _change("day reveal", "yes", ("POST", "/api/day/reveal"),
            ("POST", "/api/dev/day/reveal"), transport="server"),
    _change("day quarantine", "yes"),
    _change("schedule pause", "none", ("POST", "/api/dev/rollover/pause")),
    _change("schedule resume", "none", ("POST", "/api/dev/rollover/pause")),
    # The rollover sends each move to the server (spec OC1 section 4).
    _change("schedule run", "yes", ("POST", "/api/dev/rollover/run"),
            transport="server"),
    _change("players recovery-code", "yes",
            ("POST", _PLAYER + "/recovery-code")),
    _change("players restore", "yes", ("POST", _PLAYER + "/restore")),
    _change("players revoke", "yes", ("POST", _PLAYER + "/revoke")),
    _change("players signout", "yes", ("POST", _PLAYER + "/signout"),
            ("DELETE", _PLAYER + "/sessions/{session_id}")),
    _change("players describe", "none", ("PUT", _PLAYER + "/description")),
    _change("players avatar-set", "none", ("PUT", _PLAYER + "/avatar")),
    _change("players avatar-clear", "none",
            ("DELETE", _PLAYER + "/avatar")),
    _change("players delete", "typed-name", ("GET", _PLAYER + "/deletion"),
            ("POST", _PLAYER + "/delete")),
    _change("players prune", "none", ("POST", "/api/dev/prune")),
    _change("players claim-names", "none"),
    _change("db build", "none", ("POST", "/api/dev/index/build")),
    # Spec OC1 section 3.3: the target and the rank. The two store
    # nothing. `shows_target_needs_question` gives the one condition in
    # which they get a question and a journal entry.
    _read("day target"),
    _read("day rank", ("GET", "/api/dev/rankings")),
    # Spec OC1 section 3.4: the commands that go to a module command.
    _module("day rescore"),
    _module("day migrate"),
    _module("day day-scores"),
    _module("db export"),
    _module("public"),
    _module("rollup assemble"),
    _module("pool-keys make"),
)

# The commands of spec OC1 section 3.4. Each one names the module with
# the entry function that does its work, and the words that this module
# command gets before the arguments of the operator.
MODULE_COMMANDS: Mapping[tuple[str, ...], tuple[str, tuple[str, ...]]] = \
    MappingProxyType({
        ("day", "rescore"): ("service.day", ("rescore",)),
        ("day", "migrate"): ("service.day", ("migrate",)),
        ("day", "day-scores"): ("service.day", ("day-scores",)),
        ("db", "export"): ("service.index", ("export",)),
        ("public",): ("service.public", ()),
        ("rollup", "assemble"): ("service.rollup", ("assemble",)),
        ("pool-keys", "make"): ("service.pool_keys", ("make",)),
    })

# The paths of the server with an operator prefix and no command, each
# with its cause. The parity test of spec OC1 section 9 reads this table.
NOT_IN_CLI: Mapping[tuple[str, str], str] = MappingProxyType({
    ("POST", _PLAYER + "/device-code"):
        "retired: the path answers the constant 404 in each mode "
        "(spec OC1 section 3.5, spec A2 section 10.1)",
    ("GET", "/api/door"):
        "the open door is a development sign-in for a browser, not an "
        "operator action",
    ("POST", "/api/door"):
        "the open door is a development sign-in for a browser, not an "
        "operator action",
    ("POST", "/api/day/start"):
        "a player's path below the day prefix: it records the first time "
        "a player opens the drawing screen, with a session and no operator "
        "token",
})

_BY_PATH: Mapping[tuple[str, ...], Command] = MappingProxyType(
    {command.path: command for command in COMMANDS})


def command_for(path: Sequence[str]) -> Command:
    """The command with these words after `sv`.

    Raises Refusal, a ValueError, for words that name no command.
    """
    command = _BY_PATH.get(tuple(path))
    if command is None:
        raise Refusal(f"unknown command: sv {' '.join(path)}")
    return command


def journal_name(command: Command) -> str:
    """The name of the command in a journal entry: its words, one space
    apart."""
    return " ".join(command.path)


def module_argv(command: Command, service_config: str,
                rest: Sequence[str]) -> tuple[str, list[str]]:
    """The module of a command of spec OC1 section 3.4, and the
    arguments that its entry function gets.

    The arguments are the config flag with the config of the operator
    command, the words of the module command, and then the arguments of
    the operator with no change. Raises Refusal for a command with no
    module.
    """
    found = MODULE_COMMANDS.get(command.path)
    if found is None:
        raise Refusal(f"sv {journal_name(command)} has no module command")
    module, words = found
    return module, ["--service-config", service_config, *words, *rest]


def covered_routes() -> frozenset[tuple[str, str]]:
    """Each pair of a method and a path template that some command
    covers."""
    return frozenset(pair for command in COMMANDS for pair in command.covers)


# ---- the questions (spec OC1 section 6) ----


def _fact(command: Command, facts: Mapping[str, object], key: str) -> object:
    """One fact that a question must have.

    A fact that is not there is an error of the shell, not a refusal.
    """
    if key not in facts:
        raise ValueError(
            f"the question of {journal_name(command)!r} needs the fact "
            f"{key!r}")
    return facts[key]


def step_text(step: str, day: str | None, opens: str | None) -> str:
    """One rollover step in the words of the console.

    day is the latest stored day, and opens is the day that an `open`
    step starts. Raises ValueError for a step that is not a move.
    """
    match step:
        case "close":
            return f"Close {day or 'the day'} and score it"
        case "reveal":
            return f"Reveal {day or 'the day'}"
        case "open":
            return f"Open {opens or 'the next day'}"
        case _:
            raise ValueError(f"unknown rollover step {step!r}")


def _close_question(command: Command, facts: Mapping[str, object]) -> str:
    day = _fact(command, facts, "day")
    status = _fact(command, facts, "status")
    latest = _fact(command, facts, "latest")
    if status not in ("open", "closing"):
        raise Refusal(f"{day} is {status}: a close is for a day that is "
                      "open or closing")
    if not latest:
        return (f"{day} is still {status} behind a newer day. Close it and "
                "score its sends?")
    if status == "closing":
        # The console has a plain button here. The terminal asks before
        # each close (spec OC1 section 3.2), in the console's words.
        return (f"Finish closing {day}? A close stopped part way. Finishing "
                "it scores the sends that are left and closes the day. It "
                "can't be reopened.")
    return f"Close {day}? New sends stop, and each send is scored now."


def _reveal_question(command: Command, facts: Mapping[str, object]) -> str:
    day = _fact(command, facts, "day")
    status = _fact(command, facts, "status")
    latest = _fact(command, facts, "latest")
    if status != "closed":
        raise Refusal(f"{day} is {status}: a reveal is for a day that is "
                      "closed")
    if not latest:
        return (f"{day} stayed closed behind a newer day. Reveal it? "
                "Players see its photo and results.")
    return f"Reveal {day}? Players see the photo and their results."


def _run_question(command: Command, facts: Mapping[str, object]) -> str:
    steps = _fact(command, facts, "steps")
    paused = _fact(command, facts, "paused")
    if isinstance(steps, str) or not isinstance(steps, Sequence):
        raise ValueError("the fact 'steps' must be a sequence of steps")
    if not steps:
        raise Refusal("Nothing is due now.")
    day = facts.get("day")
    opens = facts.get("opens")
    question = ", then ".join(
        step_text(step, None if day is None else str(day),
                  None if opens is None else str(opens))
        for step in steps) + " — now?"
    if paused:
        # Ruling D6: the question says that the pause does not stop this.
        question += (" The automatic days are paused, and this command "
                     "does not read the pause: it does these steps anyway.")
    return question


def confirmation_for(command: Command,
                     facts: Mapping[str, object]) -> str | None:
    """The question to print before a command, or None for no question.

    The words are the words of the browser console, changed only where
    a terminal has no control to point at. facts holds what the words
    name: `player`, `day`, `status`, `latest`, `steps`, `opens`,
    `paused`, and `session`. The command `players delete` gives None,
    because `deletion_confirmed` is its confirmation. A sign-out of one
    session gives None, as in the console.

    Raises Refusal for a day move that is illegal for the status of the
    day, and for a rollover with no step due. Raises ValueError for a
    fact that is not there.
    """
    if command.confirm != "yes":
        return None
    match command.path:
        case ("day", "close"):
            return _close_question(command, facts)
        case ("day", "reveal"):
            return _reveal_question(command, facts)
        case ("day", "quarantine"):
            player = _fact(command, facts, "player")
            day = _fact(command, facts, "day")
            return (f"Skip the send of {player} on {day}? It gets no score, "
                    "and the close continues with the other sends. The "
                    "blind score of that one send runs first, and a send "
                    "that scores is not skipped.")
        case ("schedule", "run"):
            return _run_question(command, facts)
        case ("players", "recovery-code"):
            player = _fact(command, facts, "player")
            return (f"Make a recovery code for {player}? It works only "
                    "after 24 hours, and until then each signed-in device "
                    f"of {player} shows a notice with a control that stops "
                    "it. Their password, their own recovery code, and "
                    "their devices stay as they are. Give a code only to "
                    "the person the account belongs to.")
        case ("players", "restore"):
            player = _fact(command, facts, "player")
            return (f"Restore {player}? The account is active again and "
                    "you get a recovery code for them, which works only "
                    "after 24 hours. No old device comes back.")
        case ("players", "revoke"):
            player = _fact(command, facts, "player")
            return (f"Revoke {player}? Every signed-in device stops "
                    "working, and the password and each recovery code sign "
                    "nobody in. Their play stays stored.")
        case ("players", "signout"):
            if facts.get("session") is not None:
                return None
            player = _fact(command, facts, "player")
            return f"Sign {player} out on every device?"
        case _:
            raise ValueError(
                f"no question is written for {journal_name(command)!r}")


def shows_target_question(day: str) -> str:
    """The question before an output that shows the target of a closed
    day. The console's question is for an open day, which the terminal
    refuses (ruling D2), thus the first sentence is different."""
    return (f"{day} is closed and not revealed. This output shows the "
            "target, and that ends a blind view of this day. The journal "
            "records it.")


def accepts(answer: str) -> bool:
    """Is the typed answer the word `yes`. Spaces at the ends do not
    count, and a capital letter is the same as a small one."""
    return answer.strip().lower() == "yes"


# ---- the target and the rank (spec OC1 section 3.3) ----


def _check_status(status: str) -> None:
    if status not in DAY_STATUSES:
        raise ValueError(f"unknown day status {status!r}")


def target_visibility(status: str, protocol: str, has_target: bool,
                      show_target: bool) -> str:
    """Does an output show the target of a day: one of VISIBILITIES.

    The four answers, in the sequence of VISIBILITIES:

    - The output holds the target.
    - A target is stored, and the output does not hold it.
    - The day is a `vp1` day before its pick, with no target to show
      or to hide.
    - The operator gave `--show-target` for a day that is open or
      closing, and the command stops (ruling D2).

    Raises ValueError for a status or a protocol that the store does
    not have.
    """
    _check_status(status)
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown pick protocol {protocol!r}")
    if status == "revealed":
        return "shown"
    if status == "closed":
        return "shown" if show_target else "hidden"
    if protocol == "vp1" and not has_target:
        return "none-yet"
    return "refused" if show_target else "hidden"


def rank_allowed(status: str) -> bool:
    """Can `sv day rank` score a send of a day with this status. A day
    that is open or closing gets no rank on the terminal (ruling D2)."""
    _check_status(status)
    return status not in ("open", "closing")


def shows_target_needs_question(status: str, show_target: bool) -> bool:
    """Does this output end a blind view of the day.

    That is a closed day with `--show-target`. The shell then prints
    `shows_target_question` and writes a journal entry (spec OC1
    section 7).
    """
    _check_status(status)
    return status == "closed" and show_target


def redact_day(view: Mapping[str, object], visibility: str) -> dict:
    """A copy of a day view that holds the target only when it shows.

    view is the day view, a day row, or a history row of the console
    module. With a visibility that is not `shown`, the copy has no key
    of TARGET_KEYS, and each row of `sends` has no key of
    SEND_TARGET_KEYS. The copy gets the visibility below VISIBILITY_KEY,
    which the text output and the JSON output read. The argument does
    not change.

    Raises Refusal for the visibility `refused`: the command stops
    before it makes an output.
    """
    if visibility not in VISIBILITIES:
        raise ValueError(f"unknown target visibility {visibility!r}")
    if visibility == "refused":
        raise Refusal(
            "The terminal does not show the target or a rank of a day that "
            "is open or closing. No flag changes this.")
    redacted = copy.deepcopy(dict(view))
    redacted[VISIBILITY_KEY] = visibility
    if visibility == "shown":
        return redacted
    for key in TARGET_KEYS:
        redacted.pop(key, None)
    sends = redacted.get("sends")
    if isinstance(sends, list):
        redacted["sends"] = [
            {key: value for key, value in send.items()
             if key not in SEND_TARGET_KEYS}
            for send in sends]
    return redacted


# ---- the guards of a change (spec OC1 sections 4, 5, and 6) ----


def code_output_allowed(stdout_is_tty: bool, code_to_pipe: bool) -> bool:
    """Can the command print a recovery code. A code goes to a terminal,
    or to a pipe with the flag `--code-to-pipe` (ruling D9)."""
    return stdout_is_tty or code_to_pipe


def needs_terminal(command: Command, assume_yes: bool,
                   stdin_is_tty: bool) -> bool:
    """Does the command have a question that no person and no flag can
    answer: a `yes` command with no `--yes` and no terminal on the
    standard input."""
    return command.confirm == "yes" and not assume_yes and not stdin_is_tty


def check_terminal(command: Command, question: str | None, assume_yes: bool,
                   stdin_is_tty: bool) -> None:
    """Refuse a question that nothing can answer, before a change.

    question is the answer of `confirmation_for`. With None the command
    has no question and this guard does nothing.
    """
    if question is not None \
            and needs_terminal(command, assume_yes, stdin_is_tty):
        raise Refusal(
            f"sv {journal_name(command)} asks a question, and the standard "
            "input is not a terminal. Give --yes to answer it from a "
            "script. Nothing changed.")


def check_loopback(url: str) -> str:
    """The base address of the server, when it is on this computer.

    Accepts the scheme `http` and the hosts `127.0.0.1`, `::1`, and
    `localhost`, with a port or with none. The answer has no slash at
    its end. Raises Refusal for each other address, thus the operator
    token does not go to a different computer (spec OC1 section 4).
    """
    refusal = Refusal(
        "--base-url takes a loopback address alone, for example "
        "http://127.0.0.1:8000. The operator token does not go to a "
        "different computer.")
    if not isinstance(url, str) or "\\" in url \
            or any(mark.isspace() or not mark.isprintable() for mark in url):
        raise refusal
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise refusal from error
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        raise refusal
    if parts.username is not None or parts.password is not None \
            or parts.query or parts.fragment:
        raise refusal
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    address = host if port is None else f"{host}:{port}"
    return f"http://{address}{parts.path.rstrip('/')}"


def deletion_confirmed(name: str, typed: str | None) -> bool:
    """Is the typed copy equal to the username. `--yes` is not an input
    here, thus it cannot replace the typed copy (spec MD1 section 8)."""
    return typed is not None and typed == name


def match_session(prefix: str, ids: Sequence[str]) -> str:
    """The one session identifier that starts with the prefix.

    Raises Refusal for a prefix of less than SESSION_PREFIX_MIN
    characters, for no session, and for two sessions or more.
    """
    if len(prefix) < SESSION_PREFIX_MIN:
        raise Refusal(f"--session takes the first {SESSION_PREFIX_MIN} "
                      "characters of a session id, or more")
    found = [session for session in ids if session.startswith(prefix)]
    if not found:
        raise Refusal("no live session starts with that id")
    if len(found) > 1:
        raise Refusal(f"{len(found)} sessions start with that id - give "
                      "more characters")
    return found[0]


def actor_of(environ: Mapping[str, str],
             effective_name: str) -> tuple[str, str]:
    """The login name of the operator and where it came from.

    The script of spec OC1 section 5 gives the name in LOGIN_VARIABLE
    and its source in LOGIN_SOURCE_VARIABLE. With the two not set, the
    name is effective_name, the user of the process, and the source is
    EFFECTIVE_USER_SOURCE.

    Raises Refusal for one of the two with no partner, for a source that
    the script cannot name, and for a name that is not 1 to 64
    characters of letters, digits, and `. _ -`.
    """
    login = environ.get(LOGIN_VARIABLE)
    source = environ.get(LOGIN_SOURCE_VARIABLE)
    if login is None and source is None:
        login, source = effective_name, EFFECTIVE_USER_SOURCE
    elif login is None or source is None:
        raise Refusal(f"{LOGIN_VARIABLE} and {LOGIN_SOURCE_VARIABLE} come "
                      "together: one is set and one is not")
    elif source not in SCRIPT_LOGIN_SOURCES:
        raise Refusal(f"{LOGIN_SOURCE_VARIABLE} must be one of "
                      f"{', '.join(SCRIPT_LOGIN_SOURCES)}")
    if not isinstance(login, str) or not _LOGIN_RULE.fullmatch(login):
        raise Refusal("the operator login name must be 1 to 64 characters "
                      "of letters, digits, and . _ -")
    return login, source


# ---- the journal (spec OC1 section 7) ----


def _is_fact_text(value: object) -> bool:
    return isinstance(value, str) and _FACT_RULE.fullmatch(value) is not None


def _checked_facts(facts: Mapping[str, object] | None) -> dict[str, object]:
    """A copy of the facts, or a refusal.

    The refusal shows no key and no value: a refused value can be the
    text that the rule keeps out of the journal.
    """
    checked: dict[str, object] = {}
    for key, value in (facts or {}).items():
        if key not in FACT_KEYS:
            raise Refusal("a journal fact has a key that is not one of "
                          f"{', '.join(FACT_KEYS)}")
        if isinstance(value, (bool, int)) or _is_fact_text(value):
            checked[key] = value
        elif isinstance(value, (list, tuple)) \
                and all(_is_fact_text(item) for item in value):
            checked[key] = tuple(value)
        else:
            raise Refusal(
                f"the journal fact {key} must be a bool, an int, a text of "
                "at most 80 characters from letters, digits, the space, and "
                "_ . : , / -, or a sequence of such texts")
    return checked


def journal_fields(*, entry_id: str, phase: str, at: str, login: str,
                   login_source: str, command: Command,
                   player: str | None = None, day: str | None = None,
                   outcome: str | None = None,
                   facts: Mapping[str, object] | None = None,
                   error_kind: str | None = None) -> dict[str, object]:
    """The keyword arguments of one `OperatorEntry` of the store.

    The entry names the command by `journal_name`. facts holds keys of
    FACT_KEYS alone, and each value is a `bool`, an `int`, a short text
    of machine characters, or a sequence of such texts. Thus a
    description, a note, a query, a recovery code, and the message of an
    error cannot go in the journal through this function.

    Raises Refusal for a phase, an outcome, a source, a fact, or an
    error type that breaks a rule of spec OC1 section 7.
    """
    if phase not in PHASES:
        raise Refusal(f"a journal phase must be one of {', '.join(PHASES)}")
    if phase == "start" and outcome is not None:
        raise Refusal("a start record of the journal has no outcome")
    if phase == "end" and outcome not in OUTCOMES:
        raise Refusal("an end record of the journal has one of the "
                      f"outcomes {', '.join(OUTCOMES)}")
    if login_source not in LOGIN_SOURCES:
        raise Refusal("a journal login source must be one of "
                      f"{', '.join(LOGIN_SOURCES)}")
    if error_kind is not None and not (
            isinstance(error_kind, str) and _ERROR_RULE.fullmatch(error_kind)):
        raise Refusal("a journal error type must be 1 to 80 characters of "
                      "letters, digits, and _ . : -")
    return {
        "entry_id": entry_id,
        "phase": phase,
        "at": at,
        "login": login,
        "login_source": login_source,
        "command": journal_name(command),
        "player": player,
        "day": day,
        "outcome": outcome,
        "facts": _checked_facts(facts),
        "error_kind": error_kind,
    }


def error_kind_of(error: BaseException | None,
                  http_status: int | None = None,
                  cause: str | None = None) -> str | None:
    """The type of an error for the journal, and not its message.

    With an HTTP status, the answer is `http-409` or `http-409:refused`:
    the status, and the `cause` field of the server's answer when it is
    a short machine word. A cause with other text becomes OTHER_CAUSE.
    With no status, the answer is the class name of the error. With no
    status and no error, the answer is None.

    The message of an error does not go in the answer: a refusal of the
    model provider can hold the words of a send.
    """
    if http_status is not None:
        if cause is None:
            return f"http-{int(http_status)}"
        legal = isinstance(cause, str) and _CAUSE_RULE.fullmatch(cause)
        return f"http-{int(http_status)}:{cause if legal else OTHER_CAUSE}"
    if error is None:
        return None
    return type(error).__name__
