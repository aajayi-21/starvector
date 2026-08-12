# Spec S1 — the daily trial server and Layer 9

**Status:** draft, for review.
**Phase:** after the P2c adoption (`docs/specs/photo-embedding-bridge.md`
§9c). Runs in parallel with the Phase 4 live gates — this build touches
no fit artifact, and the leaderboard display it deliberately excludes
stays gated on V3 (`CLAUDE.md` §7).
**Architecture sections:** §6 (the submission and the interface), §8
(Layer 0), §16 (Layer 8, as consumer), §17 (Layer 9), §18 (what needs
speed and what does not), §21 (versioning), §22 (protocol integrity),
§27 (the worked example, for the feedback shape).
**Working agreement:** `CLAUDE.md` §3, §5, §7, §10.
**Input:** the adopted base (preparation
`dev-wit-prep-photo-inst-d67a70c3`, the re-pointed
`configs/scoring/dev-wit.json`), the committed P2c records, and the
demo tool (spec T1) as the wiring precedent.

This spec is written for implementation by an AI agent. Where a value
or a rule is not given by the architecture, §14 says so and proposes a
default. Do not implement an open decision without agreement.

---

## 1. Purpose

Each thing built so far scores submissions that a harness made.
Nothing lets a person sit down with a trial identifier, sketch,
send the result in, and get a trial score back the next morning. This
stage builds that smallest playable loop, for one player, on the
owner's machine, against the dev pool — and it builds the §22
integrity structure at the same time, because `CLAUDE.md` §7 rules
that identifier hygiene and window-close gating are structural and a
retrofit means re-run trials.

The stage also builds Layer 9 (`core/aggregate.py`), the last unbuilt
layer of the stack: the skill number, the evidence value, and
shrinkage, as pure functions with tests.

Out of the stage, deliberately: anything that looks like a
leaderboard (gated on V3), the production pool, practice mode
(Phase 5), Layer 7, frontloading, and account protection. The single
player is a stored field, not a structural assumption — the store and
the day records hold a player identity from the first row, thus a
subsequent multi-player stage adds players, not migrations.

## 2. Scope

**In scope**

- `core/aggregate.py` — Layer 9 as pure functions: skill number,
  evidence, shrinkage, and the §17 rate adjustment for many players
  (`fdr_adjusted`).
- The trial store: permanent raw submissions (Rule 4), day records,
  trial rows, `write-once` and append-only.
- The day lifecycle as owner commands: open, close, reveal, status,
  rescore. Commitment at open, the secret at reveal (§22).
- The scoring task at close: `pipeline.score.score_trial` with the
  committed scoring config, plus the atom-by-atom report
  (`core.channels.element.match_report`) stored for the reveal.
- A localhost server with the intake page — the interface **is** the
  atom assembler (§6): impressions rows, the stroke canvas, the group
  lasso with labels, the relation builder, one send action.
- The reveal page: the target image, the trial score with its decoy
  count, the atom-by-atom report, the published secret.
- A history page: earlier revealed trials and the Layer 9 summary for
  the one player, labeled as development numbers.
- The rescore command and the byte-equality invariant test
  (`CLAUDE.md` §9).

**Out of scope**

- The leaderboard and each between-player display (V3 gate,
  `CLAUDE.md` §7). Layer 9 ships as functions and a one-player
  summary only.
- Practice mode and the 50 ms budget (Phase 5). The daily close task
  has hours (§18), and at 225 images the plain path completes in seconds.
- Layer 7, frontloading and the tag vocabulary (§20), source-3
  fitting.
- Accounts, sessions, and network hardening. The server binds to
  localhost. One player, named in configuration.
- The production pool. The server reads a preparation record path
  from its config, thus the pool release that follows is a config
  change here.

## 3. Terms this spec adds

| Term | Meaning |
|---|---|
| **Day** | One trial cycle: open → closed → revealed. Identified by its ISO date. |
| **Day record** | The stored facts of one day: target, seed, commitment, secret, config hashes, status, timestamps. |
| **Commitment** | The digest published at open: SHA-256 of the target identifier plus the day secret (§22). |
| **Trial row** | The stored scoring output for one (day, player): trial score, decoy count, beaten, tied, rank, atom-by-atom report, config hashes. |
| **Store** | The permanent on-disk root for days, submissions, and trial rows. Not a cache: nothing in it is rebuildable from elsewhere. |

## 4. Requirements

