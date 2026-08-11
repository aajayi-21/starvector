# Spec P4 — fuse and validate

**Status:** draft, for review.
**Phase:** 4 — fuse and validate (`docs/ARCHITECTURE.md` §25).
**Architecture sections:** §6 (the submission, RELATION atoms), §12.3
(the placement channel), §13.2 (commonness sources), §19 (fitting
without human judges), §23 (V3 through V6), §20 (frontloading, a
consumer of tag work this phase does not do).
**Working agreement:** `CLAUDE.md` §2 (I6 above all), §5, §6, §7.
**Input:** the merged Phase 3 build on `main` (22d3190), preparation
`dev-wit-prep-002-f24e0b9e`, five gate records with a `pass` verdict
(V1 sketch, V1 text, V1 mixed, V2 sketch, V2 text) plus the V2 mixed
record with its conditional-row measurement, and the p07 box
artifacts on disk — 3,598 box entries across the 225 images, 150
null, 18.2% near-full-frame, keys aligned with each
image's capped element list (checked 2026-08-10).

This spec is written for implementation by an AI agent. Where a value
or a rule is not given by the architecture, §17 says so and proposes
a default. Do not implement an open decision without agreement.

---

## 1. Purpose

Phase 3 left the system with two proven channels and one deliberate
hole: the fusion weights are equal and unfitted, thus each mixed-mode
number is diagnostic, not calibrated. This phase closes that hole in
the one permitted manner — fit on data where correspondence is known
to be there **by construction**, freeze the result, and prove the
frozen configuration with the V3 through V6 harnesses (§19, §23).

The phase also builds the two instruments the fit uses and the
system lacks. The **synthetic submission generator** (§13.2 source B,
§19 source 2) makes labeled submissions at controlled quality from
the pool itself. The **placement channel** (§12.3) reads RELATION
atoms against the p07 boxes and is the one channel the architecture
marks optional. The generator also builds a new commonness background
from source B, which holds the standing measurement of the Phase 3
records: the image-level commonness slope (+0.4722 outline, +0.2053
element) must shrink.

**The trap this phase must not fall into** (§19, I6): do not fit on
live player trials with the target as the label. There are no live
players so far, and the discipline is built at the point where that
is easy.

## 2. Scope

**In scope**

- The synthetic submission generator: seeded, versioned, pure — pool
  image in, wire-shape submission out, at a written degradation
  level. Text atoms from the element list, RELATION atoms from the
  p07 box geometry.
- The generalization table: one broader phrase for each vocabulary
  entry, built one time, stored as a keyed artifact (I4).
- The placement channel as a **gated build**: pure functions behind
  the fixed channel contract, the p07 loading, and a written cut
  criterion. If the criterion fails, the channel is cut and the
  RELATION atom type stays (§12.3).
- Weight fitting by a grid across labeled pairs, a committed fit
  record, and frozen weights in the scoring configs (§19).
- Harnesses V3 (monotone quality response), V4 (channel ablation),
  V5 (commonness concentration), V6 (tier recall), each with records
  and human verdicts.
- The source B commonness build, with the slope acceptance criterion
  from the Phase 3 records.
- Two hygiene items ruled in on 2026-08-10: `commonness_config_hash`
  gains the intake section, and the harness trial loops warm their
  caption encodes in one batched step before the loop.

**Out of scope**

- Source 3 fitting (a VLM as judge): it belongs with Layer 7 and
  arrives in Phase 6, validated against source 2 first (§19).
- Frontloading and the tag vocabulary (§20), Layer 7, Layer 9, the
  leaderboard, and each server surface.
- The 50 ms budget and residency (Phase 5). V6 runs the tier
  interface. Its production thresholds wait for the production pool.
- The next pool release (curation on the production encoder, the
  drawing-space check,
  the near-duplicate percolation risk) — a standing item with its own
  path, not this build.

## 3. Terms this spec adds

| Term | Meaning |
|---|---|
| **Synthetic submission** | A wire-shape submission the generator builds from one pool image's element list and boxes, with the source image kept as the label. |
| **Degradation level** | The written value that controls how much of the source image survives into the synthetic submission. Level 0 is strongest, the top level is pure noise. |
| **Generalization table** | One broader phrase for each vocabulary entry ("brass sextant" to "metal instrument"), a keyed artifact the generator reads. |
| **Labeled pair** | One (submission, known target) pairing where correspondence is there by construction — a dataset pair (source 1) or a synthetic submission (source 2). |
| **Fit split / holdout split** | Disjoint labeled-pair sets. The grid reads the fit split alone, and each reported quality number comes from the holdout split alone. |
| **Fit record** | The committed record of one grid: data identity, the full curve, the winner, and the holdout value. The provenance each frozen weight table points at. |
| **Cut criterion** | The written test that decides if the placement channel ships or is cut (§12.3). |

