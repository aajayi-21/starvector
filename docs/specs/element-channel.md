# Spec P3 — the element channel

**Status:** draft, for review.
**Phase:** 3 — the element channel (`docs/ARCHITECTURE.md` §25).
**Architecture sections:** §5 (pool preparation, as producer), §6 (the
submission and atom routing), §12.1 (the element channel), §13
(normalization), §14 (fusion), §18 (the tiered structure), §23
(validation).
**Working agreement:** `CLAUDE.md` §2 (invariants), §5, §6, §7.
**Input:** the merged Phase 2 build on `main`, preparation
`dev-wit-prep-002-f24e0b9e` — 225 images, a vocabulary of 1,527
entries at dimension 3,072, incidence 225 × 20, element lists capped
at 16 by the P1b D2 count contract — and the pinned FS-COCO dataset
with its caption files (`text/<user>/<id>.txt`, one sentence for
each pair, 10,000 files, checked on the extracted tree 2026-08-09).

This spec is written for implementation by an AI agent. Where a value
or a rule is not given by the architecture, §16 says so and proposes
a default. Do not implement an open decision without agreement.

---

## 1. Purpose

Phase 2 proved the outline channel: shape and composition. This build
adds the channel the architecture puts first (§25): the
**element channel** — *what things are in the image*, with a score
of rarity-weighted correspondence between the
submission's written atoms and each image's element list. It is the
only channel that can tell a player which of their impressions were
right, and it is the channel the architecture expects to hold
remote-viewing-style output — correct things in an incorrect
layout (§12).

The element channel activates the second term of the Layer 6 fusion
that Phase 2 built before it was necessary (P2 decision D5):
text-only submissions
become scorable, and mixed submissions engage the two channels with
no path change.

## 2. Scope

**In scope**

- Rarity weights for each atom, computed for each submission against
  the pool vocabulary (§12.1 step 1).
- The similarity table between atom vectors and element vectors, with
  the type rule (§12.1 step 2).
- Soft matching by Sinkhorn's algorithm, unbalanced — unmatched atoms
  and unmatched elements are permitted (§12.1 step 3).
- The channel score (§12.1 step 4), as `element_channel` behind the
  fixed `Channel` contract.
- The tier structure **as an interface** (§18): tier 1 approximate
  across the full pool, tier 2 accurate on a shortlist. The
  development build runs the full matching on the full pool
  (`CLAUDE.md` §7),
  and the interface keeps Phase 5 an optimization, not a rewrite.
- Text atoms through the existing `TextEncoder` slot at scoring time,
  driven by the routing table (no modality branch — I5).
- The element commonness table, and the commonness task generalized
  to one table for each built channel.
- Context loading of the p04 artifacts (vocabulary, vocabulary
  vectors, incidence, element-space mean), digest-checked like the
  outline artifacts.
- Harness extension: a submission mode (sketch, text, mixed) so V1
  and V2 run the element channel on FS-COCO captions, plus the union
  element side for V1 photographs.
- A minimal match report for each atom, recorded after ranking for V1
  trials — the seed of the §27 player feedback.
- `SketchPair` gains the caption, with the FS-COCO and fake adapters
  extended.

**Out of scope**

- The placement channel, the synthetic submission generator, and
  V3–V6 (Phase 4).
- **Fusion weight fitting.** The two-channel weight table stays
  unfitted (I6). Phase 4 fits on labeled data and freezes. Mixed-mode
  numbers in this phase are diagnostic, not calibrated.
- The 50 ms budget, batching, and residency (Phase 5). The tier
  interface exists here. Its performance targets do not.
- Layer 7, Layer 9, frontloading, each server surface, and the
  leaderboard.
- The sketch side of the element channel (α below 1.0, §6 of the
  architecture): the mixing knob exists in config, the sketch-vector
  path behind it does not run in this phase (D10).

## 3. Terms this spec adds

The glossary in `docs/ARCHITECTURE.md` §2 defines the scoring terms
(element, element list, vocabulary, rarity weight, similarity table,
match table, soft matching). This spec adds pipeline terms only.