- **R1 — the interface is Layer 1.** The page sends the wire record
  the harnesses score, field for field (`impressions`,
  `canvas_strokes`, `groups`, `relations`, `pasted_text` —
  `core/intake.py`). The server runs Layer 0 validation and nothing
  else on it: no parser, no normalization, no model (§6, §9 of the
  architecture).
- **R2 — raw before derived.** The submission record is written to
  the store before scoring is attempted, and the store is `write-once`:
  a second submission for one (day, player) is refused, and no code
  path edits a stored record (Rule 4, §22 lockout).
- **R3 — nothing answers with score information before close.** No
  endpoint, page, response length, or status difference reveals
  anything about the target while the day is open (§22, I7). The
  target image bytes go out at reveal alone, and for revealed days
  alone.
- **R4 — commitment before play.** Open publishes the commitment.
  Reveal publishes the secret and the target identifier, thus the
  player can check the day was not rewritten (§22).
- **R5 — the context is precomputed, the close task is deliberate.**
  Open requires the pool index and the commonness tables to load and
  stops loudly when they are missing — it builds nothing and posts
  nothing. Close is the one step that can spend: it encodes the
  stored submission through the configured providers, and the owner
  runs it with the key set (the standing key rule).
- **R6 — the target is an equally likely pick with a recorded seed.**
  From the full pool, with the seed and the pick stored in the day
  record. The decoy set is the pool minus the target's near-duplicate
  group (`core/ranking.py`, unchanged), and the decoy count is stored
  with the trial row (§16).
- **R7 — Layer 9 is pure, with no new dependency.** `core/aggregate.py`
  implements §17 as given: `skill number = n / S` with the
  `(n - 1) / S` unbiased variant, the evidence value from `2S`
  against chi-squared at `2n` degrees of freedom, and the shrinkage
  formula. The chi-squared tail at `2n` degrees of freedom is the
  finite Poisson sum, thus no new numeric dependency. The §17
  rate adjustment for many players ships as a pure function for the
  multi-player stage. Population parameters are function arguments.
- **R8 — rescore reproduces history byte-for-byte.** The rescore
  command re-runs each stored submission with a named scoring config
  and compares against the stored trial rows. With the pinned config
  the scores must agree byte-for-byte (`CLAUDE.md` §9). With a
  different config it writes a new result set adjacent to the stored
  one and edits nothing (§21: rescore, do not migrate).
- **R9 — the shell stays thin.** The server and the commands wire
  providers, read and write the store, and use `core/` and
  `pipeline/` functions. No scoring logic, no formula, no cutoff
  lives in `service/` (`CLAUDE.md` §3, §5).
- **R10 — offline tests, loud failures.** The full test suite runs
  with fake providers and no network. A missing table, a gate
  violation, a double send, and a pre-reveal image fetch each stop
  loudly with the cause named.

## 5. The store

The store is a new top-level directory, gitignored like `data/` but
permanent — the documentation and the directory README must say so
(§14 D2 rules the root name).

```
store/
  days/<YYYY-MM-DD>/day.json            # the day record
  days/<YYYY-MM-DD>/submissions/<player>.json
  days/<YYYY-MM-DD>/trials/<player>.json
```

- `day.json` holds: the day identifier, the target identifier, the
  pick seed, the day secret, the commitment, the scoring config path
  and its hash at open, the preparation version, the status
  (`open` | `closed` | `revealed`), and the three timestamps. The
  target sits in this file before reveal — the §22 rules apply to
  the wire, and the store is the owner's own disk. No endpoint reads
  the target out of it before reveal (R3), and the integration tests
  check that.
- `submissions/<player>.json` holds the wire record plus received-at,
  the trial identifier served to the client, and the player name.
  One write, no edit (R2).
- `trials/<player>.json` holds the trial row (§3) plus the identity
  fields a rescore compares: scoring config hash, commonness config
  hash, preparation version. Written by close, read by reveal.
- Writes go through the atomic-write helpers that are there
  (`pool/artifacts.py`). Rescore with a different config writes
  `trials/<player>.<scoring-hash8>.json` adjacent to the first row
  set (R8).

The trial identifier the client sees is a new random 128-bit hex
value with no derivation from the day, the target, or the pool (§22).
The map from trial identifier to (day, player) lives in the
submission record.

## 6. The day lifecycle

One command surface, the P1b resume rules in spirit: each status move
is deliberate, repeatable, and refuses to run out of sequence.

