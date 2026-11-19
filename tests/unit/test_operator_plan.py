"""Unit tests for the rules of the operator command line (spec OC1)."""

import copy
import itertools
import re
from pathlib import Path

import pytest

from service import operator_plan as plan
from service import store

SECRET_TEXT = "ABCD-EFGH secret words!"

# The rules of the store for a journal command name and an error type
# (spec OC1 section 7), written again here: the store keeps them private.
COMMAND_NAME_RULE = re.compile(r"[a-z0-9-]+(?: [a-z0-9-]+)*")
COMMAND_NAME_LIMIT = 64
ERROR_KIND_RULE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")

# Each command of spec OC1 sections 3.1 to 3.4.
SPEC_PATHS = {
    ("status",), ("days",), ("day", "show"), ("day", "send"), ("schedule",),
    ("players", "list"), ("players", "show"), ("players", "history"),
    ("players", "avatar"), ("db", "status"), ("db", "verify"),
    ("db", "query"), ("db", "trials"), ("log",),
    ("day", "open"), ("day", "close"), ("day", "reveal"),
    ("day", "quarantine"), ("schedule", "pause"), ("schedule", "resume"),
    ("schedule", "run"), ("players", "recovery-code"),
    ("players", "restore"), ("players", "revoke"), ("players", "signout"),
    ("players", "describe"), ("players", "avatar-set"),
    ("players", "avatar-clear"), ("players", "delete"),
    ("players", "prune"), ("players", "claim-names"), ("db", "build"),
    ("day", "target"), ("day", "rank"),
    ("day", "rescore"), ("day", "migrate"), ("day", "day-scores"),
    ("db", "export"), ("public",), ("rollup", "assemble"),
    ("pool-keys", "make"),
}

# The facts that give each `yes` command its question.
QUESTION_FACTS = {
    ("day", "close"): {"day": "2026-11-18", "status": "open",
                       "latest": True},
    ("day", "reveal"): {"day": "2026-11-18", "status": "closed",
                        "latest": True},
    ("day", "quarantine"): {"day": "2026-11-18", "player": "mira"},
    ("schedule", "run"): {"day": "2026-11-18", "steps": ("close", "reveal"),
                          "paused": False},
    ("players", "recovery-code"): {"player": "mira"},
    ("players", "restore"): {"player": "mira"},
    ("players", "revoke"): {"player": "mira"},
    ("players", "signout"): {"player": "mira"},
}


# ---- the command table ----


def test_the_command_paths_are_unique_and_cover_the_spec() -> None:
    paths = [command.path for command in plan.COMMANDS]
    assert len(paths) == len(set(paths))
    assert set(paths) == SPEC_PATHS


def test_each_command_holds_legal_fields() -> None:
    for command in plan.COMMANDS:
        assert command.kind in plan.KINDS
        assert command.transport in plan.TRANSPORTS
        assert command.confirm in plan.CONFIRMS
        for method, path in command.covers:
            assert method in ("GET", "POST", "PUT", "DELETE")
            assert path.startswith("/api/")
        # A read and a module command have no question in the table.
        if command.kind != "change":
            assert command.confirm == "none"
        assert (command.kind == "module") == (command.transport == "module")


def test_the_day_moves_go_to_the_server() -> None:
    for words in (("day", "open"), ("day", "close"), ("day", "reveal"),
                  ("schedule", "run")):
        assert plan.command_for(words).transport == "server"
    assert plan.command_for(("players", "revoke")).transport == "store"


def test_the_confirmations_follow_the_spec_table() -> None:
    confirms = {command.path: command.confirm for command in plan.COMMANDS
                if command.kind == "change"}
    assert {path for path, confirm in confirms.items()
            if confirm == "yes"} == set(QUESTION_FACTS)
    assert {path for path, confirm in confirms.items()
            if confirm == "typed-name"} == {("players", "delete")}


def test_no_route_is_covered_and_also_left_out() -> None:
    covered = plan.covered_routes()
    assert not covered & set(plan.NOT_IN_CLI)
    assert ("POST", "/api/dev/players/{name}/revoke") in covered
    assert ("DELETE", "/api/dev/players/{name}/sessions/{session_id}") \
        in covered
    assert ("GET", "/api/ops/trials") in covered
    assert ("POST", "/api/dev/players/{name}/device-code") in plan.NOT_IN_CLI
    assert ("GET", "/api/door") in plan.NOT_IN_CLI
    assert ("POST", "/api/door") in plan.NOT_IN_CLI
    assert all(reason for reason in plan.NOT_IN_CLI.values())