## 4. Requirements from the architecture

- **R1** — Fit only on labeled pairs. The fit code path must have no
  path to a live trial: no import from a module that stores or
  serves player submissions, enforced by a scan test in the style of
  the target scan (I6, §19).
- **R2** — With two or three channels, a grid, no optimizer. Weights
  are scale-invariant, thus K channels give K−1 free numbers (§19).
  Record the full curve. A flat curve is a cut signal for a channel,
  and a sharp peak is information.
- **R3** — Freeze before scoring. The winning weights go into the
  committed scoring configs with `fusion_weights_fitted` set and the
  fit record named. Harness records after the freeze hold the same.
- **R4** — V3 is the gate: mean trial score across degradation
  levels, on holdout synthetic submissions, **must be monotone**.
  §25: no public leaderboard before V2 and V3 clear together.
- **R5** — V4 removes one channel at a time, fits the remaining
  weights again on the fit split, and reports the holdout change. A
  channel with no measurable cost on removal is cut (§23).
- **R6** — V5 counts top-ten appearances for each pool image across
  the background set. A heavy tail means the correction
  is too weak (§23). This phase pairs V5 with the source B build
  and the slope measurement from the Phase 3 records.
- **R7** — V6 measures tier recall on labeled synthetic submissions:
  the fraction of known targets in the tier-1 shortlist and the
  tier-2 head (§23). The dev pool has 225 images, thus the production
  values (500 / 25) are trivial here. V6 runs at reduced shortlist
  widths and the production line stays a Phase 5 number.
- **R8** — The placement channel fires only when the two named atoms
  are located (§12.3): a stroke group with canvas positions, or a
  text atom with a best-matching element in the image that has a
  usable box. A relation between unlocated atoms scores nothing.
- **R9** — `soft_check` is near 1 when the relation clearly holds,
  near 0 when it clearly does not, smooth in between (§12.3). No
  hard boolean enters a score (I2).
- **R10** — The placement channel obeys the fixed contract: one
  number for each pool image, no target upstream of Layer 8, no
  modality branch (I1, I5). A missing channel is handled by the
  fusion denominator, as always.
- **R11** — Each new derived artifact is a cache with the config
  hash of what made it in its key (I4): the generalization table, the
  synthetic-submission sets, the fit record inputs, the p07 loading.
- **R12** — The generator is deterministic with its seed and its
  version string. Two runs with one seed give equal bytes. Seeds are
  logged with each artifact and record (§21).

### User constraints

- **U1 — `POST` accounting** (continued). Each OpenRouter-backed step
  reports posts and cache hits. §14 estimates the phase: about 2,100
  cold with the model-built generalization table, about 600 without
  it.
- **U2 — OpenRouter first, warm caches used again everywhere.** The
  fit split's photographs go through the same p01 describer path V1
  built. Each vocabulary string is in the text-encode cache.

## 5. Overview

```
              INSTRUMENTS (this build)
              ══════════════════════════
  generalization table   one phrase for each vocabulary entry (D2)
  generator              pool image -> synthetic submission at level L (D1)
                         text atoms + RELATION atoms (D3)
  placement channel      RELATION atoms vs p07 boxes (D4) — gated

              FIT (§19)
              ═════════
  labeled pairs          source 1: dataset pairs (fit/holdout splits, D5)
                         source 2: synthetic submissions (levels, seeds)
  weight grid            21 points for two channels, 231 on the
                         simplex if placement survives (D6)
  freeze                 fit record committed, configs updated (D7)

              VALIDATE (§23)
              ══════════════
  V3  monotone quality response on holdout synthetics      — gate
  V4  ablation: fit again without each channel, report deltas
  V5  top-ten concentration + the source B slope numbers
  V6  tier recall at dev shortlist widths
  V1/V2 runs again with the frozen weights                 — gate
```

## 6. Identity and versioning

- The generator has a version string and a config hash that covers
  its parameters, the vocabulary digest, and the generalization-table
  hash. Synthetic-submission sets are cached at that hash plus the
  seed (R11, R12).
- The generalization table is keyed by the vocabulary digest and the
  slot config hash that built it. A vocabulary change forks it.
- A change to `fusion.weights` forks `scoring_config_hash`, thus the
  frozen-weight gate runs get new artifact lineages — intended.