```
uv run python -m service.day open     [--config configs/scoring/dev-wit.json] [--date ...]
uv run python -m service.day close    [--date ...]
uv run python -m service.day reveal   [--date ...]
uv run python -m service.day status
uv run python -m service.day rescore  --config <scoring config> [--from ... --to ...]
```

- **open** — loads the pool index and the commonness tables (R5,
  stop-loudly), picks the target with a seeded, equally likely pick
  (R6), makes the day secret (256 random bits), computes the
  commitment, writes `day.json` with status `open`, and prints the
  commitment. Refuses when the day exists.
- **close** — refuses unless the status is `open`. Scores each stored
  submission through `score_trial` and `match_report`, writes the
  trial rows, sets the status to `closed`. This is the one live step
  (R5). With a warm sketch-slot cache it costs one embedding item
  for each new drawing. A day with no submission closes to an empty
  trial set — a recorded fact, not an error.
- **reveal** — refuses unless the status is `closed`. Sets the status
  to `revealed`. From here the server answers the reveal page with
  the target, the score, the report, and the secret (R4).
- **status** — prints the current day, its status, and if a
  submission is stored. No score information while open (R3 applies
  to each surface, the terminal included).
- **rescore** — R8. Reads each stored submission across the named
  date range, scores with the named config, and compares or writes
  new rows. Byte-equality failures name the day and the field.

Close and reveal stay manual in this stage: a solo dev loop closes
the day when the owner is done, and automation is one cron line in a
stage after this one, not a server item (§14 D3).

## 7. The scoring task

Close wires the providers from the day's scoring config as the
harnesses do (`validation.harness.wire_encoders`), loads the
context one time (`pipeline.context.load_pool_index`,
`build_scoring_context` with the stored commonness tables), and runs
Layers 0 through 8 in one step for each submission
(`pipeline.score.score_trial`). It stores, for each trial row:

- the trial score `p`, the decoy count `D`, `beaten`, `tied`, and
  the strict target rank (the V1 rule).
- the atom-by-atom report from `match_report` against the target —
  which atom corresponded to which element, at what similarity and
  rarity — the §27 feedback shape, and an input to no score.
- the identity fields of §5.

The commonness tables come from the keyed artifact the V2 runs
built, warm (`pipeline.commonness.ensure_commonness_tables` with the
background thunk unreachable at close — a missing table is an
open-time error, R5).

## 8. Layer 9 — `core/aggregate.py`

Pure functions on a sequence of trial scores, §17 as written:

```python
SkillSummary = skill_summary(ps, unbiased=True)
# S = -sum(log p), theta = n/S (or (n-1)/S), log_theta,
# evidence_statistic = 2S, dof = 2n, evidence_p

shrunk_log_theta(log_theta, n, population_mean, population_spread)

fdr_adjusted(p_values)     # Benjamini-Hochberg, for the later stage
```

- A trial score of 0.0 is clamped to the smallest positive
  representable value before the logarithm, and the clamp count is
  reported — a silent infinity is worse than a named clamp.
- The chi-squared tail at `2n` degrees of freedom is the finite
  Poisson sum `exp(-S) * sum_{k<n} S^k / k!` — no new dependency
  (R7).
- Property tests: seeded `Uniform(0, 1)` trial scores give a skill
  number near 1 and evidence values that also agree with
  `Uniform(0, 1)`. Shrinkage moves to the population mean with a
  weight that rises in `n`. Each function is deterministic and
  argument-pure.
- The one-player history page shows the raw and the shrunk number
  with the trial count named with them (§17: display the count
  prominently). Population parameters for the solo display come from
  §14 D5 — they are display inputs, not fitted values.

## 9. The server and the intake page

A localhost HTTP server (§14 D1 rules the mechanism), started as
`uv run python -m service.server [--port ...]`. Surfaces:

| Endpoint | While open | After reveal |
|---|---|---|
| `GET /` | the intake page, or "submitted" when a record exists | the reveal report |
| `GET /api/day` | day identifier, status, commitment | plus the target identifier and the secret |
| `POST /api/submission` | Layer 0 validation, store, acknowledgment | refused |
| `GET /api/reveal` | refused (404, constant body) | score, report rows, target reference |
| `GET /image/<id>` | refused | the target bytes of a revealed day |
| `GET /history` | earlier revealed days, Layer 9 summary | same |

