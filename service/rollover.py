"""The daily rollover: close, reveal, and open, in that sequence.

Spec: BR1 (in docs/specs/beta-readiness.md) section 3. A systemd
timer starts this command at the rollover hour. It reads the latest
day from the store, then moves it with the three operator endpoints
of the live server - the server holds the resident scoring
context and the provider key, thus the close costs no second context
in memory.

The command is safe to start again at each moment:

- It closes a day only when the calendar says the day is due.
- It reads the status again before each step, thus a start after a
  stop continues from the step that stopped.
- It opens one day at most, and it holds a file lock, thus of two
  starts at one moment, one alone moves the day.

The operator console (spec BR1 section 7.2) pauses the timer's
rollover and starts one of its own. The two share the lock and the
pause in the store, and each rollover writes one run record there.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from service import schedule, store
from service.config import ServiceConfigError, load_service_config

# The steps of a rollover. "wait" ends the rollover with no move:
# the open day has not got to its close time.
STEPS = ("open", "close", "reveal", "wait")

# A close encodes each new submission through the provider. The
# provider client retries each POST for some minutes at most, thus
# the loopback timeout is much longer than that.
_CLOSE_TIMEOUT_SECONDS = 900.0
_STEP_TIMEOUT_SECONDS = 120.0
_MAX_MOVES = 6


class RolloverError(RuntimeError):
    """A step did not complete after its retries, or the setup is bad."""


class TransportError(RuntimeError):
    """The server did not answer: refused, closed, or timed out."""


@dataclass(frozen=True, slots=True)
class Answer:
    """One endpoint answer: the HTTP status and the JSON body."""

    status: int
    body: dict


@dataclass(frozen=True, slots=True)
class Latest:
    """The latest stored day, or no day at all."""

    label: str | None
    status: str | None


Post = Callable[[str, float], Answer]


def plan_step(latest: Latest, instant: datetime.datetime,
              closes_at_utc: str) -> str:
    """The next step for the latest day, one of STEPS."""
    if latest.status is None or latest.label is None:
        return "open"
    if latest.status == "open":
        due = schedule.is_due(latest.label, instant, closes_at_utc)
        return "close" if due else "wait"
    if latest.status == "closing":
        return "close"
    if latest.status == "closed":
        return "reveal"
    if latest.status == "revealed":
        return "open"
    raise RolloverError(f"unknown day status {latest.status!r}")


def planned_steps(latest: Latest, instant: datetime.datetime,
                  closes_at_utc: str) -> tuple[str, ...]:
    """The steps a rollover at this instant takes when each succeeds.

    The same loop as run_rollover with the status moves assumed: a
    close leaves the day closed, a reveal leaves it revealed, and the
    loop ends at an open or a wait. An empty answer means nothing is
    due. The console shows it as the next run's work.
    """
    steps: list[str] = []
    status = latest.status
    while True:
        step = plan_step(Latest(label=latest.label, status=status), instant,
                         closes_at_utc)
        if step == "wait":
            return tuple(steps)
        steps.append(step)
        if step == "open":
            return tuple(steps)
        status = "closed" if step == "close" else "revealed"


def read_latest(root: Path) -> Latest:
    """The latest stored day and its status, read from the store."""
    label = store.latest_day(root)
    if label is None:
        return Latest(label=None, status=None)
    return Latest(label=label, status=store.read_day_record(root,
                                                            label).status)


def _post_with_retries(post: Post, step: str, *, retries: int,
                       backoff_seconds: float,
                       sleep: Callable[[float], None],
                       say: Callable[[str], None]) -> Answer:
    """Post one step, retrying when the server does not answer or the
    close meets a provider failure.

    A 409 comes back immediately - the store refused the move, and
    the caller reads the status again to learn why. A 401 comes back
    immediately too: no retry repairs a missing operator token.
    """
    timeout = _CLOSE_TIMEOUT_SECONDS if step == "close" \
        else _STEP_TIMEOUT_SECONDS
    wait = backoff_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            answer = post(f"/api/day/{step}", timeout)
        except TransportError as error:
            failure = f"no answer: {error}"
        else:
            if answer.status in (200, 401, 409):
                return answer
            detail = answer.body.get("detail") or answer.body.get("cause")
            failure = f"HTTP {answer.status}: {detail}"
        if attempt > retries:
            raise RolloverError(
                f"{step} did not complete after {attempt} attempts - "
                f"{failure}")
        say(f"rollover: {step} attempt {attempt} - {failure}; again in "
            f"{wait:.0f} s")
        sleep(wait)
        wait *= 2


def run_rollover(*, root: Path, closes_at_utc: str, post: Post,
                 now: Callable[[], datetime.datetime],
                 sleep: Callable[[float], None] = time.sleep,
                 retries: int = 4, backoff_seconds: float = 30.0,
                 say: Callable[[str], None] = print) -> list[str]:
    """Move the latest day as far as the calendar says, and name the
    steps taken."""
    return list(iter_rollover(root=root, closes_at_utc=closes_at_utc,
                              post=post, now=now, sleep=sleep,
                              retries=retries,
                              backoff_seconds=backoff_seconds, say=say))


def iter_rollover(*, root: Path, closes_at_utc: str, post: Post,
                  now: Callable[[], datetime.datetime],
                  sleep: Callable[[float], None] = time.sleep,
                  retries: int = 4, backoff_seconds: float = 30.0,
                  say: Callable[[str], None] = print) -> Iterator[str]:
    """Move the latest day as far as the calendar says, and give each
    step when it completes.

    The loop ends at "wait" or after one open. Each step reads the
    store again first. A 409 from the server means the store refused
    the move - a second process moved the day - and the loop reads
    the status again, for a fixed count of moves at most. A caller
    that collects the steps thus keeps the steps before a failure.
    """
    taken: list[str] = []
    for _ in range(_MAX_MOVES):
        latest = read_latest(root)
        step = plan_step(latest, now(), closes_at_utc)
        if step == "wait":
            say(f"rollover: day {latest.label} is open and not due - "
                "nothing to do")
            return
        answer = _post_with_retries(post, step, retries=retries,
                                    backoff_seconds=backoff_seconds,
                                    sleep=sleep, say=say)
        if answer.status == 401:
            raise RolloverError(
                f"{step}: the server refused the operator token - set "
                "STARVECTOR_OPERATOR_TOKEN in the unit's environment")
        if answer.status == 409:
            say(f"rollover: {step} refused - "
                f"{answer.body.get('detail', 'no detail')}; reading the "
                "status again")
            continue
        taken.append(step)
        say(f"rollover: {step} {json.dumps(answer.body, sort_keys=True)}")
        yield step
        if step == "open":
            return
    raise RolloverError(
        f"no stable status after {_MAX_MOVES} moves - steps taken: "
        f"{taken}")


def http_post(base_url: str, token: str | None) -> Post:
    """A poster for the live server's loopback address."""

    def post(path: str, timeout: float) -> Answer:
        headers = {} if token is None \
            else {"Authorization": f"Bearer {token}"}
        request = urllib.request.Request(base_url.rstrip("/") + path,
                                         data=b"", method="POST",
                                         headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return Answer(status=reply.status,
                              body=_json_object(reply.read()))
        except urllib.error.HTTPError as error:
            return Answer(status=error.code, body=_json_object(error.read()))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransportError(str(error)) from error

    return post


def _json_object(raw: bytes) -> dict:
    try:
        value = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"detail": raw[:200].decode("utf-8", "replace")}
    return value if isinstance(value, dict) else {"detail": str(value)}


