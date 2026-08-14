"""The e2e fixture server (spec W1 B11).

Runs the live trial server on a throwaway store: fake providers,
warm commonness tables, one revealed day for practice and one open
day to play. No network and no API key — the fixture config wires
the fake encoder slots. Playwright's webServer starts this script
and waits on the port.
"""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# svc_fixture does `from conftest import ...`, which pytest gives a
# path for — a standalone script adds the two test roots by hand.
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tests" / "service"))

import uvicorn  # noqa: E402
from svc_fixture import FIXED_CLOCK, build_service_fixture  # noqa: E402

from service.day import close_day, open_day, reveal_day  # noqa: E402
from service.server import create_app  # noqa: E402

PRACTICE_DAY = "2026-08-10"
LIVE_DAY = "2026-08-12"


def main() -> None:
    port = int(os.environ.get("SV_E2E_PORT", "8199"))
    root = Path(tempfile.mkdtemp(prefix="sv-e2e-"))
    print(f"building the fixture store in {root}", file=sys.stderr, flush=True)
    fixture = build_service_fixture(root)
    config = fixture["service_config"]

    def clock() -> str:
        return FIXED_CLOCK

    # A revealed day for practice: opened, closed clean (zero
    # submissions), revealed. Then the day the tests play.
    open_day(config, date=PRACTICE_DAY, clock=clock,
             pick_seed="a" * 32, secret="b" * 64)
    close_day(config, clock=clock)
    reveal_day(config, clock=clock)
    open_day(config, date=LIVE_DAY, clock=clock,
             pick_seed="c" * 32, secret="d" * 64)
    print("fixture ready", file=sys.stderr, flush=True)
    uvicorn.run(create_app(config), host="127.0.0.1", port=port,
                log_level="warning")


if __name__ == "__main__":
    main()