- The acknowledgment names the stored atom count and the trial
  identifier and nothing else — a validation echo, not a score (§8:
  acknowledgment below 200 ms, with no encoder in this path).
- Layer 0 rejections come back with the gate named, and the page
  shows them — the player corrects the submission before the window
  closes, which is the §8 contract.
- The intake page is one static HTML file with plain JavaScript, no
  build step (§14 D4 rules the canvas values):
  - impressions — a repeating single-line field, Enter commits a row.
  - the canvas — pointer strokes captured as unit-square float
    coordinates, the §8 shape, rendered locally for the player alone.
  - the group lasso — select strokes, give them a group, attach an
    optional label.
  - the relation builder — two groups and one of the four relation
    strings from the scoring config.
  - paste — one optional free-text field that lands in `pasted_text`
    and splits by the fixed Layer 1 rule, server-side, as built.
- The page holds the same bytes for each possible target while the
  day is open (R3): it embeds the day identifier and the commitment
  and nothing target-dependent.

## 10. Integrity checklist (§22, built and tested)

| §22 item | This stage |
|---|---|
| No feedback before close | R3. An integration test walks each endpoint while open and asserts no score bytes |
| Stroke coordinates alone | The wire shape has no image field, and the canvas sends coordinates (§8) |
| Identifier hygiene | Random trial identifier, no content-derived path, target bytes gated on reveal |
| Shared-target leakage | One player. The lockout (R2) is built anyway |
| Commitment | R4, published at open, checkable at reveal |
| Autocomplete leakage | The impressions field has no suggestion source at all in this stage |

## 11. Testing

- **Unit:** aggregate functions (property-based where §8 names it),
  store `write-once` behavior and atomicity, day status moves and their
  refusals, the commitment digest, the trial-identifier shape.
- **Integration** (fake providers, the `build_direct_prepared_pool`
  fixture): one full day — open, send through the HTTP surface, a
  second send refused, close, reveal, history — asserting the R3
  rule on each endpoint in each status, and the trial row against a
  plain `score_trial` result.
- **Invariant:** rescore byte-equality on a stored fixture day with
  the pinned config. A rescore with a different config writes new
  rows and touches nothing stored.
- **The page logic** (stroke capture, lasso, wire-record assembly)
  is plain JavaScript in one file, and its wire-record output is
  pinned by a fixture: a recorded interaction script must give the same
  record the intake tests validate. No browser automation in CI.

## 12. Code layout

```
core/aggregate.py          # Layer 9, pure (the missing CLAUDE.md section 8 row)
service/
  __init__.py
  store.py                 # paths, atomic write-once, read-back
  day.py                   # the lifecycle commands (__main__)
  scoring.py               # the close task: wiring + score_trial + report
  server.py                # the HTTP surface (__main__)
  ui/index.html            # the intake and reveal page
  ui/trial.js              # strokes, lasso, relations, wire assembly
tests/service/             # the section 11 suite
```

`service/` imports `core/`, `pipeline/`, `pool/artifacts`, and
`validation.harness` for wiring. Nothing imports `service/`.
`CLAUDE.md` §8 gains the two layout rows when this lands.

## 13. What this stage deliberately sets up

- A second player is one more name: the store, the lockout, and the
  trial rows are keyed by (day, player) from the first day.
- The leaderboard needs V3 plus a display ruling — Layer 9 and the
  many-player adjustment are built and tested before it comes.
- The production pool is a config change: the server reads one
  scoring config, and the §21 rescore-do-not-migrate rule is the
  rescore command.
- Practice mode (Phase 5) can use the same server and page against a
  resident context. Nothing in this stage assumes cold loads.

## 14. Open decisions — agreement required before implementation

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | Server mechanism | Python stdlib `ThreadingHTTPServer`, no new dependency | The surface is six endpoints on localhost for one player. A framework is one ruling away if the multi-player stage wants it. The endpoint handlers stay thin regardless (R9). |
| D2 | Store root | `store/` at the repository top level, gitignored, with a README naming it permanent | Not below `data/` — that root is documented as rebuildable cache, and raw submissions are the one thing that is not (Rule 4). |
| D3 | Close and reveal timing | Manual commands | A solo loop has no clock pressure, and `--date` covers catch-up days. Automation is a cron line in a stage after this one. |
| D4 | Canvas values | A square canvas rendered at 512 CSS pixels, coordinates normalized to the unit square, pointer sampling as the browser delivers it, line width 3 in the local preview | The server render is canonical (§8) — these values shape capture only. The preview and the canonical render can be different. |
| D5 | Solo shrinkage display inputs | `population_mean` 0.0, `population_spread` 0.15 | The §27 worked example's value. Display-only (R7). A fitted population comes with live players. |
| D6 | Player identity | One configured player name in the server config, stored on each row | No auth on localhost. |
| D7 | Day secret | 256 random bits from the system generator, hex in `day.json` | §22 names the mechanism, not the width. |
| D8 | The date of a day | The owner machine's local date at open, ISO `YYYY-MM-DD` | One machine, one player. Timezone rules can wait for live players. |

