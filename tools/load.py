"""The load test: active-player capacity as a number (spec PL1 section 9).

Starts the server in its own process on a throwaway fake-provider
world, then drives it from a closed loop at rising concurrency. Each
client sends the traffic mix of an active player in the busiest ten
minutes of a day. A level passes with no error and a 95th percentile
at or below the budget. The capacity is the rate at the highest
concurrency that passes, divided by the rate of one active player.

Offline: no GPU, no network, no API key. A fake encoder costs no network
time and the fake pool is small, thus the number is a maximum for the
HTTP path alone. Do this again on the deployed box. Dev-only, not in CI.
"""

import argparse
import asyncio
import datetime
import json
import os
import platform
import random
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

OPERATOR_TOKEN = "load-test-operator-token"
BUDGET_MS = 500.0
LIVE_DAY = "2026-08-31"

# One active player in the busiest ten minutes of a day: an open tab
# across the close polls each 20 s (web/src/api/day-query.ts), one app
# load reads three paths, and the player sends one time and practices
# one time. The busiest ten minutes set the capacity, because the mean
# rate of a day is far below this.
MODEL_WINDOW_SECONDS = 600.0
PLAYER_MODEL = {"day": 30 + 1, "me": 1, "history": 1, "send": 1, "practice": 1}


def player_rate() -> float:
    """The requests each second of one active player in the model."""
    return sum(PLAYER_MODEL.values()) / MODEL_WINDOW_SECONDS


@dataclass(frozen=True, slots=True)
class LevelResult:
    """One concurrency level: its rate, its latency, and its errors."""

    concurrency: int
    seconds: float
    requests: int
    errors: int
    rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    by_kind_p95_ms: dict[str, float] = field(default_factory=dict)
    first_error: str | None = None


