# Spec F1 — the weight fit and freeze on dev-wit-002

**Status:** ruled, prepared to build and run.
**Phase:** the Phase 4 close (`docs/ARCHITECTURE.md` §25). The
method is spec P4 (`fuse-and-validate.md`) and stays there — this
spec plans the live close of that method on the dev-wit-002
lineage, with the rulings of 2026-08-13.
**Architecture sections:** §14 (fusion), §19 (fitting), §23
(validation), §25 (phases).
**Working agreement:** `CLAUDE.md` §2 (I6 above all), §7, §10, §11.
**Input:** release `dev-wit-002-9644fac1` (204 images), preparation
record `dev-wit-prep-photo-inst-2-40f06be1` (rgb render), the four
gate verdicts of 2026-08-13 (V1, V2 sketch, V2 mixed, V2c — each a
recorded `pass`), and the provisional weight table
`{outline: 1.0, element: 1.0}` with `fit_record: null`.

---

## 1. Purpose

Each Phase 4 code path — `validation/generalize.py`,
`validation/fit.py`, the V3 through V6 harnesses — is built, merged,
and tested offline, and none has run live: `validation/records/`
holds no fit record and no V3 through V6 record. The trial server
scores with provisional equal weights, and the placement channel has
no weight at all — a relation is stored and scores as nothing.

This phase runs the fit on data where correspondence exists by
construction, freezes the winner into committed configs, gates the
result with V3 through V6, and moves the live server onto the frozen
weights. It is configuration and runs, not new machinery: three new
config files, two small repairs, the owner's commands, the owner's
verdicts, and one committed freeze edit.

## 2. The rulings of 2026-08-13

1. **Adoption timing.** The freeze happens on the fit verdict, and
   the live server moves to the frozen config only after V3 also
   clears — V3 is the gate `CLAUDE.md` §7 pairs with V2 for anything
   a player faces. V4 through V6 verdicts follow without blocking
   play.
2. **The placement question has a standing answer.** If the fit
   finds no placement signal — an endpoint winner
   (`freeze_blocked: true`) or a V4 ablation cost below the 0.01
   line — the ruling is: cut the channel for this lineage. Placement
   stays unweighted, relations keep being stored (they cost nothing
   and supply a future fit), and the question reopens at the
   production pool. The runbook does not stop to renegotiate.
3. **This spec closes with a roadmap** (§7) sequencing the phases
   that follow, each with its gate.

## 3. Build items

- **B1 — `configs/fit/dev-wit-2.json`.** A copy of
  `configs/fit/dev-wit.json` with `"tag": "dev-wit-2"` and nothing
  else changed. The fit-record filename and the V3 through V6
  harness hashes key on the fit config hash, thus the tag change
  keeps 001-lineage and 002-lineage records apart by name. The
  generator identity forks on its own — its hash covers the
  vocabulary digest, and the 002 vocabulary is its own.
- **B2 — `configs/scoring/dev-wit-b-2.json`.** The source-B scoring
  config of this lineage: `dev-wit-mixed-2.json` plus
  `commonness.synthetic = {fit_config: "configs/fit/dev-wit-2.json",
  count: 500, seed: 20260813}`, the tag `dev-wit-b-2`, and the
  candidate weight table `{outline: 1.0, element: 1.0,
  placement: 1.0}`. The placement entry is the P4 §17a item 4 rule:
  a harness config holds the full candidate set while the placement
  build is alive — the committed `dev-wit-b.json` misses it, and a
  relation-bearing synthetic trial stops fusion there. Submission
  mode stays `mixed`: the fit scores its source-1 pairs as mixed
  submissions by P4 decision D5, and the commonness background must
  match.
- **B3 — small repairs.** The `validation/v6.py` module docstring
  names a 225-image dev pool — reword to the pool the config names.
  Scan the V3 through V5 headers for the same stale count.
- **B4 — the freeze edit (after the fit verdict).** New files, with
  the earlier configs untouched — stored days rescore against their
  pinned configs forever:
  - `configs/scoring/dev-wit-mixed-3.json` = `dev-wit-mixed-2.json`
    plus the winning weight table and
    `fusion.fit_record = "validation/records/fit-dev-wit-2-<hash8>.json"`,
    tag `dev-wit-mixed-3`.
  - `configs/scoring/dev-wit-photo-inst-sym-3.json` = the sym gate
    config with the same two fields, tag `dev-wit-sym-3`, for the
    frozen V1/V2 reruns.
  - `configs/service/dev-wit.json` moves to the mixed-3 config —
    only after V3 clears (ruling 1).
- **B5 — the placement-cut record (conditional).** If ruling 2
  fires, the cut is recorded in the fit record's notes field with
  the date, and the mixed-3/sym-3 weight tables hold no placement
  entry. `pipeline/config.py` rejects a zero weight deliberately — a
  cut channel is out of the table, not at zero.

## 4. The owner runbook

The owner runs each command with the key in the environment. The
counts below are computed from the artifacts on disk, not guessed.

1. **The generalization table.**
   `uv run python -m validation.generalize --config
   configs/fit/dev-wit-2.json --scoring-config
   configs/scoring/dev-wit-b-2.json`
   The output line is `table entries=1379` — the 002 vocabulary
   count. Of the
   1379 entries, 676 are warm in the generalizer response cache
   from the 001 build and about 703 are cold posts. The table lands
   at `data/generalization/a08b8df4/862fe2ad/`.