- The hygiene change to `commonness_config_hash` (intake section in
  the document) forks the commonness lineage one time. The tables
  build again from warm caches.

## 7. Input — the p07 artifacts

The context loader extends its verified set with one inventory key:

| Artifact | Shape and rule |
|---|---|
| `p07-boxes/boxes.jsonl` | one row for each image: `image_id`, `boxes` mapping each capped element string to `[x_min, y_min, x_max, y_max]` in the unit square, or null when the detector declined |

Digest checks as in P2 §7. `PoolIndex` gains the box side, aligned
with the incidence table: for each image position and element slot,
one box or a none marker. `build_pool_index` checks: keys equal the
image's capped element list, coordinates in [0, 1], min at or below
max on the two axes. Dev measurements (2026-08-10): 3,598 entries,
150 null (4.2%), 656 near-full-frame at area 0.95 or more (18.2% —
ambience and scale entries, "quiet" and "large" for example), median
area 0.411.

The union index side: V1-style runs with placement active must
have boxes for inserted photographs. That takes the p07 detector slot on
~200 photographs (~200 cold posts, one time, cached) through the same
capability path the pool used (Rule 3). Only the placement gate run
takes that cost. Text and mixed runs do not.

## 8. The synthetic submission generator (D1, D2, D3)

Pure functions in `validation/generator.py`. The RNG comes in as an
argument, seeded by the caller — no ambient randomness (`CLAUDE.md`
§3).

### 8.1 Shape (D1)

For one pool image at level L, the generator:

1. samples `n_atoms(L)` entries from the image's capped
   element list, without replacement.
2. generalizes each sampled element with probability
   `generalize_p(L)`, through the table (§8.2).
3. adds `n_noise(L)` elements sampled from the element lists of
   other images — player noise (§13.2).
4. emits the result as the frozen wire shape, each atom one row of
   the `impressions` field, thus Layer 0 and Layer 1 run unchanged
   (R10 of spec P3 applies — no new parsing).
5. at levels that include relations, adds RELATION rows (§8.3).

Proposed level table (D1):

| Level | n_atoms | generalize_p | n_noise | relations |
|---|---|---|---|---|
| 0 | 7 | 0.0 | 0 | 2 |
| 1 | 5 | 0.3 | 1 | 1 |
| 2 | 4 | 0.6 | 2 | 1 |
| 3 | 2 | 0.8 | 3 | 0 |
| 4 | 0 | — | 5 | 0 |

Level 4 is the no-information control: V3's curve must land near 0.5
there, which ties V3 to V2's claim.

### 8.2 The generalization table (D2)

One broader phrase for each of the 1,527 vocabulary entries, built
one time by a chat-slot post in the p01 style (the instruction
`"give one broader, less specific phrase for this element"`) and
stored at
`data/generalization/<vocab_digest[:8]>/<slot_hash[:8]>/table.jsonl`
with a meta file (R11). The generator reads the table. It makes no
model post itself. Answers go through the p02 normalization rules
before storage, thus the generalized strings live in the same string
space as the atoms.

The alternative — a pure head-noun rule ("brass sextant" to
"sextant") — is free and offline but produces narrower degradation.
D2 decides.

### 8.3 Synthetic relations (D3)

At levels with relations, sample two located elements of the source
image (boxes there, area below the cap of D4), get their correct
relation from the box geometry with the written rule of §9, and emit
a RELATION row naming the two atoms. At a level with
`corrupt_relation` in its row — level 2 in the committed table — one of the two
named atoms is a noise atom: a stated relation about something not
there, which is what a weak player produces. The flag is config
(amended 2026-08-10): the first build inferred corruption from the
noise count, which corrupted level 1 too and halved the honest
levels behind the D8 signal.

Two geometry rules are part of the `synthetic-v1` rule itself, not
config (ruling 2026-08-10): the noise box comes from the
submission's RNG with its corner in [0, 0.7] and its side in
[0.1, 0.3], each with equal probability across the interval — a
change is a new rule version, not a knob. And a candidate pair with
equal box centers emits no relation: the axis rule has no honest
label there, and a coin-flip label can only pull the D8 signal
down.

This gives the placement channel labeled data with a known answer,
and it is the only labeled source that produces RELATION atoms at
all.

## 9. The placement channel — a gated build (D4)

Pure functions in `core/channels/placement.py`, behind the fixed
contract (R10). The architecture marks this channel optional and
prescribes the exit: "If it proves fiddly, cut it and keep the
`RELATION` atom type" (§12.3).

### 9.1 Construction

