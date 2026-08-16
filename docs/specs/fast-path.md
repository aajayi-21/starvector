# Spec P5 — the fast path and practice mode

**Status:** ruled, prepared to build.
**Phase:** 5 (`docs/ARCHITECTURE.md` §25) — tier the element channel,
make the context resident, batch where the seam is built, and open
practice mode. The method source is §18.
**Architecture sections:** §18 (latency), §15 (what stays out of the
interactive path), §22 (integrity), §25 (phases).
**Working agreement:** `CLAUDE.md` §2 (I6, I7), §3, §7, §10.
**Input:** Phase 4 closed on dev-wit-002 (204 images, frozen weights
`{element: 0.45, outline: 0.55}`, placement cut), the server on
`configs/scoring/dev-wit-mixed-3.json`, the adopted encoder
`google/gemini-embedding-2` through OpenRouter.

---

## 1. Purpose

The daily trial needs no speed — §18's structural insight — and the
solo build honors that today: the acknowledgment is thin and prompt,
and close has hours. What the current build does not have:

- **No resident context.** Each close and each dev score wires the
  full context: about 32 MB read and SHA-256-checked, the box tables
  rebuilt, the commonness tables re-read. The outline channel then
  re-centers the full pool matrix — a 15 MB allocation — on each
  scoring step.
- **A tier boundary with no data behind it.** `tier2_count` (500) is
  above the dev pool count, thus the live path runs the accurate
  matching on each image through a Python loop, and the
  tier-1-to-tier-2 stitching has run on no data at all.
- **A batch seam with no caller.** `encode_submissions` batches
  across submissions. The close loop encodes one at a time, two
  times each.
- **No practice mode.** The one interactive consumer of the scoring
  path is not built, and its open questions (target source, leakage,
  storage) were open until the rulings below.

This phase closes those four holes with no change to a stored
artifact: the daily scores, the hashes, and the rescore byte
equality stay as they are. Speed work that moves a number is not
speed work.

## 2. The rulings of 2026-08-13

1. **Phase 5 runs at this time, on the dev pool.** The engineering
   holds at each pool count. The production-only numbers —
   shortlist widths 500/25 and the 90% recall line — stay parked
   for the production pool, as F1 recorded. (F1's roadmap wrote
   "50/25" — an error this spec corrects to 500/25.)
2. **Practice replays earlier day targets alone.** The
   architecture's own words. Only targets of revealed days are
   playable: their images are public after reveal, thus practice
   shows no new pool image, leaks no pool membership, and gives no
   preview of a future daily target. The set grows by one with
   each played day.
3. **The budget is local.** The adopted encoder is an API model,
   and no local work brings a network POST below 50 ms. The
   ruling: keep the adopted encoder. One batched embedding POST
   for each practice score is accepted (about one to two seconds of
   felt latency), and the local work after the vectors come back —
   channels, normalization, fusion, ranking — must clear the §18
   50 ms budget, measured at a synthetic 20,000-image pool. The
   end-to-end 50 ms question reopens with the encoder decision at
   the production pool.
4. **Practice is ephemeral.** Score, show, discard — the
   `dev_rankings` pattern. Nothing lands in the store, thus the I6
   fence is structural: practice trials are live-player data with
   known targets, the one thing fitting must not touch, and data
   that is not on disk cannot be fit on. A session counter in the
   page is permitted.

## 3. Requirements

- **R1 — one resident context for each server process.** The
  scoring context loads one time — hash checks included — and the
  close endpoint, the dev console, and practice all read it. A new
  process re-reads config. The CLI commands keep their own wiring,
  and the resident path and the CLI path must score byte-equal.
- **R2 — pool-side precomputation.** The centered, normed outline
  pool matrix is calculated one time at context build, not on each
  channel step. The day-start values §18 names — the decoy set, the
  decoy count, the target's duplicate group — are calculated at
  most one time for each day, off the serving path.
- **R3 — the batched tier 2 is byte-equal to the loop.** The
  shortlist loop becomes one batched tensor computation, and the
  batched result must equal the loop's output byte-for-byte on the
  same inputs — the rescore invariant (`trial-service.md` R8) rides on
  it. A batched path that moves a float is a scoring change, not an
  optimization, and stops the work.
- **R4 — practice touches no store and no open day.** The practice
  surfaces read the revealed-day targets, score through the
  resident context, and write nothing. While a day is open, no
  practice answer varies with the open day's target (I7): the
  practice target set is a function of revealed days alone, and the
  refusal bodies are constants. Practice needs the provider key in
  the server environment — the rule close-from-the-page set.
- **R5 — the fit path stays sealed.** No practice module enters the
  import closure of the fit and V3 through V6 runners
  (`tests/unit/test_fit_isolation.py` pins it).
- **R6 — measured, not asserted.** A bench tool times the local
  stages on synthetic pools at 204 and 20,000 images with warm fake
  encoders, and the numbers land in a committed record. If 20,000
  on the dev machine misses 50 ms, that is a recorded result and a
  standing item for the production phase (device placement), not an
  inline failure.