| Term | Meaning |
|---|---|
| **Element bank** | One image's element vectors and strings, as a channel reads them. For pool images it is a view of the vocabulary through the incidence table. For union photographs the harness builds it (§12). |
| **Tier-2 set** | The images that get the full soft matching on one trial: the tier-1 shortlist, count `tier2_count`. |
| **Submission mode** | The harness rule for building the wire record from one sketch pair: `sketch`, `text`, or `mixed`. |
| **Match report** | One row for each atom, read from the match table of one (submission, image) pairing, after ranking. |

## 4. Requirements from the architecture

- **R1** — Rarity: `rarity(a) = −log(fraction of pool images with
  something the atom matches)`, natural logarithm, in nats, computed one
  time for each submission against the vocabulary — not for each
  image (§12.1). The worked example (§27) pins the shape:
  frequency 0.09 gives 2.4 nats.
- **R2** — The similarity table: `C[i][j] = similarity(vector(aᵢ),
  vector(bⱼ))` when the types are compatible, else minus infinity
  (§12.1). In this build the compatible atoms are DESCRIPTION atoms
  with text. RELATION atoms do not enter the element channel.
- **R3** — Soft matching by the standard iterative procedure:
  `K = exp(C/ε)`, about twenty alternating rescaling steps (§12.1).
  Matching is **unbalanced**: atoms and elements can go unmatched,
  and forced complete matching manufactures unwanted correspondence.
- **R4** — The channel score: `Σᵢⱼ Π[i][j] × C[i][j] × rarity(aᵢ)`
  (§12.1 step 4). No precision-style penalty enters the score — by
  Rule 2 it cannot change the ranking (§12.1 note).
- **R5** — The tiers (§18): tier 1 gathers each atom's best element
  for each image through the incidence table — one matrix
  multiplication plus an incidence lookup, no competition between
  atoms, optimistic on purpose. Tier 2 runs the full matching on
  the shortlist. The shortlist boundary must sit far from the region
  that decides the score.
- **R6** — The channel obeys the fixed contract (`CLAUDE.md` §5):
  one number for each pool image, no target anywhere upstream of
  Layer 8 (I1), no modality branch (I5), pure function of
  (encoded submission, pool index, channel config).
- **R7** — Vectors compare after the pool-mean subtraction (§10).
  p04 stored `element_space_mean.npy` for this.
- **R8** — Commonness correction and standardizing run for each
  channel alone, each with its own table (§13, R13 of spec P2).
- **R9** — Fusion stays the fixed formula. The active set for a
  text-bearing submission gains `element` through the routing table
  (§14, §6). **No weight is fitted in this phase** (I6).
- **R10** — Atom assembly does not change. Captions become atoms
  through the frozen paste rule (§6: split on newlines and commas) —
  the Layer 0/1 tier stays untouched.
- **R11** — Each derived artifact is a cache with the config hash of
  what made it in its key (I4). Rarity weights are derived for each
  submission and stored nowhere — they recompute from the vocabulary
  (P1b §2).
- **R12** — Validation results are reported with numbers and
  recorded with human verdicts (`CLAUDE.md` §9, §11).

### User constraints

- **U1 — `POST` accounting** (P1b U1 continued). Each
  OpenRouter-backed step reports posts and cache hits. §14 estimates
  the development counts (~300 cold).
- **U2 — OpenRouter first.** The `TextEncoder` slot for atom text is
  the existing embeddings path with `google/gemini-embedding-2` —
  the same model as the vocabulary vectors, thus atom and element
  vectors share one space. The V1 union element side uses the
  existing `VlmDescriber` slot (§12).

## 5. Overview

```
                     SCORING PATH (one submission)
                     ═════════════════════════════
  L0/L1  unchanged (frozen tier)
  L2     routing table drives encoding:
           WHOLE-DRAWING -> render -> SketchEncoder     (Phase 2)
           DESCRIPTION with text  -> TextEncoder        (this build)
  L4     outline channel                                (Phase 2)
         element channel                                (this build)
           rarity weights   — one pass against the vocabulary
           tier 1           — approximate scores, all N
           tier 2           — exact Sinkhorn on the shortlist
           stitched scores  — one number for each image
  L5     commonness correction + standardizing, per channel
  L6     fusion across the active channels (weights unfitted)
  L8     ranking                                        (unchanged)

                     HARNESSES
                     ═════════
  submission modes: sketch | text | mixed
  V1 text/mixed: captions against the union index
                 (union photographs get an element bank — §12)
  V2 text:       captions against random targets
```