- **Relation vocabulary** (D4): `left-of`, `right-of`, `above`,
  `below`. Layer 0 carries relation strings through the text gate
  unchanged. Scoring reads only these four, and a RELATION atom with
  a different string contributes nothing in this phase. The
  vocabulary is config, not code.
- **Locating an atom in image x** (R8, amended 2026-08-10): a
  DESCRIPTION atom with a Layer 2 vector takes the box of its
  best-matching element in image x — the same argmax the element
  channel makes — when that box is there and its area is below
  `area_cap` (0.9). Near-full-frame boxes say nothing about
  placement, and 18.2% of dev boxes are of that type. When image x
  gives the matched slot no usable box, the atom has no location
  there and its relations add zero. A strokes-only atom — one with
  no vector — takes its stroke bounding box on the canvas, the same
  box in each image. The review refuted the former rule, which fell
  back to the canvas box on an image-dependent condition: an image
  with missing detector data then got the maximum for the stated
  relation, and the D8 signal read 0.63, not 0.75.
- **`soft_check`** (R9), rule `axis-ramp-v1`: for `left-of`, the
  signed center distance `cx_B − cx_A` maps through a linear ramp
  that is 0 at −`margin`, 0.5 at 0, and 1 at +`margin` (proposed
  margin 0.15), clamped to [0, 1]. The other three relations are the
  same rule on the mirrored or vertical axis.
- **The channel score** (amended 2026-08-10): the sum of `soft_check`
  across relations that fire in image x. A relation that does not
  fire adds zero — it does not abstain (§12.3). The first ruling
  divided by the count of stated relations and called the denominator
  cosmetic (Rule 2). The review refuted that: a submission-only
  multiplicative term is not neutral through `2·raw − commonness`,
  and stated relations with no rule moved 61 of 80 dev trial scores.
  With the sum they move nothing. A fraction for display is a report
  task after fusion.
- **Activation**: RELATION atoms are not encoded, thus the P3
  vector-driven activation rule extends: an atom activates its
  routed channels when it holds a Layer 2 vector, or when its type
  is RELATION. The routing table gains
  `"RELATION": ("placement",)` — one data change (I5).
- **Commonness**: one more channel table at the same key, built
  by the same task (P3 D11 generalizes with no new work).

### 9.2 The cut criterion (D8)

The build ships only if the two tests hold on holdout synthetic data:

1. **Signal**: placement-only trials at level 0–1 (relations from
   the box geometry) score a mean trial score at or above 0.65.
2. **Contribution**: V4 shows that removal of placement costs a
   minimum of 0.01 holdout mean trial score with weights fitted
   again.

If one fails: the channel is cut, the RELATION atom type and the p07
loading stay, the numbers go into a committed record, and the weight
grid drops to the two-channel line. The cut is a recorded ruling, not
a code deletion — the module stays behind its contract.

## 10. Fitting (D5, D6, D7)

### 10.1 Labeled pairs (D5)

- **Source 1 — dataset pairs.** New fit and holdout splits from the
  FS-COCO v1 split tail, selected by the D8 hash rule of spec P2 with
  a new salt, disjoint from the 200 recorded gate pairs. Proposed
  sizes: fit 300, holdout 150. Each split member is a mixed
  submission (sketch plus caption) against the union index — the only
  labeled source where the outline channel holds signal. Cold cost:
  ~450 describer posts plus ~45 batched crop-embedding posts, one
  time.
- **Source 2 — synthetic submissions.** Text and relation atoms
  against the plain pool index, at all levels, fit and holdout seeds
  disjoint. This is the primary source (§13.2) and the only one for
  placement.

### 10.2 The grid (D6)

Two channels: `alpha` across `linspace(0, 1, 21)`, weights
`{element: alpha, outline: 1 − alpha}`, objective = mean trial score
across the source 1 fit split (§19). Three channels, if placement
survives §9.2: the 0.05-step simplex, 231 points, objective = the
equal mix of the source 1 and source 2 fit means. The full curve or
surface is stored with the fit record. Flat regions and sharp peaks
are results, not noise (R2).

Two rules the review settled (2026-08-10): the objective basis is a
property of the grid, and not of the candidate — one basis across a
grid keeps each point and each V4 cost like-for-like. And a trial
with no channel the candidate reads counts 0.5 — with no information
the trial score falls at each point of [0, 1] with equal
probability, thus 0.5 is the one honest mean — and each curve row
records how many trials of each source the candidate read. The
former key-driven rules crashed the simplex on its pure-placement
vertex and subtracted two V4 objectives measured across different
trials.

