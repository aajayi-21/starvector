"""The day calendar: labels, close times, and the next label to open.

Spec: BR1 (in docs/specs/beta-readiness.md) section 3. Pure functions
of a date string, an instant, and the configured rollover hour - no
clock read, no file read. The server, the day commands, and the
rollover command read the clock and give the instant.

The rule. A day runs for 24 hours and ends at the rollover hour H in
UTC. Its label is the UTC date that holds the larger part of those 24
hours:

- H at 12:00 or after: the day ends on the date of its label, thus
  the day labeled D runs from D - 1 at H to D at H.
- H before 12:00: the day starts on the date of its label, thus the
  day labeled D runs from D at H to D + 1 at H.

At H = 00:00 the label is the full UTC date, and at H = 22:00 the
label is the date on which the day closes. The two read as "today"
to a player for most of the window.
"""

import datetime
import re

_HOUR_RULE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_DAY_RULE = re.compile(r"\d{4}-\d{2}-\d{2}")
_HALF_DAY_MINUTES = 12 * 60


class ScheduleError(ValueError):
    """A label, an hour, or an instant broke the calendar rule."""


def rollover_minutes(closes_at_utc: str) -> int:
    """The rollover hour "HH:MM" as minutes after midnight UTC."""
    found = _HOUR_RULE.fullmatch(closes_at_utc) \
        if isinstance(closes_at_utc, str) else None
    if found is None:
        raise ScheduleError(
            f"expected \"HH:MM\" (24-hour UTC), got {closes_at_utc!r}")
    return int(found.group(1)) * 60 + int(found.group(2))


def parse_label(label: str) -> datetime.date:
    """One day label, "YYYY-MM-DD", as a date. Refuses other text."""
    if not isinstance(label, str) or not _DAY_RULE.fullmatch(label):
        raise ScheduleError(f"expected a YYYY-MM-DD label, got {label!r}")
    try:
        return datetime.date.fromisoformat(label)
    except ValueError as error:
        raise ScheduleError(f"not a calendar date: {label!r}") from error


def _utc(instant: datetime.datetime) -> datetime.datetime:
    """The instant in UTC. A naive instant has no zone and refuses."""
    if instant.tzinfo is None:
        raise ScheduleError("the instant has no time zone - pass UTC")
    return instant.astimezone(datetime.UTC)


def _at(day: datetime.date, minutes: int) -> datetime.datetime:
    return datetime.datetime.combine(
        day, datetime.time(minutes // 60, minutes % 60),
        tzinfo=datetime.UTC)


def closes_at_for(label: str, closes_at_utc: str) -> datetime.datetime:
    """The instant the day with this label closes, in UTC."""
    minutes = rollover_minutes(closes_at_utc)
    day = parse_label(label)
    if minutes >= _HALF_DAY_MINUTES:
        return _at(day, minutes)
    return _at(day + datetime.timedelta(days=1), minutes)


def closes_at_text(label: str, closes_at_utc: str) -> str:
    """The close instant as the wire string "YYYY-MM-DDTHH:MM:00+00:00".

    The string shape is the one the day view served before this
    module, thus an unchanged client reads it the same.
    """
    moment = closes_at_for(label, closes_at_utc)
    return f"{moment.date().isoformat()}T{moment:%H:%M}:00+00:00"


def label_at(instant: datetime.datetime, closes_at_utc: str | None) -> str:
    """The label of the day that runs at this instant.

    With no rollover hour configured, the label is the UTC date of the
    instant - the development flow, where days move by hand.
    """
    moment = _utc(instant)
    today = moment.date()
    if closes_at_utc is None:
        return today.isoformat()
    minutes = rollover_minutes(closes_at_utc)
    rollover_today = _at(today, minutes)
    if minutes >= _HALF_DAY_MINUTES:
        chosen = today if moment < rollover_today \
            else today + datetime.timedelta(days=1)
    else:
        chosen = today if moment >= rollover_today \
            else today - datetime.timedelta(days=1)
    return chosen.isoformat()


def next_open_label(latest: str | None, instant: datetime.datetime,
                    closes_at_utc: str | None) -> str:
    """The label the next open gets: the current day, or the day after
    the latest stored day when that one holds the current label.

    A day that closed and revealed before its rollover thus opens the
    next label before its window, and the new day gets more hours.
    The caller checks the latest day's status - this function reads
    dates alone.
    """
    running = label_at(instant, closes_at_utc)
    if latest is None:
        return running
    after_latest = (parse_label(latest)
                    + datetime.timedelta(days=1)).isoformat()
    return max(running, after_latest)


def check_open_label(label: str, instant: datetime.datetime,
                     closes_at_utc: str | None) -> None:
    """Refuse a label more than one day after the current day.

    Applies when a rollover hour is configured: a production open
    cannot put a day on the calendar before its time and then hold the
    rollover back. Without the hour the development flow keeps its
    back-to-back days, and nothing refuses.
    """
    parse_label(label)
    if closes_at_utc is None:
        return
    running = parse_label(label_at(instant, closes_at_utc))
    if parse_label(label) > running + datetime.timedelta(days=1):
        raise ScheduleError(
            f"day {label} is more than one day after the running day "
            f"{running.isoformat()} - open refuses to go ahead of the "
            "calendar")


def is_due(label: str, instant: datetime.datetime,
           closes_at_utc: str) -> bool:
    """The day with this label has reached its close time."""
    return _utc(instant) >= closes_at_for(label, closes_at_utc)


def next_rollover_at(instant: datetime.datetime,
                     closes_at_utc: str) -> datetime.datetime:
    """The first rollover hour at or after this instant, in UTC.

    The console shows it as the next start of the day timer, which
    fires at the same hour (spec BR1 section 7.2).
    """
    moment = _utc(instant)
    today = _at(moment.date(), rollover_minutes(closes_at_utc))
    return today if moment <= today else today + datetime.timedelta(days=1)