## 6. Identity and versioning

- `scoring_config_hash` gains the element channel section, the
  submission mode, and the `text_encoder` slot hash
  (`SCORING_SLOT_NAMES` grows to three). Each change forks the
  artifact lineage as before.
- The commonness artifact grows to one array for each built channel
  at the same key: `outline.npy` and `element.npy` with one
  `meta.json`. The commonness hash covers the full channels config
  (D11).
- Harness records keep their naming. The submission mode is in
  `scoring_config_hash`, thus each mode has its own record lineage.

## 7. Input — the p04 artifacts

The context loader (`pipeline/context.py`) extends its verified set
with four inventory keys:

| Artifact | Shape and rule |
|---|---|
| `p04-vocabulary/vocabulary.jsonl` | rows `{element, index, pool_frequency}`, indices `0..V−1` in row sequence, `1 ≤ pool_frequency ≤ N` |
| `p04-vocabulary/vocabulary_vectors.npy` | `(V, d)` float32, unit-norm rows, `d` equal to the outline dimension |
| `p04-vocabulary/incidence.npy` | `(N, 20)` int32, entries in `[−1, V)`, `−1` is padding, rows aligned with `image_ids` |
| `p04-vocabulary/element_space_mean.npy` | `(d,)` float32, the raw mean of the vocabulary vectors |

Digest checks against the preparation record inventory, as in P2 §7.
`PoolIndex` gains the element side: `vocabulary` (V strings),
`pool_frequency` (V ints), `vocabulary_vectors`, `incidence`,
`element_space_mean`. `build_pool_index` makes sure the rules above
hold. Dev values: V = 1,527, d = 3,072, element lists of 16.

## 8. The channel

All pure functions in `core/channels/element.py`, typed with the
`core/types.py` aliases. Shapes: `m` atoms in the channel, `k ≤ 20`
elements for one image, `V` vocabulary entries, `N` images.

### 8.1 The channel's atoms and their vectors

The channel reads the DESCRIPTION atoms that hold text. Their vectors
come from Layer 2 (`encode_submission` extended): one batched
`TextEncoder` run across the routed text atoms, cached by string at
the provider. A DESCRIPTION atom with strokes and no text contributes
nothing in this phase (D10, α = 1.0). A submission with no text-
bearing atom leaves the element channel out of the active set — the
fusion denominator handles it, as always (I5).

### 8.2 Rarity weights (R1, D1)

One matrix multiplication for each submission:

```
A = atom_vectors @ vocabulary_vectors.T        # (m, V), centered per D2
best_entry(i) = argmax over V of A[i]          # the entry the atom matches
rarity(i) = −ln(pool_frequency[best_entry(i)] / N)
```

The atom's frequency is its best-matching vocabulary entry's document
frequency (D1). `pool_frequency ≥ 1` by construction, thus the
logarithm is finite. An atom matching an everywhere-element gets a
weight near zero, which is the intent (§12.1: flooding does not
help).

### 8.3 The similarity table (R2, D2)

For one image with element bank rows `E` (`k × d`):

```
C = centered_cosine(atom_vectors, E)           # (m, k), rule element-center-cosine-v1
```

`element-center-cosine-v1` (D2): subtract `element_space_mean` from
the two sides, then cosine — the element-space mirror of the P2
outline rule. The type rule is structural in this build: only
text-bearing DESCRIPTION atoms go into the table (R2).

### 8.4 Soft matching (R3, D3)

Rule `sinkhorn-slack-v1` (D3), fixed and deterministic:

1. Add one reserve row and one reserve column to `C` at similarity
   zero — the "stay unmatched" selection for each side.
2. `K = exp(C_aug / ε)`, float64. `ε` is `channels.element.epsilon`
   (proposed 0.10).
3. Twenty alternating row/column rescaling steps (the fixed count is
   what keeps determinism). Row marginals: 1 for each atom row, `k`
   for the reserve row. Column marginals: 1 for each element column,
   `m` for the reserve column.
4. `Π` is the atom-by-element `(m, k)` region after the last step.

Unmatched mass parks on the reserve row and column, not in
unwanted pairings (R3). Twenty steps, float64, fixed
sequence — two runs give equal bytes.

