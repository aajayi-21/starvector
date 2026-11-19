"""Unit tests for the output of the operator command line (spec OC1)."""

import copy
import json

import pytest

from service import operator_plan as plan
from service import operator_view as view

ESC = "\x1b"
# A text that clears the screen and sets the window title on a terminal
# that obeys it.
PLANTED = f"{ESC}[2J{ESC}]0;owned\x07 nice bridge\r\nsecond line \u202eevil"


def _no_raw_control(lines: list[str]) -> None:
    """No line holds a control character, a direction mark, or a line
    end."""
    for line in lines:
        assert isinstance(line, str)
        for mark in line:
            assert mark.isprintable(), (mark, line)
        assert ESC not in line
        assert "\u202e" not in line


# ---- safe_text ----


def test_safe_text_changes_an_escape_sequence_to_a_code() -> None:
    assert view.safe_text(f"{ESC}[31mred{ESC}[0m") == "\\x1b[31mred\\x1b[0m"
    assert view.safe_text("\x07\x00\x7f\x9b") == "\\x07\\x00\\x7f\\x9b"


def test_safe_text_keeps_one_value_on_one_line() -> None:
    assert view.safe_text("one\ntwo") == "one\\ntwo"
    assert view.safe_text("one\r\ntwo\ttab") == "one\\r\\ntwo\\ttab"
    assert view.safe_text("a\u2028b\u2029c") == "a\\u2028b\\u2029c"


def test_safe_text_changes_the_direction_and_width_marks() -> None:
    assert view.safe_text("abc\u202edef") == "abc\\u202edef"
    assert view.safe_text("\u2066x\u2069") == "\\u2066x\\u2069"
    assert view.safe_text("a\u200bb\u200fc") == "a\\u200bb\\u200fc"
    assert view.safe_text("\ufeffx") == "\\ufeffx"
    assert view.safe_text("\U000e0001") == "\\U000e0001"


@pytest.mark.parametrize("text", [
    "", "plain text 123", "naïve café", "Łódź", "日本語のテキスト",
    "Ελληνικά", "emoji 🌉 bridge", "back\\slash and 'quotes' \"too\"",
    "~!@#$%^&*()_+-=[]{}|;:,.<>?/",
])
def test_safe_text_keeps_printable_text(text: str) -> None:
    assert view.safe_text(text) == text