## 14a. Rulings (2026-08-12)

The owner ruled on the §14 decisions before implementation:

- **D1 is overridden: the server builds on FastAPI, with uvicorn as
  the runner** — two new dependencies. Tests go through
  `fastapi.testclient` on the httpx dependency the repository has, and
  the one uvicorn import sits in the `service.server` entry point.
- **D2 through D8 stand at their proposed defaults.**

The implementation surfaced two contract questions, each ruled by
the owner on 2026-08-12:

- **The weighted-channel cut.** `score_trial` raised for an active
  channel with no configured weight, thus a relation-bearing
  submission could not score with a placement-free config. The
  ruling: an active channel with no configured weight is cut — the
  fusion denominator renormalizes without it (architecture §12.3),
  the rule lives in the shared `standardized_channels` helper, and a
  weighted channel with a missing commonness table raises as before.
- **The no-scoreable-atom refusal.** A record can clear each Layer 0
  gate and read into no weighted channel — stored, it can not score,
  and the one-write rule (R2) can wedge the day. The ruling: the
  submission endpoint adds one pre-store refusal (400, cause
  `no-scoreable-atom`) computed from the assembled atoms and the
  configured weights — no encoder, nothing target-dependent — and
  the page disables its send action in the same condition. This is
  the one sanctioned extension of R1's Layer-0-alone rule.

Resolutions the implementation pinned, recorded here as rulings:

- **The scoring config is `configs/scoring/dev-wit-mixed.json`.**
  Players send arbitrary mixtures (Rule 5), thus the commonness
  background must be the mixed mode, with the element table and the
  outline table stored together. The one-time build before the first
  live open, named by the R5 refusal:
  `uv run python -m validation.v2 --config
  configs/scoring/dev-wit-mixed.json` — a warm run at near zero
  posts.
- **The evidence value is the lower chi-squared tail**,
  `1 - exp(-S) * sum_{k<n} S^k / k!` — small values are the
  evidence direction (§17), and the architecture §27 example
  (2S = 10.96 at 24 degrees of freedom gives 0.011) pins it in the
  tests.
- **The unbiased skill number requires n >= 2** — `(n - 1) / S` at
  n = 1 is 0, not an estimate. The history page uses the biased
  variant at n = 1 and says so.
- **The server config** is one strict five-field document
  (`configs/service/dev-wit.json`): player, scoring config, data
  root, store root, port. The player name is pinned to a
  file-name-safe shape.
- **`/api/day` holds** `submitted`, `relation_vocabulary`,
  `player`, and `canvas_px` with the §9 fields — values with no
  target dependence, which the one static page needs.
- **The served day is the latest stored day** by ISO date. An empty
  store answers each surface with one constant body.
- **The commitment string** is SHA-256 of `"{target_id}:{secret}"`,
  and the reveal prints the check command.
- **The trial row quantizes** its measured values (the trial score
  and the report columns) through the repository `quantize_measured`
  rule, thus the R8 byte equality reads on stable digits.

## 14b. Amendments (2026-08-12, owner-requested)

Three changes after the first build, ruled by the owner:

- **The trial code.** Each day gets a player-facing identifier for
  the hidden target: six random characters, A-Z and 0-9, made at
  open with no derivation from the image (§22). It sits front and
  center on the page and in the open and status command output, and
  `/api/day` serves it in each day status. The §5 trial identifier
  of a submission stays as bookkeeping - the code names the target,
  the identifier names the submission.
- **Dev mode.** `service.server --dev` adds the owner's scoring
  surfaces, on the development pool alone: `/api/dev` names the
  day's target, `/api/dev/score` scores a draft record when asked
  and answers with the trial numbers plus the full fused ordering
  of the pool with the target marked, and `/image/*` serves each
  stored pool image. A dev score stores nothing and moves no day
  status - the one-write submission stays the one committed play,
  thus the owner iterates freely against the lockout. Without the
  flag each dev path answers one constant 404, and the R3 tests
  hold as written. The dev panel also shows the §6 run sequence
  for a live day.