def test_command_for_finds_a_command_and_refuses_unknown_words() -> None:
    command = plan.command_for(["players", "revoke"])
    assert command.path == ("players", "revoke")
    assert plan.journal_name(command) == "players revoke"
    assert plan.journal_name(plan.command_for(("log",))) == "log"
    with pytest.raises(ValueError):
        plan.command_for(("players", "explode"))
    with pytest.raises(plan.Refusal):
        plan.command_for(())


def test_a_command_is_frozen() -> None:
    command = plan.command_for(("days",))
    with pytest.raises(AttributeError):
        command.kind = "change"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.NOT_IN_CLI[("GET", "/x")] = "y"  # type: ignore[index]


def test_each_journal_name_is_legal_for_the_store() -> None:
    for command in plan.COMMANDS:
        name = plan.journal_name(command)
        assert COMMAND_NAME_RULE.fullmatch(name)
        assert len(name) <= COMMAND_NAME_LIMIT


def test_each_module_command_names_a_module_with_a_main() -> None:
    import importlib

    paths = {command.path for command in plan.COMMANDS
             if command.kind == "module"}
    assert set(plan.MODULE_COMMANDS) == paths
    for path, (module, words) in plan.MODULE_COMMANDS.items():
        assert callable(importlib.import_module(module).main), path
        assert all(isinstance(word, str) for word in words)


def test_the_module_arguments_keep_the_words_of_the_operator() -> None:
    rest = ["--config", "x.json", "--from", "2026-11-01", "--json"]
    assert plan.module_argv(plan.command_for(("day", "rescore")),
                            "/etc/sv.json", rest) == (
        "service.day",
        ["--service-config", "/etc/sv.json", "rescore", *rest])
    assert plan.module_argv(plan.command_for(("public",)), "c.json",
                            ["build", "--out", "o"]) == (
        "service.public", ["--service-config", "c.json", "build", "--out",
                           "o"])
    assert plan.module_argv(plan.command_for(("pool-keys", "make")),
                            "c.json", []) == (
        "service.pool_keys", ["--service-config", "c.json", "make"])
    with pytest.raises(plan.Refusal):
        plan.module_argv(plan.command_for(("days",)), "c.json", [])


# ---- the questions ----


@pytest.mark.parametrize("path", sorted(QUESTION_FACTS))
def test_each_yes_command_has_a_question_that_names_its_subject(
        path: tuple[str, ...]) -> None:
    facts = QUESTION_FACTS[path]
    question = plan.confirmation_for(plan.command_for(path), facts)
    assert question
    for key in ("player", "day"):
        if key in facts:
            assert str(facts[key]) in question


def test_a_command_with_no_question_gives_none() -> None:
    for command in plan.COMMANDS:
        if command.confirm != "yes":
            assert plan.confirmation_for(command, {}) is None
    # The typed name is the confirmation of a deletion.
    assert plan.confirmation_for(plan.command_for(("players", "delete")),
                                 {"player": "mira"}) is None


def test_the_close_questions_are_the_words_of_the_console() -> None:
    close = plan.command_for(("day", "close"))
    assert plan.confirmation_for(
        close, {"day": "2026-11-18", "status": "open", "latest": True}) \
        == "Close 2026-11-18? New sends stop, and each send is scored now."
    assert plan.confirmation_for(
        close, {"day": "2026-11-17", "status": "closing", "latest": False}) \
        == ("2026-11-17 is still closing behind a newer day. Close it and "
            "score its sends?")
    finish = plan.confirmation_for(
        close, {"day": "2026-11-18", "status": "closing", "latest": True})
    assert finish.startswith("Finish closing 2026-11-18?")
    assert "can't be reopened" in finish


def test_the_reveal_questions_are_the_words_of_the_console() -> None:
    reveal = plan.command_for(("day", "reveal"))
    assert plan.confirmation_for(
        reveal, {"day": "2026-11-18", "status": "closed", "latest": True}) \
        == "Reveal 2026-11-18? Players see the photo and their results."
    assert plan.confirmation_for(
        reveal, {"day": "2026-11-17", "status": "closed", "latest": False}) \
        == ("2026-11-17 stayed closed behind a newer day. Reveal it? "
            "Players see its photo and results.")