- **R7 — the close loop uses the batch seam.** One
  `prewarm_records` step across the day's stored submissions
  before the scoring loop — the built helper, thus each cold atom
  rides a shared batch and not its own POST. Full multi-player
  batching stays with the multi-player phase.

## 4. Build items

- **B1 — the resident context** (`service/server.py`,
  `service/scoring.py`, `service/day.py`). Promote the `_dev_wired`
  pattern to one shared wiring on the app object: one lazy
  `wire_for_close` result read by the close endpoint, the dev
  surfaces, and practice. `close_day` takes an optional pre-wired
  context — the CLI wires its own, the server hands in the resident
  one. Byte-equality test: a day closed through the resident path
  equals a day closed through the CLI path, snapshot for snapshot.
- **B2 — outline precompute** (`pipeline/context.py`,
  `core/channels/outline.py`, `core/types.py`). The centered unit
  pool matrix and its norms land in the built context as derived
  fields — calculated one time, read by the channel. Byte-equality
  with the current computation is the test.
- **B3 — the batched tier 2** (`core/channels/element.py`). The
  shortlist solves stack into one `(S, m, k)` Sinkhorn computation
  with the same iteration count and dtype. Pinned by a test that
  runs the loop and the batch on random fixtures and asserts equal
  bytes, plus the channel tests unchanged.
- **B4 — day-start precompute** (`service/scoring.py`). The decoy
  set, decoy count, and duplicate group of the day's target are
  kept from the first use for the day — small at dev scale,
  structural for production.
- **B5 — practice mode** (`service/server.py`, `service/ui/`).
  **Dated note, 2026-08-16:** the two endpoints landed with spec
  S2 and the page half is the app's `/practice` screen (spec W1).
  `service/ui/` no longer exists — the hand-written pages retired
  and `docs/specs/trial-service.md` §5 records it. Read the page
  bullet below as the screen that is built, not as work to do.
  - `GET /api/practice` — the playable set: the revealed days with
    their target identifiers (public after reveal), or a constant
    refusal when none is revealed.
  - `POST /api/practice/score` — one wire record plus one chosen
    revealed target. Validates, scores through the resident
    context, answers the trial numbers, the match report, and the
    ranking head. Stores nothing.
  - The player page gains a practice view: pick an earlier day (or
    random), sketch with the full intake and the palette, score at
    the moment of sending, see the result with the revealed image.
    A session counter, no history.
  - The R3 walk extends across the practice surfaces: while a day
    is open, no practice byte varies with the open target.
- **B6 — close prewarm** (`service/day.py`). One `prewarm_records`
  step before the submission loop.
- **B7 — the bench tool** (`tools/bench.py`). Synthetic pool arrays
  at a given count and dimension, warm fake encoders, stage timings
  for render, channels, normalization, fusion, and ranking, at 204
  and 20,000. Prints numbers. A committed record documents the run
  (`validation/records/bench-*.json`, machine noted). Not in CI.
- **B8 — a stitched-boundary V6** (config plus run). One committed
  variant scoring config with `tier2_count` below the dev pool
  count (25), thus the tier boundary runs on data before
  production: the V6 harness on it measures stitched recall against
  the accurate channel. Dev numbers.
- **B9 — document repairs.** The F1 roadmap's "50/25" becomes
  500/25, and `trial-service.md`'s stale 225 count gets the same
  treatment the V6 docstring got.

## 5. The owner runbook

Offline work at each step but one — the live surface is practice
itself.

1. Merge the build, start the server again. Play one practice trial
   against an earlier day: sketch, score, result in about one to
   two seconds, nothing in the store.
2. `uv run python -m tools.bench --count 204` and
   `--count 20000` — the local-stage numbers, recorded. The 50 ms
   line applies to the 20,000 run (ruling 3).
3. The stitched V6:
   `uv run python -m validation.v6 --config configs/fit/dev-wit-2.json
   --scoring-config <the B8 variant config> --report` — warm, one
   record, owner verdict. What it says: stitched recall against the
   accurate channel at a boundary that finally cuts.
4. Verdicts on the bench record and the V6 record. Dev numbers, not
   published.

## 6. Acceptance criteria

1. Byte-equality holds three times: batched tier 2 equals the loop,
   the resident close equals the CLI close, and the outline
   precompute equals the current computation. The stored-day
   rescore invariant stays green untouched.
2. The R3 integrity walk, extended across the practice surfaces,
   stays green while a day is open.
3. A practice trial runs end to end on the dev build with nothing
   written to the store.
4. The bench record is committed with numbers at 204 and 20,000,
   and the 20,000 local time is on the record — below 50 ms, or
   recorded with the shortfall as a standing item.
5. The stitched-boundary V6 record is committed with an owner
   verdict.
6. Full suite green offline. Vale at zero errors on changed prose.

## 7. Out of scope

- The production thresholds (500/25, the 90% line) and each
  production-pool measurement.
- A local encoder and the end-to-end 50 ms — the production pool's
  encoder decision.
- Multi-player batching after the close-loop seam, accounts, and
  the leaderboard — its V2 plus V3 gate is met, and the build is
  its own phase.
- Layer 7, frontloading, tags.