def percentile(values: list[float], fraction: float) -> float:
    """The nearest-rank percentile of the values. Zero with no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    at = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[at]


def passes(level: LevelResult, budget_ms: float) -> bool:
    """A level passes with no error and a 95th percentile in budget."""
    return level.errors == 0 and level.requests > 0 \
        and level.p95_ms <= budget_ms


def capacity(levels: list[LevelResult], budget_ms: float,
             rate_of_one_player: float) -> tuple[int, float]:
    """The active players and the rate at the highest level that passes.

    The highest concurrency and not the highest rate: players come with
    no regard to the answers before them, thus a live server holds many
    calls at one moment, and one process gives fewer answers each second
    then. A rate from two clients in a loop says nothing of that. Levels
    after the first one with no agreement to the budget do not count: a
    level that recovers after a failure is noise and not capacity. Zero
    when the first level misses.
    """
    rate = 0.0
    for level in levels:
        if not passes(level, budget_ms):
            break
        rate = level.rate
    return int(rate / rate_of_one_player), rate


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _build_world(root: Path, *, players: int, pool: int,
                 seeded_days: int) -> dict:
    """The store and pool, with seeded revealed days and live sessions.

    Each seeded day holds a send from the first players, thus history
    and streak reads walk rows, as they do on a live box. The last day
    is open and has no sends.
    """
    sys.path.insert(0, str(REPO / "tests"))
    sys.path.insert(0, str(REPO / "tests" / "service"))
    from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

    from service import access, players as player_commands, store
    from service.day import close_day, open_day, reveal_day

    fixture = build_service_fixture(root, count=pool)
    config = fixture["service_config"]

    def clock() -> str:
        return FIXED_CLOCK

    sessions: dict[str, str] = {}
    instant = datetime.datetime.now(datetime.UTC)
    for number in range(players):
        name = f"p{number:05d}"
        player_commands.make_player(config, player=name, display_name=name,
                                    clock=clock)
        sessions[name] = access.open_session(
            root / "store", name, user_agent="load", instant=instant)

    first = datetime.date.fromisoformat(LIVE_DAY) \
        - datetime.timedelta(days=seeded_days)
    seeded: list[str] = []
    for offset in range(seeded_days):
        label = (first + datetime.timedelta(days=offset)).isoformat()
        open_day(config, date=label, clock=clock, pick_seed=f"{offset:032d}",
                 secret=f"{offset:064d}")
        for name in list(sessions)[:min(players, 50)]:
            store.write_once_json(
                store.submission_path(root / "store", label, name),
                {"day": label, "player": name, "trial_id": f"{offset:032d}",
                 "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
        close_day(config, providers=fixture["providers"], clock=clock)
        reveal_day(config, clock=clock)
        seeded.append(label)
    open_day(config, date=LIVE_DAY, clock=clock, pick_seed="f" * 32,
             secret="e" * 64)
    return {"config": config, "sessions": sessions, "seeded": seeded,
            "record": mixed_wire_record()}


def serve(root: Path, port: int) -> None:
    """The server process: the app of the deployment, with no practice
    limit, because this measures the scoring path and not the limiter.
    The limiter stands in front of that path in production."""
    from dataclasses import replace

    import uvicorn

    from service import limits
    from service.config import ServiceConfig
    from service.server import create_app

    document = json.loads((root / "load-config.json").read_text())
    config = replace(ServiceConfig(**document))
    open_limiter = limits.WindowLimiter(window_seconds=1.0,
                                        client_cap=10**9, global_cap=10**9)
    app = create_app(config, dev_mode=False, cookie_secure=False,
                     operator_token=OPERATOR_TOKEN,
                     practice_limiter=open_limiter)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning",
                access_log=False)


def _start_server(root: Path, port: int) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "tools.load", "--serve", "--root", str(root),
         "--port", str(port)],
        cwd=REPO, env={**os.environ, "PYTHONPATH": str(REPO)})
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/about", timeout=1.0):
                return process
        except OSError:
            if process.poll() is not None:
                raise RuntimeError("the load server stopped at start") from None
            time.sleep(0.2)
    process.kill()
    raise RuntimeError("the load server did not answer in 120 s")


def _kinds_of_mix() -> list[str]:
    return [kind for kind, count in PLAYER_MODEL.items()
            for _ in range(count)]


async def _client_loop(client, *, stop_at: float, names: list[str],
                       sessions: dict[str, str], unsent: deque,
                       world: dict, rng: random.Random,
                       latencies: dict[str, list[float]],
                       errors: list[str]) -> None:
    """One closed-loop client: it sends after the last answer."""
    mix = _kinds_of_mix()
    while time.monotonic() < stop_at:
        kind = rng.choice(mix)
        name = rng.choice(names)
        method, path, body = "GET", "", None
        match kind:
            case "day":
                path = "/api/day"
            case "me":
                path = "/api/me"
            case "history":
                path = "/api/history"
            case "send":
                if not unsent:
                    path = "/api/day"
                else:
                    name = unsent.popleft()
                    method, path = "POST", f"/api/submission?day={LIVE_DAY}"
                    body = world["record"]
            case "practice":
                method, path = "POST", "/api/practice/score"
                body = {"day": world["seeded"][-1], "record": world["record"]}
        started = time.perf_counter()
        answer = await client.request(
            method, path, json=body,
            headers={"cookie": f"sv_session={sessions[name]}"})
        elapsed = (time.perf_counter() - started) * 1000.0
        latencies.setdefault(kind, []).append(elapsed)
        if answer.status_code != 200:
            errors.append(f"{kind} HTTP {answer.status_code} {answer.text[:80]}")


async def _run_level(base_url: str, world: dict, unsent: deque,
                     concurrency: int, seconds: float,
                     seed: int) -> LevelResult:
    """Run one level and collect its result."""
    import httpx

    latencies: dict[str, list[float]] = {}
    errors: list[str] = []
    names = list(world["sessions"])
    limit = httpx.Limits(max_connections=concurrency,
                         max_keepalive_connections=concurrency)
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, limits=limit,
                                 timeout=60.0) as client:
        await asyncio.gather(*(
            _client_loop(client, stop_at=started + seconds, names=names,
                         sessions=world["sessions"], unsent=unsent,
                         world=world, rng=random.Random(seed + at),
                         latencies=latencies, errors=errors)
            for at in range(concurrency)))
    elapsed = time.monotonic() - started
    every = [value for values in latencies.values() for value in values]
    return LevelResult(
        concurrency=concurrency, seconds=round(elapsed, 2),
        requests=len(every), errors=len(errors),
        rate=round(len(every) / elapsed, 1),
        p50_ms=round(percentile(every, 0.50), 1),
        p95_ms=round(percentile(every, 0.95), 1),
        p99_ms=round(percentile(every, 0.99), 1),
        by_kind_p95_ms={kind: round(percentile(values, 0.95), 1)
                        for kind, values in sorted(latencies.items())},
        first_error=errors[0] if errors else None)


def _peak_memory_mb(pid: int) -> float | None:
    """The peak resident memory of a process, from /proc."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmHWM:"):
            return round(int(line.split()[1]) / 1024.0, 1)
    return None