def test_a_day_move_refuses_a_status_it_cannot_move() -> None:
    close = plan.command_for(("day", "close"))
    reveal = plan.command_for(("day", "reveal"))
    for status in ("closed", "revealed"):
        with pytest.raises(plan.Refusal):
            plan.confirmation_for(
                close, {"day": "2026-11-18", "status": status,
                        "latest": True})
    for status in ("open", "closing", "revealed"):
        with pytest.raises(plan.Refusal):
            plan.confirmation_for(
                reveal, {"day": "2026-11-18", "status": status,
                         "latest": True})


def test_a_question_with_a_fact_not_there_raises() -> None:
    with pytest.raises(ValueError):
        plan.confirmation_for(plan.command_for(("players", "revoke")), {})
    with pytest.raises(ValueError):
        plan.confirmation_for(plan.command_for(("day", "close")),
                              {"day": "2026-11-18"})


def test_the_recovery_code_question_holds_the_hold_of_24_hours() -> None:
    question = plan.confirmation_for(
        plan.command_for(("players", "recovery-code")), {"player": "mira"})
    assert question.startswith("Make a recovery code for mira?")
    assert "works only after 24 hours" in question
    assert "shows a notice" in question
    restore = plan.confirmation_for(
        plan.command_for(("players", "restore")), {"player": "mira"})
    assert "works only after 24 hours" in restore


def test_the_revoke_question_is_the_words_of_the_console() -> None:
    assert plan.confirmation_for(
        plan.command_for(("players", "revoke")), {"player": "mira"}) == (
        "Revoke mira? Every signed-in device stops working, and the "
        "password and each recovery code sign nobody in. Their play stays "
        "stored.")


def test_a_sign_out_asks_for_each_device_and_not_for_one_session() -> None:
    signout = plan.command_for(("players", "signout"))
    assert plan.confirmation_for(signout, {"player": "mira"}) \
        == "Sign mira out on every device?"
    assert plan.confirmation_for(
        signout, {"player": "mira", "session": None}) \
        == "Sign mira out on every device?"
    assert plan.confirmation_for(
        signout, {"player": "mira", "session": "abcdef012345"}) is None


def test_the_run_question_joins_the_steps_and_says_the_pause() -> None:
    run = plan.command_for(("schedule", "run"))
    facts = {"day": "2026-11-18", "opens": "2026-11-19",
             "steps": ("close", "reveal", "open"), "paused": False}
    question = plan.confirmation_for(run, facts)
    assert question == ("Close 2026-11-18 and score it, then Reveal "
                        "2026-11-18, then Open 2026-11-19 — now?")
    paused = plan.confirmation_for(run, facts | {"paused": True})
    assert paused.startswith(question)
    assert "The automatic days are paused" in paused
    assert "does not read the pause" in paused
    assert "paused" not in question


def test_the_run_question_refuses_no_step_and_an_unknown_step() -> None:
    run = plan.command_for(("schedule", "run"))
    with pytest.raises(plan.Refusal):
        plan.confirmation_for(run, {"steps": (), "paused": False})
    with pytest.raises(ValueError):
        plan.confirmation_for(run, {"steps": ("wait",), "paused": False})
    with pytest.raises(ValueError):
        plan.confirmation_for(run, {"steps": "close", "paused": False})
    assert plan.confirmation_for(
        run, {"steps": ("open",), "paused": False}) \
        == "Open the next day — now?"


def test_the_show_target_question_names_the_day() -> None:
    question = plan.shows_target_question("2026-11-18")
    assert "2026-11-18" in question
    assert "ends a blind view" in question


@pytest.mark.parametrize("answer,expected", [
    ("yes", True), (" yes\n", True), ("YES", True), ("Yes", True),
    ("y", False), ("", False), ("no", False), ("yes please", False),
    ("yes, close and score", False),
])
def test_accepts_takes_the_word_yes_alone(answer: str,
                                          expected: bool) -> None:
    assert plan.accepts(answer) is expected


# ---- the target and the rank ----