def ping(url: str | None, *, failed: bool,
         say: Callable[[str], None] = print) -> None:
    """Tell the health check the outcome. A ping that does not go
    through is reported and does not change the outcome - the
    rollover is done by then."""
    if not url:
        return
    target = url.rstrip("/") + ("/fail" if failed else "")
    try:
        with urllib.request.urlopen(target, timeout=10.0):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        say(f"rollover: the health check ping did not go through: {error}")


def run_and_record(*, root: Path, closes_at_utc: str, post: Post,
                   now: Callable[[], datetime.datetime], source: str,
                   sleep: Callable[[float], None] = time.sleep,
                   retries: int = 4, backoff_seconds: float = 30.0,
                   say: Callable[[str], None] = print) -> store.RolloverRun:
    """One rollover with its run record written to the store.

    The record holds the steps that completed and each line the
    rollover printed, thus the console shows a failure with the step
    it stopped at. A failure is recorded and not raised: the caller
    reads the outcome.
    """
    lines: list[str] = []

    def keep(line: str) -> None:
        lines.append(line)
        say(line)

    started = now()
    taken: list[str] = []
    outcome = "failed"
    try:
        for step in iter_rollover(root=root, closes_at_utc=closes_at_utc,
                                  post=post, now=now, sleep=sleep,
                                  retries=retries,
                                  backoff_seconds=backoff_seconds, say=keep):
            taken.append(step)
        outcome = "moved" if taken else "nothing due"
    except (RolloverError, store.StoreError) as error:
        keep(f"rollover failed: {error}")
    run = store.RolloverRun(
        started_at=started.isoformat(), finished_at=now().isoformat(),
        source=source, outcome=outcome, steps=tuple(taken),
        detail="\n".join(lines))
    store.write_rollover_run(root, run)
    return run