### 10.3 Freeze (D7)

The fit writes a committed record
`validation/records/fit-<tag>-<hash>.json`: grid definition, data
identity (split salts, sizes, seeds, generator hash), the curve, the
winner, the holdout value, and verdict fields for the owner. On a
`pass` verdict, the scoring configs get the winning weights, and each
harness record after that holds `fusion_weights_fitted: true` with
the fit record's label. The weights then do not move until a new fit
record says so (R3).

## 11. Harnesses (D9, D10, D11)

Each harness follows the P2/P3 shape: a runner in `validation/`, an
artifact directory below `data/validation/<name>/`, a committed
record with verdict fields, numbers not adjectives.

- **V3 — monotone quality response** (R4, gate). Holdout synthetic
  submissions at each level, frozen weights. Report the mean trial
  score for each level with a bootstrap interval — the resample
  count and the interval level are fit config (`v3_bootstrap_count` and
  `v3_interval`, ruling 2026-08-10), and the verdict reads the
  quantized values the record shows. The gate clears when each
  adjacent pair of level means is in sequence and level 4 sits in
  the interval around 0.5. An inversion is a gate failure, not a
  note.
- **V4 — ablation** (R5). For each built channel: fit again on the
  fit split without it, report the holdout delta. The report feeds
  the placement cut criterion and stands as the record for a cut of
  a different channel in a phase after this one.
- **V5 — concentration** (R6, D9). Across the background set, count
  each pool image's top-ten appearances. Report the histogram, the
  count of images above three times the equal-share expectation, and
  the image-level commonness slope of the Phase 3 records — before and
  after the source B build (§12). V5 has no hard line in the
  architecture. The record is the owner's read of the tail.
- **V6 — tier recall** (R7, D10). On labeled synthetic submissions
  at the fit config's `v6_levels` (the committed value reads levels
  {0, 1}, ruling 2026-08-10), the fraction of known targets in the
  tier-1 shortlist at widths {10, 25, 50} and in the tier-2 head at
  {5, 10}. Dev-only numbers. The 90% line applies to the production
  pool in Phase 5.
- **Runs again with frozen weights** (gate). V1 mixed and V2 mixed
  run again in the fitted configuration: V1 must not regress against
  the equal-weight record by more than noise, and V2 must agree with
  `Uniform(0, 1)`. A V2 failure here is a Rule 3 audit of the fit,
  not a tuning task.

## 12. The source B commonness build (D11)

A new commonness lineage with a background that is a stated mix of
source A (FS-COCO, as today) and source B (synthetic submissions from
the generator at mixed levels, labels discarded). Proposed mix: 500 +
500 (D11). §13.2 names source B the more important because it matches
the pool's vocabulary and element statistics.

**Acceptance criterion** (from the Phase 3 standing measurement): on
V2 runs against the new tables, the trial-level Spearman between the
target's commonness and p shrinks against the recorded values — below
+0.4722 for the outline channel and below +0.2053 for the element
channel — and the V2 marginal stays in agreement with
`Uniform(0, 1)`. The slope numbers go into the V5 record in each
outcome. If the slope does not shrink, that is a result about the
correction, not a tuning knob: record it and stop.

## 13. Hygiene items (ruled 2026-08-10)

1. **`commonness_config_hash` gains the intake section.** The gate
   pre-flight shapes the background set, thus the gates belong in the
   table key. One-time lineage fork. The tables build again from warm
   caches.
2. **Trial-loop pre-warm.** Before a harness trial loop, the runner
   encodes each selected trial record in one batched
   `encode_submissions` step and discards the result — the provider
   cache then serves the loop. This changes the post count alone. The
   Phase 3 gates spent 641 of 871 posts on this. A determinism note
   in the harness states that the pre-warm cannot change a score.

## 14. Artifacts, storage, cost

- `data/generalization/<vocab[:8]>/<slot[:8]>/{table.jsonl, meta.json}`
- Synthetic submission sets are **ephemeral by construction** (ruling
  2026-08-10 — the stored `data/synthetic/` artifact this section
  first named is withdrawn): a deterministic function of (generator hash,
  seed, count), regenerated at use and stored nowhere — a stored
  copy is a second source of truth that can drift. Each consuming
  record holds the three identity values.
- `data/validation/{v3,v4,v5,v6}/...` in the P2 layout. Fit records
  and harness records go in `validation/records/`.