def test_safe_text_takes_a_str_alone() -> None:
    with pytest.raises(TypeError):
        view.safe_text(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        view.safe_text(b"bytes")  # type: ignore[arg-type]


# ---- days and sends ----


def _day_view() -> dict:
    return {
        "day": "2026-11-18", "status": "revealed", "trial_code": "K3P9QZ",
        "target_id": "a" * 64, "commitment": "c" * 64,
        "opened_at": "2026-11-18T00:00:05+00:00",
        "closed_at": "2026-11-19T00:00:07+00:00",
        "revealed_at": "2026-11-19T00:01:00+00:00",
        "closes_at": "2026-11-19T00:00:00+00:00",
        "scoring_config_hash": "h" * 64,
        "preparation_version_id": "prep-1",
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


def test_day_rows_lines_show_the_code_the_status_and_the_sends() -> None:
    rows = [
        {"day": "2026-11-18", "status": "open", "trial_code": "K3P9QZ",
         "target_id": "a" * 64, "commitment": "c" * 64, "submitted": False,
         "sends": 4, "quarantined": 0},
        {"day": "2026-11-17", "status": "revealed", "trial_code": "AAAAAA",
         "target_id": "b" * 64, "commitment": None, "submitted": True,
         "sends": 7, "quarantined": 1},
    ]
    assert view.day_rows_lines(rows) == [
        "2026-11-18  K3P9QZ  open  sends=4",
        "2026-11-17  AAAAAA  revealed  sends=7  quarantined=1",
    ]
    assert view.day_rows_lines([]) == ["no stored day"]


def test_day_lines_of_a_shown_day() -> None:
    lines = view.day_lines(plan.redact_day(_day_view(), "shown"))
    assert lines == [
        "day 2026-11-18",
        "trial code K3P9QZ",
        "status revealed",
        "opened 2026-11-18T00:00:05+00:00",
        "closes 2026-11-19T00:00:00+00:00",
        "closed 2026-11-19T00:00:07+00:00",
        "revealed 2026-11-19T00:01:00+00:00",
        "commitment " + "c" * 64,
        "scoring config " + "h" * 64,
        "preparation prep-1",
        "target " + "a" * 64,
        "credit A bridge - Wikimedia Commons",
        "page https://commons.wikimedia.org/wiki/File:B.jpg",
        "sends 2",
        "  2026-11-18T10:00:00+00:00  mira  trial=t1  p=0.9  rank=3  "
        "decoys=20  beaten=18  tied=0  Mira",
        "  2026-11-18T11:00:00+00:00  odo  trial=t2  no trial row  Odo",
    ]


def test_day_lines_of_a_hidden_day_hold_no_target_and_no_score() -> None:
    closed = _day_view() | {"status": "closed", "revealed_at": None}
    lines = view.day_lines(plan.redact_day(closed, "hidden"))
    text = "\n".join(lines)
    assert "a" * 64 not in text
    assert "A bridge" not in text
    assert "p=" not in text and "rank=" not in text
    assert "target not shown: the day is not revealed" in lines
    assert "sends 2" in lines
    assert "  2026-11-18T10:00:00+00:00  mira  trial=t1  Mira" in lines


def test_day_lines_of_a_vp1_day_before_its_close() -> None:
    day = _day_view() | {"status": "open", "target_id": None,
                         "credit": None, "commitment": None,
                         "closed_at": None, "revealed_at": None}
    day["sends"] = [send | {"trial": None} for send in day["sends"]]
    lines = view.day_lines(plan.redact_day(day, "none-yet"))
    assert "no target until the close" in lines
    text = "\n".join(lines).lower()
    # Spec VP1 section 8: no line says that a photo is hidden.
    assert "hidden" not in text
    assert "not shown" not in text
    assert "photo" not in text


def test_day_lines_refuse_a_view_that_is_not_redacted() -> None:
    with pytest.raises(ValueError):
        view.day_lines(_day_view())
    with pytest.raises(ValueError):
        view.day_lines(_day_view() | {view.VISIBILITY_KEY: "refused"})
    with pytest.raises(ValueError):
        view.day_lines(_day_view() | {view.VISIBILITY_KEY: "shown",
                                      "target_id": None})


def test_the_two_modules_name_the_same_visibility_key() -> None:
    assert view.VISIBILITY_KEY == plan.VISIBILITY_KEY


def test_target_lines_with_a_credit_and_with_none() -> None:
    assert view.target_lines("a" * 64, None) == ["target " + "a" * 64,
                                                 "credit none"]
    assert view.target_lines(
        "a" * 64, {"source": "example.org", "title": f"x{ESC}[2J",
                   "page": "https://example.org/x"}) == [
        "target " + "a" * 64,
        "credit x\\x1b[2J - example.org",
        "page https://example.org/x"]


def _stored_send() -> dict:
    return {
        "day": "2026-11-18", "player": "mira", "trial_id": "t1",
        "received_at": "2026-11-18T10:00:00+00:00",
        "record": {
            "impressions": ["a tall bridge", "cold water"],
            "canvas_strokes": [{"points": [[0.1, 0.2], [0.3, 0.4]],
                                "group_id": "g1"}],
            "groups": [{"id": "g1", "label": "tower"},
                       {"id": "g2", "label": ""}],
            "relations": [{"relation": "above", "of": ["g1", "g2"]}],
            "pasted_text": "pasted notes",
        },
    }


def test_send_lines_show_each_text_of_the_send() -> None:
    assert view.send_lines(_stored_send()) == [
        "day 2026-11-18",
        "player mira",
        "trial t1",
        "received 2026-11-18T10:00:00+00:00",
        "strokes 1  groups 2  relations 1",
        "impression: a tall bridge",
        "impression: cold water",
        "group: tower (g1)",
        "group: g2",
        "relation: tower (g1) above g2",
        "pasted: pasted notes",
    ]
    no_paste = _stored_send()
    no_paste["record"]["pasted_text"] = None
    assert not any(line.startswith("pasted")
                   for line in view.send_lines(no_paste))


def test_a_planted_sequence_in_a_send_does_not_come_out_raw() -> None:
    send = _stored_send()
    send["record"]["impressions"] = [PLANTED]
    send["record"]["groups"][0]["label"] = PLANTED
    send["record"]["groups"][1]["id"] = f"g2{ESC}[1m"
    send["record"]["relations"] = [
        {"relation": PLANTED, "of": ["g1", f"g2{ESC}[1m"]}]
    send["record"]["pasted_text"] = PLANTED
    before = copy.deepcopy(send)
    lines = view.send_lines(send)
    _no_raw_control(lines)
    assert "impression: \\x1b[2J\\x1b]0;owned\\x07 nice bridge\\r\\n" \
           "second line \\u202eevil" in lines
    # Each text of the player is one line.
    assert sum(line.startswith("impression: ") for line in lines) == 1
    assert sum(line.startswith("pasted: ") for line in lines) == 1
    assert send == before


def test_history_lines_show_a_score_for_a_shown_day_alone() -> None:
    trial = {"p": 0.5, "target_rank": 11, "decoy_count": 20, "beaten": 10,
             "tied": 0}
    rows = [
        plan.redact_day({"day": "2026-11-18", "status": "closed",
                         "trial_code": "K3P9QZ", "target_id": "a" * 64,
                         "submitted": True, "trial": trial}, "hidden"),
        plan.redact_day({"day": "2026-11-17", "status": "revealed",
                         "trial_code": "AAAAAA", "target_id": "b" * 64,
                         "submitted": True, "trial": trial}, "shown"),
        plan.redact_day({"day": "2026-11-16", "status": "revealed",
                         "trial_code": "BBBBBB", "target_id": "c" * 64,
                         "submitted": False, "trial": None}, "shown"),
    ]
    assert view.history_lines({"player": "mira", "days": rows}) == [
        "player mira",
        "2026-11-18  K3P9QZ  closed  sent=yes",
        "2026-11-17  AAAAAA  revealed  sent=yes  p=0.5  rank=11  decoys=20  "
        "beaten=10  tied=0",
        "2026-11-16  BBBBBB  revealed  sent=no",
    ]
    assert view.history_lines({"player": "mira", "days": []}) == [
        "player mira", "no stored day"]
    with pytest.raises(ValueError):
        view.history_lines({"player": "mira", "days": [
            {"day": "2026-11-18", "status": "closed", "trial_code": "K3P9QZ",
             "target_id": "a" * 64, "submitted": True, "trial": trial}]})


def test_trial_lines_show_each_revealed_row() -> None:
    rows = [{"day": "2026-11-17", "trial_code": "AAAAAA", "player": "mira",
             "display_name": f"Mira{ESC}[5m", "p": 0.75, "target_rank": 6,
             "decoy_count": 20, "beaten": 15, "tied": 0,
             "scoring_config_hash": "h" * 64,
             "preparation_version_id": "prep-1",
             "received_at": "2026-11-17T10:00:00+00:00",
             "target_id": "b" * 64}]
    assert view.trial_lines(rows) == [
        "2026-11-17  mira  p=0.75  rank=6  decoys=20  beaten=15  tied=0  "
        "target=" + "b" * 64 + "  Mira\\x1b[5m"]
    assert view.trial_lines(rows, truncated=True)[-1].startswith("truncated")
    assert view.trial_lines([]) == ["no revealed trial rows"]


def _rankings() -> dict:
    rows = [{"position": position, "image_id": f"image-{position}",
             "fused": 1.0 - position / 10,
             "channels": {"element": 0.5, "outline": -0.25},
             "is_target": position == 4}
            for position in range(1, 7)]
    return {
        "trial": {"p": 0.4, "target_rank": 4, "decoy_count": 5, "beaten": 2,
                  "tied": 0},
        "target_position": 4,
        "channel_names": ["element", "outline"],
        "rankings": rows,
        "report": [{"atom_id": "a1", "atom_text": f"tall{ESC}[2J tower",
                    "element": "tower", "weight": 0.6, "similarity": 0.8,
                    "rarity": 1.2}],
    }


def test_rankings_lines_mark_the_target_row() -> None:
    lines = view.rankings_lines(_rankings(), None)
    assert lines[0] == "p=0.4  rank=4  decoys=5  beaten=2  tied=0"
    assert lines[1] == "target position 4 of 6"
    assert lines[2].split() == ["position", "fused", "element", "outline",
                                "image"]
    marked = [line for line in lines if line.startswith("*")]
    assert len(marked) == 1
    assert marked[0].split() == ["*", "4", "0.6", "0.5", "-0.25", "image-4"]
    assert sum("image-" in line for line in lines) == 6
    assert lines[-1] == ("atom: tall\\x1b[2J tower  element=tower  "
                         "weight=0.6  similarity=0.8  rarity=1.2")
    _no_raw_control(lines)


def test_rankings_lines_keep_the_target_row_after_the_limit() -> None:
    lines = view.rankings_lines(_rankings(), 2)
    shown = [line for line in lines if "image-" in line]
    assert [line.split()[-1] for line in shown] == ["image-1", "image-2",
                                                    "image-4"]
    assert shown[-1].startswith("*")
    inside = view.rankings_lines(_rankings(), 5)
    assert sum("image-" in line for line in inside) == 5
    assert sum(line.startswith("*") for line in inside) == 1
    with pytest.raises(ValueError):
        view.rankings_lines(_rankings(), 0)


# ---- the schedule and the status ----


def _schedule() -> dict:
    return {
        "closes_at_utc": "00:00",
        "now": "2026-11-19T00:10:00+00:00",
        "running_label": "2026-11-19",
        "latest": {"day": "2026-11-18", "status": "open",
                   "closes_at": "2026-11-19T00:00:00+00:00"},
        "paused": True,
        "pause_changed_at": "2026-11-18T20:00:00+00:00",
        "pause_note": "pool swap",
        "lock_held": True,
        "due_now": {"at": "2026-11-19T00:10:00+00:00",
                    "steps": ["close", "reveal", "open"],
                    "opens": "2026-11-19"},
        "next_run": {"at": "2026-11-19T01:00:00+00:00", "steps": [],
                     "opens": None},
        "runs": [{"started_at": "2026-11-18T00:00:02+00:00",
                  "finished_at": "2026-11-18T00:01:00+00:00",
                  "source": "timer", "outcome": "failed",
                  "steps": ["close"],
                  "detail": f"close-failed: refused {ESC}[2J words"}],
    }


def test_schedule_lines_show_the_pause_the_due_steps_and_the_moves() -> None:
    lines = view.schedule_lines(_schedule())
    assert lines == [
        "rollover hour 00:00 UTC",
        "paused yes  changed 2026-11-18T20:00:00+00:00  note: pool swap",
        "due now: close, reveal, open 2026-11-19",
        "now 2026-11-19T00:10:00+00:00",
        "latest day 2026-11-18  status open  "
        "closes 2026-11-19T00:00:00+00:00",
        "a rollover holds the lock",
        "next run 2026-11-19T01:00:00+00:00: nothing",
        "recent moves:",
        "  2026-11-18T00:00:02+00:00  timer  failed  close  "
        "close-failed: refused \\x1b[2J words",
    ]


def test_schedule_lines_with_no_hour_and_no_day() -> None:
    off = _schedule() | {"closes_at_utc": None, "latest": None,
                         "paused": False, "lock_held": False,
                         "due_now": None, "next_run": None, "runs": []}
    assert view.schedule_lines(off) == [
        "automatic days off: no rollover hour in the server config",
        "paused no",
        "now 2026-11-19T00:10:00+00:00",
        "no stored day",
        "no recent moves",
    ]


def test_status_lines_show_the_day_the_schedule_and_the_server() -> None:
    latest = {"day": "2026-11-18", "status": "open", "trial_code": "K3P9QZ",
              "target_id": "a" * 64, "commitment": None, "submitted": False,
              "sends": 4, "quarantined": 0}
    lines = view.status_lines(
        latest=latest, schedule=_schedule(),
        player_counts={"revoked": 1, "active": 12}, server_answers=True)
    assert lines == [
        "latest 2026-11-18  K3P9QZ  open  sends=4",
        "rollover hour 00:00 UTC",
        "paused yes  changed 2026-11-18T20:00:00+00:00  note: pool swap",
        "due now: close, reveal, open 2026-11-19",
        "players active=12  revoked=1",
        "public server answers",
    ]
    # The status holds no target, open day or not.
    assert "a" * 64 not in "\n".join(lines)
    down = view.status_lines(latest=None, schedule=_schedule(),
                             player_counts={}, server_answers=False)
    assert down[0] == "no stored day"
    assert down[-2:] == ["players none", "public server does not answer"]
    assert view.status_lines(latest=None, schedule=_schedule(),
                             player_counts={}, server_answers=None)[-1] \
        == "public server not checked"


# ---- players ----


def test_roster_lines_show_one_line_for_each_player() -> None:
    rows = [
        {"player": "mira", "display_name": "Mira B", "status": "active",
         "created_at": "2026-11-01T00:00:00+00:00", "devices": 2,
         "last_signed_in": "2026-11-18T09:00:00+00:00", "device_codes": 0,
         "sends": 9},
        {"player": "odo", "display_name": f"Odo{ESC}[2J", "status": "revoked",
         "created_at": None, "devices": 0, "last_signed_in": None,
         "device_codes": 1, "sends": 0},
    ]
    assert view.roster_lines(rows) == [
        "mira  active  devices=2  sends=9  device_codes=0  "
        "last_signed_in=2026-11-18T09:00:00+00:00  Mira B",
        "odo  revoked  devices=0  sends=0  device_codes=1  "
        "last_signed_in=-  Odo\\x1b[2J",
    ]
    assert view.roster_lines([]) == ["no stored player"]


def _player() -> dict:
    return {
        "player": "mira", "display_name": "Mira B", "status": "active",
        "created_at": "2026-11-01T00:00:00+00:00",
        "description": "I draw bridges",
        "has_avatar": True,
        "account_updated_at": "2026-11-02T00:00:00+00:00",
        "sessions": [{"id": "0123456789abcdef0123456789abcdef",
                      "label": "Firefox on Linux",
                      "created_at": "2026-11-18T09:00:00+00:00",
                      "ends_at": "2026-12-18T09:00:00+00:00"}],
        "device_codes": [],
        "has_password": True,
        "operator_code": {"issued_at": "2026-11-18T12:00:00+00:00",
                          "usable_at": "2026-11-19T12:00:00+00:00"},
        "sends": 9,
    }


def test_player_lines_show_the_account_and_its_devices() -> None:
    assert view.player_lines(_player()) == [
        "player mira",
        "display name Mira B",
        "status active",
        "created 2026-11-01T00:00:00+00:00",
        "password yes",
        "avatar yes",
        "description: I draw bridges",
        "account updated 2026-11-02T00:00:00+00:00",
        "sends 9",
        "operator code made 2026-11-18T12:00:00+00:00  "
        "works from 2026-11-19T12:00:00+00:00",
        "devices 1",
        "  0123456789ab  2026-11-18T09:00:00+00:00  "
        "ends 2026-12-18T09:00:00+00:00  Firefox on Linux",
        "device codes 0",
    ]
    bare = _player() | {"description": "", "operator_code": None,
                        "sessions": [], "has_avatar": False,
                        "account_updated_at": None}
    lines = view.player_lines(bare)
    assert "description: -" in lines
    assert "operator code none" in lines
    assert "devices 0" in lines


def test_a_planted_sequence_in_an_account_does_not_come_out_raw() -> None:
    player = _player()
    player["description"] = PLANTED
    player["display_name"] = f"Mira{ESC}]0;title\x07"
    player["sessions"][0]["label"] = f"Mozilla{ESC}[2J\nX-Injected: 1"
    lines = view.player_lines(player)
    _no_raw_control(lines)
    assert ("description: \\x1b[2J\\x1b]0;owned\\x07 nice bridge\\r\\n"
            "second line \\u202eevil") in lines
    assert len(lines) == len(view.player_lines(_player()))


def test_deletion_preview_lines_say_what_goes_and_what_stays() -> None:
    preview = {
        "player": "mira", "status": "active", "days_played": 3,
        "first_day": "2026-11-10", "last_day": "2026-11-18", "sessions": 2,
        "has_password": True, "identifier": None,
        "removes": ["the player record", "the account and the avatar"],
        "keeps": ["each send and trial result, with an anonymous name"],
    }
    assert view.deletion_preview_lines(preview) == [
        "preview: deleting mira removes the player record; the account and "
        "the avatar",
        "it keeps each send and trial result, with an anonymous name",
        "days played 3 (one send each), 2026-11-10 to 2026-11-18, "
        "sessions 2",
        "the earlier results will show as a new anonymous identifier",
        "this cannot be undone: restore does not work on a deleted "
        "account, and no one can register the username again",
        "nothing changed. To delete, run again with --confirm mira",
    ]
    none_played = preview | {"days_played": 0, "first_day": None,
                             "last_day": None, "identifier": "anon-7f3a"}
    lines = view.deletion_preview_lines(none_played)
    assert lines[2] == "days played 0 (one send each), sessions 2"
    assert lines[3] == "the earlier results will show as anon-7f3a"


def test_recovery_code_lines_hold_the_code_and_the_caution() -> None:
    assert view.recovery_code_lines(
        "mira", "ABCD-EFGH-JKLM", "2026-11-20T12:00:00+00:00") == [
        "player mira",
        "recovery code ABCD-EFGH-JKLM",
        "it works from 2026-11-20T12:00:00+00:00",
        "this is the one time the code prints - give it to the player, "
        "then forget it",
    ]


# ---- the results index ----


def test_index_lines_show_the_file_and_each_table() -> None:
    described = {
        "path": "/var/lib/starvector/index.sqlite", "exists": True,
        "schema_version": 4, "built_at": "2026-11-19T00:02:00+00:00",
        "current": False, "problem": None,
        "tables": [
            {"name": "days", "rows": 12, "columns": ["day", "status"],
             "view": False},
            {"name": "revealed_trials", "rows": 40,
             "columns": ["day", "player", "p"], "view": True},
        ],
    }
    assert view.index_lines(described) == [
        "index /var/lib/starvector/index.sqlite",
        "exists yes",
        "schema version 4",
        "built 2026-11-19T00:02:00+00:00",
        "current no",
        "  days  rows=12  table  day,status",
        "  revealed_trials  rows=40  view  day,player,p",
    ]
    absent = described | {"exists": False, "built_at": None, "tables": [],
                          "problem": "file is not a database"}
    assert view.index_lines(absent) == [
        "index /var/lib/starvector/index.sqlite",
        "exists no",
        "schema version 4",
        "built -",
        "current no",
        "problem: file is not a database",
    ]


def test_verify_lines_say_if_the_index_agrees() -> None:
    assert view.verify_lines({"agrees": True, "problems": []}) == [
        "the index agrees with the store"]
    assert view.verify_lines({"agrees": False, "problems": [
        "days: 1 rows missing from the index, 0 rows the store does not "
        "hold"]}) == [
        "days: 1 rows missing from the index, 0 rows the store does not hold",
        "the index does not agree with the store"]


def test_query_lines_align_the_columns() -> None:
    answer = {"columns": ["day", "player", "p"],
              "rows": [["2026-11-17", "mira", 0.75],
                       ["2026-11-18", "a-long-player-name", None]],
              "truncated": False, "elapsed_ms": 3}
    assert view.query_lines(answer) == [
        "day         player              p",
        "----------  ------------------  ----",
        "2026-11-17  mira                0.75",
        "2026-11-18  a-long-player-name  NULL",
        "2 rows  3 ms",
    ]


def test_query_lines_say_when_the_answer_is_truncated() -> None:
    answer = {"columns": ["n"], "rows": [[1], [2]], "truncated": True,
              "elapsed_ms": 12}
    lines = view.query_lines(answer)
    assert lines[-2] == "2 rows  12 ms"
    assert lines[-1].startswith("truncated")
    assert not any(line.startswith("truncated") for line in
                   view.query_lines(answer | {"truncated": False}))


def test_a_planted_sequence_in_a_query_cell_does_not_come_out_raw() -> None:
    answer = {"columns": ["description", f"x{ESC}[2J"],
              "rows": [[PLANTED, 1], ["plain", 2]],
              "truncated": False, "elapsed_ms": 1}
    lines = view.query_lines(answer)
    _no_raw_control(lines)
    # The header, the rule, two rows, and the count: a line end in a
    # cell adds no line.
    assert len(lines) == 5
    assert "\\x1b[2J" in lines[0]


# ---- the operator journal ----


def _entry(entry_id: str, phase: str, **changes: object) -> dict:
    entry = {"entry_id": entry_id, "phase": phase,
             "at": "2026-11-19T10:00:00+00:00", "login": "ade",
             "login_source": "login-uid", "command": "players revoke",
             "player": "mira", "day": None, "outcome": None, "facts": {},
             "error_kind": None}
    entry.update(changes)
    return entry


def test_journal_lines_pair_a_start_with_its_end() -> None:
    entries = [
        _entry("aaaaaaaa", "start"),
        _entry("bbbbbbbb", "start", command="day close", player=None,
               day="2026-11-18", at="2026-11-19T10:01:00+00:00",
               login_source="sudo-user"),
        _entry("aaaaaaaa", "end", outcome="done", facts={"ended": 2},
               at="2026-11-19T10:00:01+00:00"),
        _entry("bbbbbbbb", "end", command="day close", player=None,
               day="2026-11-18", outcome="failed",
               facts={"steps": ("close",), "exit_code": 1},
               error_kind="http-400:close-failed",
               at="2026-11-19T10:01:30+00:00", login_source="sudo-user"),
    ]
    assert view.journal_lines(entries) == [
        "2026-11-19T10:00:00+00:00  ade (login-uid)  players revoke  "
        "player=mira  done  ended=2",
        "2026-11-19T10:01:00+00:00  ade (sudo-user)  day close  "
        "day=2026-11-18  failed  exit_code=1  steps=close  "
        "error=http-400:close-failed",
    ]


def test_journal_lines_show_a_start_with_no_end() -> None:
    lines = view.journal_lines([
        _entry("aaaaaaaa", "start"),
        _entry("cccccccc", "start", command="schedule pause", player=None,
               facts={"paused": True}),
        _entry("cccccccc", "end", command="schedule pause", player=None,
               outcome="done", facts={"paused": True}),
    ])
    assert lines == [
        "2026-11-19T10:00:00+00:00  ade (login-uid)  players revoke  "
        "player=mira  outcome not recorded",
        "2026-11-19T10:00:00+00:00  ade (login-uid)  schedule pause  done  "
        "paused=yes",
    ]


def test_journal_lines_show_an_end_with_no_start() -> None:
    assert view.journal_lines([
        _entry("dddddddd", "end", outcome="refused", facts=None)]) == [
        "2026-11-19T10:00:00+00:00  ade (login-uid)  players revoke  "
        "player=mira  start not recorded  refused"]


def test_journal_lines_show_a_day_that_the_end_record_alone_names() -> None:
    # The start of `sv day open` has no day: the server gives the label.
    assert view.journal_lines([
        _entry("eeeeeeee", "start", command="day open", player=None),
        _entry("eeeeeeee", "end", command="day open", player=None,
               day="2026-11-19", outcome="done")]) == [
        "2026-11-19T10:00:00+00:00  ade (login-uid)  day open  "
        "day=2026-11-19  done"]


def test_journal_lines_of_an_empty_journal_and_a_bad_phase() -> None:
    assert view.journal_lines([]) == ["no journal entry"]
    with pytest.raises(ValueError):
        view.journal_lines([_entry("aaaaaaaa", "middle")])


def test_journal_lines_read_the_fields_that_the_plan_builds() -> None:
    fields = plan.journal_fields(
        entry_id="0123456789abcdef", phase="end",
        at="2026-11-19T10:00:00+00:00", login="ade",
        login_source="effective-user",
        command=plan.command_for(("schedule", "run")), outcome="done",
        facts={"steps": ["close", "reveal"], "retries": 0})
    assert view.journal_lines([fields]) == [
        "2026-11-19T10:00:00+00:00  ade (effective-user)  schedule run  "
        "start not recorded  done  retries=0  steps=close,reveal"]


# ---- JSON and CSV ----


def test_to_json_sorts_the_keys_and_holds_no_raw_control() -> None:
    text = view.to_json({"b": 1, "a": PLANTED, "c": "café"})
    assert text.index('"a"') < text.index('"b"') < text.index('"c"')
    assert ESC not in text
    assert "\u202e" not in text
    assert "\r" not in text
    assert text.isascii()
    assert json.loads(text) == {"a": PLANTED, "b": 1, "c": "café"}
    assert view.to_json({"a": 1}) == '{\n  "a": 1\n}'


def test_to_csv_quotes_as_rfc_4180() -> None:
    text = view.to_csv(
        ["day", "note"],
        [["2026-11-18", "plain"],
         ["2026-11-17", 'say "hi", twice'],
         ["2026-11-16", "two\nlines"],
         ["2026-11-15", None],
         [5, 0.25]])
    assert text == ('day,note\r\n'
                    '2026-11-18,plain\r\n'
                    '2026-11-17,"say ""hi"", twice"\r\n'
                    '2026-11-16,"two\nlines"\r\n'
                    '2026-11-15,\r\n'
                    '5,0.25\r\n')
    assert view.to_csv(["a,b"], []) == '"a,b"\r\n'
    assert view.to_csv(["a"], [["x\ry"]]) == 'a\r\n"x\ry"\r\n'


def test_to_csv_for_a_terminal_holds_no_raw_control() -> None:
    text = view.to_csv(["note"], [[PLANTED], ["a,b"]], terminal=True)
    assert ESC not in text
    assert "\u202e" not in text
    assert text == ('note\r\n'
                    '\\x1b[2J\\x1b]0;owned\\x07 nice bridge\\r\\n'
                    'second line \\u202eevil\r\n'
                    '"a,b"\r\n')
    # A file gets the bytes as they are.
    assert ESC in view.to_csv(["note"], [[PLANTED]])
