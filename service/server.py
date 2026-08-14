"""The localhost HTTP surface (spec S1 section 9).

FastAPI endpoints in front of the store, with the R3 rules held
structurally: pre-reveal refusals are module constants returned
before target-dependent work, the intake page is one constant byte
string, and the acknowledgment is a validation echo with no score in
it. The server binds to localhost, one configured player (D6).
"""

import argparse
import math
import secrets
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core.aggregate import shrunk_log_theta, skill_summary
from core.intake import IntakeError, validate_submission
from core.types import ROUTING_TABLE, IntakeGates, Submission, Weights
from pipeline.config import (fusion_weights, intake_gates,
                             load_scoring_config, placement_config)
from pipeline.context import load_preparation_record
from pool.artifacts import load_image_bytes
from pool.preparation.config import load_preparation_config
from service import store
from service.config import ServiceConfig, load_service_config

# The D5 solo display inputs (spec S1 section 14a): display-only, a
# fitted population comes with live players.
POPULATION_MEAN = 0.0
POPULATION_SPREAD = 0.15

# Constant pre-reveal refusal bytes (R3): one body for each refused
# path, with no target-dependent work before it.
_NOT_REVEALED = b'{"detail":"not revealed"}'
_NO_DAY = b'{"detail":"no day open"}'
_DEV_OFF = b'{"detail":"not found"}'
_NO_PRACTICE = b'{"detail":"no revealed day"}'
_NOT_PRACTICE = b'{"detail":"not a practice day"}'

