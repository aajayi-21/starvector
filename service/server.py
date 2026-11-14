"""The localhost HTTP surface (spec S1 section 9).

FastAPI endpoints in front of the store, with the R3 rules held
structurally: pre-reveal refusals are module constants returned
before target-dependent work, and the acknowledgment is a
validation echo with no score in it.

This process serves the API and no page. The player app and the
operator console are the built web app of spec W1, which the edge
serves from web/dist and which reaches this process at /api and
/image. The hand-written pages that stood in before
that app existed retired on 2026-08-16, thus GET / answers 404
here and the app owns each path a person types.
"""

import argparse
import asyncio
import datetime
import json
import logging
import math
import os
import secrets
import sqlite3
import sys
import threading
import urllib.parse
from collections.abc import Container
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from core import aggregate
from core.aggregate import shrunk_log_theta, skill_summary
from core.intake import IntakeError, validate_submission
from core.types import ROUTING_TABLE, IntakeGates, Submission, Weights
from pipeline.config import (fusion_weights, intake_gates,
                             load_scoring_config, placement_config)
from pipeline.context import load_preparation_record
from pool.artifacts import load_image_bytes
from pool.preparation.config import load_preparation_config
from service import (access, auth, console, credits, digests, limits,
                     passwords, rollover, rollup, schedule, signin, store)
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)

# The D5 solo display inputs (spec S1 section 14a): display-only, a
# fitted population comes with live players.
POPULATION_MEAN = 0.0
POPULATION_SPREAD = 0.15

# Constant pre-reveal refusal bytes (R3): one body for each refused
# path, with no target-dependent work before it.
_NOT_REVEALED = b'{"detail":"not revealed"}'
_NO_DAY = b'{"detail":"no day open"}'
_UNAUTHORIZED = b'{"detail":"unauthorized"}'
_NO_SUBMISSION = b'{"detail":"no submission"}'
_DEV_OFF = b'{"detail":"not found"}'
_NO_PRACTICE = b'{"detail":"no revealed day"}'
_NOT_PRACTICE = b'{"detail":"not a practice day"}'
# One constant body covers a player with no picture and a name
# with no record (spec A1 section 3) - no roster oracle.
_NO_AVATAR = b'{"detail":"no avatar"}'
# The sign-in refusals (spec BR1 section 4): one body for each
# condition that stops a code, and one for a session id that is not
# the caller's.
_BAD_CODE = b'{"cause":"bad-code"}'
_TOO_MANY = b'{"cause":"too-many-attempts"}'
_NO_SESSION = b'{"detail":"no session"}'
_NO_ACCOUNTS = b'{"cause":"no-accounts"}'
# The password refusals (spec A2 section 8): one body for each pair
# that does not sign in, one for each recovery that does not work, and
# one for a current password that does not agree.
_BAD_SIGN_IN = b'{"cause":"sign-in"}'
_BAD_RECOVERY = b'{"cause":"recovery"}'
_WRONG_PASSWORD = b'{"cause":"password"}'
_BAD_ORIGIN = b'{"cause":"origin"}'
_BAD_CONTENT_TYPE = b'{"cause":"content-type"}'
# The practice limit (spec PL1 section 1).
_PRACTICE_LIMIT = b'{"cause":"practice-limit"}'

# The gated skill board (spec M1 section 8). Two properties, each
# load-bearing. It carries each field the view declares, thus a
# screen that trusts the type reads no missing value while the
# board is gated. And it carries the two floors, thus it holds no
# number the wire does not give it - they are different
# quantities, one counting a player's trials and one counting
# eligible players. The floors come from the module that owns
# them, thus one edit moves the board and the gate together.
_SKILL_INACTIVE = json.dumps({
    "active": False,
    "player_count": 0,
    "eligible_count": 0,
    "degenerate_count": 0,
    "eligibility_floor": aggregate.ELIGIBLE_TRIAL_FLOOR,
    "recomputed_floor": None,
    "fit_floor": aggregate.FIT_PLAYER_FLOOR,
    "provisional": True,
    "rows": [],
    "baseline_band": [],
    "population": None,
    "variation": None,
    "discovery": None,
}, separators=(",", ":")).encode()

# The skill-board fields the artifact keeps and the player wire
# drops (spec M1 section 8).
#
# The configuration identity: the two hashes, and the rank seed,
# which is a digest of one of them. The operator keeps the ability
# to reproduce the board. A player wants none of it, and a body
# that carries it makes the R4 two-world compare read a difference
# that has nothing to do with the target.
#
# The two standing monitors: the baseline check and the stopping
# monitor. Ruling 5 of 2026-08-15 publishes the discovery claim
# and holds these two for the operator, because they hold no
# player-facing copy, and a reader gives a number that arrives
# with no sentence one of their own. Section 6 asks for the
# goodness-of-fit check in its four numbers, thus the player panel
# shows three of the four and the operator reads the fourth in the
# artifact - a divergence this comment records rather than
# resolves.
_OPERATOR_ONLY = ("scoring_config_hash", "preparation_version_id",
                  "rank_seed", "baseline", "stopping_monitor")

# Error lines of the password paths. A line names the record that
# stopped a move and holds no password, no code, and no digest.
credential_log = logging.getLogger("starvector.credentials")


def _skill_value(ps: list[float]) -> dict | None:
    """The history skill values, or None (spec S2 section 3).

    None is a defined wire value for two conditions: no revealed
    trial with a stored row, and each stored p equal to 1.0 - the
    aggregation refuses an S statistic of zero there.
    """
    if not ps or all(p == 1.0 for p in ps):
        return None
    summary = skill_summary(ps, unbiased=(len(ps) >= 2))
    shrunk = shrunk_log_theta(summary.log_theta, summary.n,
                              POPULATION_MEAN, POPULATION_SPREAD)
    return {
        "theta": summary.theta,
        "shrunk": math.exp(shrunk),
        "evidence_p": summary.evidence_p,
        "n": summary.n,
    }


def _newest_revealed(root: Path) -> str | None:
    """The newest revealed day, or None.

    Hoisted out of _streak: the daily board calls the streak one
    time for each row, and this walk reads a day record for each
    day. Passing it in drops the cost for each row to the length of
    the run (spec M1 section 7).
    """
    for day in reversed(store.list_days(root)):
        if store.read_day_record(root, day).status == "revealed":
            return day
    return None


def _streak(root: Path, player: str, newest: str | None) -> int:
    """Spec S2 section 3: the count of calendar days in an unbroken
    run that ends on the newest revealed day, each day holding the
    player's stored submission. Zero without a revealed day or when
    the newest revealed day holds none. The open day cannot enter -
    it lies after the run's last day, thus the value is a function
    of revealed days and the player's own records alone (R4).
    """
    if newest is None:
        return 0
    count = 0
    cursor = date.fromisoformat(newest)
    while store.submission_path(
            root, cursor.isoformat(), player).is_file():
        count += 1
        cursor -= timedelta(days=1)
    return count


def _activates_weighted_channel(submission: Submission,
                                weights: Weights) -> bool:
    """The section 14a OP2 pre-check: one weighted channel must read.

    The pure mirror of the routing rules: a DESCRIPTION atom counts
    with text alone (the D10 no-text rule), a WHOLE-DRAWING atom
    counts, and a RELATION atom counts for placement. No encoder in
    the path - the check reads no target and no vector.
    """
    for atom in submission.atoms:
        channels = ROUTING_TABLE[atom.type]
        if not channels or channels[0] not in weights:
            continue
        if atom.type == "DESCRIPTION" and atom.text is None:
            continue
        return True
    return False


