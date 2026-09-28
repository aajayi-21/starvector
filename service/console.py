"""The read views of the operator console (spec BR1 section 7).

Each function reads the store and answers a plain value, and the
dev paths of the server send it as JSON. No function here writes,
and no value holds a secret: an invite digest, a session secret, and
a device code stay out. A session id is the digest of its secret,
which the player's own device screen shows too - a cookie cannot
come from it.

The console reaches the dev unit alone (spec S2 ruling 2), thus a
view shows the target of an open day. That is the dev plane's
purpose, and the edge refuses each dev path.
"""

import datetime
from pathlib import Path

from service import access, rollover, schedule, store

# The recent runs the automatic-days tab shows.
RUN_LIMIT = 20


def send_counts(root: Path) -> dict[str, int]:
    """The count of stored submissions of each player, each day."""
    counts: dict[str, int] = {}
    for day in store.list_days(root):
        for player in store.list_submissions(root, day):
            counts[player] = counts.get(player, 0) + 1
    return counts


def _live_sessions(root: Path, player: str, instant: datetime.datetime
                   ) -> list[tuple[str, store.SessionRecord]]:
    """The player's sessions before the end of their life, oldest first."""
    return [(digest, record)
            for digest, record in store.list_sessions(root, player)
            if not access.session_expired(record, instant)]


def _waiting_codes(root: Path, instant: datetime.datetime
                   ) -> dict[str, list[store.DeviceCodeRecord]]:
    """The device codes before their expiry, by player."""
    waiting: dict[str, list[store.DeviceCodeRecord]] = {}
    for _digest, record in store.list_device_codes(root):
        if not access.code_expired(record, instant):
            waiting.setdefault(record.player, []).append(record)
    return waiting


def roster_rows(root: Path, configured_player: str,
                instant: datetime.datetime) -> list[dict]:
    """One row for each stored player, with devices and sends.

    With no record stored, the roster holds one row for the
    configured player - the world of spec M1 ruling 7, where that
    name is the identity and nothing holds credentials.
    """
    counts = send_counts(root)
    names = store.list_players(root)
    if not names:
        return [{"player": configured_player,
                 "display_name": configured_player,
                 "status": "configured", "created_at": None, "devices": 0,
                 "last_signed_in": None, "device_codes": 0,
                 "sends": counts.get(configured_player, 0)}]
    codes = _waiting_codes(root, instant)
    rows = []
    for name in names:
        record = store.read_player_record(root, name)
        sessions = _live_sessions(root, name, instant)
        rows.append({
            "player": record.player,
            "display_name": record.display_name,
            "status": record.status,
            "created_at": record.created_at,
            "devices": len(sessions),
            "last_signed_in": sessions[-1][1].created_at if sessions
            else None,
            "device_codes": len(codes.get(name, [])),
            "sends": counts.get(name, 0),
        })
    return rows


def player_detail(root: Path, player: str,
                  instant: datetime.datetime) -> dict:
    """One player's record, account, devices, and device codes.

    Raises StoreError when no record by that name is stored.
    """
    record = store.read_player_or_none(root, player)
    if record is None:
        raise store.StoreError(f"no stored player {player!r}")
    account = store.read_account_or_none(root, player)
    sessions = [{"id": digest, "label": session.label,
                 "created_at": session.created_at,
                 "ends_at": access.session_ends_at(session).isoformat()}
                for digest, session in _live_sessions(root, player, instant)]
    codes = [{"created_at": code.created_at, "expires_at": code.expires_at}
             for code in _waiting_codes(root, instant).get(player, [])]
    return {
        "player": record.player,
        "display_name": record.display_name,
        "status": record.status,
        "created_at": record.created_at,
        "description": "" if account is None else account.description,
        "has_avatar": account is not None
        and account.avatar_hash is not None,
        "account_updated_at": None if account is None
        else account.updated_at,
        "sessions": sessions,
        "device_codes": codes,
        "sends": send_counts(root).get(player, 0),
    }