def record_paused(root: Path, control: store.RolloverControl, *,
                  source: str, instant: datetime.datetime) -> store.RolloverRun:
    """Write the run record of a rollover that the pause stopped."""
    note = f" - {control.note}" if control.note else ""
    run = store.RolloverRun(
        started_at=instant.isoformat(), finished_at=instant.isoformat(),
        source=source, outcome="paused", steps=(),
        detail=f"paused by the operator at {control.changed_at}{note}")
    store.write_rollover_run(root, run)
    return run


def hold_lock(path: Path) -> int | None:
    """Hold the rollover lock with no wait. None: a second start
    holds it."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(handle)
        return None
    return handle


def lock_is_held(path: Path) -> bool:
    """A rollover holds the lock at this moment. A read, for the
    console: with no lock file, nothing holds it, and no file is made."""
    import fcntl

    try:
        handle = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(handle)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.rollover")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    parser.add_argument("--base-url", default=None,
                        help="the server's loopback address; the default "
                             "is http://127.0.0.1:<config port>")
    parser.add_argument("--lock", default=None,
                        help="the lock file; the default is rollover/.lock "
                             "in the store, which the console holds too")
    parser.add_argument("--source", choices=("timer", "command-line"),
                        default="command-line",
                        help="the source the run record names; the day "
                             "timer passes timer")
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff", type=float, default=30.0,
                        help="seconds before the first retry; doubles")
    parser.add_argument("--plan", action="store_true",
                        help="print the next step and move nothing")
    arguments = parser.parse_args(argv)

    try:
        config = load_service_config(Path(arguments.service_config))
    except ServiceConfigError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    if config.closes_at_utc is None:
        print("refused: the rollover needs closes_at_utc in the server "
              "config - it is the rollover hour", file=sys.stderr)
        return 1
    root = Path(config.store_root)

    def now() -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)

    if arguments.plan:
        latest = read_latest(root)
        step = plan_step(latest, now(), config.closes_at_utc)
        paused = store.read_rollover_control(root).paused
        print(f"latest {latest.label} {latest.status} - next step {step}"
              + (" - paused: the timer moves nothing" if paused else ""))
        return 0

    lock = Path(arguments.lock) if arguments.lock \
        else store.rollover_lock_path(root)
    handle = hold_lock(lock)
    if handle is None:
        print("refused: a rollover holds the lock", file=sys.stderr)
        return 2
    base_url = arguments.base_url or f"http://127.0.0.1:{config.port}"
    health = os.environ.get("STARVECTOR_HEALTHCHECK_URL")
    try:
        # The pause is read with the lock held, thus a pause set
        # before this start stops it.
        control = store.read_rollover_control(root)
        if control.paused:
            run = record_paused(root, control, source=arguments.source,
                                instant=now())
            print(f"rollover: {run.detail} - nothing moves")
        else:
            run = run_and_record(
                root=root, closes_at_utc=config.closes_at_utc,
                post=http_post(base_url,
                               os.environ.get("STARVECTOR_OPERATOR_TOKEN")),
                now=now, source=arguments.source,
                retries=arguments.retries, backoff_seconds=arguments.backoff)
    except store.StoreError as error:
        print(f"rollover failed: {error}", file=sys.stderr)
        ping(health, failed=True)
        return 1
    finally:
        os.close(handle)
    # The operator sets a pause, and a pause is not a failure: the
    # health check gets a success (spec BR1 section 7.2).
    failed = run.outcome == "failed"
    if failed:
        print("rollover failed - the run record in store/rollover/runs "
              "holds each line", file=sys.stderr)
    ping(health, failed=failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