- **Development `POST` estimate (U1):** generalization table ~1,527
  chat posts (one time, and zero if D2 picks the pure rule).
  Fit/holdout photographs ~450 describer + ~45 embedding posts.
  Synthetic atom encodes: sampled vocabulary strings are warm, and
  the ~1,527 generalized strings are cold at ~24 batched posts.
  Placement boxes for the union ~200 detector posts, only if the
  placement gate run happens. V-runs and the frozen-weight runs are
  warm. About **2,100 cold** with the model-built table, about **600
  cold** without it. Runs with unchanged config: zero.

## 15. Determinism and testing

Determinism: the generator with a fixed seed is byte-stable (R12).
The grid is a pure fold across cached trial scores. The placement
rules are closed formulas. Argmax equal values resolve to the lowest
index, as in P3.

**Unit tests** — the level table (atom and noise counts for each
level), generalization-table lookups and the p02-space rule, relation
truth from hand-built boxes, `axis-ramp-v1` on hand values (0, 0.5, 1
and the clamp), the located-atom rule with the area cap and the null
box, channel score with zero firing relations, activation with
RELATION atoms, the grid winner on a hand-built score table,
fit/holdout disjointness, and the monotone check itself.

**Invariant tests** — the fit-boundary scan (R1), placement output
length N, fusion across each subset that includes placement, the
routing table change, rescoring stored synthetic submissions
byte-for-byte, hash sensitivity for each new config field, and the
commonness-hash intake coverage (a gate change forks the key).

**Integration** — fake end-to-end: generator to V3 with a scripted
generalization table, a placement trial with scripted boxes through
the full path, a fake grid producing a fit record, and the pre-warm
step leaving each score unchanged byte-for-byte.

Development gate runs (not CI): the fit, V3, V4, V5, V6, the
frozen-weight V1/V2 runs, and the source B slope numbers — each
recorded with verdicts (R4, §11).

## 16. Repo readiness (checked 2026-08-10)

- `main` at 22d3190: 660 tests green offline, Vale 0 errors across
  the five specs, working tree clean.