def _timed_post(base_url: str, path: str) -> float:
    request = urllib.request.Request(
        base_url + path, data=b"", method="POST",
        headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600.0):
        pass
    return round(time.perf_counter() - started, 3)


def run_load(*, players: int, pool: int, seeded_days: int,
             levels: list[int], seconds: float, budget_ms: float) -> dict:
    """Build a world, step through the levels, and give the report."""
    with tempfile.TemporaryDirectory(prefix="sv-load-") as scratch:
        root = Path(scratch)
        print(f"building: {players} players, a pool of {pool}, "
              f"{seeded_days} revealed days", file=sys.stderr, flush=True)
        world = _build_world(root, players=players, pool=pool,
                             seeded_days=seeded_days)
        (root / "load-config.json").write_text(
            json.dumps(asdict(world["config"])))
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        process = _start_server(root, port)
        try:
            # Warm the resident context, as the first close or the
            # first practice does on a live box.
            unsent = deque(world["sessions"])
            asyncio.run(_run_level(base_url, world, deque(), 1, 2.0, 0))
            results: list[LevelResult] = []
            for number, concurrency in enumerate(levels):
                level = asyncio.run(_run_level(
                    base_url, world, unsent, concurrency, seconds,
                    seed=1000 * (number + 1)))
                results.append(level)
                print(f"concurrency {concurrency:4d}  {level.rate:8.1f} /s  "
                      f"p95 {level.p95_ms:8.1f} ms  errors {level.errors}",
                      file=sys.stderr, flush=True)
                if not passes(level, budget_ms):
                    break
            sends = players - len(unsent)
            close_seconds = _timed_post(base_url, "/api/day/close")
            reveal_seconds = _timed_post(base_url, "/api/day/reveal")
            peak = _peak_memory_mb(process.pid)
        finally:
            process.terminate()
            process.wait(timeout=30)
    active, best = capacity(results, budget_ms, player_rate())
    return {
        "date": datetime.date.today().isoformat(),
        "machine": {"node": platform.node(), "cpus": os.cpu_count(),
                    "system": platform.platform(),
                    "python": platform.python_version()},
        "world": {"players": players, "pool": pool,
                  "seeded_days": seeded_days, "providers": "fake"},
        "budget_ms": budget_ms,
        "player_model": {"window_seconds": MODEL_WINDOW_SECONDS,
                         "requests": PLAYER_MODEL,
                         "rate": round(player_rate(), 4)},
        "levels": [asdict(level) for level in results],
        "best_rate": best,
        "active_players": active,
        "sends_stored": sends,
        "close_seconds": close_seconds,
        "reveal_seconds": reveal_seconds,
        "ran_out_of_senders": not unsent,
        "server_peak_memory_mb": peak,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.load")
    parser.add_argument("--players", type=int, default=2000)
    parser.add_argument("--pool", type=int, default=40)
    parser.add_argument("--seeded-days", type=int, default=14)
    parser.add_argument("--levels", default="1,2,4,8,16,32,64,128")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    parser.add_argument("--out", default=None,
                        help="the report path; the default prints it alone")
    parser.add_argument("--serve", action="store_true",
                        help="the server process; the tool starts this")
    parser.add_argument("--root", default=None)
    parser.add_argument("--port", type=int, default=None)
    arguments = parser.parse_args(argv)
    if arguments.serve:
        serve(Path(arguments.root), arguments.port)
        return 0
    report = run_load(
        players=arguments.players, pool=arguments.pool,
        seeded_days=arguments.seeded_days,
        levels=[int(part) for part in arguments.levels.split(",")],
        seconds=arguments.seconds, budget_ms=arguments.budget_ms)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.out is not None:
        Path(arguments.out).write_text(text, encoding="utf-8")
    print(text)
    print(f"capacity: {report['active_players']} active players "
          f"({report['best_rate']} requests/s at p95 <= "
          f"{report['budget_ms']:g} ms, {report['machine']['cpus']} CPUs, "
          f"pool of {report['world']['pool']}, fake providers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
