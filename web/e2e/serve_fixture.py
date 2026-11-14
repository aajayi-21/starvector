"""The e2e fixture server (spec W1 B11, grown by spec M1 B9).

Runs the live trial server on a throwaway store: fake providers,
warm commonness tables, one revealed day for practice and one open
day to play. No network and no API key — the fixture config wires
the fake encoder slots. Playwright's webServer starts this script
and waits on the port.

Two players are stored, which switches access control on for the
full world: each spec plants a session cookie and the operator
calls hold the bearer. Each player gets one session with a pinned
secret (spec BR1 section 4: the cookie holds a session). The two
players are records of before spec A2: they have no password, and
the account spec sets one. The session secrets, the pepper, and
the operator token are constants here on purpose. The store is a
temporary directory built for one test run and thrown away, and a
browser cannot plant a cookie nobody gave it, so a spec that wants
a session must name one.

Sign-up is open (spec A2), thus the sign-up spec makes an account
through the screens. The digester is the deployed one, Argon2id
with a pepper, so the browser walk spends the deployed digest.

Two arguments the deployed server does not get:

`cookie_secure` off, because Chromium stores a cookie with the
transport flag sent from an http loopback port and then does not
send it back. The failure has no connection to the code a reader
blames for it. The specs that sign in through the screens use
the cookie the server itself set, thus the flag comes off here
and nowhere else.

`operator_token`, because create_app refuses to start with player
records stored and no token — a quiet hole is worse than a loud
stop, and this world stores two.
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

import dataclasses  # noqa: E402
import datetime  # noqa: E402

import uvicorn  # noqa: E402
from svc_fixture import (FIXED_CLOCK, build_service_fixture,  # noqa: E402
                         mixed_wire_record)

from service import access, players, signin, store  # noqa: E402
from service.day import close_day, open_day, reveal_day  # noqa: E402
from service.digests import Argon2Digester  # noqa: E402
from service.server import create_app  # noqa: E402

PRACTICE_DAY = "2026-08-10"
LIVE_DAY = "2026-08-12"
OPERATOR_TOKEN = "e2e-operator-token"
# The store key "ade" matches the configured player, thus the
# fallback world and this one resolve to the same identity and no
# stored path moves.
CAST = (("ade", "Ade"), ("bru", "Bru Lin"))
# Not a secret: the throwaway world's pepper.
PEPPER = b"e2e-pepper-for-a-throwaway-store"
# The pinned session secrets: web/e2e/helpers.ts SESSIONS holds the
# same values, kept equal by hand.
SESSION_SECRETS = {"ade": "3" * 43, "bru": "4" * 43}


def main() -> None:
    port = int(os.environ.get("SV_E2E_PORT", "8199"))
    root = Path(tempfile.mkdtemp(prefix="sv-e2e-"))
    print(f"building the fixture store in {root}", file=sys.stderr, flush=True)
    fixture = build_service_fixture(root)
    # The close time lights the countdown field (spec S2 B8).
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc="22:00", signup="open")

    def clock() -> str:
        return FIXED_CLOCK

    now = datetime.datetime.now(datetime.UTC)
    for name, label in CAST:
        players.make_player(config, player=name, display_name=label,
                            clock=clock)
        access.open_session(root / "store", name, user_agent="Playwright",
                            instant=now, secret=SESSION_SECRETS[name])
    # Open sign-up wants a name claim for each stored player.
    signin.claim_stored_names(root / "store", now)

    # A revealed, played day: the live history, leaderboard, and
    # stored-submission surfaces then hold one honest row.
    open_day(config, date=PRACTICE_DAY, clock=clock,
             pick_seed="a" * 32, secret="b" * 64)
    store.write_once_json(
        store.submission_path(root / "store", PRACTICE_DAY, "ade"),
        {"day": PRACTICE_DAY, "player": "ade", "trial_id": "e" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=clock)
    reveal_day(config, clock=clock)
    open_day(config, date=LIVE_DAY, clock=clock,
             pick_seed="c" * 32, secret="d" * 64)
    # The second player sends on the live day and the first does
    # not, thus the board the reveal spec opens holds two rows in a
    # sequence the scores set. This record is not the one the
    # browser draws, thus the two scores are different.
    store.write_once_json(
        store.submission_path(root / "store", LIVE_DAY, "bru"),
        {"day": LIVE_DAY, "player": "bru", "trial_id": "b" * 32,
         "received_at": FIXED_CLOCK,
         "record": {**mixed_wire_record(),
                    "impressions": ["a wide flat plain", "warm light"]}})
    print("fixture ready", file=sys.stderr, flush=True)
    # dev_mode: the throwaway world is what the owner's offline
    # runbook (spec S2 section 9 step 2) drives from the operator
    # console, and the console reads the dev surfaces.
    uvicorn.run(create_app(config, dev_mode=True, cookie_secure=False,
                           operator_token=OPERATOR_TOKEN,
                           digester=Argon2Digester(pepper=PEPPER)),
                host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