_UI_ROOT = Path(__file__).parent / "ui"


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
               dev_mode: bool = False) -> FastAPI:
    """The app factory - tests run it through TestClient.

    With dev_mode the server adds the section 14b surfaces: the
    target is readable while the day is open, a draft scores when
    asked with the full pool ordering, and each pool
    image serves - the R3 wire rules are deliberately off, for the
    owner's scoring work on the development pool alone. Without the
    flag the dev paths answer one constant 404.
    """
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
    page_bytes = (_UI_ROOT / "index.html").read_bytes()
    script_bytes = (_UI_ROOT / "trial.js").read_bytes()
    dev_page_bytes = (_UI_ROOT / "dev.html").read_bytes()
    dev_script_bytes = (_UI_ROOT / "dev.js").read_bytes()
    root = Path(service_config.store_root)
    data_root = Path(service_config.data_root)
    player = service_config.player

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

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

    @app.get("/dev")
    def dev_page() -> Response:
        if not dev_mode:
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        return HTMLResponse(content=dev_page_bytes)

    @app.get("/ui/dev.js")
    def dev_script() -> Response:
        if not dev_mode:
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        return Response(content=dev_script_bytes,
                        media_type="text/javascript")

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
    def dev_days() -> Response:
        if not dev_mode:
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
            })
        return JSONResponse({"days": rows})

    @app.get("/api/dev/submission")
    def dev_submission(day: str | None = None) -> Response:
        if not dev_mode:
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        picked = _picked_day(day)
        if isinstance(picked, Response):
            return picked
        stored = store.read_json_or_none(
            store.submission_path(root, picked, player))
        if stored is None:
            return JSONResponse({"cause": "no-submission",
                                 "detail": "no stored submission this "
                                           "day"}, status_code=404)
        return JSONResponse(stored)

    @app.get("/api/dev")
    def dev_view() -> Response:
        if not dev_mode:
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
    def dev_stored_rankings(day: str | None = None) -> Response:
        if not dev_mode:
            return Response(content=_DEV_OFF, status_code=404,
                            media_type="application/json")
        picked = _picked_day(day)
        if isinstance(picked, Response):
            return picked
        record = store.read_day_record(root, picked)
        stored = store.read_json_or_none(
            store.submission_path(root, picked, player))
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

    @app.get("/api/practice")
    def practice_days() -> Response:
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
        return JSONResponse({"day": day, **value})

    @app.get("/")
    def index() -> Response:
        return HTMLResponse(content=page_bytes)

    @app.get("/ui/trial.js")
    def script() -> Response:
        return Response(content=script_bytes,
                        media_type="text/javascript")

    @app.get("/api/day")
    def day_view() -> Response:
        day = store.latest_day(root)
        if day is None:
            return Response(content=_NO_DAY, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        value = {
            "day": record.day,
            "trial_code": record.trial_code,
            "status": record.status,
            "commitment": record.commitment,
            "player": player,
            "submitted": player in store.list_submissions(root, day),
            "relation_vocabulary": relation_vocabulary,
            "canvas_px": canvas_px,
        }
        if record.status == "revealed":
            value["target_id"] = record.target_id
            value["secret"] = record.secret
        return JSONResponse(value)

    @app.post("/api/submission")
    async def submit(request: Request) -> Response:
        day = store.latest_day(root)
        if day is None:
            return Response(content=_NO_DAY, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        if record.status != "open":
            return JSONResponse({"cause": "day-closed"}, status_code=409)
        if player in store.list_submissions(root, day):
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
        try:
            store.write_once_json(
                store.submission_path(root, day, player),
                {"day": day, "player": player, "trial_id": trial_id,
                 "received_at": store_received_at(),
                 "record": wire_record})
        except store.StoreError:
            return JSONResponse({"cause": "already-submitted"},
                                status_code=409)
        return JSONResponse({"trial_id": trial_id,
                             "atom_count": len(submission.atoms)})

    @app.post("/api/day/open")
    def day_open() -> Response:
        import datetime

        from service.day import open_day

        # The next free date: today, or the day after the latest
        # stored day - the test flow runs many days back to back
        # (section 14b). One active day at a time:
        # an open latest day refuses.
        latest = store.latest_day(root)
        date = None
        if latest is not None:
            if store.read_day_record(root, latest).status == "open":
                return JSONResponse(
                    {"cause": "refused",
                     "detail": f"day {latest} is open - close it first"},
                    status_code=409)
            today = datetime.date.today().isoformat()
            if latest >= today:
                date = (datetime.date.fromisoformat(latest)
                        + datetime.timedelta(days=1)).isoformat()
        try:
            record = open_day(service_config, date=date)
        except store.StoreError as error:
            return JSONResponse({"cause": "refused",
                                 "detail": str(error)}, status_code=409)
        except Exception as error:
            return JSONResponse({"cause": "open-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"day": record.day,
                             "trial_code": record.trial_code,
                             "commitment": record.commitment})

    @app.post("/api/day/close")
    def day_close() -> Response:
        from service.day import close_day

        # The one live step (R5): the server process needs the
        # provider key in its environment for a live config. The
        # answer names the row count and no score (R3). The resident
        # context serves the close when the day's pinned config path
        # is the server's own - a day opened with a different config
        # wires anew from its pinned path (P5 R1).
        try:
            wired = None
            day = store.latest_day(root)
            if day is not None:
                record = store.read_day_record(root, day)
                if record.status == "open" \
                        and record.scoring_config_path \
                        == service_config.scoring_config:
                    wired = _resident()
            count = close_day(service_config, wired=wired)
        except store.StoreError as error:
            return JSONResponse({"cause": "refused",
                                 "detail": str(error)}, status_code=409)
        except Exception as error:
            return JSONResponse({"cause": "close-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"trial_rows": count})

    @app.post("/api/day/reveal")
    def day_reveal() -> Response:
        from service.day import reveal_day

        try:
            record = reveal_day(service_config)
        except store.StoreError as error:
            return JSONResponse({"cause": "refused",
                                 "detail": str(error)}, status_code=409)
        except Exception as error:
            return JSONResponse({"cause": "reveal-failed",
                                 "detail": str(error)}, status_code=400)
        return JSONResponse({"day": record.day})

    @app.get("/api/reveal")
    def reveal_view() -> Response:
        day = store.latest_day(root)
        if day is None:
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        record = store.read_day_record(root, day)
        if record.status != "revealed":
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        row = store.read_json_or_none(
            store.trial_row_path(root, day, player))
        value = {
            "day": record.day,
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
        return JSONResponse(value)

    @app.get("/image/{image_id}")
    def image(image_id: str) -> Response:
        if not dev_mode:
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

    @app.get("/history")
    def history() -> Response:
        from html import escape

        rows = []
        ps = []
        for day in store.list_days(root):
            record = store.read_day_record(root, day)
            if record.status != "revealed":
                continue
            row = store.read_json_or_none(
                store.trial_row_path(root, day, player))
            if row is None:
                continue
            ps.append(float(row["p"]))
            rows.append(
                f"<tr><td>{escape(day)}</td>"
                f"<td>{row['p']:.4f}</td>"
                f"<td>{row['target_rank']} of {row['decoy_count'] + 1}"
                f"</td></tr>")
        if ps:
            summary = skill_summary(ps, unbiased=(len(ps) >= 2))
            shrunk = shrunk_log_theta(summary.log_theta, summary.n,
                                      POPULATION_MEAN, POPULATION_SPREAD)
            variant = "unbiased" if len(ps) >= 2 else "biased at n = 1"
            aggregate = (
                f"<p>skill number {summary.theta:.3f} ({variant}), "
                f"shrunk {math.exp(shrunk):.3f}, "
                f"evidence {summary.evidence_p:.3f}, "
                f"across <strong>{summary.n}</strong> trial(s)</p>")
        else:
            aggregate = "<p>no revealed trial yet</p>"
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>trial history</title>"
            "<p><strong>DEV-ONLY</strong> - development pool numbers, "
            "not for publication</p>"
            f"{aggregate}"
            "<table><tr><th>day</th><th>trial score</th><th>rank</th></tr>"
            + "".join(rows) + "</table>"
            "<p><a href='/'>today</a></p>")
        return HTMLResponse(content=body)

    return app


def store_received_at() -> str:
    """The submission timestamp - one seam for the tests to pin."""
    from validation.harness import default_clock

    return default_clock()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.server")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--dev", action="store_true",
                        help="the section 14b dev surfaces - target "
                             "readable, draft scoring, all images")
    arguments = parser.parse_args(argv)
    try:
        service_config = load_service_config(Path(arguments.service_config))
    except Exception as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run(create_app(service_config, dev_mode=arguments.dev),
                host="127.0.0.1",
                port=arguments.port or service_config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