def _expected_visibility(status: str, protocol: str, has_target: bool,
                         show_target: bool) -> str:
    table = {
        # (status, vp1 with no target, show_target)
        ("revealed", False, False): "shown",
        ("revealed", False, True): "shown",
        ("revealed", True, False): "shown",
        ("revealed", True, True): "shown",
        ("closed", False, False): "hidden",
        ("closed", False, True): "shown",
        ("closed", True, False): "hidden",
        ("closed", True, True): "shown",
        ("open", False, False): "hidden",
        ("open", False, True): "refused",
        ("open", True, False): "none-yet",
        ("open", True, True): "none-yet",
        ("closing", False, False): "hidden",
        ("closing", False, True): "refused",
        ("closing", True, False): "none-yet",
        ("closing", True, True): "none-yet",
    }
    return table[(status, protocol == "vp1" and not has_target, show_target)]


@pytest.mark.parametrize("status,protocol,has_target,show_target", list(
    itertools.product(plan.DAY_STATUSES, plan.PROTOCOLS, (False, True),
                      (False, True))))
def test_the_full_table_of_target_visibility(
        status: str, protocol: str, has_target: bool,
        show_target: bool) -> None:
    assert plan.target_visibility(status, protocol, has_target, show_target) \
        == _expected_visibility(status, protocol, has_target, show_target)


def test_no_flag_shows_the_target_of_an_open_or_closing_day() -> None:
    for status, protocol, has_target, show_target in itertools.product(
            ("open", "closing"), plan.PROTOCOLS, (False, True),
            (False, True)):
        assert plan.target_visibility(status, protocol, has_target,
                                      show_target) != "shown"


def test_target_visibility_raises_for_an_unknown_status_or_protocol() -> None:
    with pytest.raises(ValueError):
        plan.target_visibility("none", "vp1", False, False)
    with pytest.raises(ValueError):
        plan.target_visibility("open", "commit-v2", True, False)


def test_rank_allowed_refuses_an_open_and_a_closing_day() -> None:
    assert plan.rank_allowed("open") is False
    assert plan.rank_allowed("closing") is False
    assert plan.rank_allowed("closed") is True
    assert plan.rank_allowed("revealed") is True
    with pytest.raises(ValueError):
        plan.rank_allowed("none")


def test_the_show_target_question_is_for_a_closed_day_with_the_flag() -> None:
    for status in plan.DAY_STATUSES:
        assert plan.shows_target_needs_question(status, False) is False
        assert plan.shows_target_needs_question(status, True) \
            is (status == "closed")
    with pytest.raises(ValueError):
        plan.shows_target_needs_question("none", True)


def _day_view() -> dict:
    return {
        "day": "2026-11-18", "status": "closed", "trial_code": "K3P9QZ",
        "target_id": "a" * 64, "commitment": "c" * 64, "secret": "s3cr3t",
        "pick_seed": "seed", "target_index": 4, "target_salt": "salt",
        "target_proof": ["p1", "p2"],
        "credit": {"source": "Wikimedia Commons", "title": "A bridge",
                   "page": "https://commons.wikimedia.org/wiki/File:B.jpg"},
        "sends": [
            {"player": "mira", "display_name": "Mira",
             "received_at": "2026-11-18T10:00:00+00:00", "trial_id": "t1",
             "trial": {"p": 0.9, "target_rank": 3, "decoy_count": 20,
                       "beaten": 18, "tied": 0}},
            {"player": "odo", "display_name": "Odo",
             "received_at": "2026-11-18T11:00:00+00:00", "trial_id": "t2",
             "trial": None},
        ],
    }


@pytest.mark.parametrize("visibility", ["hidden", "none-yet"])
def test_redact_day_drops_each_key_that_gives_the_target(
        visibility: str) -> None:
    view = _day_view()
    before = copy.deepcopy(view)
    redacted = plan.redact_day(view, visibility)
    for key in ("target_id", "credit", "secret", "pick_seed",
                "target_index", "target_salt", "target_proof", "trial"):
        assert key not in redacted
    assert all("trial" not in send for send in redacted["sends"])
    assert [send["player"] for send in redacted["sends"]] == ["mira", "odo"]
    assert redacted["commitment"] == "c" * 64
    assert redacted["trial_code"] == "K3P9QZ"
    assert redacted[plan.VISIBILITY_KEY] == visibility
    # The target does not come back through a nested value.
    assert "a" * 64 not in repr(redacted)
    assert view == before


