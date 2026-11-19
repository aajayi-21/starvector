"""The shared world of the operator command tests (spec OC1 section 9).

Two players, one revealed day that bru played, one open day that ade
played, a pinned clock, and a config file. The public server is a test
client of the app with dev mode off, adapted to the sender of the
command. Thus a test shows that a command works with no dev unit.
"""

import dataclasses
import datetime
import itertools
import json
from pathlib import Path

from fastapi.testclient import TestClient
from svc_fixture import (FIXED_CLOCK, build_service_fixture, mint_player,
                         mixed_wire_record)

from service import operator_cli, rollover, store
from service import operator_plan as plan
from service.config import ServiceConfig
from service.day import close_day, open_day, reveal_day
from service.server import create_app

FIRST_DAY = "2026-08-10"
OPEN_DAY = "2026-08-12"
TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
HOUR = "22:00"
LOGIN = "opal"
ENVIRON = {plan.LOGIN_VARIABLE: LOGIN,
           plan.LOGIN_SOURCE_VARIABLE: "sudo-user"}


class Clock:
    """A settable instant for the command, the server, and the day
    functions."""

    def __init__(self, text: str) -> None:
        self.instant = datetime.datetime.fromisoformat(text).replace(
            tzinfo=datetime.UTC)

    def __call__(self) -> datetime.datetime:
        return self.instant


@dataclasses.dataclass
class World:
    """One test world and what the command got from the test."""

    fixture: dict
    config: ServiceConfig
    path: Path
    client: TestClient
    clock: Clock
    answer: str = "yes"
    prompts: list[str] = dataclasses.field(default_factory=list)
    sent: list[tuple] = dataclasses.field(default_factory=list)
    _ids: itertools.count = dataclasses.field(
        default_factory=lambda: itertools.count(1))

    @property
    def root(self) -> Path:
        return self.fixture["store"]

    def call(self, method: str, path: str, body: dict | None,
             timeout: float) -> rollover.Answer:
        """The sender of the command, on the test client of the app.
        It adds the bearer, as the sender of the process does."""
        self.sent.append((method, path, body, timeout))
        answer = self.client.request(method, path, headers=HEADERS,
                                     json=body)
        return rollover.Answer(status=answer.status_code, body=answer.json())

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer

    def new_id(self) -> str:
        return f"{next(self._ids):016x}"

    def journal(self) -> tuple[store.OperatorEntry, ...]:
        return store.list_operator_entries(self.root)


def send(world_or_fixture, day: str, player: str,
         record: dict | None = None) -> None:
    """Store one send with no server."""
    root = world_or_fixture["store"] if isinstance(world_or_fixture, dict) \
        else world_or_fixture.root
    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": record or mixed_wire_record()})


def config_file(tmp_path: Path, config: ServiceConfig, *,
                name: str = "service.json", **changes) -> Path:
    """The config of the world as a file, with the given fields changed."""
    value = {"config_version": 1, "player": config.player,
             "scoring_config": config.scoring_config,
             "data_root": config.data_root, "store_root": config.store_root,
             "port": config.port}
    if config.closes_at_utc is not None:
        value["closes_at_utc"] = config.closes_at_utc
    value.update(changes)
    path = Path(tmp_path) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def build_world(tmp_path, monkeypatch, *, hour: str | None = None,
                instant: str = "2026-08-12T12:00:00") -> World:
    """One revealed day bru played, one open day ade played, two
    players, a pinned clock, and the public app with dev mode off."""
    from service import day as day_module
    from service import server as server_module

    fixture = build_service_fixture(tmp_path, with_credits=True)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=hour)
    clock = Clock(instant)
    monkeypatch.setattr(day_module, "utc_now", clock)
    monkeypatch.setattr(server_module, "utc_now", clock)
    for name, label, secret in (("ade", "Ade", "1" * 43),
                                ("bru", "Bru Lin", "2" * 43)):
        mint_player(config, player=name, display_name=label,
                    clock=lambda: FIXED_CLOCK, secret=secret)
    open_day(config, date=FIRST_DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    send(fixture, FIRST_DAY, "bru")
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    open_day(config, date=OPEN_DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="c" * 32, secret="d" * 64)
    send(fixture, OPEN_DAY, "ade")
    client = TestClient(create_app(config, dev_mode=False,
                                   operator_token=TOKEN))
    return World(fixture=fixture, config=config,
                 path=config_file(tmp_path, config), client=client,
                 clock=clock)


def sv(world: World, *argv: str, **changes) -> int:
    """Run one command on the world. A keyword argument replaces one
    injected value, and None gives the value of the process."""
    values = {"call": world.call, "ask": world.ask, "now": world.clock,
              "environ": ENVIRON, "stdin_is_tty": True,
              "stdout_is_tty": True, "new_id": world.new_id}
    values.update(changes)
    return operator_cli.main(["--service-config", str(world.path), *argv],
                             **values)


def put_a_newer_day_in_front(world: World) -> str:
    """Store a newer revealed day in front of the open day, and give
    its label. The open day stays as it is, behind the newer one."""
    newer = "2026-08-14"
    record = store.read_day_record(world.root, OPEN_DAY)
    store.write_day_record(world.root, dataclasses.replace(
        record, day=newer, status="open", closed_at=None, revealed_at=None))
    for before, after, field in (("open", "closed", "closed_at"),
                                 ("closed", "revealed", "revealed_at")):
        store.update_day_status(world.root, newer, expect_status=before,
                                new_status=after, timestamp_field=field,
                                timestamp=FIXED_CLOCK)
    return newer


def build_vp1_world(tmp_path, monkeypatch, *, instant: str) -> World:
    """A spec VP1 world with one open day and no player record. The
    day has no target: the pulse after the close picks it."""
    from svc_fixture import make_vp1

    from service import day as day_module
    from service import server as server_module

    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    config = fixture["service_config"]
    clock = Clock(instant)
    monkeypatch.setattr(day_module, "utc_now", clock)
    monkeypatch.setattr(server_module, "utc_now", clock)
    open_day(config, date=OPEN_DAY, clock=lambda: FIXED_CLOCK, now=clock)
    send(fixture, OPEN_DAY, "ade")
    path = config_file(
        tmp_path, config, pick_protocol="vp1", beacon={"kind": "fake"},
        pool_roots_dir=str(fixture["pool_roots_dir"]))
    return World(fixture=fixture, config=config, path=path,
                 client=TestClient(create_app(config, dev_mode=False)),
                 clock=clock)