2. **The fit.**
   `uv run python -m validation.fit --config
   configs/fit/dev-wit-2.json --scoring-config
   configs/scoring/dev-wit-b-2.json --report`
   The spend, one time: about 450 cold describer posts and about 45
   batched crop-embedding posts (the 450 fit and holdout
   photographs of the source-1 split — the 002 V1 run warmed the
   first 200 gate photographs alone), the text encodes of the new
   generalized phrases (about 24 batched posts), and the synthetic
   renders (about 13 batched posts). The source-B commonness
   background builds its own table directory.
   The record lands at
   `validation/records/fit-dev-wit-2-<hash8>.json` with the curve,
   the winner, the holdout objective, `placement_signal`,
   `placement_alive`, `endpoint`, and `freeze_blocked`. The verdict
   is the owner's. `freeze_blocked: true` fires ruling 2.
3. **The freeze** — build item B4, a committed edit on the verdict.
4. **V3 — response to quality.**
   `uv run python -m validation.v3 --config
   configs/fit/dev-wit-2.json --scoring-config
   configs/scoring/dev-wit-b-2.json --report`
   1000 trials (five degradation levels, 200 each), warm after the
   fit. The gate: mean trial score monotone across levels, and the
   level-4 bootstrap interval covers 0.5. On the owner's verdict,
   the server moves to mixed-3 (ruling 1) and the next open day
   scores with frozen weights.
5. **V4 through V6.**
   Same command shape with `validation.v4`, `validation.v5`,
   `validation.v6`. V4 refits with one channel out at a time — warm
   after the fit — and its `cost` against the 0.01 line is the
   placement evidence of ruling 2. V5 checks commonness health across
   the full background plus 500 no-information trials. V6 measures
   tier recall at the reduced dev widths — the production line
   waits for the production pool. Each writes a record with verdict
   fields.
6. **Frozen reruns.** V1 and V2 on
   `configs/scoring/dev-wit-photo-inst-sym-3.json`, and V2 on
   mixed-3 (it builds the mixed-3 commonness tables for the server
   as a side effect). Near-zero posts follow — the weight table
   moves no encoder input. A text-mode V1 on a text-3 config is
   optional and waits until the text mode matters for an adoption
   decision.

Estimated total spend for the phase: about 1,250 posts, with the
generalizer (~703) and the describer (~450) as the two large
items. Dev numbers at each step — nothing is published (R13).

## 5. Rules this phase holds

- **I6 shapes this phase.** The fit
  reads dataset pairs and synthetic submissions — correspondence by
  construction — and has no code path to a live trial. The import
  scan (`tests/unit/test_fit_isolation.py`) pins it. The stored
  live days stay out of the full fit path.
- **Verdicts are the owner's.** Each record ships `verdict:
  pending`. The agent recommends with numbers and edits the record
  on the owner's word.
- **The freeze is provenance, not a fork.** `fusion.fit_record`
  stays out of the scoring config hash (P4 review ruling 8) — the
  weight values move the hash, the label does not.
- **Earlier configs are permanent.** The -2 and earlier scoring
  configs stay byte-for-byte as committed. Adoption lands in a new
  file, and `configs/service/dev-wit.json` moves its pointer.
- The color rulings hold with no interaction: the fit sources emit
  colorless strokes, which render byte-for-byte the monochrome
  canonical PNG on the rgb lineage — the caches stay warm and the
  fit sees the same bytes a mono lineage gives.

## 6. Acceptance criteria

1. B1 through B3 land with the full test suite green offline and
   Vale at zero errors on changed prose.
2. The generalize run reports `table entries=1379` and the fit run
   completes with a committed record naming the 002 lineage hashes.
3. The freeze edit moves stored artifact keys through the weight
   values alone, and `fusion_weights_fitted: true` shows in each
   harness record after it.
4. V3 through V6 records are on disk with the owner's verdicts.
   The server runs mixed-3 only after V3 clears.
5. The frozen V1/V2 reruns reproduce the gate quality of 2026-08-13
   to noise level, with `fusion_weights_fitted: true`.
6. If ruling 2 fired, the cut is recorded and the frozen weight
   tables hold no placement entry.

## 7. The roadmap after this phase

Each row names its gate. The sequence is the architecture's §25.

- **Production pool.** Curation at production scale with the
  working encoder and the 512 canonical input rule, a new release,
  a new preparation, and a full re-measure: V1, V2, a new fit, and
  new frozen weights on that pool. Gate: this phase closed. Public
  numbers come only after this row (R13).
- **Phase 5 — the fast path.** Tiering residency, batching, the
  50 ms budget, practice mode, and the production V6 thresholds
  (shortlist widths 500/25, the 90% recall line). Gate: the
  production pool. The tier interface is built in
  `core/channels/element.py` — this is optimization, not rewrite.
- **Phase 6 — Layer 7 deferred rerank.** The VLM judge above the
  head of the ranking, plus source-3 fitting validated against
  source 2 first. Gate: quality evidence that the head is worth
  the spend, after Phase 5.
- **Multi-player and the leaderboard.** The store and the trial
  rows hold a player identity from the first row, and
  `core/aggregate.py` ships the
  many-player rate adjustment. The build is accounts, a player
  registry, the leaderboard surface, and the §22 hardening the
  solo build deferred. Gate: V2 and V3 clear together
  (`CLAUDE.md` §7) — this phase's V3 verdict is the second half of
  that gate.
- **Frontloading and the tag vocabulary** (architecture §20).
  Gate: after Layer 7 — the tag set rides the same judge
  infrastructure.
