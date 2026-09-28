"""The localhost HTTP surface (spec S1 section 9).

FastAPI endpoints in front of the store, with the R3 rules held
structurally: pre-reveal refusals are module constants returned
before target-dependent work, and the acknowledgment is a
validation echo with no score in it.

This process serves the API and no page. The player app and the
operator console are the built web app of spec W1, which the edge
serves from web/dist and which reaches this process at /api,
/image, and the invite path. The hand-written pages that stood in before
that app existed retired on 2026-08-16, thus GET / answers 404
here and the app owns each path a person types.
"""

import argparse
import datetime
import json
import math
import os
import secrets
import sqlite3
import sys
import threading
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
from service import (access, auth, console, credits, limits, rollover,
                     rollup, schedule, store)
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

# The digest the caller path compares against with no record
# stored, thus an unknown name costs the same work as an incorrect
# secret (the architecture's section 22 hygiene rule).
_ABSENT_HASH = "0" * 64


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
               operator_token: str | None = None) -> FastAPI:
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

    Raises ServiceConfigError when the store holds player records
    and no operator token is set. A quiet hole is worse than a loud
    stop (spec M1 section 4).
    """
    if store.any_player(Path(service_config.store_root)) \
            and not operator_token:
        raise ServiceConfigError(
            "the store holds player records and the operator token is "
            "not set - put STARVECTOR_OPERATOR_TOKEN in the deployment "
            "environment file")
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
    code_limiter = limits.FailureLimiter()

    def _unauthorized() -> Response:
        return Response(content=_UNAUTHORIZED, status_code=401,
                        media_type="application/json")

    def _resolve_token(token: object) -> str | Response:
        """The player one invite or cookie names, or the refusal.

        Divides the token at its one separator, reads that single
        player record, and compares the digests in constant time.
        The compare also runs with no record stored, thus an
        unknown name costs the same work as an incorrect secret,
        and the refusal says nothing about who is stored. The lookup
        reads one file and walks nothing, which is what lets the
        shape hold thousands of players (spec M1 section 7).
        """
        parsed = auth.parse_token(token)
        if parsed is None:
            return _unauthorized()
        name, secret = parsed
        record = store.read_player_or_none(root, name)
        stored_hash = _ABSENT_HASH if record is None else record.token_hash
        agreed = auth.secret_matches(secret, stored_hash)
        if record is None or record.status != "active" or not agreed:
            return _unauthorized()
        return name

    def _bearer_ok(request: Request) -> bool:
        """This holds the operator token.

        Not agreed with no configured token, thus the mint refuses
        in each world where nobody set the operator plane up.
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
        edit. The first mint closes this.
        """
        return not store.any_player(root) or _bearer_ok(request)

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
        if not store.any_player(root):
            return player
        resolved = access.resolve_session(
            root, request.cookies.get(auth.SESSION_COOKIE), utc_now())
        return _unauthorized() if resolved is None else resolved

    def _session_cookie(value: str) -> dict[str, str]:
        return {"set-cookie": auth.session_cookie_header(
            value, secure=cookie_secure)}

    @app.get("/join/{token}")
    def join(request: Request, token: str) -> Response:
        """The invite gate (spec M1 section 4, spec BR1 section 4).

        On agreement the answer moves the browser to the app and
        sets a new session cookie - the invite itself does not ride in
        a cookie. A browser that holds a live session of the same
        player keeps it, thus a second visit to the invite adds no
        session. A refusal is one constant body, equal for a token
        that does not parse, an unknown player, an incorrect secret,
        and a revoked record.
        """
        resolved = _resolve_token(token)
        if isinstance(resolved, Response):
            return resolved
        instant = utc_now()
        headers = {"location": "/"}
        current = access.resolve_session(
            root, request.cookies.get(auth.SESSION_COOKIE), instant)
        if current != resolved:
            value = access.open_session(
                root, resolved,
                user_agent=request.headers.get("user-agent"),
                instant=instant)
            headers.update(_session_cookie(value))
        return Response(status_code=302, headers=headers)

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
        if not store.any_player(root):
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
            removed = store.any_player(root) \
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
        if not store.any_player(root):
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
        if not store.any_player(root):
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
            code_limiter.record_failure(key)
            return Response(content=_BAD_CODE, status_code=400,
                            media_type="application/json")
        value = access.open_session(
            root, redeemed, user_agent=request.headers.get("user-agent"),
            instant=instant)
        return JSONResponse({"player": redeemed,
                             "display_name": _label_of(redeemed)},
                            headers=_session_cookie(value))

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

        Development alone, deliberately without a password. The
        gate is dev_mode by itself and not the operator bearer -
        the door is a player surface. An unknown name mints, an
        active name turns its token (each other session of that
        player stops at its next read), and a revoked name is
        refused: the door cannot put a revoked player back.
        """
        from service import players

        if not dev_mode:
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
                # The mint's invite is not answered: the door hands
                # out a session and nothing else.
                record, _invite = players.mint_player(
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
            # The read above and the write here can straddle a mint
            # or a revoke from a different process - the CLI on the
            # box. The store's own guards refuse, and the door says
            # so rather than crashing.
            return JSONResponse({"cause": "refused",
                                 "detail": str(error)}, status_code=409)
        return JSONResponse(
            {"player": record.player,
             "display_name": record.display_name},
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

    def _invite_value(record: store.PlayerRecord, token: str) -> dict:
        # The same shape as the mint: a path and not an address, and
        # the token one time.
        return {"player": record.player,
                "display_name": record.display_name,
                "token": token, "join_path": f"/join/{token}"}

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
        """The commands of the players module, and a device code."""
        from service import players

        record = _stored_player(name)
        if isinstance(record, Response):
            return record
        try:
            match command:
                case "rotate":
                    turned, token = players.rotate_player(service_config,
                                                          player=name)
                    return JSONResponse(_invite_value(turned, token))
                case "restore":
                    turned, token = players.restore_player(service_config,
                                                           player=name)
                    return JSONResponse(_invite_value(turned, token))
                case "revoke":
                    revoked = players.revoke_player(service_config,
                                                    player=name)
                    return JSONResponse({"player": revoked.player,
                                         "status": revoked.status})
                case "signout":
                    ended = players.signout_player(service_config,
                                                   player=name)
                    return JSONResponse({"player": name, "ended": ended})
                case "device-code":
                    if record.status != "active":
                        raise store.StoreError(
                            f"player {name!r} is {record.status} - a "
                            "device code is for an active player")
                    code, expires_at = access.issue_device_code(
                        root, name, utc_now())
                    return JSONResponse({
                        "player": name, "code": code,
                        "display": auth.display_device_code(code),
                        "expires_at": expires_at})
                case _:
                    raise ValueError(f"unknown command {command!r}")
        except store.StoreError as error:
            return JSONResponse({"cause": "refused", "detail": str(error)},
                                status_code=409)

    @app.post("/api/dev/players/{name}/rotate")
    def dev_player_rotate(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "rotate")

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
    def dev_player_device_code(request: Request, name: str) -> Response:
        refused = _dev_refused(request)
        if refused is not None:
            return refused
        return _player_command(name, "device-code")

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
        return JSONResponse({"days": rows})

    @app.post("/api/practice/score")
    async def practice_score_endpoint(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        from service.scoring import day_precompute, practice_score

        # The gate stands before the work: this is the one player
        # path that scores, thus a caller with no invite does none
        # of it.
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
            "submitted": caller in store.list_submissions(root, day),
            "relation_vocabulary": relation_vocabulary,
            "canvas_px": canvas_px,
            "closes_at": closes_at,
        }
        if record.status == "revealed":
            value["target_id"] = record.target_id
            value["secret"] = record.secret
        return JSONResponse(value)

    @app.post("/api/submission")
    async def submit(request: Request) -> Response:
        caller = _caller(request)
        if isinstance(caller, Response):
            return caller
        day = store.latest_day(root)
        if day is None:
            return Response(content=_NO_DAY, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        if record.status != "open":
            return JSONResponse({"cause": "day-closed"}, status_code=409)
        if caller in store.list_submissions(root, day):
            return JSONResponse({"cause": "already-submitted"},
                                status_code=409)
        try:
            wire_record = await request.json()
        except Exception:
            return JSONResponse(
                {"cause": "bad-shape",
                 "detail": "bad-shape: the body is not JSON"},
                status_code=400)
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
        trial_id = secrets.token_hex(16)
        # The status check again, with the day's write lock held: the
        # body read above lasts until the client stops sending, and a
        # close can move the day in that time. A close holds the same
        # lock for its move, thus this write lands before the close
        # reads the submissions, or it refuses (spec BR1 section 3).
        with store.day_write_lock(root, day):
            if store.read_day_record(root, day).status != "open":
                return JSONResponse({"cause": "day-closed"},
                                    status_code=409)
            try:
                store.write_once_json(
                    store.submission_path(root, day, caller),
                    {"day": day, "player": caller, "trial_id": trial_id,
                     "received_at": store_received_at(),
                     "record": wire_record})
            except store.StoreError:
                return JSONResponse({"cause": "already-submitted"},
                                    status_code=409)
        return JSONResponse({"trial_id": trial_id,
                             "atom_count": len(submission.atoms)})

    # One lifecycle move at a time in this process: the three day
    # endpoints run in the thread pool, and two of them on one day
    # can race the guarded moves. A second process meets the store's
    # guards and the rollover command's lock.
    lifecycle_lock = threading.Lock()

    def _day_move(step: str) -> tuple[int, dict]:
        """One lifecycle move as (HTTP status, body).

        The three day endpoints answer it, and so does the console's
        rollover (spec BR1 section 7.2), thus the two paths refuse
        alike. A StoreError is the store refusing the move (409), and
        each other error is the move not completing (400).
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
                        record = open_day(service_config)
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
                        day = store.latest_day(root)
                        if day is not None:
                            record = store.read_day_record(root, day)
                            if record.status in ("open", "closing") \
                                    and record.scoring_config_path \
                                    == service_config.scoring_config:
                                wired = _resident()
                        return 200, {"trial_rows": close_day(
                            service_config, wired=wired)}
                    case "reveal":
                        record = reveal_day(service_config)
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
        """The board label for one store key.

        The board artifact carries the store key alone, thus this
        joins to the player record at read time - one file read,
        and an edited label wants no new assembly. A name with no
        record falls back to its key, which is what the world of
        ruling 7 needs.
        """
        found = store.read_player_or_none(root, name)
        return name if found is None else found.display_name

    def _avatar_of(name: str) -> str | None:
        """The avatar digest for one store key, or None.

        Joined at read time in the manner of _label_of (D5 as
        ruled 2026-08-21: the boards hold avatars): one file
        read, and a new picture wants no new board assembly.
        """
        found = store.read_account_or_none(root, name)
        return None if found is None else found.avatar_hash

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
        rows = [{
            "player": entry["player"],
            "display_name": _label_of(entry["player"]),
            "avatar_hash": _avatar_of(entry["player"]),
            "p": entry["p"],
            "target_rank": entry["target_rank"],
            "decoy_count": entry["decoy_count"],
            "streak": _streak(root, entry["player"], newest),
        } for entry in prepared["rows"]]
        return JSONResponse({"day": day, "rows": rows})

    @app.post("/api/players")
    async def mint_player_endpoint(request: Request) -> Response:
        """Mint one invite (spec M1 section 8).

        The gate is the bearer and not the operator gate of
        ruling 7. With no configured token this answers the
        constant refusal forever: the switch that turns access
        control on must not itself be open in the world where
        nothing holds credentials.

        The answer holds the invite path and not a full address.
        The server does not know its public source and must not
        trust the Host header for one. The console knows its own
        source and the command-line path takes an argument.

        The token prints one time. The store keeps its digest
        alone, thus no read that follows can collect it.
        """
        from service import players

        if not _bearer_ok(request):
            return _unauthorized()
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
        try:
            record, token = players.mint_player(
                service_config, player=name, display_name=label)
        except store.StoreError as error:
            return JSONResponse({"cause": "already-minted",
                                 "detail": str(error)}, status_code=409)
        return JSONResponse({"player": record.player,
                             "display_name": record.display_name,
                             "token": token,
                             "join_path": f"/join/{token}"})

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
        rows = index.revealed_trial_rows(target, from_day=day_from,
                                         to_day=day_to, player=player_name)
        return JSONResponse({"rows": rows, "count": len(rows)})

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
                       single_player: bool) -> str | None:
    """Refuse a public start with no player records (spec BR1 section 4).

    With no record stored each caller is the configured player (spec
    M1 ruling 7), thus a public box in that condition lets each
    visitor play as the owner. The dev server and an explicit
    --single-player keep that world on purpose.
    """
    if has_players or dev_mode or single_player:
        return None
    return ("the store holds no player records, thus each visitor would "
            "play as the configured player - mint one first (python -m "
            "service.players mint <name>), or start with --single-player "
            "for a private box")


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
        world_refusal = open_world_refusal(
            has_players=store.any_player(Path(service_config.store_root)),
            dev_mode=arguments.dev, single_player=arguments.single_player)
        if world_refusal is not None:
            raise ServiceConfigError(world_refusal)
        app = create_app(
            service_config, dev_mode=arguments.dev,
            cookie_secure=not arguments.cookie_insecure,
            operator_token=os.environ.get("STARVECTOR_OPERATOR_TOKEN"))
    except Exception as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run(app, host="127.0.0.1",
                port=arguments.port or service_config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