def _trial_value(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {"p": row["p"], "target_rank": row["target_rank"],
            "decoy_count": row["decoy_count"], "beaten": row["beaten"],
            "tied": row["tied"]}


def day_detail(root: Path, day: str, *, closes_at_utc: str | None,
               credits: dict[str, dict[str, str]]) -> dict:
    """One day record with its close instant, credit, and each send.

    The sends come in the sequence they arrived. A send's trial row
    is the pinned one, and it is None until the close writes it.
    """
    record = store.read_day_record(root, day)
    sends = []
    for player in store.list_submissions(root, day):
        stored = store.read_json_or_none(
            store.submission_path(root, day, player))
        if stored is None:
            raise store.StoreError(
                f"day {day}: the submission of {player} does not read")
        owner = store.read_player_or_none(root, player)
        sends.append({
            "player": player,
            "display_name": player if owner is None else owner.display_name,
            "received_at": stored["received_at"],
            "trial_id": stored["trial_id"],
            "trial": _trial_value(store.read_json_or_none(
                store.trial_row_path(root, day, player))),
        })
    sends.sort(key=lambda row: (row["received_at"], row["player"]))
    return {
        "day": record.day,
        "status": record.status,
        "trial_code": record.trial_code,
        "target_id": record.target_id,
        "commitment": record.commitment,
        "opened_at": record.opened_at,
        "closed_at": record.closed_at,
        "revealed_at": record.revealed_at,
        "closes_at": None if closes_at_utc is None
        else schedule.closes_at_text(day, closes_at_utc),
        "scoring_config_hash": record.scoring_config_hash,
        "preparation_version_id": record.preparation_version_id,
        "credit": credits.get(record.target_id),
        "sends": sends,
    }


def run_value(run: store.RolloverRun) -> dict:
    """One rollover run record, as the console reads it."""
    return {"started_at": run.started_at, "finished_at": run.finished_at,
            "source": run.source, "outcome": run.outcome,
            "steps": list(run.steps), "detail": run.detail}


def _plan_value(latest: rollover.Latest, instant: datetime.datetime,
                closes_at_utc: str) -> dict:
    """The steps a rollover at this instant takes, and the label it
    opens when it opens one."""
    steps = rollover.planned_steps(latest, instant, closes_at_utc)
    opens = schedule.next_open_label(latest.label, instant, closes_at_utc) \
        if "open" in steps else None
    return {"at": instant.isoformat(), "steps": list(steps), "opens": opens}


def schedule_view(root: Path, *, closes_at_utc: str | None,
                  instant: datetime.datetime, lock_held: bool) -> dict:
    """The automatic days: the hour, the latest day, the pause, the
    steps due at this instant, the next run and its steps, and the
    recent runs.

    With no rollover hour configured, automatic days are off: the
    plans are None and the pause shows as stored.
    """
    latest = rollover.read_latest(root)
    control = store.read_rollover_control(root)
    value = {
        "closes_at_utc": closes_at_utc,
        "now": instant.isoformat(),
        "running_label": schedule.label_at(instant, closes_at_utc),
        "latest": None if latest.label is None else {
            "day": latest.label, "status": latest.status,
            "closes_at": None if closes_at_utc is None
            else schedule.closes_at_text(latest.label, closes_at_utc)},
        "paused": control.paused,
        "pause_changed_at": control.changed_at,
        "pause_note": control.note,
        "lock_held": lock_held,
        "due_now": None,
        "next_run": None,
        "runs": [run_value(run)
                 for run in store.list_rollover_runs(root, RUN_LIMIT)],
    }
    if closes_at_utc is not None:
        value["due_now"] = _plan_value(latest, instant, closes_at_utc)
        value["next_run"] = _plan_value(
            latest, schedule.next_rollover_at(instant, closes_at_utc),
            closes_at_utc)
    return value