def test_redact_day_keeps_a_shown_view_and_does_not_mutate() -> None:
    view = _day_view()
    before = copy.deepcopy(view)
    shown = plan.redact_day(view, "shown")
    assert shown == before | {plan.VISIBILITY_KEY: "shown"}
    shown["sends"][0]["trial"]["p"] = 0.0
    shown["credit"]["title"] = "changed"
    assert view == before


def test_redact_day_drops_the_trial_of_a_history_row() -> None:
    row = {"day": "2026-11-18", "status": "closed", "trial_code": "K3P9QZ",
           "target_id": "a" * 64, "submitted": True,
           "trial": {"p": 0.9, "target_rank": 3, "decoy_count": 20,
                     "beaten": 18, "tied": 0}}
    assert plan.redact_day(row, "hidden") == {
        "day": "2026-11-18", "status": "closed", "trial_code": "K3P9QZ",
        "submitted": True, plan.VISIBILITY_KEY: "hidden"}


def test_redact_day_refuses_the_refused_visibility() -> None:
    with pytest.raises(plan.Refusal):
        plan.redact_day(_day_view(), "refused")
    with pytest.raises(ValueError):
        plan.redact_day(_day_view(), "visible")


# ---- the guards of a change ----


def test_a_code_goes_to_a_terminal_or_to_a_pipe_with_the_flag() -> None:
    assert plan.code_output_allowed(True, False) is True
    assert plan.code_output_allowed(True, True) is True
    assert plan.code_output_allowed(False, True) is True
    assert plan.code_output_allowed(False, False) is False


def test_needs_terminal_is_for_a_yes_command_with_no_answer() -> None:
    revoke = plan.command_for(("players", "revoke"))
    assert plan.needs_terminal(revoke, False, False) is True
    assert plan.needs_terminal(revoke, True, False) is False
    assert plan.needs_terminal(revoke, False, True) is False
    for words in (("days",), ("day", "open"), ("players", "delete"),
                  ("public",)):
        assert plan.needs_terminal(plan.command_for(words), False,
                                   False) is False


def test_check_terminal_refuses_before_a_change() -> None:
    revoke = plan.command_for(("players", "revoke"))
    with pytest.raises(plan.Refusal) as refusal:
        plan.check_terminal(revoke, "Revoke mira?", False, False)
    assert "--yes" in str(refusal.value)
    plan.check_terminal(revoke, "Revoke mira?", True, False)
    plan.check_terminal(revoke, "Revoke mira?", False, True)
    # A sign-out of one session has no question.
    plan.check_terminal(plan.command_for(("players", "signout")), None,
                        False, False)


@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
    ("http://localhost:8000", "http://localhost:8000"),
    ("http://LOCALHOST", "http://localhost"),
    ("http://[::1]:8000", "http://[::1]:8000"),
    ("HTTP://127.0.0.1:8000", "http://127.0.0.1:8000"),
])
def test_check_loopback_accepts_the_three_hosts(url: str,
                                                expected: str) -> None:
    assert plan.check_loopback(url) == expected


@pytest.mark.parametrize("url", [
    "http://example.com",
    "https://127.0.0.1",
    "https://localhost:8000",
    "http://user:pass@127.0.0.1:8000",
    "http://user@127.0.0.1",
    "http://127.0.0.1:8000@example.com",
    "http://127.0.0.1.example.com",
    "http://localhost.example.com:8000",
    "http://127.0.0.2:8000",
    "http://0.0.0.0:8000",
    "http://10.0.0.5:8000",
    "http://127.0.0.1:8000?next=http://example.com",
    "http://127.0.0.1:8000#fragment",
    "http://127.0.0.1:notaport",
    "http://127.0.0.1\\@example.com",
    "http://127.0.0.1 :8000",
    "http://127.0.0.1:8000\n",
    "127.0.0.1:8000",
    "//127.0.0.1:8000",
    "ftp://127.0.0.1",
    "",
])
def test_check_loopback_refuses_each_other_address(url: str) -> None:
    with pytest.raises(plan.Refusal):
        plan.check_loopback(url)


def test_a_deletion_takes_the_typed_name_alone() -> None:
    assert plan.deletion_confirmed("mira", "mira") is True
    assert plan.deletion_confirmed("mira", None) is False
    assert plan.deletion_confirmed("mira", "Mira") is False
    assert plan.deletion_confirmed("mira", "mira ") is False
    assert plan.deletion_confirmed("mira", "yes") is False
    assert plan.deletion_confirmed("mira", "") is False