### 8.5 The score and the tiers (R4, R5, D4)

```
tier1_scores(encoded, index)  -> (N,)   # gather + max, every image
tier2_scores(encoded, banks)  -> (K,)   # exact matching, shortlist
element_channel(encoded, index, config) -> (N,)
```

- Tier 1 (§18): `A` from §8.2 gathered through the incidence table
  (`−1` padding masked to minus infinity), each atom takes its best
  element for each image, `scores = (best × rarity).sum(axis 0)`.
- Tier 2: the full §8.4 matching on the `tier2_count` best tier-1
  images, with the R4 score.
- Stitching (D4): the output starts as the tier-1 vector and the
  tier-2 entries **replace** their images' values. The two tiers
  measure the same quantity in the same units (rarity-weighted
  correspondence mass). Tier 1 is optimistic by a small margin, and the
  boundary sits far from the score region (R5). With `tier2_count ≥
  N` — the development default — each image gets the full matching
  and tier 1 is
  only the shortlist heuristic it will be in Phase 5.

### 8.6 The match report (D12)

```
match_report(encoded, bank, config) -> tuple[MatchRow, ...]
```

One row for each atom: the best-matched element string, `Π`,
`C`, and the rarity weight — the §27 feedback shape ("atom 3 matched
the lighthouse at 0.71"). Pure, and called only **after** ranking
(the report needs a chosen image — the channel itself does not know
one). The V1 harness records the target's report for each trial —
the review sheet gains a correspondence column only eyes can judge.

## 9. Configuration

`pipeline/config.py` extends:

- `channels.element`: `comparison_rule` (`element-center-cosine-v1`),
  `matching_rule` (`sinkhorn-slack-v1`), `epsilon` (0.10),
  `sinkhorn_iterations` (20), `tier2_count` (500), `alpha` (1.0,
  D10).
- `fusion.weights`: `{"outline": 1.0, "element": 1.0}` — equal,
  unfitted, recorded as such (R9, I6). `BUILT_CHANNELS` grows.
- `providers.text_encoder`: the P1b slot shape, model
  `google/gemini-embedding-2`, dimension 3,072 (U2).
- `validation.submission_mode`: `sketch` | `text` | `mixed` (D7).
- `SCORING_SLOT_NAMES` gains `text_encoder`. The wiring and
  hash-without-wiring helpers extend accordingly.

The routing table in `core/types.py` becomes
`{"DESCRIPTION": ("element",), "RELATION": (), "WHOLE-DRAWING":
("outline",)}` — one data change, no code branch (R9, I5).

## 10. Layer 2 and orchestration changes

- `encode_submission(submission, render, encoders)` — the encoder
  argument becomes a small frozen record with the `sketch` and `text`
  slots. Routed WHOLE-DRAWING atoms render and encode as in Phase 2,
  and routed DESCRIPTION atoms with text encode in one batched
  `encode_texts` run. `score_trial` gets the same record.
- `_run_channel` gains the `element` branch.
- The commonness task builds one table for each channel in
  `BUILT_CHANNELS` that the weights name, writing `<channel>.npy`
  (D11). Background submissions build with the run's submission
  mode.

## 11. Harness modes (D7)

The harness builds the wire record from one sketch pair by the mode:

| Mode | Wire record |
|---|---|
| `sketch` | `canvas_strokes` from the vector strokes (Phase 2 rule) |
| `text` | `pasted_text` = the pair's caption (R10 — the frozen paste rule makes the atoms) |
| `mixed` | the two together |

The Phase 3 development gates (R12): **V1 text**, **V2 text**, and
**V1 mixed**, each a recorded run with a human verdict. The sketch
mode stays available unchanged. A text-mode V2 must agree with
`Uniform(0, 1)` the same as the sketch mode did — the baseline claim
is modality-free (§14 of the architecture).

## 12. The V1 union element side (D8)

V1 puts photographs in the decoy set. The element channel scores
an image through its element bank — and the union photographs have
none. The harness builds them, through the same capability path the
pool went through (Rule 3):

1. `VlmDescriber` on each V1 photograph — the p01 slot, the p01
   instruction template and count contract from the preparation
   config, the P1a response cache (`image_id` + slot hash keys,
   ~200 cold `POST` operations, then free).
2. The p02 normalization and p03 cap **pure functions, imported and
   applied as-is** — the same rule tables, the same flatten
   sequence. Capping rarity uses the pool document frequencies: a
   photograph element found in the pool vocabulary takes its pool
   frequency, and one not found gets frequency 1 (it appears nowhere in
   the pool — the rarest thing there is).
3. `TextEncoder` on the photograph element strings (cached by
   string — the pool vocabulary holds most of them).
4. The union element banks: pool images through the incidence table,
   photographs through their own vectors — one bank abstraction
   (§3), one channel code path.

**Rarity is pool-defined and does not move** (R1): atoms get their
weights from the pool vocabulary in each mode, thus adding
photographs changes no atom's weight. Tier 1 runs the incidence
lookup for pool images and the plain computation for the 200
photographs — trivial at development scale.

The fake path mirrors it offline: fake pair photographs hold
scripted `fake_elements` chunks (the P1b mechanism), the fake
describer reads them, and the fake caption (D6) is drawn from those
same elements — `FakeTextEncoder` seeds by string, thus a caption
element and its photograph element share one vector, and the V1 text
mode gets a strong offline signal through the full production path.

## 13. Dataset extension (D6)

- `SketchPair` gains `text: str | None`. The FS-COCO adapter reads
  `text/<user>/<id>.txt` (one sentence, checked at first read — a
  missing caption file raises, check-at-first-download style). The
  fake source writes scripted captions from its photographs'
  elements plus one noise word.
- `check_sketch_pair` accepts text-only pairs? No — FS-COCO always
  has strokes, and `text` is one more field. The rule stays: one of
  the sketch fields filled, `text` optional with them.

## 14. Artifacts, storage, cost

- Commonness: `data/commonness/<index_id[:8]>/<hash[:8]>/{outline.npy,
  element.npy, meta.json}` (D11).
- Validation trees and records: unchanged layout, new lineages from
  the new config hash.
- **Development `POST` estimate (U1)**: V1 photograph descriptions
  ~200 (one time, cached), caption text encodes for the background,
  V1, and V2 selections — ~1,700 strings, batched at 64, ~30
  `POST` operations — and photograph element encodes ~50 batched. About
  **300 cold** across the three gate runs, near zero on re-runs.

## 15. Determinism and testing

Determinism: a fixed Sinkhorn iteration count with float64
additions. Argmax equal values resolve to the lowest vocabulary
index (written rule). The caption file read is bytes-to-UTF-8 with
no normalization other than the frozen paste rule. All else inherits
the P2 rules.

**Unit tests** — rarity on hand vocabularies (the §27 example shape:
frequency 0.09 → 2.4 nats), the similarity type rule, Sinkhorn on
hand-built tables (marginals at or below capacity, unmatched atoms
park on the reserve, determinism byte-for-byte, a 2 × 2 table
checked against a by-hand computation), the tier-1 lookup with
padding, stitching, the
flooding property (adding five near-zero-rarity atoms moves no
ranking materially — the §12.1 claim as a test), and the match
report shape.

**Invariant tests** — the target-scan module tables cover the new
files, channel output length N in each mode, fusion across
{outline}, {element}, and the two together, text-mode rescoring
byte-for-byte, and hash sensitivity for each new config field.

**Integration** — fake end-to-end in each mode, V1-text positive
signal through scripted elements, V2-text KS below the acceptance
line, the union element bank built from fake describer output, and a
mixed
trial engaging the two channels (assert the two raw score vectors
enter fusion).

Development gate runs (not CI): V1 text, V2 text, V1 mixed, recorded
with verdicts (R12).

## 16. Decisions — ruled 2026-08-09

The owner ruled the twelve decisions one by one on 2026-08-09, each
at its proposed default. The table below is the record.

| # | Decision | Ruling | Notes |
|---|---|---|---|
| D1 | Rarity match rule | The atom's best-matching vocabulary entry (argmax centered cosine) supplies the document frequency, and equal values resolve to the lowest index | §12.1 defines rarity by "something this atom matches" without a rule. Argmax is deterministic, one lookup, and it uses the tier-1 matrix again. Alternative: a similarity-weighted soft frequency — more machinery, unclear benefit. Look again with V-harness data. |
| D2 | Element similarity rule | `element-center-cosine-v1`: center the two sides on `element_space_mean`, then cosine | The mirror of P2 D4 (R7). The rule name is in config. |
| D3 | Soft matching shape | `sinkhorn-slack-v1`: one reserve row and column at similarity zero, `ε` 0.10, twenty iterations, float64 | §12.1 names the algorithm and the unbalanced relaxation, not the construction. Reserve bins are the simplest written shape of "unmatched is permitted". `ε` and the iteration count sit in config, and each change forks the hash. |
| D4 | Tier interface and stitching | `tier2_count` 500 in config, tier-2 values replace tier-1 values on the shortlist, and the development default runs the full matching on each image (`tier2_count ≥ N`) | §18 puts the shortlist at 500 so the boundary sits far from the score region. The interface lands in this phase, the speed in Phase 5 (`CLAUDE.md` §7). |
| D5 | Provisional fusion weights | `{"outline": 1.0, "element": 1.0}`, equal and unfitted, recorded as unfitted in the harness records | I6 forbids fitting here. Equal weights make mixed-mode numbers diagnostic only — the records must say so. Phase 4 fits and freezes. |
| D6 | Captions on `SketchPair` | New `text: str \| None` field. FS-COCO reads `text/<user>/<id>.txt` and raises on a missing file. The fake source builds captions from its scripted elements plus one noise word | The caption files were checked on the extracted tree 2026-08-09 (10,000 files, one sentence each). |
| D7 | Submission modes and gates | `validation.submission_mode` ∈ {`sketch`, `text`, `mixed`}, and the Phase 3 gates are V1 text, V2 text, and V1 mixed | The mode is in the scoring hash, thus each mode is its own recorded lineage. Sketch mode stays available for regression runs. |
| D8 | Union element side | Describe the V1 photographs through the p01 slot and cache, apply the p02/p03 pure rules as-is, give unknown-to-the-pool elements document frequency 1, and build the photographs their own element banks | Rule 3: the photograph element path is the pool element path. Rarity stays pool-defined for each atom. ~200 cold describer `POST` operations, one time. |
| D9 | Caption to atoms | Through `pasted_text` and the frozen Layer 1 paste rule | R10 — no new parsing, no Layer 1 change. A one-sentence caption becomes one atom unless it holds commas. |
| D10 | The α knob | `channels.element.alpha` exists at 1.0, and the sketch-vector path behind values below 1.0 is not built | §6 of the architecture: start text-only, and increase α only when the V-harness says the sketch path helps. A DESCRIPTION atom with strokes and no text contributes nothing at 1.0. |
| D11 | Commonness generalization | One `<channel>.npy` for each weighted channel at the existing key, and the commonness hash covers the full channels config | The P2 layout wrote `outline.npy` alone. The meta gains counts for each channel. Amended 2026-08-10: each *built* channel the background activates — see §10 item 2. |
| D12 | Match report scope | The pure `match_report` function plus V1 trial recording, and no player-facing surface | The §27 feedback seed and a review instrument. The full report on the results screen comes with a phase after this one. |

## 16a. What the build settled that the spec left open

The build made these decisions because §16 does not answer them. Each
one is a point a reader will come back to, so each is written down.

1. **The element bank is one table.** `vocabulary` and
   `vocabulary_vectors` hold B entries and `pool_frequency` holds the
   first V of them, which are the pool vocabulary. Rarity reads the
   first V alone. A V1 union index appends photograph entries above V
   and keeps `pool_image_count` as it is. Pool images and photographs
   then share one incidence table and one channel code path, and
   rarity is pool-defined by construction (R1, I3).
2. **A commonness table exists for each built channel the
   background activates** (amended by the P4 review ruling
   2026-08-10 — the first wording said "each weighted channel", and the
   caller's weight table then shaped the stored bytes at a
   weight-free key). The set is a subset of the built channels when
   the submission mode leaves a channel silent: a sketch-mode
   background cannot build an element table. The scoring context
   selects the weighted subset, and a trial that activates a channel
   with no table raises in `score_trial`. The pre-flight makes the
   background set the same in this respect, so a table is built from
   the full background or not at all.
3. **The p03 cap is factored, not copied.** `cap_decisions` measures
   document frequency across the sequences it caps.
   `cap_with_frequencies` takes the frequencies as an argument, and
   `cap_decisions` runs it. The V1 union side gives it the pool
   frequencies with unknown elements at 1 (D8). The outputs of
   `cap_decisions` do not move.
4. **The active channel set follows the encoded atoms, not the atom
   types.** A DESCRIPTION atom with strokes and no text routes to the
   element channel by type and has no vector at alpha 1.0 (D10). The
   channel set is the union of the routing entries across the atoms
   that hold a vector. This is data-driven and adds no modality branch
   (I5).
5. **The submission mode is in the scoring config, so each mode is a
   config file.** `configs/scoring/dev-wit.json` holds the sketch
   mode and `dev-wit-text.json` and `dev-wit-mixed.json` hold the
   others. A scoring config is not a released artifact, so the
   extension of the committed file is one edit.
6. **The element space has its own Rule 3 guard.**
   `check_element_space` stops a run when the scoring `text_encoder`
   config hash is not the one the preparation record names. The p04
   stage encoded the vocabulary with that slot, and two different
   encoders give cosine values with no meaning. This mirrors the P2
   R7 guard on the outline space.
7. **The element dimension is not tied to the outline dimension.**
   The §7 table says `d` equal to the outline dimension. The build
   checks the element artifacts against each other and against the
   atom vectors, and does not compare them with the p06 space: the
   text encoder and the image encoder are different slots (CLAUDE.md
   §6), and a text encoder of a different width is a correct future
   configuration. The check that matters is item 6.
8. **Twenty alternations do not converge, and that is the pinned
   behavior.** At epsilon 0.10 the kernel spans exp(20), and the
   plan after twenty alternations is short of the limit. The count is
   fixed for reproducibility (D3), and the sequence ends on a row
   rescaling so each atom holds one unit of mass accurately — the
   quantity the score adds up. A unit test records the distance from
   the limit as a measured property. Phase 5 can revisit epsilon and
   the count together with the tier work.
9. **The match report names an element only when it beats the
   reserve.** An atom with no similarity to anything in an image
   spreads its mass equally. To name the first element then reports a
   correspondence the submission does not hold, so the row gives
   element None. The row keeps its similarity and weight, thus a small
   value stays a small value to the reader. No threshold enters the
   scoring path (I2).

## 17. Code layout

```
core/
  channels/element.py     # rarity, similarity table, Sinkhorn, tiers,
                          # element_channel, match_report — pure
  types.py                # routing table change; PoolIndex element side;
                          # Encoders record; MatchRow
pipeline/
  config.py               # element section, mode, text_encoder slot
  context.py              # p04 loading + checks
  commonness.py           # per-channel tables (D11)
  score.py                # Encoders record; element case
providers/
  protocols.py            # SketchPair.text
  sketchsets/fscoco.py    # caption read
  sketchsets/fake.py      # scripted captions
validation/
  harness.py              # mode-aware record builder; text_encoder wiring
  v1.py                   # union element side; match-report recording
  v2.py                   # mode-aware
configs/scoring/dev-wit.json  # extended (one committed edit — the
                          # scoring config is not a released artifact)
```

Import direction rules unchanged. The p02/p03 pure functions import
from `pool/preparation/stages/` into `validation/v1.py` — shell to
shell, permitted.

## 18. Acceptance criteria

1. `uv run pytest` completes with zero errors, offline, no GPU.
2. The §15 unit and invariant tests are written and green, with
   the flooding property and the Sinkhorn hand-check.
3. Fake end-to-end runs in the three modes write the artifact shapes,
   and the V1 text mode shows the offline positive signal.
4. The development gate runs complete: V1 text, V2 text, V1 mixed —
  reported with numbers against their references, recorded with
  verdict fields for the owner, weights marked unfitted (D5).
5. A text-mode V2 KS result agrees with `Uniform(0, 1)` at the
   acceptance line, or the failure is treated as a Rule 3 audit.
6. Re-runs with unchanged config make zero new `POST` operations.
7. No open decision from §16 is implemented without recorded
   agreement.
8. Documentation is Vale-clean at error level, with warning decisions
   noted.
9. Development numbers stay unpublished (`CLAUDE.md` §7).