def _mime_of(image_bytes: bytes) -> str:
    """The media type from magic bytes, the resolve.data_uri set."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def _revealed_targets(root: Path) -> dict[str, str]:
    """Map of target image id to day, for revealed days alone."""
    targets: dict[str, str] = {}
    for day in store.list_days(root):
        record = store.read_day_record(root, day)
        if record.status == "revealed":
            targets[record.target_id] = day
    return targets


def create_app(service_config: ServiceConfig,
               dev_mode: bool = False, *,
               cookie_secure: bool = True,
               operator_token: str | None = None,
               practice_limiter: limits.WindowLimiter | None = None,
               digester: digests.PasswordDigester | None = None,
               usual_passwords: Container[str] | None = None,
               ) -> FastAPI:
    """The app factory - tests run it through TestClient.

    With dev_mode the server adds the section 14b surfaces: the
    target is readable while the day is open, a draft scores when
    asked with the full pool ordering, and each pool
    image serves - the R3 wire rules are deliberately off, for the
    owner's scoring work on the development pool alone. Without the
    flag the dev paths answer one constant 404.

    cookie_secure turns off the session cookie's transport flag for
    the offline browser tests, which speak http to a loopback port.
    The default is the deployed attribute set, thus a deployment
    that forgets the argument gets the safe one.

    operator_token arrives as an argument and is not read from the
    environment here, in the manner of open_day's secret: a
    component reads no global configuration. The start-up path
    does the environment read.

    practice_limiter is an argument for the tests. The default holds
    the values of spec PL1 section 1.

    digester computes the password digests (spec A2 section 5.2). It
    arrives as an argument, because the start-up path reads the pepper
    from the environment. With None the server has no password paths:
    each of them answers the constant 404. usual_passwords is the
    table of usual passwords, and the default reads the committed
    file.

    Raises ServiceConfigError when the store holds player records
    and no operator token is set. A quiet hole is worse than a loud
    stop (spec M1 section 4). With sign-up open it also raises with no
    operator token, with no digester, and with a stored player that
    has no name claim (spec A2 section 10).
    """
    signup_open = service_config.signup == "open"
    if (signup_open or store.any_player(Path(service_config.store_root))) \
            and not operator_token:
        raise ServiceConfigError(
            "the store holds player records or sign-up is open, and the "
            "operator token is not set - put STARVECTOR_OPERATOR_TOKEN in "
            "the deployment environment file")
    if signup_open and digester is None:
        raise ServiceConfigError(
            "sign-up is open and the password pepper is not set - put "
            f"{digests.PEPPER_ENVIRONMENT_NAME} in the deployment "
            "environment file")
    if signup_open:
        unclaimed = signin.unclaimed_players(Path(service_config.store_root))
        if unclaimed:
            raise ServiceConfigError(
                "sign-up is open and these stored players have no name "
                f"claim: {', '.join(unclaimed)} - run python -m "
                "service.players claim-names")
    if digester is not None and usual_passwords is None:
        usual_passwords = passwords.load_usual_passwords()
    scoring_config = load_scoring_config(Path(service_config.scoring_config))
    gates: IntakeGates = intake_gates(scoring_config)
    weights: Weights = fusion_weights(scoring_config)
    relation_vocabulary = list(
        placement_config(scoring_config).relation_vocabulary)
    # The canonical canvas comes from the preparation config the
    # record names - the one render source (R2 of spec P2).
    record = load_preparation_record(
        Path(scoring_config.input.preparation_record))
    canvas_px = load_preparation_config(
        Path(record.config_path)).linedraw.canvas_px
    # The season facts (spec BR1 section 6): a pool with the dev_only
    # flag is a test season, and its numbers stay off each public
    # surface (spec P1a R13). The app labels them as test numbers.
    about_value = {"test_season": record.dev_only,
                   "photo_count": record.image_count,
                   "closes_at_utc": service_config.closes_at_utc}
    image_credits = credits.load_credits(
        Path(record.pool_release_record_path), Path(service_config.data_root))
    root = Path(service_config.store_root)
    data_root = Path(service_config.data_root)
    player = service_config.player

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    # The avatar path has its own stream check and its own refusal.
    app.add_middleware(limits.BodyCap, exempt=("/api/account/avatar",))
    code_limiter = limits.WindowLimiter()
    practice_counts = practice_limiter or limits.practice_limiter()
    # The password counters (spec A2 section 9.2). Each failure counts
    # for its client address and for its username.
    address_failures = limits.WindowLimiter()
    name_failures = limits.name_failure_limiter()
    signup_counts = limits.signup_limiter()

    def _access_on() -> bool:
        """Access control is on: a caller needs a session.

        Ruling 7 of spec M1 turns it on at the first stored player
        record. Open sign-up also turns it on, with no record stored:
        no caller then plays as the configured player (spec A2 section
        10.2).
        """
        return signup_open or store.any_player(root)

    def _unauthorized() -> Response:
        return Response(content=_UNAUTHORIZED, status_code=401,
                        media_type="application/json")

    def _bearer_ok(request: Request) -> bool:
        """This holds the operator token.

        Not agreed with no configured token, thus each bearer path
        refuses in each world where nobody set the operator plane up.
        """
        if not operator_token:
            return False
        scheme, _, given = request.headers.get(
            "authorization", "").partition(" ")
        return (scheme.lower() == "bearer"
                and auth.constant_time_equal(given, operator_token))

    def _operator_ok(request: Request) -> bool:
        """The operator gate: open in the fallback, the bearer above.

        Ruling 7 of spec M1: with no stored player record nothing
        holds credentials, thus the day commands and the console
        answer as they do today and the offline runbook wants no
        edit. The first player record closes this, and open sign-up
        closes it too (spec A2 section 10.2).
        """
        return not _access_on() or _bearer_ok(request)

    def _caller(request: Request) -> str | Response:
        """The player behind the cookie, or the constant refusal.

        Ruling 7 of spec M1: with no player record stored the
        identity is the configured player and nothing holds
        credentials, thus a box that plays alone answers as it does
        today. With records stored the session cookie names a session
        record (spec BR1 section 4), read for each answer. A deleted
        session, a session at the end of its life, and a revoked player
        thus
        stop at the next read.
        """
        if not _access_on():
            return player
        resolved = access.resolve_session(
            root, request.cookies.get(auth.SESSION_COOKIE), utc_now())
        return _unauthorized() if resolved is None else resolved

    def _session_cookie(value: str) -> dict[str, str]:
        return {"set-cookie": auth.session_cookie_header(
            value, secure=cookie_secure)}

    @app.get("/join/{token}")
    def join(token: str) -> Response:
        """The invite address of before spec A2. The invite is gone
        (ruling 2 of that spec), and each token gets the constant 404:
        a stored invite digest opens nothing."""
        return Response(content=_DEV_OFF, status_code=404,
                        media_type="application/json")

    @app.post("/api/session/signout")
    def sign_out(request: Request) -> Response:
        """Sign this device out: delete its session, clear its cookie.

        The answer is the same with a live session, a dead one, and
        none - the device is signed out in each of them.
        """
        access.close_session(root, request.cookies.get(auth.SESSION_COOKIE))
        return JSONResponse(
            {"signed_out": True},
            headers={"set-cookie": auth.clear_cookie_header(
                secure=cookie_secure)})

    def _current_digest(request: Request) -> str | None:
        key = access.session_key(request.cookies.get(auth.SESSION_COOKIE))
        return None if key is None else key[1]

    @app.get("/api/sessions")
    def sessions_view(request: Request) -> Response:
        """The caller's signed-in devices (spec BR1 section 4)."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if not _access_on():
            return JSONResponse({"sessions": []})
        return JSONResponse({"sessions": access.session_rows(
            root, caller, _current_digest(request), utc_now())})

    @app.delete("/api/sessions/{session_id}")
    def session_remove(request: Request, session_id: str) -> Response:
        """Sign one of the caller's devices out. A session id that is
        not one of the caller's answers the constant 404."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        try:
            removed = _access_on() \
                and store.delete_session(root, caller, session_id)
        except store.StoreError:
            removed = False
        if not removed:
            return Response(content=_NO_SESSION, status_code=404,
                            media_type="application/json")
        return JSONResponse({"removed": 1})

    @app.post("/api/sessions/others/signout")
    def sessions_others_signout(request: Request) -> Response:
        """Sign each of the caller's other devices out."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if not _access_on():
            return JSONResponse({"removed": 0})
        removed = store.delete_player_sessions(
            root, caller, keep=_current_digest(request))
        return JSONResponse({"removed": removed})

    @app.post("/api/device-code")
    def device_code_issue(request: Request) -> Response:
        """A one-time code that signs one more device in (BR1 section 4).

        With no player records there is no sign-in to extend, thus
        the answer is the constant refusal.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if not _access_on():
            return Response(content=_NO_ACCOUNTS, status_code=409,
                            media_type="application/json")
        code, expires_at = access.issue_device_code(root, caller, utc_now())
        return JSONResponse({"code": auth.display_device_code(code),
                             "expires_at": expires_at})

    @app.post("/api/device-code/redeem")
    async def device_code_redeem(request: Request) -> Response:
        """Trade a device code for a session on this device.

        The failure limiter stands before the store read: a client
        at its cap gets the 429 with no work done. Each condition a
        code does not succeed on answers one constant body, and each
        failure
        counts. The handler is async with no await after the body
        read, thus the claim runs on the loop thread in one piece.
        """
        key = limits.client_key(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"))
        if not code_limiter.allowed(key):
            return Response(content=_TOO_MANY, status_code=429,
                            media_type="application/json")
        try:
            body = await request.json()
        except Exception:
            body = None
        text = body.get("code") if isinstance(body, dict) else None
        instant = utc_now()
        redeemed = access.redeem_device_code(root, text, instant)
        if redeemed is None:
            code_limiter.record(key)
            return Response(content=_BAD_CODE, status_code=400,
                            media_type="application/json")
        value = access.open_session(
            root, redeemed, user_agent=request.headers.get("user-agent"),
            instant=instant)
        return JSONResponse({"player": redeemed,
                             "display_name": _label_of(redeemed)},
                            headers=_session_cookie(value))

    # -- accounts with a username and a password (spec A2 section 8) --

    def _constant(body: bytes, status: int) -> Response:
        return Response(content=body, status_code=status,
                        media_type="application/json")

    def _address_key(request: Request) -> str:
        return limits.client_key(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"))

    async def _credential_body(request: Request) -> dict | Response:
        """The JSON object of one credential POST, or the refusal.

        The header that names the site of the page must name the
        host that the browser spoke to. A page of a different site
        thus cannot sign this browser in to an account that it picks,
        which SameSite=Lax does not stop for a POST with no cookie.
        The media type must be JSON, which plain HTML of a different
        site cannot send.
        """
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if not origin or not host \
                or urllib.parse.urlsplit(origin).netloc != host:
            return _constant(_BAD_ORIGIN, 403)
        media_type = request.headers.get("content-type", "")
        if media_type.split(";")[0].strip().lower() != "application/json":
            return _constant(_BAD_CONTENT_TYPE, 415)
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body must be a JSON object"},
                status_code=400)
        return body

    def _failures_allowed(address: str, name: str) -> bool:
        return address_failures.allowed(address) \
            and name_failures.allowed(name)

    def _count_failure(address: str, name: str) -> None:
        address_failures.record(address)
        name_failures.record(name)

    def _signed_in(player_name: str, request: Request,
                   extra: dict | None = None, status: int = 200) -> Response:
        """Open a session for the player and answer with its cookie."""
        value = access.open_session(
            root, player_name, user_agent=request.headers.get("user-agent"),
            instant=utc_now())
        headers = _session_cookie(value)
        body = {"player": player_name,
                "display_name": _label_of(player_name)}
        if extra:
            body.update(extra)
            # A recovery code is in this answer one time.
            headers["cache-control"] = "no-store"
        return JSONResponse(body, status_code=status, headers=headers)

    @app.get("/api/signup")
    def signup_view() -> Response:
        """Does this server make accounts (spec A2 section 8). The gate
        screen reads this one time. With sign-up closed the answer is
        the constant 404."""
        if not signup_open:
            return _constant(_DEV_OFF, 404)
        return JSONResponse({"open": True})

    @app.post("/api/signup")
    async def signup_make(request: Request) -> Response:
        """Make one account and sign this device in (spec A2 section
        3.1).

        The cap counts the accounts made, for the client address and
        for the process, and stands before the store is read. The
        digest and the store writes are away from the loop thread.
        """
        if not signup_open:
            return _constant(_DEV_OFF, 404)
        body = await _credential_body(request)
        if isinstance(body, Response):
            return body
        address = _address_key(request)
        if not signup_counts.allowed(address):
            return _constant(_TOO_MANY, 429)
        try:
            name, code = await asyncio.to_thread(
                signin.sign_up, root, username=body.get("username"),
                password=body.get("password"), digester=digester,
                usual=usual_passwords, instant=utc_now())
        except signin.Refused as refused:
            status = 409 if refused.cause == signin.NAME_TAKEN else 400
            return JSONResponse({"cause": refused.cause}, status_code=status)
        signup_counts.record(address)
        return _signed_in(
            name, request, status=201,
            extra={"recovery_code": auth.display_recovery_code(code)})

    @app.post("/api/signin")
    async def signin_open(request: Request) -> Response:
        """Open a session for a username and a password (spec A2
        section 3.2).

        Each pair that does not sign in gets one constant body and
        counts as one failure, for the address and for the username.
        A credential record that does not parse is an error line and
        the same constant body: it does not read as "no password".
        """
        if digester is None:
            return _constant(_DEV_OFF, 404)
        body = await _credential_body(request)
        if isinstance(body, Response):
            return body
        address = _address_key(request)
        name = limits.name_key(body.get("username"))
        if not _failures_allowed(address, name):
            return _constant(_TOO_MANY, 429)
        try:
            found = await asyncio.to_thread(
                signin.sign_in, root, username=body.get("username"),
                password=body.get("password"), digester=digester,
                instant=utc_now())
        except (store.StoreError, ValueError) as error:
            credential_log.error("sign-in stopped on a stored record: %s",
                                 error)
            found = None
        if found is None:
            _count_failure(address, name)
            return _constant(_BAD_SIGN_IN, 401)
        return _signed_in(found, request)

    @app.post("/api/recover")
    async def recover_account(request: Request) -> Response:
        """Trade a recovery code for a new password (spec A2 section
        3.3). One constant body covers each recovery that does not
        work, and each of them counts as one failure."""
        if digester is None:
            return _constant(_DEV_OFF, 404)
        body = await _credential_body(request)
        if isinstance(body, Response):
            return body
        address = _address_key(request)
        name = limits.name_key(body.get("username"))
        if not _failures_allowed(address, name):
            return _constant(_TOO_MANY, 429)
        try:
            found = await asyncio.to_thread(
                signin.recover, root, username=body.get("username"),
                recovery_code=body.get("recovery_code"),
                password=body.get("password"), digester=digester,
                usual=usual_passwords, instant=utc_now())
        except signin.Refused as refused:
            return JSONResponse({"cause": refused.cause}, status_code=400)
        except (store.StoreError, ValueError) as error:
            credential_log.error("recovery stopped on a stored record: %s",
                                 error)
            found = None
        if found is None:
            _count_failure(address, name)
            return _constant(_BAD_RECOVERY, 401)
        player_name, new_code = found
        return _signed_in(
            player_name, request,
            extra={"recovery_code": auth.display_recovery_code(new_code)})

    async def _account_move(request: Request) -> tuple[str, dict] | Response:
        """The caller and the body of one account POST, or the refusal."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if digester is None:
            return _constant(_DEV_OFF, 404)
        if not _access_on():
            return _constant(_NO_ACCOUNTS, 409)
        body = await _credential_body(request)
        if isinstance(body, Response):
            return body
        return caller, body

    @app.post("/api/account/password")
    async def account_password(request: Request) -> Response:
        """Replace the caller's password (spec A2 section 3.4).

        A caller with no password - a player from before spec A2 -
        sets the first one with the session alone, and the answer
        holds the first recovery code. Each other device signs out.
        """
        moved = await _account_move(request)
        if isinstance(moved, Response):
            return moved
        caller, body = moved
        address = _address_key(request)
        if not _failures_allowed(address, caller):
            return _constant(_TOO_MANY, 429)
        try:
            code = await asyncio.to_thread(
                signin.set_password, root, player=caller,
                current_password=body.get("current_password"),
                password=body.get("password"), digester=digester,
                usual=usual_passwords, instant=utc_now())
        except signin.Refused as refused:
            return JSONResponse({"cause": refused.cause}, status_code=400)
        except signin.WrongPassword:
            _count_failure(address, caller)
            return _constant(_WRONG_PASSWORD, 403)
        removed = store.delete_player_sessions(
            root, caller, keep=_current_digest(request))
        return JSONResponse(
            {"changed": True, "signed_out": removed,
             "recovery_code": None if code is None
             else auth.display_recovery_code(code)},
            headers={"cache-control": "no-store"})

    @app.post("/api/account/recovery-code")
    async def account_recovery_code(request: Request) -> Response:
        """A new recovery code for the caller. The earlier one is dead."""
        moved = await _account_move(request)
        if isinstance(moved, Response):
            return moved
        caller, body = moved
        address = _address_key(request)
        if not _failures_allowed(address, caller):
            return _constant(_TOO_MANY, 429)
        try:
            code = await asyncio.to_thread(
                signin.new_recovery_code, root, player=caller,
                current_password=body.get("current_password"),
                digester=digester, instant=utc_now())
        except signin.WrongPassword:
            _count_failure(address, caller)
            return _constant(_WRONG_PASSWORD, 403)
        return JSONResponse(
            {"recovery_code": auth.display_recovery_code(code)},
            headers={"cache-control": "no-store"})

    @app.post("/api/account/recovery-code/stop")
    async def account_recovery_stop(request: Request) -> Response:
        """Remove the operator's code of the caller (spec A2 section
        6.1). The session is sufficient, and the answer is the same
        with a code and with none."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if _access_on():
            await asyncio.to_thread(signin.stop_operator_code, root,
                                    player=caller, instant=utc_now())
        return JSONResponse({"stopped": True})

    @app.get("/api/door")
    def door_view(request: Request) -> Response:
        """Is the open door on (spec A1 section 4). The gate screen
        probes this one time. Without --dev the answer is the dev
        surfaces' constant 404, thus production bytes do not move."""
        if not dev_mode:
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        return JSONResponse({"open": True})

    @app.post("/api/door")
    async def door_enter(request: Request) -> Response:
        """The open door: a typed name becomes a session (spec A1
        section 4).

        Development alone. The gate is dev_mode and the operator
        gate (spec PL1 section 5): the dev unit shares the production
        store, thus a typed name with no bearer can sign in as each
        player. An unknown name gets a record, an active name makes a
        new session, and a revoked name is refused: the door cannot put a
        revoked player back.
        """
        from service import players

        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body is not JSON"},
                status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body must be an object"},
                status_code=400)
        name = body.get("player")
        label = body.get("display_name") or name
        try:
            store.check_player_name(name, "player")
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-player",
                                 "detail": str(error)}, status_code=400)
        try:
            store.check_display_name(label, "display_name")
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-display-name",
                                 "detail": str(error)}, status_code=400)
        record = store.read_player_or_none(root, name)
        try:
            if record is None:
                # A door record has no password: the door hands out
                # a session and nothing else (spec A2 section 10.2).
                record = players.make_player(
                    service_config, player=name, display_name=label)
            elif record.status != "active":
                return JSONResponse({"cause": "revoked"}, status_code=409)
            # A new session for a known name, and no token turn: a
            # sign-in on a second device leaves the first signed in
            # (spec BR1 section 4 supersedes the A1 turn).
            value = access.open_session(
                root, record.player,
                user_agent=request.headers.get("user-agent"),
                instant=utc_now())
        except (store.StoreError, access.AccessError) as error:
            # The read above and the write here can straddle a
            # sign-up or a revoke from a different process - the
            # command line on the box. The store's own guards refuse, and the door says
            # so rather than crashing.
            return JSONResponse({"cause": "refused",
                                 "detail": str(error)}, status_code=409)
        return JSONResponse(
            {"player": record.player,
             "display_name": _label_of(record.player)},
            headers=_session_cookie(value))

    # The resident scoring context (P5 R1): wired lazily one time
    # for each process from the server's config, read by the close
    # endpoint, the dev surfaces, and practice. The lock stops a
    # double wire when two threadpool handlers race the first use.
    # A new start re-reads config. This supersedes the fifth 14b
    # ruling's wording: the dev surfaces score with the config the
    # server names, not the one the latest day names - the two are
    # the same file in usual operation.
    resident_state: dict[str, object] = {}
    resident_lock = threading.Lock()
    # Day-start values (P5 item B4), keyed by target - targets
    # of revealed days do not change, thus no invalidation. Its own
    # lock: the resident lock does not nest.
    practice_precompute: dict[str, object] = {}
    precompute_lock = threading.Lock()

    def _resident():
        from service.scoring import wire_for_close

        with resident_lock:
            if "wired" not in resident_state:
                resident_state["wired"] = wire_for_close(
                    scoring_config, service_config.scoring_config,
                    data_root)
            return resident_state["wired"]

    def _picked_day(day: str | None) -> str | Response:
        """The requested day, or the latest one - the day browser
        (fifth 14b ruling) reads each stored day."""
        if day is None:
            latest = store.latest_day(root)
            if latest is None:
                return Response(content=_NO_DAY, status_code=404,
                                media_type="application/json")
            return latest
        if day not in store.list_days(root):
            return JSONResponse({"cause": "no-such-day",
                                 "detail": f"no stored day {day!r}"},
                                status_code=404)
        return day

    @app.get("/api/dev/days")
    def dev_days(request: Request) -> Response:
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        rows = []
        for day in reversed(store.list_days(root)):
            record = store.read_day_record(root, day)
            rows.append({
                "day": record.day,
                "status": record.status,
                "trial_code": record.trial_code,
                "target_id": record.target_id,
                "commitment": record.commitment,
                "submitted": player in store.list_submissions(root, day),
                "sends": len(store.list_submissions(root, day)),
            })
        return JSONResponse({"days": rows})

    def _picked_player(name: str | None) -> str | Response:
        """The named player, or the configured one - the spec A1
        growth on the dev read surfaces. The check keeps the query
        string out of the path arithmetic."""
        if name is None:
            return player
        try:
            store.check_player_name(name, "player")
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-player",
                                 "detail": str(error)}, status_code=400)
        return name

    @app.get("/api/dev/submission")
    def dev_submission(request: Request, day: str | None = None,
                       player: str | None = None) -> Response:
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        picked = _picked_day(day)
        if isinstance(picked, Response):
            return picked
        picked_player = _picked_player(player)
        if isinstance(picked_player, Response):
            return picked_player
        stored = store.read_json_or_none(
            store.submission_path(root, picked, picked_player))
        if stored is None:
            return JSONResponse({"cause": "no-submission",
                                 "detail": "no stored submission this "
                                           "day"}, status_code=404)
        return JSONResponse(stored)

    @app.get("/api/dev/players")
    def dev_players(request: Request) -> Response:
        """The roster (spec A1 section 5, grown by spec BR1 section 7).

        With no record stored the roster holds one row for the
        configured player - the world of ruling 7, where that name
        is the identity and nothing holds credentials.
        """
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        # Spec BR1 section 7.4 adds the live devices, the last sign-in,
        # the device codes that wait, and the send count.
        return JSONResponse({"players": console.roster_rows(
            root, player, utc_now())})

    @app.get("/api/dev/history")
    def dev_history(request: Request,
                    player: str | None = None) -> Response:
        """One player's full history (spec A1 section 5).

        Each stored day, newest first, with the sent flag and the
        stored trial row. The dev plane reads open days too - that
        is what the plane is for, and the production answer stays
        the constant 404.
        """
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        picked_player = _picked_player(player)
        if isinstance(picked_player, Response):
            return picked_player
        rows = []
        for day in reversed(store.list_days(root)):
            record = store.read_day_record(root, day)
            stored = store.read_json_or_none(
                store.trial_row_path(root, day, picked_player))
            trial = None if stored is None else {
                "p": stored["p"], "target_rank": stored["target_rank"],
                "decoy_count": stored["decoy_count"],
                "beaten": stored["beaten"], "tied": stored["tied"]}
            rows.append({
                "day": record.day,
                "status": record.status,
                "trial_code": record.trial_code,
                "target_id": record.target_id,
                "submitted": picked_player in store.list_submissions(
                    root, day),
                "trial": trial,
            })
        return JSONResponse({"player": picked_player, "days": rows})

    @app.get("/api/dev")
    def dev_view(request: Request) -> Response:
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        day = store.latest_day(root)
        if day is None:
            # The dev page needs its open control in this status.
            return JSONResponse({"day": None, "status": "none"})
        record = store.read_day_record(root, day)
        return JSONResponse({
            "day": record.day,
            "status": record.status,
            "trial_code": record.trial_code,
            "target_id": record.target_id,
        })

    @app.get("/api/dev/rankings")
    def dev_stored_rankings(request: Request, day: str | None = None,
                            player: str | None = None) -> Response:
        if not (dev_mode and _operator_ok(request)):
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        picked = _picked_day(day)
        if isinstance(picked, Response):
            return picked
        picked_player = _picked_player(player)
        if isinstance(picked_player, Response):
            return picked_player
        record = store.read_day_record(root, picked)
        stored = store.read_json_or_none(
            store.submission_path(root, picked, picked_player))
        if stored is None:
            return JSONResponse({"cause": "no-submission",
                                 "detail": "no stored submission this "
                                           "day"}, status_code=404)
        from service.scoring import dev_rankings

        try:
            # An earlier day scores with the resident context - a
            # drifted config gives the browser numbers different
            # from the stored trial row, and the stored row stays
            # the record.
            value = dev_rankings(stored["record"], record.target_id,
                                 _resident())
        except Exception as error:
            return JSONResponse({"cause": "dev-score-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse(value)

    # ── the console's growth (spec BR1 section 7) ──────────────────
    #
    # Each path below answers the constant 404 without --dev or with
    # a bearer that does not agree, as the dev reads above do, and the
    # edge refuses the /api/dev prefix.

    def _dev_refused(request: Request) -> Response | None:
        if dev_mode and _operator_ok(request):
            return None
        return Response(content=_DEV_OFF, status_code=404,
                        media_type="application/json")

    async def _json_object_body(request: Request) -> dict | Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"cause": "bad-shape",
                                 "detail": "the body is not JSON"},
                                status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"cause": "bad-shape",
                                 "detail": "the body must be an object"},
                                status_code=400)
        return body

    def _stored_player(name: str) -> store.PlayerRecord | Response:
        """The record a path names, or the refusal that says why."""
        try:
            store.check_player_name(name, "player")
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-player",
                                 "detail": str(error)}, status_code=400)
        record = store.read_player_or_none(root, name)
        if record is None:
            return JSONResponse({"cause": "no-such-player",
                                 "detail": f"no stored player {name!r}"},
                                status_code=404)
        return record

    @app.get("/api/dev/day")
    def dev_day(request: Request, day: str | None = None) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        picked = _picked_day(day)
        if isinstance(picked, Response):
            return picked
        return JSONResponse(console.day_detail(
            root, picked, closes_at_utc=service_config.closes_at_utc,
            credits=image_credits))

    def _schedule_value() -> dict:
        return console.schedule_view(
            root, closes_at_utc=service_config.closes_at_utc,
            instant=utc_now(),
            lock_held=rollover.lock_is_held(store.rollover_lock_path(root)))

    @app.get("/api/dev/schedule")
    def dev_schedule(request: Request) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return JSONResponse(_schedule_value())

    @app.post("/api/dev/rollover/pause")
    async def dev_rollover_pause(request: Request) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        body = await _json_object_body(request)
        if isinstance(body, Response):
            return body
        paused = body.get("paused")
        if not isinstance(paused, bool):
            return JSONResponse({"cause": "bad-shape",
                                 "detail": "paused: expected true or false"},
                                status_code=400)
        try:
            store.write_rollover_control(root, store.RolloverControl(
                paused=paused, changed_at=utc_now().isoformat(),
                note=body.get("note", "")))
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-note", "detail": str(error)},
                                status_code=400)
        return JSONResponse(_schedule_value())

    def _local_post(path: str, _timeout: float) -> rollover.Answer:
        """The rollover's poster in this process: the step is the last
        part of the day path, and _day_move makes the move."""
        status, body = _day_move(path.rsplit("/", 1)[-1])
        return rollover.Answer(status=status, body=body)

    @app.post("/api/dev/rollover/run")
    def dev_rollover_run(request: Request) -> Response:
        """Do the steps due at this instant, as the timer does (spec
        BR1 section 7.2).

        No retries: the operator reads a failure immediately. The
        pause does not apply - the operator starts this by hand.
        """
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        closes_at_utc = service_config.closes_at_utc
        if closes_at_utc is None:
            return JSONResponse(
                {"cause": "no-schedule",
                 "detail": "automatic days are off: closes_at_utc is not "
                           "in the server config"}, status_code=409)
        handle = rollover.hold_lock(store.rollover_lock_path(root))
        if handle is None:
            return JSONResponse({"cause": "locked",
                                 "detail": "a rollover holds the lock"},
                                status_code=409)
        try:
            run = rollover.run_and_record(
                root=root, closes_at_utc=closes_at_utc, post=_local_post,
                now=lambda: utc_now(), source="console", retries=0,
                backoff_seconds=0.0, sleep=lambda _seconds: None)
        finally:
            os.close(handle)
        return JSONResponse({"run": console.run_value(run),
                             "schedule": _schedule_value()})

    async def _named_day_move(request: Request, step: str) -> Response:
        """Close or reveal the day the body names (spec BR1 section 7.6).

        For a day behind the latest one, for example a closed day that no
        reveal reached. The status rules of close_day and reveal_day
        apply.
        """
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        body = await _json_object_body(request)
        if isinstance(body, Response):
            return body
        named = body.get("day")
        if not isinstance(named, str):
            return JSONResponse({"cause": "bad-shape",
                                 "detail": "day: expected a stored day"},
                                status_code=400)
        picked = _picked_day(named)
        if isinstance(picked, Response):
            return picked
        status, answer = await asyncio.to_thread(_day_move, step, picked)
        return JSONResponse(answer, status_code=status)

    @app.post("/api/dev/day/close")
    async def dev_day_close(request: Request) -> Response:
        return await _named_day_move(request, "close")

    @app.post("/api/dev/day/reveal")
    async def dev_day_reveal(request: Request) -> Response:
        return await _named_day_move(request, "reveal")

    @app.get("/api/dev/players/{name}")
    def dev_player(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        record = _stored_player(name)
        if isinstance(record, Response):
            return record
        return JSONResponse(console.player_detail(root, name, utc_now()))

    @app.get("/api/dev/players/{name}/avatar")
    def dev_player_avatar(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        record = _stored_player(name)
        if isinstance(record, Response):
            return record
        data = store.read_avatar_or_none(root, name)
        media_type = None if data is None else store.avatar_media_type(data)
        if data is None or media_type is None:
            return Response(content=_NO_AVATAR, status_code=404,
                            media_type="application/json")
        return Response(content=data, media_type=media_type)

    def _player_command(name: str, command: str) -> Response:
        """The commands of the players module (spec A2 section 10.1)."""
        from service import players

        record = _stored_player(name)
        if isinstance(record, Response):
            return record
        try:
            match command:
                case "restore":
                    restored, code, usable_at = players.restore_player(
                        service_config, player=name, instant=utc_now())
                    return JSONResponse(
                        {"player": restored.player,
                         "status": restored.status,
                         "recovery_code": auth.display_recovery_code(code),
                         "usable_at": usable_at},
                        headers={"cache-control": "no-store"})
                case "recovery-code":
                    code, usable_at = players.operator_code(
                        service_config, player=name, instant=utc_now())
                    return JSONResponse(
                        {"player": name,
                         "recovery_code": auth.display_recovery_code(code),
                         "usable_at": usable_at},
                        headers={"cache-control": "no-store"})
                case "revoke":
                    revoked = players.revoke_player(service_config,
                                                    player=name)
                    return JSONResponse({"player": revoked.player,
                                         "status": revoked.status})
                case "signout":
                    ended = players.signout_player(service_config,
                                                   player=name)
                    return JSONResponse({"player": name, "ended": ended})
                case _:
                    raise ValueError(f"unknown command {command!r}")
        except store.StoreError as error:
            return JSONResponse({"cause": "refused", "detail": str(error)},
                                status_code=409)

    @app.post("/api/dev/players/{name}/recovery-code")
    def dev_player_recovery_code(request: Request, name: str) -> Response:
        """The operator's recovery code (spec A2 section 6.1): its own
        slot, a hold of 24 hours, and a notice on the player's
        devices."""
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "recovery-code")

    @app.post("/api/dev/players/{name}/revoke")
    def dev_player_revoke(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "revoke")

    @app.post("/api/dev/players/{name}/restore")
    def dev_player_restore(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "restore")

    @app.post("/api/dev/players/{name}/signout")
    def dev_player_signout(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "signout")

    @app.post("/api/dev/players/{name}/device-code")
    def dev_player_device_code(name: str) -> Response:
        """The console device code is gone (spec A2 decision D13): it
        was a procedure into an account with no hold. The path answers
        the constant 404 in each world."""
        return Response(content=_DEV_OFF, status_code=404,
                        media_type="application/json")

    @app.delete("/api/dev/players/{name}/sessions/{session_id}")
    def dev_player_session_end(request: Request, name: str,
                               session_id: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        record = _stored_player(name)
        if isinstance(record, Response):
            return record
        try:
            ended = store.delete_session(root, name, session_id)
        except store.StoreError:
            # An id that is not a digest names no session.
            ended = False
        if not ended:
            return JSONResponse({"cause": "no-session",
                                 "detail": "no live session by that id"},
                                status_code=404)
        return JSONResponse({"player": name, "ended": 1})

    @app.post("/api/dev/prune")
    def dev_prune(request: Request) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return JSONResponse(access.prune(root, utc_now()))

    @app.get("/api/dev/index")
    def dev_index(request: Request) -> Response:
        from service import index

        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return JSONResponse(index.describe(root, index.index_path(data_root)))

    @app.post("/api/dev/index/build")
    def dev_index_build(request: Request) -> Response:
        from service import index

        refused = _dev_refused(request)
        if refused is not None:
            return refused
        target = index.index_path(data_root)
        try:
            index.build(root, target)
        except (index.ResultsIndexError, store.StoreError,
                sqlite3.Error) as error:
            return JSONResponse({"cause": "index-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse(index.describe(root, target))

    @app.post("/api/dev/index/verify")
    def dev_index_verify(request: Request) -> Response:
        from service import index

        refused = _dev_refused(request)
        if refused is not None:
            return refused
        try:
            problems = index.verify(root, index.index_path(data_root))
        except (index.ResultsIndexError, store.StoreError,
                sqlite3.Error) as error:
            return JSONResponse({"cause": "index-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"agrees": not problems, "problems": problems})

    @app.post("/api/dev/index/query")
    async def dev_index_query(request: Request) -> Response:
        from service import index

        refused = _dev_refused(request)
        if refused is not None:
            return refused
        body = await _json_object_body(request)
        if isinstance(body, Response):
            return body
        try:
            # The query reads a current index: a store write since the
            # last build builds it again. That writes the cache file,
            # not the store.
            target = index.ensure_current(root, index.index_path(data_root))
            answer = index.read_only_query(target, body.get("sql"))
        except (index.ResultsIndexError, store.StoreError,
                sqlite3.Error) as error:
            return JSONResponse({"cause": "bad-query", "detail": str(error)},
                                status_code=400)
        return JSONResponse(answer)

    @app.get("/api/practice")
    def practice_days(request: Request) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # A function of revealed days alone (P5 R4): while a day is
        # open, this body cannot change with its target.
        rows = []
        for day in reversed(store.list_days(root)):
            record = store.read_day_record(root, day)
            if record.status == "revealed":
                rows.append({"day": record.day,
                             "target_id": record.target_id,
                             "trial_code": record.trial_code})
        if not rows:
            return Response(content=_NO_PRACTICE, status_code=404,
                            media_type="application/json")
        return JSONResponse({"days": rows,
                             "min_strokes": gates.min_strokes_whole_drawing})

    async def _parsed_body(request: Request) -> object:
        """The JSON body, parsed off the loop thread: at the body cap
        the parse takes some milliseconds."""
        return await asyncio.to_thread(json.loads, await request.body())

    def _checked_or_refusal(wire_record: object) -> Submission | Response:
        """The caps, Layer 0, and the channel pre-check, in sequence."""
        too_large = limits.record_caps_refusal(wire_record)
        if too_large is not None:
            return JSONResponse({"cause": "too-much-drawing",
                                 "detail": too_large}, status_code=400)
        try:
            submission = validate_submission(wire_record, gates, canvas_px)
        except IntakeError as error:
            return JSONResponse({"cause": error.cause,
                                 "detail": str(error)}, status_code=400)
        if not _activates_weighted_channel(submission, weights):
            return JSONResponse(
                {"cause": "no-scoreable-atom",
                 "detail": "no atom reads into a weighted channel - add "
                           "an impression, a labeled group, or strokes"},
                status_code=400)
        return submission

    async def _checked_submission(
            wire_record: object) -> Submission | Response:
        """Layer 0 off the loop thread: a record at its caps holds a
        thread for more than a second, and no other caller waits on
        that (spec PL1 section 1)."""
        return await asyncio.to_thread(_checked_or_refusal, wire_record)

    @app.post("/api/practice/score")
    async def practice_score_endpoint(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        from service.scoring import day_precompute, practice_score

        # The gate stands before the work: this is the one player
        # path that scores, thus a caller with no session does none
        # of it.
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        if not practice_counts.allowed(caller):
            return Response(content=_PRACTICE_LIMIT, status_code=429,
                            media_type="application/json")
        try:
            body = await _parsed_body(request)
        except Exception:
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body is not JSON"},
                status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body must be an object"},
                status_code=400)
        day = body.get("day")
        wire_record = body.get("record")
        # One constant refusal for a missing, unknown, open, or
        # unrevealed day - the distinctions tell nothing, and one
        # body is the cheapest R4 argument.
        try:
            if not isinstance(day, str) \
                    or day not in store.list_days(root):
                raise store.StoreError("not a practice day")
            record = store.read_day_record(root, day)
            if record.status != "revealed":
                raise store.StoreError("not a practice day")
        except store.StoreError:
            return Response(content=_NOT_PRACTICE, status_code=404,
                            media_type="application/json")
        checked = await _checked_submission(wire_record)
        if isinstance(checked, Response):
            return checked
        practice_counts.record(caller)

        def compute():
            wired = _resident()
            with precompute_lock:
                pre = practice_precompute.get(record.target_id)
                if pre is None:
                    pre = day_precompute(wired.context, record.target_id)
                    practice_precompute[record.target_id] = pre
            return practice_score(wire_record, record.target_id, wired,
                                  pre)

        try:
            value = await run_in_threadpool(compute)
        except Exception as error:
            return JSONResponse({"cause": "practice-score-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"day": day, **value,
                             "credit": image_credits.get(record.target_id)})

    @app.get("/api/day")
    def day_view(request: Request) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        day = store.latest_day(root)
        if day is None:
            return Response(content=_NO_DAY, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        # closes_at is a pure function of the day label and the
        # config, with no target dependence, thus R3 holds by
        # construction. The calendar rule of spec BR1 section 3
        # names the instant. The close itself stays the operator's
        # or the rollover command's move.
        closes_at = None
        if (record.status == "open"
                and service_config.closes_at_utc is not None):
            closes_at = schedule.closes_at_text(
                record.day, service_config.closes_at_utc)
        value = {
            "day": record.day,
            "trial_code": record.trial_code,
            "status": record.status,
            "commitment": record.commitment,
            "player": caller,
            # One stat and not a walk of the day's sends: an open tab
            # polls this path (spec PL1 section 4).
            "submitted": store.submission_path(root, day, caller).is_file(),
            "relation_vocabulary": relation_vocabulary,
            "canvas_px": canvas_px,
            "min_strokes": gates.min_strokes_whole_drawing,
            "closes_at": closes_at,
        }
        if record.status == "revealed":
            value["target_id"] = record.target_id
            value["secret"] = record.secret
        return JSONResponse(value)

    def _store_submission(day: str, caller: str, trial_id: str,
                          wire_record: object) -> Response | None:
        """Write one send with the day's write lock held, or refuse.

        The status check again, with the lock held: a close can move
        the day after the first check, and a close holds the same lock
        for its move, thus this write lands before the close reads the
        submissions, or it refuses (spec BR1 section 3). A worker thread
        calls this: the lock can wait on a close, and the write syncs
        to the disk.
        """
        with store.day_write_lock(root, day):
            if store.read_day_record(root, day).status != "open":
                return JSONResponse({"cause": "day-closed"}, status_code=409)
            try:
                store.write_once_json(
                    store.submission_path(root, day, caller),
                    {"day": day, "player": caller, "trial_id": trial_id,
                     "received_at": store_received_at(),
                     "record": wire_record})
            except store.StoreError:
                return JSONResponse({"cause": "already-submitted"},
                                    status_code=409)
        return None

    @app.post("/api/submission")
    async def submit(request: Request,
                     day: str | None = None) -> Response:
        """Store one send for the day the query names (spec PL1 section 2).

        The name is not in the stored record, thus stored bytes do
        not move. It answers the stale tab: a send composed for a day
        that is not the latest one refuses, and it does not land on
        the target of the latest day. The refusal names a label that
        GET /api/day gives each player, thus it says nothing of a target.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        latest = store.latest_day(root)
        if latest is None:
            return Response(content=_NO_DAY, status_code=404,
                            media_type="application/json")
        if day is None:
            return JSONResponse({"cause": "day-required",
                                 "detail": "day: the query must name the "
                                           "day of this send"},
                                status_code=400)
        if day != latest:
            return JSONResponse({"cause": "day-moved", "day": latest},
                                status_code=409)
        record = store.read_day_record(root, day)
        if record.status != "open":
            return JSONResponse({"cause": "day-closed"}, status_code=409)
        if store.submission_path(root, day, caller).is_file():
            return JSONResponse({"cause": "already-submitted"},
                                status_code=409)
        try:
            wire_record = await _parsed_body(request)
        except Exception:
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body is not JSON"},
                status_code=400)
        checked = await _checked_submission(wire_record)
        if isinstance(checked, Response):
            return checked
        trial_id = secrets.token_hex(16)
        refused = await asyncio.to_thread(_store_submission, day, caller,
                                          trial_id, wire_record)
        if refused is not None:
            return refused
        return JSONResponse({"trial_id": trial_id, "day": day,
                             "atom_count": len(checked.atoms)})

    # One lifecycle move at a time in this process: the three day
    # endpoints run in the thread pool, and two of them on one day
    # can race the guarded moves. A second process meets the store's
    # guards and the rollover command's lock.
    lifecycle_lock = threading.Lock()

    def _day_move(step: str, day: str | None = None) -> tuple[int, dict]:
        """One lifecycle move as (HTTP status, body).

        The three day endpoints answer it, and so do the console's
        rollover (spec BR1 section 7.2) and its moves of a named day
        (section 7.6), thus each path refuses alike. With no day, a
        close or a reveal moves the latest stored day. A StoreError is
        the store refusing the move (409), and each other error is the
        move not completing (400).
        """
        from service.day import close_day, open_day, reveal_day

        try:
            with lifecycle_lock:
                match step:
                    case "open":
                        # The label comes from the UTC calendar (spec
                        # BR1 section 3): the current day, or the day
                        # after the latest stored day. open_day refuses
                        # unless the latest day is revealed - one
                        # active day at a time, and no closed day left
                        # behind.
                        # The resident context serves the open when
                        # one is there, thus the process holds one copy
                        # of the pool. With none, the open wires warm
                        # and frees that copy (spec PL1 section 5).
                        with resident_lock:
                            resident = resident_state.get("wired")
                        record = open_day(service_config, wired=resident)
                        return 200, {"day": record.day,
                                     "trial_code": record.trial_code,
                                     "commitment": record.commitment}
                    case "close":
                        # The one live step (R5): the server process
                        # needs the provider key in its environment for
                        # a live config. The answer names the row count
                        # and no score (R3). The resident context serves
                        # the close when the day's pinned config path is
                        # the server's own - a day opened with a
                        # different config wires anew from its pinned
                        # path (P5 R1).
                        wired = None
                        target = day or store.latest_day(root)
                        if target is not None:
                            record = store.read_day_record(root, target)
                            if record.status in ("open", "closing") \
                                    and record.scoring_config_path \
                                    == service_config.scoring_config:
                                wired = _resident()
                        return 200, {"trial_rows": close_day(
                            service_config, date=day, wired=wired)}
                    case "reveal":
                        record = reveal_day(service_config, date=day)
                        return 200, {"day": record.day}
                    case _:
                        raise ValueError(f"unknown day step {step!r}")
        except store.StoreError as error:
            return 409, {"cause": "refused", "detail": str(error)}
        except Exception as error:
            return 400, {"cause": f"{step}-failed", "detail": str(error)}

    @app.post("/api/day/open")
    def day_open(request: Request) -> Response:
        if not _operator_ok(request):
            return _unauthorized()
        status, body = _day_move("open")
        return JSONResponse(body, status_code=status)

    @app.post("/api/day/close")
    def day_close(request: Request) -> Response:
        if not _operator_ok(request):
            return _unauthorized()
        status, body = _day_move("close")
        return JSONResponse(body, status_code=status)

    @app.post("/api/day/reveal")
    def day_reveal(request: Request) -> Response:
        if not _operator_ok(request):
            return _unauthorized()
        status, body = _day_move("reveal")
        return JSONResponse(body, status_code=status)

    @app.get("/api/about")
    def about_view() -> Response:
        """The season facts the home screen and the landing page show.

        No session: the facts name the pool and the calendar, not a
        player, and a signed-out visitor reads them on the landing
        page. Constant for each start of the server (R3).
        """
        return JSONResponse(about_value)

    def _reveal_value(record: store.DayRecord, row: dict | None) -> dict:
        """The reveal document for one revealed day (spec S2 B2).

        credit names the source of the target image (spec BR1
        section 6), or null when the server holds no manifest.
        """
        return {
            "day": record.day,
            "credit": image_credits.get(record.target_id),
            "target_id": record.target_id,
            "secret": record.secret,
            "commitment": record.commitment,
            "check": "printf '%s:%s' TARGET SECRET | sha256sum",
            "trial": None if row is None else {
                "p": row["p"], "decoy_count": row["decoy_count"],
                "beaten": row["beaten"], "tied": row["tied"],
                "target_rank": row["target_rank"]},
            "report": [] if row is None else row["report"],
        }

    @app.get("/api/reveal")
    def reveal_view(request: Request, day: str | None = None) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # No argument names the latest day. A named day serves only
        # when that day is revealed - one constant refusal for the
        # unknown, open, and closed-unrevealed conditions (R3).
        if day is None:
            day = store.latest_day(root)
        if day is None or day not in store.list_days(root):
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        if record.status != "revealed":
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        row = store.read_json_or_none(
            store.trial_row_path(root, day, caller))
        return JSONResponse(_reveal_value(record, row))

    @app.get("/api/history")
    def history_view(request: Request) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # Revealed days that hold the player's trial row, newest
        # first (spec S2 B3). Read-only against the store.
        days = []
        ps: list[float] = []
        for day in reversed(store.list_days(root)):
            record = store.read_day_record(root, day)
            if record.status != "revealed":
                continue
            row = store.read_json_or_none(
                store.trial_row_path(root, day, caller))
            if row is None:
                continue
            ps.append(float(row["p"]))
            days.append({
                "day": day,
                "trial_code": record.trial_code,
                "p": row["p"],
                "target_rank": row["target_rank"],
                "decoy_count": row["decoy_count"],
            })
        return JSONResponse({"days": days, "skill": _skill_value(ps)})

    @app.get("/api/submission")
    def submission_view(request: Request,
                        day: str | None = None) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # The player's own stored record - an echo of their input
        # with no target information and no score. The caller of
        # ruling 7 names the record. The day membership check keeps
        # the query string out of the path arithmetic.
        if day is None:
            day = store.latest_day(root)
        if day is None or day not in store.list_days(root):
            return Response(content=_NO_SUBMISSION, status_code=404,
                            media_type="application/json")
        stored = store.read_json_or_none(
            store.submission_path(root, day, caller))
        if stored is None:
            return Response(content=_NO_SUBMISSION, status_code=404,
                            media_type="application/json")
        return JSONResponse({"trial_id": stored["trial_id"],
                             "record": stored["record"]})

    def _label_of(name: str) -> str:
        """The board label for one store key: the key itself.

        Ruling 3 of spec A2: the username is the one name of a
        player, and it shows on each board. The display name of a
        record from before that spec stays in its record and shows on
        no board. The wire keeps its display_name field, with the
        username in it, thus each screen reads one name.
        """
        return name

    def _avatar_of(name: str) -> str | None:
        """The avatar digest for one store key, or None.

        Joined at read time in the manner of _label_of (D5 as
        ruled 2026-08-21: the boards hold avatars): one file
        read, and a new picture wants no new board assembly.
        """
        found = store.read_account_or_none(root, name)
        return None if found is None else found.avatar_hash

    # The played days before each board day, for the floor of the
    # daily board. A day that has a revealed board is after each
    # earlier day's close, thus the counts of its earlier days do not
    # change and one walk for each day is sufficient.
    earlier_played_cache: dict[str, dict[str, int]] = {}
    earlier_played_lock = threading.Lock()

    def _earlier_played(day: str) -> dict[str, int]:
        with earlier_played_lock:
            found = earlier_played_cache.get(day)
            if found is None:
                found = {}
                for earlier in store.list_days(root):
                    if earlier >= day:
                        continue
                    for name in store.list_submissions(root, earlier):
                        found[name] = found.get(name, 0) + 1
                earlier_played_cache[day] = found
            return found

    @app.get("/api/leaderboard")
    def leaderboard_view(request: Request,
                         day: str | None = None) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # Revealed days alone (spec S2 B3), each player with a row.
        # The prepared board serves it. With no board the reader
        # falls back to the stored rows, thus a day revealed before
        # the rollup was written continues to answer.
        #
        # No day names the newest revealed one. The leaderboard
        # screen wants that day and nothing else answers it: the
        # reveal reads the latest day, which is the open one for
        # most of each day, and the history reads the days that one
        # caller played. This says nothing new, because a caller
        # who names that day reads the same board today.
        if day is None:
            day = _newest_revealed(root)
        if day is None or day not in store.list_days(root):
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        if record.status != "revealed":
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        prepared = store.read_json_or_none(rollup.leaderboard_path(
            data_root, day, record.scoring_config_hash))
        if prepared is not None and not rollup.board_is_current(prepared):
            # A board from before the target rank travelled. The
            # trial rows hold it and they are permanent.
            prepared = None
        if prepared is None:
            board = []
            for name in store.list_submissions(root, day):
                stored = store.read_json_or_none(
                    store.trial_row_path(root, day, name))
                if stored is not None:
                    board.append((name, stored))
            prepared = rollup.daily_board_value(record, board)
        newest = _newest_revealed(root)
        # The floor of spec A2 section 9.5: a player shows after 3
        # played days, and the caller gets the caller's own row too.
        earlier = _earlier_played(day)
        shown = rollup.public_board_rows(
            prepared["rows"], earlier, caller,
            floor=rollup.DAILY_BOARD_FLOOR_DAYS)
        rows = [{
            "player": entry["player"],
            "display_name": _label_of(entry["player"]),
            "avatar_hash": _avatar_of(entry["player"]),
            "p": entry["p"],
            "target_rank": entry["target_rank"],
            "decoy_count": entry["decoy_count"],
            "streak": _streak(root, entry["player"], newest),
            "public": entry["public"],
        } for entry in shown]
        return JSONResponse({
            "day": day, "rows": rows,
            "floor": {"played_days": rollup.DAILY_BOARD_FLOOR_DAYS,
                      "caller_played_days": earlier.get(caller, 0)}})

    @app.get("/api/leaderboard/skill")
    def skill_board_view(request: Request) -> Response:
        """The skill board (spec M1 section 8).

        The prepared artifact when the rollup wrote one, and the
        gated body when it did not. The gated body carries the two
        floors, thus the screen holds no number the wire does not
        give it.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        newest = _newest_revealed(root)
        prepared = None
        if newest is not None:
            record = store.read_day_record(root, newest)
            prepared = store.read_json_or_none(rollup.skill_board_path(
                data_root, record.scoring_config_hash))
        if prepared is None:
            return Response(content=_SKILL_INACTIVE, status_code=200,
                            media_type="application/json")
        rows = [{**row, "display_name": _label_of(row["player"]),
                 "avatar_hash": _avatar_of(row["player"])}
                for row in prepared["rows"]]
        served = {name: value for name, value in prepared.items()
                  if name not in _OPERATOR_ONLY}
        return JSONResponse({**served, "rows": rows})

    @app.get("/api/me")
    def me_view(request: Request) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        # The reminder flag has no storage at this time (spec S2
        # section 3). The public flag left with ruling 3 of spec
        # M1: ruling 4 removed the opt-out, thus the field was
        # correct for each player forever, and a value that cannot
        # change is a claim that waits for a reader to trust it.
        account = store.read_account_or_none(root, caller)
        return JSONResponse({
            "player": caller,
            "display_name": _label_of(caller),
            "streak": _streak(root, caller, _newest_revealed(root)),
            "reminder": False,
            "description": "" if account is None else account.description,
            "avatar_hash": None if account is None
            else account.avatar_hash,
            # The account screen picks its password control from the
            # first, and the notice of spec A2 section 6.1 reads the
            # second. No code and no digest is here.
            "has_password": _access_on()
            and signin.has_password(root, caller),
            "operator_code": signin.operator_code_view(root, caller)
            if _access_on() else None,
        })

    @app.put("/api/account")
    async def account_update(request: Request) -> Response:
        """Store the caller's description (spec A1 section 3).

        The description check guards the boundary. The writer
        writes for the resolved caller alone - no player parameter
        on the player plane.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body is not JSON"},
                status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body must be an object"},
                status_code=400)
        try:
            record = store.set_account_description(
                root, caller, body.get("description"),
                timestamp=store_received_at())
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-description",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"description": record.description})

    # The three account writers below are async on purpose, also
    # the one with no body to read: each store mutation then runs
    # on uvicorn's one loop thread with no await in it, thus two
    # requests cannot interleave a read-modify-write and no lock
    # is wanted. The server is one process (spec S2 ruling 1).
    _AVATAR_CAP_REFUSAL = {
        "cause": "bad-avatar",
        "detail": f"avatar: expected at most {store.AVATAR_BYTE_CAP} "
                  "bytes"}

    @app.put("/api/account/avatar")
    async def avatar_update(request: Request) -> Response:
        """Store the caller's avatar (spec A1 section 3).

        The body is the raw image bytes. The cap guards the read
        itself: a declared length above it refuses before a byte
        arrives, and the stream stops at the first byte above it -
        the server holds at most the cap plus one chunk in
        memory. The store writer then checks the cap and the
        magic bytes again, in that sequence, before a write.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > store.AVATAR_BYTE_CAP:
            return JSONResponse(_AVATAR_CAP_REFUSAL, status_code=400)
        received = 0
        chunks = []
        async for chunk in request.stream():
            received += len(chunk)
            if received > store.AVATAR_BYTE_CAP:
                return JSONResponse(_AVATAR_CAP_REFUSAL, status_code=400)
            chunks.append(chunk)
        try:
            record = store.set_account_avatar(
                root, caller, b"".join(chunks),
                timestamp=store_received_at())
        except store.StoreError as error:
            return JSONResponse({"cause": "bad-avatar",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"avatar_hash": record.avatar_hash})

    @app.delete("/api/account/avatar")
    async def avatar_remove(request: Request) -> Response:
        """Remove the caller's avatar. Legal with no picture too."""
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        record = store.clear_account_avatar(
            root, caller, timestamp=store_received_at())
        return JSONResponse({"avatar_hash": record.avatar_hash})

    @app.get("/api/me/export")
    def me_export(request: Request) -> Response:
        """The caller's own data, as one JSON file (spec BR1 section 5).

        Read from the store and not from the index: the player's copy
        is the source itself. Each day the caller sent on, with the
        raw submission, and for a revealed day the trial row and the
        target. No other player's fact enters it, and a day that is
        not revealed holds no score (I7).
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        days = []
        for day in store.list_days(root):
            stored = store.read_json_or_none(
                store.submission_path(root, day, caller))
            if stored is None:
                continue
            record = store.read_day_record(root, day)
            revealed = record.status == "revealed"
            row = store.read_json_or_none(
                store.trial_row_path(root, day, caller)) if revealed else None
            days.append({
                "day": day,
                "trial_code": record.trial_code,
                "status": record.status,
                "submission": {"trial_id": stored["trial_id"],
                               "received_at": stored["received_at"],
                               "record": stored["record"]},
                "target_id": record.target_id if revealed else None,
                "result": None if row is None else {
                    "p": row["p"], "target_rank": row["target_rank"],
                    "decoy_count": row["decoy_count"],
                    "beaten": row["beaten"], "tied": row["tied"],
                    "report": row["report"]},
            })
        account = store.read_account_or_none(root, caller)
        exported_at = utc_now()
        body = {
            "player": caller,
            "display_name": _label_of(caller),
            "description": "" if account is None else account.description,
            "exported_at": exported_at.isoformat(),
            "days": days,
        }
        name = f"starvector-{caller}-{exported_at.date().isoformat()}.json"
        return JSONResponse(body, headers={
            "content-disposition": f'attachment; filename="{name}"'})

    @app.get("/api/ops/trials")
    def ops_trials(request: Request,
                   day_from: str | None = Query(None, alias="from"),
                   day_to: str | None = Query(None, alias="to"),
                   player_name: str | None = Query(None, alias="player"),
                   ) -> Response:
        """Revealed trial rows for the operator's programs (BR1 section 5).

        The operator gate stands in front, and the edge blocks the
        path. The index answers, made current first: a store write
        since the last build builds it again. The query names days
        with from and to, and a player with player.
        """
        from service import index

        if not _operator_ok(request):
            return _unauthorized()
        for value in (day_from, day_to):
            if value is not None:
                try:
                    schedule.parse_label(value)
                except schedule.ScheduleError as error:
                    return JSONResponse({"cause": "bad-day",
                                         "detail": str(error)},
                                        status_code=400)
        if player_name is not None:
            try:
                store.check_player_name(player_name, "player")
            except store.StoreError as error:
                return JSONResponse({"cause": "bad-player",
                                     "detail": str(error)}, status_code=400)
        target = index.ensure_current(root, index.index_path(data_root))
        rows, truncated = index.revealed_trial_rows(
            target, from_day=day_from, to_day=day_to, player=player_name)
        # A caller that gets truncated continues with from set to the
        # last day it read (spec PL1 section 7).
        return JSONResponse({"rows": rows, "count": len(rows),
                             "truncated": truncated,
                             "row_cap": index.TRIAL_ROW_CAP})

    @app.get("/api/avatar/{player_name}")
    def avatar_view(request: Request, player_name: str) -> Response:
        """One player's avatar bytes, for each signed-in caller.

        Display names face each player on the boards today, and
        the avatar is the same class of fact. One constant 404
        covers a player with no picture and a name with no record.
        The pool path /image/{image_id} keeps its reveal gate -
        this path serves no pool image.
        """
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        data = store.read_avatar_or_none(root, player_name)
        media_type = None if data is None else store.avatar_media_type(data)
        if data is None or media_type is None:
            return Response(content=_NO_AVATAR, status_code=404,
                            media_type="application/json")
        return Response(content=data, media_type=media_type)

    @app.get("/image/{image_id}")
    def image(request: Request, image_id: str) -> Response:
        if not (dev_mode and _operator_ok(request)):
            targets = _revealed_targets(root)
            if image_id not in targets:
                return Response(content=_NOT_REVEALED, status_code=404,
                                media_type="application/json")
        try:
            image_bytes = load_image_bytes(data_root, image_id)
        except Exception:
            # Dev mode serves each stored pool image - one with no
            # stored bytes gets the same constant refusal.
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        return Response(content=image_bytes,
                        media_type=_mime_of(image_bytes))

    return app


def store_received_at() -> str:
    """The submission timestamp - one seam for the tests to pin."""
    from validation.harness import default_clock

    return default_clock()


def utc_now() -> datetime.datetime:
    """The instant the sign-in rules read - one seam for the tests."""
    return datetime.datetime.now(datetime.UTC)


def start_refusal(*, dev_mode: bool, cookie_insecure: bool,
                  single_player: bool) -> str | None:
    """The flag combinations the server refuses, or None.

    A cookie with no Secure flag rides plain HTTP, which a public box
    must not give, thus the flag needs the dev surfaces - and the edge
    does not proxy those (spec S2 ruling 4).
    """
    if cookie_insecure and not dev_mode:
        return ("--cookie-insecure needs --dev: a cookie with no Secure "
                "flag is for a test box on plain HTTP")
    if single_player and dev_mode:
        return "--single-player and --dev: pick one"
    return None


def open_world_refusal(*, has_players: bool, dev_mode: bool,
                       single_player: bool,
                       signup_open: bool = False) -> str | None:
    """Refuse a public start with no player records (spec BR1 section 4).

    With no record stored each caller is the configured player (spec
    M1 ruling 7), thus a public box in that condition lets each
    visitor play as the owner. The dev server and an explicit
    --single-player keep that world on purpose. Open sign-up has no
    such world: a caller with no session is signed out (spec A2
    section 10.2).
    """
    if has_players or dev_mode or single_player or signup_open:
        return None
    return ("the store holds no player records, thus each visitor would "
            "play as the configured player - set \"signup\": \"open\" in "
            "the server config, or start with --single-player for a "
            "private box")


def pepper_refusal(*, has_credentials: bool, has_pepper: bool) -> str | None:
    """Refuse a start that cannot check the stored passwords (spec A2
    section 5.2).

    A store with credential records and no pepper signs nobody in, and
    a new pepper makes each stored password dead. The stop is loud.
    """
    if has_credentials and not has_pepper:
        return ("the store holds credential records and the password "
                f"pepper is not set - put {digests.PEPPER_ENVIRONMENT_NAME} "
                "in the deployment environment file")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.server")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--dev", action="store_true",
                        help="the section 14b dev surfaces - target "
                             "readable, draft scoring, all images")
    parser.add_argument("--cookie-insecure", action="store_true",
                        help="drop the cookie's Secure flag, for a test "
                             "box on plain HTTP; needs --dev")
    parser.add_argument("--single-player", action="store_true",
                        help="serve with no player records: each caller "
                             "is the configured player, with no sign-in")
    arguments = parser.parse_args(argv)
    refusal = start_refusal(dev_mode=arguments.dev,
                            cookie_insecure=arguments.cookie_insecure,
                            single_player=arguments.single_player)
    if refusal is not None:
        print(f"refused: {refusal}", file=sys.stderr)
        return 1
    # create_app sits in the try: it refuses to start when the
    # store holds players and no operator token is set, and that
    # refusal must print as one line and not as a traceback.
    try:
        service_config = load_service_config(Path(arguments.service_config))
        store_root = Path(service_config.store_root)
        world_refusal = open_world_refusal(
            has_players=store.any_player(store_root),
            dev_mode=arguments.dev, single_player=arguments.single_player,
            signup_open=service_config.signup == "open")
        if world_refusal is not None:
            raise ServiceConfigError(world_refusal)
        digester = digests.digester_from_pepper(
            os.environ.get(digests.PEPPER_ENVIRONMENT_NAME))
        no_pepper = pepper_refusal(
            has_credentials=store.any_credential(store_root),
            has_pepper=digester is not None)
        if no_pepper is not None:
            raise ServiceConfigError(no_pepper)
        app = create_app(
            service_config, dev_mode=arguments.dev,
            cookie_secure=not arguments.cookie_insecure,
            operator_token=os.environ.get("STARVECTOR_OPERATOR_TOKEN"),
            digester=digester)
    except Exception as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    import uvicorn

    # An invite of before spec A2 was a credential, and earlier lines
    # hold such paths. The filter stays (spec A2 section 10.1).
    logging.getLogger("uvicorn.access").addFilter(limits.RedactInvitePaths())
    uvicorn.run(app, host="127.0.0.1",
                port=arguments.port or service_config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