- **The page is a development surface.** The intake page is the
  working interface of this stage, not the production one - a
  production interface is a stage of its own, and nothing in the
  wire contract binds to this page's shape.

### More rulings (2026-08-12, after the first live day)

- **The day lifecycle runs from the page.** Three endpoints - open,
  close, reveal below `/api/day/` - run the same functions the
  commands use, with the same out-of-sequence refusals (409) and
  the close answer naming the row count and no score (R3). The page
  shows buttons that follow the day status. Close from the page is the one live
  step, thus the server process needs the provider key in its
  environment for a live config. The controls sit on the page in
  each mode - a solo localhost server is the owner's own terminal -
  and the production interface makes its own ruling here.
- **The migrate command.** The trial-code field landed after the
  owner's first live day, thus a stored day record without it
  refuses to read. `service.day migrate` backfills one new random
  code into each legacy day record, atomically, touching no play
  data, and is repeatable. The strict reader names the command in
  its refusal: the reader refuses loudly, and the migrate command
  moves the store forward one time.

### The single test page (2026-08-12, third ruling)

Development work happens on one page: `GET /dev`, served in dev
mode alone (one constant 404 without the flag). It holds the trial
code, the day controls, the target image behind a show-and-hide
control - hidden at first, thus a blind run works from this page
too - the intake surface, the draft scorer, and the leaderboard:
after close or reveal, `GET /api/dev/rankings` scores the stored
submission through the production path and the page shows the top
matches across the full pool with the target row marked, plus a
show-all control for the full ordering. `/api/dev` answers status
`none` before a day exists, thus the open control works from an
empty store. The player page at `/` carries none of the dev
chrome, and the day-control markup sits in the dev panel alone.

### Two pages (2026-08-12, fourth ruling)

The two surfaces divide in full. The player page is the player's
alone: the trial code, the intake, the submitted view, and a
reveal view with the score and the report and no target image -
the images stay on the console. `GET /dev` is the operator console,
in dev mode alone: the day controls, the target behind its toggle,
the player's stored submission rendered read-only (the sketch as
an SVG, the impressions, the groups, the relations, the paste),
and the scoring view - `/api/dev/rankings` scores the stored
submission through the production path at each status, a preview
before close and the trial row's numbers after. The console has no
sketch input and no send. The open control rolls to the next free
date - today, or the day after the latest stored day - with one
active day at a time, thus test days run back to back. The draft
scorer of the third ruling is out: play comes in from the player
page alone.

### Console diagnostics (2026-08-12, fifth ruling)

The console answers *why* a position, not the fused sequence
alone. Each `/api/dev/rankings` row carries the standardized score
of each active weighted channel adjacent to the fused number, the
answer carries the atom-by-atom report (the trial-row shape), and
the page shows the two. A day browser reads each stored day:
`GET /api/dev/days` lists them newest first with status, trial
code, target, and commitment, and `?day=` on the submission and
rankings surfaces selects one. The day controls move the latest
day alone. An earlier day scores with the config the latest day
names - with a drifted config the browser's numbers are different
from the stored trial row, and the stored row stays the record.
These surfaces are dev mode alone and gate to the same constant
404.

## 15. Acceptance criteria

1. `core/aggregate.py` lands with the §8 property tests, and the
   finite-sum chi-squared tail agrees with a reference value table
   in the tests.
2. One full day runs end to end on fake providers in the integration
   suite: open → send → refused second send → close → reveal →
   history, with the R3 assertions green in each status.
3. The rescore invariant holds on a stored fixture day, and the
   different-config path writes new rows without touching the stored
   ones.
4. The intake page assembles the same wire record the harnesses
   validate, from a scripted interaction (the §11 fixture), and
   Layer 0 rejections surface with the gate named.
5. The §10 checklist rows each map to a passing test.
6. `uv run pytest` stays green offline. Vale reports zero errors on
   the new documentation and docstrings.
7. The owner opens a live day against the dev pool, sketches, closes
   with the key set, and the reveal shows the trial score and the
   atom-by-atom report. The spend for that close is the new
   drawing's embedding items alone.
8. No §14 decision is implemented against a different value without
   a recorded ruling.
