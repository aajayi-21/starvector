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


def create_app(service_config: ServiceConfig) -> FastAPI:
    """The app factory - tests run it through TestClient."""
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
    root = Path(service_config.store_root)
    data_root = Path(service_config.data_root)
    player = service_config.player

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

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
        targets = _revealed_targets(root)
        if image_id not in targets:
            return Response(content=_NOT_REVEALED, status_code=404,
                            media_type="application/json")
        image_bytes = load_image_bytes(data_root, image_id)
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
    arguments = parser.parse_args(argv)
    try:
        service_config = load_service_config(Path(arguments.service_config))
    except Exception as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run(create_app(service_config), host="127.0.0.1",
                port=arguments.port or service_config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