def test_match_session_gives_the_one_session() -> None:
    ids = ["abcdef0123456789", "abcdff0123456789", "0123456789abcdef"]
    assert plan.match_session("abcdef", ids) == "abcdef0123456789"
    assert plan.match_session("0123456789abcdef", ids) == "0123456789abcdef"
    with pytest.raises(plan.Refusal):
        plan.match_session("abcd", ids)
    with pytest.raises(plan.Refusal):
        plan.match_session("abcd" + "f", ["abcdf"])
    with pytest.raises(plan.Refusal):
        plan.match_session("ffffff", ids)
    with pytest.raises(plan.Refusal):
        plan.match_session("abcdef", [])
    with pytest.raises(plan.Refusal):
        plan.match_session("abcdef", ["abcdef01", "abcdef02"])


def test_actor_of_reads_the_script_values() -> None:
    assert plan.actor_of(
        {"STARVECTOR_OPERATOR_LOGIN": "ade",
         "STARVECTOR_OPERATOR_LOGIN_SOURCE": "login-uid"},
        "starvector") == ("ade", "login-uid")
    assert plan.actor_of(
        {"STARVECTOR_OPERATOR_LOGIN": "first.last_2-x",
         "STARVECTOR_OPERATOR_LOGIN_SOURCE": "sudo-user", "HOME": "/root"},
        "starvector") == ("first.last_2-x", "sudo-user")


def test_actor_of_gives_the_effective_user_with_no_script() -> None:
    assert plan.actor_of({}, "ade") == ("ade", "effective-user")
    assert plan.actor_of({"HOME": "/home/ade"}, "ade") \
        == ("ade", "effective-user")
    with pytest.raises(plan.Refusal):
        plan.actor_of({}, "bad name")


@pytest.mark.parametrize("environ", [
    {"STARVECTOR_OPERATOR_LOGIN": "ade"},
    {"STARVECTOR_OPERATOR_LOGIN_SOURCE": "login-uid"},
    {"STARVECTOR_OPERATOR_LOGIN": "ade",
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "effective-user"},
    {"STARVECTOR_OPERATOR_LOGIN": "ade",
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "guess"},
    {"STARVECTOR_OPERATOR_LOGIN": "",
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "login-uid"},
    {"STARVECTOR_OPERATOR_LOGIN": "ade; rm -rf",
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "login-uid"},
    {"STARVECTOR_OPERATOR_LOGIN": "ade\n",
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "sudo-user"},
    {"STARVECTOR_OPERATOR_LOGIN": "a" * 65,
     "STARVECTOR_OPERATOR_LOGIN_SOURCE": "sudo-user"},
])
def test_actor_of_refuses_a_bad_login_or_source(environ: dict) -> None:
    with pytest.raises(plan.Refusal):
        plan.actor_of(environ, "starvector")


def test_the_exit_codes_are_the_codes_of_the_spec() -> None:
    assert (plan.EXIT_DONE, plan.EXIT_REFUSED, plan.EXIT_LOCKED,
            plan.EXIT_NO_END_RECORD) == (0, 1, 2, 3)


# ---- the journal ----


def _fields(**changes: object) -> dict:
    values: dict = {
        "entry_id": "0123456789abcdef", "phase": "start",
        "at": "2026-11-19T10:00:00+00:00", "login": "ade",
        "login_source": "login-uid",
        "command": plan.command_for(("players", "revoke")),
        "player": "mira"}
    values.update(changes)
    return plan.journal_fields(**values)


def test_the_journal_rules_equal_the_rules_of_the_store() -> None:
    assert plan.FACT_KEYS == store.OPERATOR_FACT_KEYS
    assert plan.PHASES == store.OPERATOR_PHASES
    assert plan.OUTCOMES == store.OPERATOR_OUTCOMES
    assert set(plan.LOGIN_SOURCES) == set(store.OPERATOR_LOGIN_SOURCES)