- Gate records: five with a `pass` verdict. The V2 mixed verdict is
  filled on branch `record/v2-mixed-verdict` (PR #6) with the
  conditional-row measurement recorded.
- p07 boxes on disk and aligned with the capped element lists. The
  p01 describer, text-encode, and embedding caches are warm.
- Standing items that are not inputs to this phase: the next pool
  release (curation on the production encoder, the percolation risk)
  and the Phase 6 judge.

## 17. Decisions — ruled 2026-08-10

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | Generator level table | The §8.1 table: five levels, level 4 pure noise | The counts are unspecified by the architecture. The shape (sample, generalize, noise) is §13.2 verbatim. V3 reads the levels, thus the table is config, hashed. |
| D2 | Generalization rule | Model-built table through the chat slot, p02-normalized, stored as a keyed artifact | ~1,527 one-time posts. Alternative: a pure head-noun rule, free but narrower degradation. §13.2 permits the two. |
| D3 | Synthetic relations | From the p07 box geometry with the §9.1 axis rule. Corrupt at level 2 by naming one noise atom | The only labeled RELATION source. Build sequence: generator first, relations behind a flag, so a D8 cut wastes nothing. Amended 2026-08-10: corruption is the level-row flag `corrupt_relation` (§8.3, §17a). |
| D4 | Placement construction | Relation vocabulary of four. Located = stroke box, or best-match element box with area below 0.9. `soft_check` = `axis-ramp-v1`, margin 0.15. Score = firing sum across the stated count | §12.3 names the shape, not the numbers. The area cap answers the 18.2% near-full-frame boxes. All values config, hashed. Amended 2026-08-10: the score is the firing sum alone, and locating is vector-driven (§9.1, §17a). |
| D5 | Fit data | Source 1: fit 300 / holdout 150 mixed pairs from the v1-split tail, new salt, disjoint from the 200 gate pairs. Source 2: synthetic at all levels, disjoint seeds | ~500 one-time posts. A 200/100 split saves ~170 posts at wider intervals. |
| D6 | Grid | 21 points on the two-channel line. 231 on the 0.05 simplex if placement survives. The three-channel objective mixes source 1 and source 2 equally | §19 fixes the method. The mix weight for the three-channel objective is the open part. Amended 2026-08-10: the basis is a property of the grid, and an unreadable trial counts 0.5 (§10.2, §17a). |
| D7 | Freeze mechanics | Committed fit record with verdict fields. Configs updated on a `pass` verdict. Records after that hold `fusion_weights_fitted: true` plus the fit label | R3. The fit record is reviewed like a harness record. |
| D8 | Placement cut criterion | Signal at or above 0.65 mean trial score on level 0–1 placement-only holdout, and V4 ablation cost at or above 0.01 | The two numbers are proposals with no architecture source — they make the "fiddly" test of §12.3 concrete. |
| D9 | V5 statistic | Histogram, count of images above 3× the equal-share expectation, and the image-level slope before and after the source B build | The architecture gives no line. The record is descriptive plus the D11 criterion. |
| D10 | V6 dev widths | Tier-1 {10, 25, 50}, tier-2 head {5, 10} | 225 images make the production 500/25 trivial. These widths run the stitching boundary the P3 tests pinned. |
| D11 | Source B mix | Background 500 source A + 500 source B. Acceptance = the two slopes shrink below the recorded values with the marginal in agreement with `Uniform(0, 1)` | §13.2 ("B is the more important one") plus the Phase 3 standing measurement. Full replacement of source A is the alternative. |
| D12 | Hygiene details | The hash gains the full intake section only, not the weight table — commonness is raw and weight-free. Pre-warm through one batched `encode_submissions` step | Weights in the key fork tables spuriously on each fit. Intake out of the key keeps the known hole. |

## 17a. What the build settled that the spec left open

The owner ruled D1 through D12 one by one on 2026-08-10, each at its
proposed default, plus one decision planning surfaced:

- **D13 — commonness on a heterogeneous background.** The Phase 3
  rule made a background that activates only some channels an error,
  which was correct for backgrounds with one mode only. The D11
  background is heterogeneous by construction — only the synthetic
  half holds RELATION atoms. Ruling: each channel's table is the
  **mean across the submissions that activate it**, the contributor
  counts go into the meta file, and a run stops before it spends
  anything if its trials read a channel with zero contributors. The
  P3 strict rule and its tests are amended.

The build settled these points the spec did not cover:

1. **Locating is image-first.** A text-bearing atom — one with a
   Layer 2 vector — locates through the box of its best-matching
   element in each image, and an image that gives that slot no
   usable box gives the atom no location. The stroke bounding box is
   the rule for atoms with no vector, not a fallback on an
   image-dependent condition (review ruling 2026-08-10). A relation
   between two canvas-located atoms scores the same value in each
   image, thus it moves no ranking (Rule 2), and a strokes-first
   rule made the full channel that: constant, and cut on an
   incorrect basis.
2. **Synthetic relations ride the frozen wire shape.** A relation
   emits two labeled rectangle groups drawn along the element boxes,
   plus the relations row naming them. The rectangle ink clears the
   Layer 0 gates, the element channel reads the groups' labels, the
   rectangle strokes make the WHOLE-DRAWING atom, and nothing in
   Layer 0 or Layer 1 changes (I5).
3. **The weight table carries its provenance.** `fusion.fit_record`
   names the committed fit record with these weights as its winner,
   null when unfitted. Harness records read `fusion_weights_fitted`
   from it — no more hardcoded `false`.
4. **A harness config carries the candidate weight set.** While the
   placement build is alive, the fit and the V3 through V6 runs must
   have a placement weight — relation-bearing synthetics activate the
   channel, and an active channel must have a weight and a table.
   After the fit, the frozen configs hold the winner.
5. **A grid endpoint cannot freeze.** The config rejects a zero
   weight and fusion rejects an active channel without one, thus an
   endpoint winner writes `freeze_blocked: true` into the fit record
   — the honest interpretation of a flat curve is a channel cut (§19), which
   is a ruling, not a weight.
6. **Union photographs hold no boxes.** The photographs' box masks
   stay `false` and no detector post is spent. The union commonness
   build does score placement across the synthetic background half,
   and with the amended locating rule a photograph with no boxes
   scores zero there — missing detector data reads as no agreement,
   not as the maximum. A placement-active union *trial* run in a
   phase after this one must first build photograph boxes through
   the p07 slot (Rule 3).
7. **The generator identity resolves through stored artifacts.** The
   commonness key covers `generator_config_hash` — the level table,
   the rule version, the vocabulary digest, and the stored table
   content — thus the table build is a deliberate step, and a
   background assembly refuses to build it as a side effect.
8. **The R1 scan pins imports, not names.** `validation/fit.py` and
   its dependencies must import only from an allowlist (datasets,
   generator, pipeline, standard library). No module that stores live
   player submissions exists in this build. The scan makes importing
   a future one a test failure and a review conversation. Amended
   2026-08-10: the scanned set is the import closure of the fit and
   V3 through V6 runners across `validation/`, pinned by a test —
   the first scan read six files and missed the runners' shared
   dependencies.

### Review rulings (2026-08-10)

An adversarial review of the committed build confirmed 13 findings.
Six were mechanical and the fixes follow written rules (the
generalizer parse defect, the R1 closure above, the fit-record
identity fields, a noise-sample stop, a referent check, the area cap
in the generator identity). Four amended ruled surfaces, each ruled
by the owner on 2026-08-10:

1. **The fit objective at an unreadable trial is 0.5.** A grid
   point that reads none of a trial's channels through its positive
   weights counts 0.5 for it, the basis (source 1 alone, or the
   equal mix) is a property of the grid and not of the candidate,
   and each curve row records its readable-trial counts (§10.2).
2. **The placement score is the sum of firing checks.** The
   stated-count denominator was not cosmetic (§9.1).
3. **Relation corruption is a level-row flag.** `corrupt_relation`
   in the D1 table, `false` at levels 0 and 1, `true` at level 2
   (§8.3).
4. **The commonness artifact covers each built channel the
   background activates.** The content is a pure function of the
   key (D12), and the scoring context selects the weighted subset —
   the caller's weight table cannot shape the stored bytes. This
   amends the "each weighted channel" wording of P3 D11.

The review's smaller findings closed with four more rulings, made
2026-08-10 with the same procedure:

5. **Synthetic sets are ephemeral by construction.** No
   `data/synthetic/` artifact — the sets regenerate from (generator
   hash, seed, count), and each consuming record holds those values
   (§14).
6. **The V3 bootstrap values and the V6 levels are fit config.**
   `v3_bootstrap_count`, `v3_interval`, and `v6_levels` are hashed
   fields, and the V3 verdict reads the quantized record values. The
   noise-box geometry stays in the `synthetic-v1` rule (§8.3, §11).
7. **The architecture's Rule 2 lemma gains its qualifier.** Additive
   submission-only adjustments are free — multiplicative ones before
   the commonness correction are not (`docs/ARCHITECTURE.md` §3,
   with the P4 measurement).
8. **`fusion.fit_record` stays out of `scoring_config_hash`.** The
   field is provenance: it names the weights' source and moves no
   score, thus a label correction after the freeze forks no
   artifact directory. The weights themselves stay in the key.

The guard code landed with these rulings: a union trial that activates
placement stops loudly (item 6 above, the p07 message), the fit and
the V3/V6 runs read the stored generalization table alone (item 7
above — the build stays a deliberate owner step), a hole in the
generalization table raises in the generator, and V5 stops on a
constant table before it spends the trial loops.

## 18. Code layout

```
core/
  channels/placement.py   # located-atom rule, axis-ramp-v1, channel — pure
  types.py                # routing table change; PoolIndex box side;
                          # PlacementConfig
pipeline/
  config.py               # placement section, generator reference,
                          # frozen weights, commonness-hash coverage
  context.py              # p07 loading + checks
  score.py                # placement arm; RELATION activation
validation/
  generator.py            # levels, sampling, relations — pure, seeded
  generalize.py           # table build job (chat slot) + loader
  fit.py                  # the grid, the fit record — the R1 scan applies
  v3.py  v4.py  v5.py  v6.py
  harness.py              # pre-warm step; shared fit/holdout splits
configs/scoring/*.json    # frozen weights after the fit (committed edit)
```

Import direction rules unchanged: `core/` sees protocols only, and
the fit code sees generators and datasets only (R1).

## 19. Acceptance criteria

1. `uv run pytest` completes with zero errors, offline, no GPU.
2. The §15 unit, invariant, and integration tests are written and
   green, the fit-boundary scan with them.
3. The generator reproduces byte-for-byte with a fixed seed, and
   each consuming record holds the generator hash, the seed, and the
   count (R11, R12 — the sets are ephemeral by construction,
   ruling 2026-08-10).
4. A committed fit record holds the full curve, and the frozen
   weights in the configs match its winner (R3).
5. V3 clears the monotone gate on holdout data with level 4 near
   0.5, and the frozen-weight V2 run agrees with `Uniform(0, 1)` —
   the two recorded.
6. V4, V5, V6 records hold their numbers. The placement channel is
   shipped with its criterion met, or cut with its numbers recorded
   (D8).
7. The source B slope numbers are recorded against the Phase 3
   values, in each direction they can move (D11).
8. Runs with unchanged config make zero new `POST` operations.
9. No open decision from §17 is implemented without recorded
   agreement. Documentation is Vale-clean at error level. Dev
   numbers stay unpublished (`CLAUDE.md` §7).