def test_journal_fields_build_an_entry_of_the_store(tmp_path: Path) -> None:
    start = _fields()
    assert start == {
        "entry_id": "0123456789abcdef", "phase": "start",
        "at": "2026-11-19T10:00:00+00:00", "login": "ade",
        "login_source": "login-uid", "command": "players revoke",
        "player": "mira", "day": None, "outcome": None, "facts": {},
        "error_kind": None}
    end = _fields(phase="end", outcome="done",
                  facts={"ended": 2, "steps": ["close", "reveal"],
                         "paused": False, "field": "description"})
    assert end["facts"] == {"ended": 2, "steps": ("close", "reveal"),
                            "paused": False, "field": "description"}
    # The store accepts the two records as they are.
    store.write_operator_entry(tmp_path, store.OperatorEntry(**start))
    store.write_operator_entry(tmp_path, store.OperatorEntry(**end))
    stored = store.list_operator_entries(tmp_path)
    assert [entry.phase for entry in stored] == ["start", "end"]
    assert stored[1].facts["steps"] == ("close", "reveal")
    assert all(entry.command == "players revoke" for entry in stored)


def test_journal_fields_refuse_an_unknown_fact_key() -> None:
    for key in ("note", "description", "query", "code", "detail", "error"):
        with pytest.raises(plan.Refusal) as refusal:
            _fields(facts={key: "x"})
        assert SECRET_TEXT not in str(refusal.value)


@pytest.mark.parametrize("value", [
    SECRET_TEXT,
    "a description with a question?",
    "x" * 81,
    "line one\nline two",
    "\x1b[2J",
    "naïve",
    1.5,
    None,
    {"nested": "value"},
    ["close", SECRET_TEXT],
    [1, 2],
])
def test_journal_fields_refuse_a_free_text_value(value: object) -> None:
    with pytest.raises(plan.Refusal) as refusal:
        _fields(facts={"field": value})
    assert SECRET_TEXT not in str(refusal.value)


def test_journal_fields_do_not_mutate_the_facts() -> None:
    facts = {"steps": ["close"], "ended": 1}
    fields = _fields(phase="end", outcome="done", facts=facts)
    assert facts == {"steps": ["close"], "ended": 1}
    assert fields["facts"] is not facts


def test_journal_fields_refuse_a_phase_and_an_outcome_out_of_the_rules(
        ) -> None:
    with pytest.raises(plan.Refusal):
        _fields(phase="middle")
    with pytest.raises(plan.Refusal):
        _fields(phase="start", outcome="done")
    with pytest.raises(plan.Refusal):
        _fields(phase="end")
    with pytest.raises(plan.Refusal):
        _fields(phase="end", outcome="ok")
    with pytest.raises(plan.Refusal):
        _fields(login_source="guess")
    with pytest.raises(plan.Refusal) as refusal:
        _fields(phase="end", outcome="failed", error_kind=SECRET_TEXT)
    assert SECRET_TEXT not in str(refusal.value)
    assert _fields(phase="end", outcome="failed",
                   error_kind="http-409:refused")["error_kind"] \
        == "http-409:refused"


def test_error_kind_of_gives_the_type_and_not_the_message() -> None:
    assert plan.error_kind_of(None) is None
    error = store.StoreError(SECRET_TEXT)
    assert plan.error_kind_of(error) == "StoreError"
    assert plan.error_kind_of(ValueError(SECRET_TEXT)) == "ValueError"
    assert plan.error_kind_of(None, 409, "refused") == "http-409:refused"
    assert plan.error_kind_of(None, 401) == "http-401"
    assert plan.error_kind_of(error, 400, "close-failed") \
        == "http-400:close-failed"
    # A cause with free text does not go in the journal.
    assert plan.error_kind_of(None, 400, SECRET_TEXT) == "http-400:other"
    assert plan.error_kind_of(None, 400, "") == "http-400:other"


@pytest.mark.parametrize("error,status,cause", [
    (RuntimeError(SECRET_TEXT), None, None),
    (store.StoreError(SECRET_TEXT), 409, SECRET_TEXT),
    (None, 500, SECRET_TEXT),
    (KeyError(SECRET_TEXT), None, SECRET_TEXT),
])
def test_error_kind_of_is_legal_for_the_journal(
        error: BaseException | None, status: int | None,
        cause: str | None) -> None:
    kind = plan.error_kind_of(error, status, cause)
    assert kind is not None
    assert SECRET_TEXT not in kind
    assert "secret" not in kind
    assert ERROR_KIND_RULE.fullmatch(kind)
    assert _fields(phase="end", outcome="failed",
                   error_kind=kind)["error_kind"] == kind
