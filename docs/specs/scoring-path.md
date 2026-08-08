# Spec P2 — The trial scoring path and the style bridge gates

**Status:** draft, for review.
**Phase:** 2 — prove the style bridge (`docs/ARCHITECTURE.md` §25).
**Architecture sections:** §6 (the submission), §8 (Layer 0), §9 (Layer 1),
§10 (Layer 2), §11 (Layer 3), §12.2 (the outline channel), §13 (Layer 5),
§14 (Layer 6), §16 (Layer 8), §19 (fitting), §23 (validation V1 and V2).
**Working agreement:** `CLAUDE.md` §2 (invariants), §5 (interchangeability),
§6 (provider agnosticism), §7 (development build).
**Input:** one preparation version from spec P1b
(`docs/specs/pool-preparation.md`), development value
`dev-wit-prep-001-efacf7ff` on pool `dev-wit-001-b89d8614` (225 images).

This spec is written for implementation by an AI agent. It defines
contracts, file layouts, and acceptance criteria. Where the architecture
does not give a value or a rule, this spec says so in §19 and proposes a
default. Do not implement an open decision without agreement.

---

## 1. Purpose

This build makes the smallest path that turns one submission into one
**trial score**: Layer 0 intake, Layer 1 atom assembly, the Layer 2 sketch
encoder, the Layer 4 outline channel, Layer 5 normalization, Layer 6
fusion, and Layer 8 ranking. It then measures the two questions that gate
all work after it (§23 of the architecture):

- **V1 — does the style bridge work?** Sketches with known paired
  photographs must rank the correct photograph far above the
  no-information reference.
- **V2 — is the baseline correct?** Trial scores from no-information
  submissions must agree with `Uniform(0, 1)`.

The architecture defines this phase as the smallest build that gives a
calibrated trial score (§25). No leaderboard, no endpoint, and no fitted
weight is in this phase.

## 2. Scope

**In scope**

- Layer 0 intake: submission validation gates and the canonical render of
  `strokes` payloads (§8 of the architecture).
- Layer 1 atom assembly, with the frozen submission record format that
  the interface will emit (§6, §9 of the architecture).
- The `SketchEncoder` provider slot — its own slot with its own
  `config_hash`, kept apart from the pool-side `ImageEncoder`
  (`CLAUDE.md` §6).
- The Layer 4 outline channel: one number for each pool image, maximum
  across the stored crop rows (§12.2).
- Layer 5 normalization: commonness correction and standardizing (§13),
  plus the offline commonness table for the outline channel from a
  background set (§13.2, source A).
- Layer 6 fusion with the fixed formula and the active-channel rule
  (§14). In this phase the built channel set is `{outline}`.
- Layer 8 ranking: decoy set construction from the near-duplicate
  groups, the trial score, and the decoy count (§16).
- The scoring context: loading the P1b artifacts into one frozen
  in-memory record, with hash checks against the preparation record.
- Sketch-pair dataset access behind a protocol, with a fake for tests.
- The V1 and V2 harnesses in `validation/`, with committed result
  records.

**Out of scope** — specs that follow cover these.

- The element channel, rarity weights, the similarity table, and soft
  matching (Phase 3).
- The placement channel, the synthetic submission generator, weight
  fitting, and V3 through V6 (Phase 4). Invariant I6 of `CLAUDE.md`
  applies: no fitting on live trials, and no fitting at all in this
  phase.
- Layer 7 deferred rerank (Phase 6) and Layer 9 aggregation.
- Frontloading and tag vectors (§20 of the architecture).
- A server, an endpoint, a submission store for live players, practice
  mode, and the 50 ms fast path (§18). This phase is offline library
  code plus harnesses. Invariant I7 (no score feedback) is satisfied
  because no interface to a player exists.

## 3. Terms this spec adds

The glossary in `docs/ARCHITECTURE.md` §2 defines all scoring terms
(submission, atom, trial score, background set, commonness score). This
spec adds pipeline terms only.

| Term | Meaning |
|---|---|
| **Scoring config** | The frozen parameter object for the scoring path and the harnesses. Its hash is part of each derived artifact key. |
| **Pool index** | The frozen in-memory record of pool-side data that channels and ranking read: image identifiers, outline vectors, means, and near-duplicate groups. |
| **Scoring context** | The pool index plus the commonness tables, the fusion weights, and the identity hashes. |
| **Index identity** | The hash that names one pool index. For the plain pool it is `preparation_version_id`. §6 defines the union index. |
| **Sketch pair** | One record from a sketch dataset: one human sketch plus the photograph it depicts. |
| **Union index** | The pool index for V1: the prepared pool plus the paired photographs, processed through the same providers (§12). |
| **Harness record** | A small committed file that documents one V1 or V2 run, with its numbers and a human verdict. |

## 4. Requirements from the architecture

Numbers in this section come from the architecture and are not
negotiable.

### Layers 0 and 1 — the frozen tier

- **R1** — `strokes` are accepted as coordinates, not as images. The
  server renders them at a fixed resolution, fixed line width, fixed
  background, and fixed anti-aliasing (§8).
- **R2** — The render parameters are the same as the pool line-drawing
  canonical render (§11: same resolution, line width, background, and
  anti-aliasing as player sketches). P1b §9 requires that this spec
  read them from one source. §9 of this spec gives the mechanism.
- **R3** — Layer 0 rejects before scoring: minimum total ink, minimum
  stroke count for `WHOLE-DRAWING` atoms, maximum text length for each
  atom, and a maximum atom count (§8). The architecture gives no
  values — decisions D3.
- **R4** — Layer 1 reads structured interface fields and does not parse
  (§6, §9). A pasted free-text value is split deterministically on
  newlines and commas, one atom for each fragment, with no model (§6).
- **R5** — The atom structure is `id`, `type`, `subtype`, `payload`
  with the three frozen types `DESCRIPTION`, `RELATION`,
  `WHOLE-DRAWING` (§6). The type set and the element schema are frozen
  (`CLAUDE.md` §5). Layer 1 output must be reproducible byte-for-byte
  from the raw stored submission forever (§9).
- **R6** — Layers 0 and 1 are in the frozen tier of §7 — they do not
  change. The submission record format this spec freezes is permanent.

### Layers 2 and 3

- **R7** — The sketch encoder and the image encoder are two slots with
  two hashes, and in the first build they hold the same weights (§10,
  `CLAUDE.md` §6). The two must output into the same vector space,
  because the outline channel takes a similarity between them (§10).
- **R8** — All vectors are unit-norm at the provider boundary, and the
  pool mean vector is subtracted before vectors are compared (§10).
  P1b p06 stored `outline_space_mean.npy` for this subtraction.
- **R9** — The pool half of the style bridge is done (P1b p05 and p06).
  The submission half is the R1 canonical render. The bridge is not
  assumed to work — V1 measures it, and the recorded fallback is
  text-only scoring with player-labeled stroke groups (§11).

### Layers 4, 5, 6, 8

- **R10** — A channel is a function of (submission, pool). It gives one
  number for each pool image and is not told the target (§3 Rule 1,
  invariant I1). The target identity enters the system in Layer 8 and
  nowhere else.
- **R11** — The outline channel score is the maximum across the stored
  rows: the full image plus the crop grid (§12.2). P1b p06 stored
  `N × 6 × d` vectors (full image plus five crops, decision P1b D6).
- **R12** — Commonness correction: `corrected = 2 × raw − common`
  (§13.1). The commonness table for a channel is the mean raw channel
  score across the background set, for each pool image (§13.2).
- **R13** — Standardizing: subtract the average across the pool, then
  divide by the standard deviation across the pool (§13.3). Each
  channel has its own table, average, and deviation. Nothing crosses
  channels before Layer 6.
- **R14** — Fusion is the fixed weighted average across active
  channels, divided by the sum of the active weights (§14). The active
  set comes from the atom types in the submission (§6). Scoring code
  does not branch on modality (invariant I5).
- **R15** — Layer 8: the decoy set is the pool minus the target's
  near-duplicate group. `D` is the decoy count.
  `p = (beaten + 0.5 × tied) / D`. `D` is stored with each trial (§16).
  P1b p08 stored the groups. No frontload filter exists in this phase.
- **R16** — No fusion weight is fitted in this phase (§19, invariant
  I6). The single built channel makes the weight value cosmetic — §14
  is scale-invariant in one channel — and the config carries
  `{"outline": 1.0}` unfitted.

### Validation

- **R17** — V1: about 200 sketch-photograph pairs from a public
  dataset, run through the full path with the photograph put into the
  ranked set. Report the fraction of trials where the correct
  photograph ranks first and the fraction where it ranks in the top
  ten (§23, §19 source 1).
- **R18** — V2: human sketches paired with random targets. The trial
  scores must agree with `Uniform(0, 1)`, tested with the
  Kolmogorov-Smirnov statistic (§23). A V2 failure is a Rule 3
  violation until shown different: check duplicate removal and pool
  curation first.
- **R19** — Harness results are reported with numbers and recorded, not
  run in CI (`CLAUDE.md` §9, §11).
- **R20** — Each derived artifact is a cache with the config hash of
  what made it in its key, and can be made again from the source
  (`CLAUDE.md` §2 invariant I4). Raw submission records in the
  harnesses are derived from datasets and can be made again from them.

### User constraints

These come from the project owner, not from the architecture. They have
the same weight.

- **U1 — OpenRouter `POST` accounting** (P1b U1 continued). Each
  OpenRouter-backed step reports its `POST` count and its cache-hit
  count, and responses are cached, thus a re-run with unchanged config
  makes no new `POST` operations. §14 of this spec estimates the
  development counts.
- **U2 — OpenRouter first, local drop-ins** (P1b U2 continued). The
  `SketchEncoder` slot runs through the OpenRouter embeddings endpoint
  in the development configuration, with the model equal to the p06
  `ImageEncoder` model (`google/gemini-embedding-2`) — R7 requires one
  shared vector space, thus a local sketch encoder is usable only
  together with a local pool re-encode and a new preparation config.

## 5. Overview

```
                     OFFLINE (one time for each config)
                     ══════════════════════════════════
  P1b artifacts ──► load + hash checks ──► pool index
  sketch dataset ─► background split ───► commonness table (outline)

                     SCORING PATH (for each submission)
                     ══════════════════════════════════
  submission record
      │
      ▼
  L0 intake       validate gates, render strokes        core/intake.py
  L1 atoms        interface fields -> atom set          core/atoms.py
  L2 encode       WHOLE-DRAWING render -> SketchEncoder pipeline/score.py
  L4 outline      max across crop rows                  core/channels/outline.py
  L5 normalize    2*raw - common, standardize           core/normalize.py
  L6 fuse         weighted average, active channels     core/fusion.py
  L8 rank         decoys, trial score p, decoy count D  core/ranking.py
                  ▲ the target identity enters here and nowhere before

                     HARNESSES (deliberate runs, recorded)
                     ═════════════════════════════════════
  V1  sketch-photograph pairs against the union index   validation/v1.py
  V2  sketches against random targets, KS statistic     validation/v2.py
```

### Functional core, imperative shell

The split is the same as P1a §5 and P1b §5. All layer logic is pure
functions in `core/`: same inputs, same outputs, no file access, no
network, no clock, no RNG without an explicit seed. The shell —
`pipeline/` and `validation/` — loads artifacts, wires providers from
config, and moves bytes. `core/` imports `providers/protocols.py` for
type annotations only.

### The fixed contracts

`CLAUDE.md` §5 fixes the signature shapes. This spec fills them in:

```python
Channel   = Callable[[EncodedSubmission, PoolIndex, ChannelConfig], PoolScores]
Encoder   = SketchEncoder                    # batched, unit-norm (§8 slot)
Normalize = Callable[[PoolScores, PoolScores], PoolScores]   # raw, common -> corrected
Fuse      = Callable[[Mapping[ChannelName, PoolScores], Weights], PoolScores]
Rank      = Callable[[PoolScores, TargetId, DecoySet, PoolIndex], TrialScore]
```

`EncodedSubmission` is the Layer 2 output — the atom set with vectors
attached (§10 of this spec). Channels receive it because encoding is
shell work: a pure channel cannot hold a provider. The `Rank` shape
carries one argument more than the `CLAUDE.md` §5 three-argument shape
(agreed 2026-08-08): a `TargetId` cannot select a row of the fused
array without the `image_id` sequence, and the `DecoySet` removes the
full duplicate group, thus the position is not recoverable from it.
The added argument is pool-side data and stays in Layer 8.

## 6. Identity and versioning

### Scoring config hash

`scoring_config_hash` is the SHA-256 hex digest of the canonical JSON of
the full `ScoringConfig` (§9), which contains each provider
`config_hash` and each seed. The `runtime` section is excluded, as in
P1b §9. Each parameter change makes a new hash and thus a new artifact
tree — no artifact is overwritten (R20).

### Index identity

- Plain pool index: `index_id = preparation_version_id`.
- Union index (V1): `index_id = sha256(preparation_version_id +
  dataset_config_hash + sha256(newline-joined sorted photograph
  image_id values))`, with the byte layout rules of P1a §6.

Photographs get `image_id = sha256(image bytes)` — the same rule as
curation s02, thus a photograph that carries the same bytes as a pool
image gets the same identifier.

### Commonness artifact key

A commonness table is keyed by `index_id` and `commonness_config_hash` —
the hash of the background section of the config (§9): dataset
identity, split rule, background count, sketch encoder hash, render
parameters, and channel config. A change to one of them makes a new
table.

### Harness records

Each V1 or V2 run writes a harness record to
`validation/records/<harness>-<tag>-<harness_config_hash[:8]>.json`,
**committed to the repository** (R19). §12 and §13 give the contents.
Each development record carries `dev_only: true` (P1b R15 continued).

## 7. Input — the prepared pool

The config names one committed preparation record
(`pool/preparations/<label>.json`, P1b §10 p09). Context loading must:

- Parse the record and read `preparation_version_id`, the pool
  reference, `N`, and `dev_only`.
- Read the artifact tree of that preparation and check each file it
  loads against the content hashes in the record's artifact inventory.
  A hash that does not agree raises with the path named.
- Recompute the hash of the preparation config file named in the
  record and make sure it equals `preparation_config_hash`. This is
  what makes the R2 one-source rule safe: the render parameters are
  read from that config file, and drift after release is detected at
  the boundary.
- Load: `image_id` sequence from p00 records, `outline_vectors.npy`
  (shape `N × 6 × d`), `outline_space_mean.npy`, and the p08 group
  table. Element artifacts are not read in this phase.

The loaded result is the frozen **pool index**. The scoring context adds
the commonness tables (§11), the weights, and the identity hashes.

## 8. Model provider slots

This phase adds two capability protocols to `providers/protocols.py`.
Each follows `CLAUDE.md` §6: batched, config-hashed, output-normalized
at the boundary. Fake implementations are required for the test suite.

| Protocol | Contract (shape) | Used by | OpenRouter? |
|---|---|---|---|
| `SketchEncoder` | `Sequence[bytes] -> Vectors` — unit-norm, `(B, d)`, input is canonical rendered PNG bytes | L2 encode step, harnesses | Yes — embeddings endpoint (U2) |
| `SketchPairSource` | identity, `config_hash`, `iter_pairs() -> Iterator[SketchPair]` | background split, V1, V2 | n/a — dataset access |

Notes:

- `SketchEncoder` has the same method shape as `ImageEncoder`
  (`encode_images`), and is its own protocol so the two slots cannot be
  wired from one config entry by accident. Its `config_hash` covers
  model identity and API parameters. R7 binds its development model to
  the p06 model. The expected dimension is a config value, and a
  response with a different width raises (P1b R14).
- `SketchPair` is a frozen record: `pair_key` (stable in a pinned
  dataset revision), `photo_bytes`, `sketch_strokes` (a tuple of
  point sequences, when the dataset ships vector data) or
  `sketch_bytes` (raster PNG, when it does not), and `category`
  (recorded, not acted on). One of the two sketch fields must be
  filled, and the adapter validates at the boundary.
- The `SketchPairSource` adapter follows the P1a §7 corpus rules:
  pinned revision, batching and retries internal, a `bytes_retrieved`
  counter, and a config `budget_bytes` with explicit accounting. The
  development dataset is decision D1.
- The fake `SketchPairSource` makes deterministic pairs in which the
  sketch and the photograph share seeded vector structure with the
  fake encoders. Thus V1 mechanics are testable offline with a
  positive signal.

## 9. Configuration

One frozen `ScoringConfig` dataclass, loaded from a committed JSON file
(`configs/scoring/dev-wit.json`), with the strict validation rule of
P1a §9: a missing or unknown field stops the load (P1b R14). Sections:

- `input`: the preparation record path.
- `intake`: the R3 gate values (D3): `min_ink_pixels`,
  `min_strokes_whole_drawing`, `max_text_length`, `max_atoms`.
- `render`: **intentionally missing.** The canonical render parameters
  come from the preparation config file through the §7 mechanism (R2).
  Restating them here makes two sources.
- `channels`: one section for each built channel. This phase:
  `outline`, with `comparison_rule` (D4, value `center-cosine-v1`).
- `fusion`: the weight table, value `{"outline": 1.0}` (R16).
- `commonness`: the background section — `dataset` (a
  `SketchPairSource` config), `split_salt`, `background_count`,
  and the split fractions of D8.
- `validation`: `v1_pair_count`, `v2_trial_count`, `v2_target_seed`,
  and `tag`.
- `providers`: the OpenRouter client section (P1a §9 shape) plus the
  `sketch_encoder` slot section.
- `runtime`: `device`, excluded from the hash (P1b §9 rule).
- `report`: `dev_only`.

The loaded object is passed as an argument. No code reads global
config.

## 10. The layers

Contract for all layers: pure functions in `core/`, typed with the
named aliases of `core/types.py`. All arrays that range across the pool
have length `N` in ascending `image_id` sequence — the same sequence as
the p06 rows. Type additions to `core/types.py`:

```python
Point       = tuple[float, float]            # unit square, y down (D2)
StrokePath  = tuple[Point, ...]              # one stroke, in input sequence
AtomType    = Literal["DESCRIPTION", "RELATION", "WHOLE-DRAWING"]
PoolScores  = NDArray[np.float32]            # length N
TargetId    = str                            # image_id
DecoySet    = NDArray[np.bool_]              # length N mask, target False

@dataclass(frozen=True)
class Atom:
    id: str                # "a1", "a2", ... in interface sequence
    type: AtomType
    subtype: str | None    # recorded, not acted on (§6)
    text: str | None
    strokes: tuple[StrokePath, ...] | None
    refers_to: tuple[str, str] | None   # RELATION only, two atom ids
    relation: str | None                # RELATION only, free string

@dataclass(frozen=True)
class Submission:
    atoms: tuple[Atom, ...]

@dataclass(frozen=True)
class TrialScore:
    p: float               # (beaten + 0.5 * tied) / D
    decoy_count: int       # D, stored with each trial (§16)
    beaten: int
    tied: int
```

### Layer 0 — intake (`core/intake.py`)

Two pure functions.

`validate_submission(record, gates, canvas_px) -> Submission` applies the R3 gates
to the raw submission record (§10, Layer 1 shape below) and raises
`IntakeError` with a cause (`min-ink`, `min-strokes`, `text-length`,
`atom-count`, `bad-shape`) on the first violation. A point out of
the unit square raises (`bad-shape`). Validation is at the boundary,
and downstream code assumes checked input (`CLAUDE.md` §3). The
`canvas_px` argument comes from the preparation config through §7 —
the ink gate counts pixels on the canvas grid (D3), and R2 forbids a
second copy of the render parameters in the scoring config.

`render_strokes(strokes, canvas_px, line_width_px) -> bytes` renders
one `strokes` payload as canonical PNG bytes: white background, black lines,
no anti-aliasing, byte-for-byte deterministic. Each stroke becomes the
pixel line segments between its points on the `canvas_px` grid
(Bresenham rule). The boolean line image then goes through the shared
dilation and render helpers of `core/lineart.py`. Thus a player line
and a pool line-drawing line have the same width and the same pixel
values (R2).
The ink gate measures line pixels on this render before dilation.

### Layer 1 — atom assembly (`core/atoms.py`)

The raw submission record is the frozen wire shape the interface will
emit (R6). Canonical JSON, one object:

```json
{
  "impressions": ["tall vertical structure", "cold and exposed"],
  "canvas_strokes": [ { "points": [[0.1, 0.2], [0.3, 0.4]],
                        "group_id": "g1" } ],
  "groups": [ { "id": "g1", "label": "tower" } ],
  "relations": [ { "relation": "left-of", "of": ["g1", "g2"] } ],
  "pasted_text": null
}
```

`assemble_atoms(record) -> Submission` maps fields to atoms in this
fixed sequence, with identifiers `a1, a2, ...` assigned in emission
sequence:

1. One `DESCRIPTION` atom for each `impressions` row (text only).
2. One `DESCRIPTION` atom for each fragment of `pasted_text`, split on
   newlines and commas, empty fragments dropped (R4).
3. One `DESCRIPTION` atom for each group: its member strokes, plus its
   label text when the label is not empty.
4. One `WHOLE-DRAWING` atom holding all canvas strokes, emitted when
   `canvas_strokes` is not empty.
5. One `RELATION` atom for each relations row, with `refers_to` mapped
   from group identifiers to the atom identifiers of step 3.

The optional point fields (`time`, `pressure`) are kept in the raw record
and are not read by assembly. The function is around fifty lines, has
no configuration, and does not change (§9 of the architecture). A
relations row that names an unknown group identifier is an intake
`bad-shape` rejection — checked in Layer 0, before assembly.

### Layer 2 — encode (shell step in `pipeline/score.py`)

The routing table of §6 of the architecture, restricted to the built
channels: for each `WHOLE-DRAWING` atom, render with `render_strokes`
and encode with the `SketchEncoder`. The result is the
`EncodedSubmission`: the atom set plus a mapping from atom identifier
to unit-norm vector. `DESCRIPTION` and `RELATION` atoms get no vector
in this phase because no built channel reads one — the routing table
is data, not a modality branch (R14). Phase 3 extends the same table.

### Layer 4 — outline channel (`core/channels/outline.py`)

```python
def outline_channel(
    submission: EncodedSubmission, index: PoolIndex, config: OutlineConfig
) -> PoolScores:
```

Active when the submission holds a `WHOLE-DRAWING` atom. Rule
`center-cosine-v1` (D4), fully vectorized:

```
s = sketch_vector - outline_space_mean            # (d,)
V = outline_vectors - outline_space_mean          # (N, 6, d)
score[x] = max across the 6 rows of cosine(s, V[x, row])
```

`cosine` divides the inner products by the vector norms after the mean
subtraction (R8). The output has length `N`. A channel that is not
active is not run — the fusion active set covers it. The channel signature has no
target and no provider (R10).

### Layer 5 — normalization (`core/normalize.py`)

```python
def commonness_correct(raw: PoolScores, commonness: PoolScores) -> PoolScores:
    """corrected = 2 * raw - commonness (architecture section 13.1)."""

def standardize(scores: PoolScores) -> PoolScores:
    """(scores - mean) / standard deviation, across the pool (13.3)."""
```

Standardizing with a deviation of zero raises. A channel that gives
each image an equal score is degenerate, and a silent zero makes
plausible numbers that are incorrect (`CLAUDE.md` §3). Layer 5 runs
for each channel alone (R13).

### Layer 6 — fusion (`core/fusion.py`)

The fixed §14 formula. The active set is derived from the submission's
atom types with the routing table — in this phase `{outline}` when a
`WHOLE-DRAWING` atom exists, else empty. An empty active set raises
`NoActiveChannels` at the fusion boundary. The submission carries no
signal a built channel can read, and to score it is to invent a
number. The §25 build sequence does not name Layer 6 in this phase.
Decision D5 builds it here, thus no temporary single-channel special
path exists for Phase 3 to remove.

### Layer 8 — ranking (`core/ranking.py`)

The only module that knows the target (R10).

```python
def decoy_set(index: PoolIndex, target: TargetId) -> DecoySet:
    """Pool minus the target's near-duplicate group (p08 groups)."""

def rank(fused: PoolScores, target: TargetId, decoys: DecoySet,
         index: PoolIndex) -> TrialScore:
    """beaten, tied, D, and p = (beaten + 0.5 * tied) / D (section 16)."""
```

Equal fused values give half credit (R15) — with `float32` scores this
is rare and the rule handles it. The §16 floor `D >= 200` binds
frontload options — this phase has none. The development
pool gives `D` near 224 — development-only results (`CLAUDE.md` §7).

### Orchestration (`pipeline/score.py`)

```python
def score_trial(
    record: JsonValue, target: TargetId, context: ScoringContext,
    encoder: SketchEncoder,
) -> TrialScore:
```

Runs L0, L1, L2, each active channel, L5, L6, then L8. The `target`
argument goes to the Layer 8 functions and to nothing before them —
invariant I1 is auditable in the source, and the §18 test suite
checks it. The function is a library entry: harnesses loop across it,
and a future server wraps it.

## 11. The commonness table

§13.2 defines the table, and P1b §2 recorded that it cannot be a
preparation artifact — it needs a channel in operation. The §25 build
sequence puts Layer 5 in this phase, thus the outline table is built
here, from **source A only**: human sketches from the D1 dataset,
unrelated to the pool, which is the no-information condition §13.2
asks to measure. Source B (synthetic submissions) arrives with the
Phase 4 generator, and the table is then calculated again — the
architecture plans this recalculation (§13.2, "recompute on a
schedule").

`pipeline/commonness.py`:

1. Select the background split (D8) of the dataset, count
   `background_count` (D6).
2. For each background sketch: render, encode (cached), run the raw
   outline channel against the index.
3. `common[x]` = mean raw score across the background set, for each
   image `x`. Shape `(N,)`, float32.
4. Write `outline.npy` plus `meta.json` (counts, `POST` and cache-hit
   totals — U1) at the §14 key.

The task has an `index_id` parameter: V2 uses the plain pool index,
V1 uses the union index (§12), and each gets its own table at its
own key. The V1 table must cover the photographs, because commonness
correction changes the ranking (§13.1) and the target must go through
the same path as the decoys (Rule 3).

## 12. The V1 harness

**Question:** does the style bridge work (R17)?

Mechanism (decision D7): V1 does not mint a pool release. The harness
builds the **union index** in memory:

1. Materialize `v1_pair_count` pairs from the V1 split (D8).
2. For each photograph: process with the same `LineDrawer` provider
   and config as p05, encode with the same `ImageEncoder` provider and
   config as p06 — the image-level caches of P1b §6 apply, keyed by
   `image_id` and provider hash. The photograph path and the pool path
   are byte-for-byte the same (Rule 3).
3. Concatenate pool and photograph vectors, sort by `image_id`, and
   run the p08 grouping function across the union at the same
   threshold. A photograph that near-duplicates a pool image exits the
   decoy set with it. The union index keeps the stored p06
   `outline_space_mean` — photographs go through the same transform
   the pool saw at preparation (Rule 3), and 200 added vectors must
   not move the centering.
4. Build the union commonness table (§11).
5. For each pair: build a submission record with the sketch as canvas
   strokes, and run `score_trial` with the paired photograph as the
   target. A pair without vector stroke data raises (D10).

**Report and record.** For each trial: `pair_key`, trial score, rank of
the target, `D`, input class (`vector` in this phase). Aggregates: the
first-rank fraction, the top-ten fraction, the mean trial score, the
median rank, and the no-information references computed from the run
itself — the means across trials of `1 / (D + 1)` and `10 / (D + 1)`,
because `D` changes with the target's group. The committed harness record
(§6) carries the aggregates, the counts, the config hashes, the `POST`
totals, and human verdict fields in the s08 shape (`verdict`,
`reviewer`, `date`, `notes`). The architecture sets no numeric bar —
a result near the no-information reference fails (§23) — thus the go
or no-go on the bridge is a recorded human decision on reported
numbers, like the s08 review gate.
If the verdict is `fail`, the R9 fallback path is the recorded plan.

## 13. The V2 harness

**Question:** is the baseline correct (R18)?

1. Select the V2 split (D8), count `v2_trial_count` (D9), disjoint
   from the background and V1 splits.
2. For each sketch: select one target from the plain pool index with
   the seeded generator (`v2_target_seed`) — the sketch has no
   relation to the target, which is the no-information condition.
3. Run `score_trial` against the plain pool index with its commonness
   table. The full path runs, correction included — the correction is
   part of the method the baseline claim covers.
4. Calculate the Kolmogorov-Smirnov statistic of the trial scores
   against `Uniform(0, 1)`, two-sided, with the closed formula — no
   sampling. Report the statistic and its significance value.

The trial score has `D + 1` possible values, thus the observed shape
is a step function. At `D` near 224 and the D9 trial count, the step
effect on the statistic is far below the failure signal V2 hunts, and
the record holds `D` together with the statistic. The harness record
carries the statistic, the significance value, the trial count, `D`,
the config hashes, and the s08-shape verdict fields. A failure is a
Rule 3 audit (R18), not a tuning task.

## 14. Artifacts and storage layout

The data-root rules of P1a §11 apply: bulk artifacts in `data/` are
caches, small durable records are committed.

```
data/
  commonness/<index_id[:8]>/<commonness_config_hash[:8]>/
    outline.npy  meta.json
  validation/<harness>/<index_id[:8]>/<harness_config_hash[:8]>/
    trials.jsonl  report.json  meta.json
  sketchsets/<dataset_config_hash[:8]>/
    pairs/<pair_key hash prefix>/...      # materialized dataset records
    meta.json                             # bytes retrieved, counts
  cache/
    openrouter/<provider_config_hash[:8]>/   # sketch encode responses, shared layout
    vectors/<combined_hash[:8]>/             # photograph outline vectors — the p06
                                             # key, sha256(encoder hash + drawer hash)

validation/records/<harness>-<tag>-<hash[:8]>.json   # committed
configs/scoring/dev-wit.json                         # committed
```

File formats follow P1a §11: canonical JSON, `.jsonl` rows, arrays as
`.npy` float32, deterministic `meta.json`, `timings.json` excluded
from determinism checks.

**Development `POST` estimate (U1).** One embedding `POST` for each
rendered sketch and each photograph, all cached: background 1,000
(D6) + V1 pairs 200 + V1 photographs 200 + V2 trials 500 (D9) — about
1,900 cold `POST` operations, and zero on re-runs. The report prints
the measured totals.

## 15. Runners

```
uv run python -m validation.v1 --config configs/scoring/dev-wit.json [--report]
uv run python -m validation.v2 --config configs/scoring/dev-wit.json [--report]
```

Each runner is a library function first (`run_v1(...) -> V1Report`)
with the CLI as a thin wrapper (P1b §12 rule). The commonness task
runs in the harness runners on a cache miss — it is a keyed artifact,
not a pipeline stage, and a warm tree makes it a read. `--report`
prints the aggregates, the reference numbers, and the U1 totals. The
runner writes the harness record only when the trials completed for
the full count — a part-done run resumes from the response caches.

## 16. Code layout

```
core/
  types.py           # + the section 10 additions
  intake.py          # L0: gates, stroke render (uses core/lineart.py helpers)
  atoms.py           # L1: assemble_atoms, frozen wire shape
  channels/
    __init__.py
    outline.py       # L4 outline channel
  normalize.py       # L5 commonness_correct, standardize
  fusion.py          # L6 fixed formula, active-set rule
  ranking.py         # L8 decoy_set, rank — the only target-aware module
pipeline/
  __init__.py
  config.py          # ScoringConfig, loading, scoring_config_hash
  context.py         # preparation loading, hash checks, PoolIndex, ScoringContext
  score.py           # L2 encode step + score_trial orchestration
  commonness.py      # background job, keyed artifact
validation/
  __init__.py
  splits.py          # hash-based disjoint splits (D8), pure
  harness.py         # shared runner plumbing: wiring, paths, usage, records
  v1.py              # union index build + V1 run + record
  v2.py              # V2 run + KS statistic + record
  records/           # committed harness records
providers/
  protocols.py       # + SketchEncoder, SketchPairSource, SketchPair
  sketchsets/        # dataset adapter (D1) + fake
  openrouter/        # sketch encoder slot wiring (embeddings client exists)
  fake/              # + fake sketch encoder, fake sketch pairs
```

Import direction rules of `CLAUDE.md` §8 apply: `core/` imports
protocols for annotations only, and a component does not import a
component — shared types live in `core/types.py`. The KS closed
formula is pure code in `validation/v2.py` or `core/` — it must not
pull a statistics dependency for one formula unless agreement says so.

## 17. Determinism

Two runs with the same config against the same preparation must give
byte-for-byte the same artifacts and records. Excluded: `timings.json`,
the verdict fields, and the commonness `meta.json` — it carries the U1
`POST` totals, which are different between a cold run and a warm-cache
run. p09 keeps meta files out of its artifact inventory for the same
cause, and this file follows that rule. Concretely:

- The canonical render of `strokes` payloads is integer pixel work with a written
  rule (Bresenham segments, shared dilation) — no anti-aliasing, no
  float rasterization.
- Encoder responses are cached with the slot `config_hash` in the key
  (P1a §8a). Re-runs read the cache and get the same bytes.
- Splits are hash-based with `split_salt` (D8) — enumeration sequence
  has no effect, the P1a s00 sampling argument.
- V2 target selection is seeded (`v2_target_seed`) and written as a
  pure function of seed and trial index.
- All pool-length arrays are in ascending `image_id` sequence, and
  float additions follow a fixed sequence.
- Reports and records are canonical JSON with quantized measured
  values (`core/canonical.py`).

## 18. Testing

All tests run offline with the fake providers — no GPU, no network
(`CLAUDE.md` §7, §9). Tests build a small prepared-pool fixture
directly (preparation record plus artifact files), as P1b §15 built
its released-pool fixture.

**Unit tests** — each pure function against fixed fixtures: gate
boundary values (ink at the threshold, text length at the limit, atom
count at the cap), render determinism (equal strokes, equal bytes),
assembly of the §10 record shape with the paste split and the
group-to-atom mapping, the outline channel on hand-built vectors with
a known maximum row, `commonness_correct` and `standardize` algebra,
the fusion denominator, `decoy_set` on a group fixture, and `rank`
with a tied pair.

**Invariant tests** — gate merges (`CLAUDE.md` §9):

1. No module upstream of `core/ranking.py` references a target
   identifier: a source scan across `core/` (without `ranking.py`)
   and `pipeline/score.py` upstream of the Layer 8 calls finds no
   `target` parameter or attribute read.
2. Each channel output has length `N` for each fixture submission.
3. The fusion denominator renormalizes for each subset of active
   channels — property test across weight tables and active sets.
4. Standardizing does not change the ranking, and adding a constant
   across all images does not change the ranking — property tests on
   seeded score arrays.
5. Commonness correction with a non-constant table does change the
   ranking on a built fixture — the correction is not cosmetic
   (§13.1).
6. V2 shape with fakes: no-information fake submissions against the
   fake pool give trial scores with a KS statistic against
   `Uniform(0, 1)` below the seeded acceptance line.
7. Rescoring: score a fixture submission set two times with a pinned
   config — trial scores agree byte-for-byte. Delete the derived
   caches, score again from raw — same bytes (R20).
8. `NoActiveChannels` raises for a text-only submission in this
   phase's channel set, and intake rejections name their gate.
9. Hash sensitivity: one config value change moves
   `scoring_config_hash` and the commonness and validation artifact
   paths.
10. Union index: the V1 build on fake pairs puts a photograph that
    near-duplicates a pool image into that image's group.

Not in CI: the development V1 and V2 runs (R19). They are deliberate,
recorded operations. Their numbers go into the committed harness
records.

## 19. Open decisions — agreement required before implementation

The architecture gives the structures and formulas cited above, but
not the items below. All twelve decisions were agreed individually
with the project owner on 2026-08-08, with the agreed values recorded
in the table. The "Proposed default" column is the agreed value, with
two amendments made at agreement time: D1 names FS-COCO after a live
check of the initial proposal, and D10 is not built in this phase.

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | Sketch-pair dataset | **FS-COCO** (`github.com/pinakinathc/fscoco`): 10,000 freehand scene sketches with vector stroke data and point-level time, each paired with one COCO photograph. CC BY-NC 4.0, one tar.gz download, with the P1a §7 adapter rules | Agreed 2026-08-08. The first proposal (the Sketchy database through a Hugging Face mirror) did not clear a live check — no usable mirror exists. Scene-level sketches also sit closer to remote-viewing output than Sketchy's single objects. The tar layout, the `coordinate_extent`, and the archive digest are unverified — the adapter pins them at first download and raises with observed values until then. |
| D2 | Space for `strokes` coordinates | Points in the unit square, `(0, 0)` top left, y down, floats as sent. The raw record stores what the client sent. The render quantizes to the `canvas_px` grid | R1 stores coordinates forever. A resolution-free space keeps the raw record device-free. |
| D3 | Intake gate values | `min_ink_pixels` 100 (line pixels on the 512 canvas before dilation), `min_strokes_whole_drawing` 2, `max_text_length` 200 characters, `max_atoms` 64 | §8 of the architecture names the gates and gives no values. The values sit in config, not code, and V1 iteration can move them — each move is a new `scoring_config_hash`. |
| D4 | Outline `comparison_rule` | `center-cosine-v1`: subtract the stored `outline_space_mean` from the two sides, then cosine on the centered vectors, maximum across the six rows | §10 names the subtraction and §12.2 the maximum. Centering, then cosine, is the standard §10 procedure. The rule name is in config, thus a second rule is a new hash, not an edit. |
| D5 | Build Layer 6 in this phase | Yes — the fixed formula with a one-channel active set | §25 lists Layer 6 in no phase before fusion matters. With the small formula built in this phase, Phase 3 adds a channel and touches no path shape. The alternative — hand the standardized outline score to Layer 8 — is a temporary special path (invariant I5). |
| D6 | Background set for this phase | Source A only, `background_count` 1,000 sketches from the background split | §13.2 names source A and source B. Source B needs the Phase 4 generator. The table is calculated again in Phase 4 with the two sources — a planned recalculation. |
| D7 | V1 mechanism | Union index in memory: photographs through the p05 and p06 providers and caches, p08 grouping across the union, own commonness table. No pool release | A pool release for V1 puts 200 validation photographs into the pool lineage and costs element-side `POST` operations that V1 does not read. The union index keeps Rule 3 — the same path for photographs and pool images — without a release. |
| D8 | Split rule | `uint64(sha256(split_salt + pair_key)[:8]) / 2**64` mapped to background, V1, and V2 ranges: `[0, 0.5)` background, `[0.5, 0.75)` V1, `[0.75, 1)` V2 | The P1a s00 sampling rule, applied three ways. Deterministic, disjoint by construction, enumeration-free. |
| D9 | V2 trial count | 500 | The KS acceptance line at 500 trials resolves the failure sizes V2 hunts, and the `POST` cost stays in the U1 estimate. More trials are one config change away. |
| D10 | Raster sketch adapter | **Not built in this phase** (agreed 2026-08-08). FS-COCO ships vector strokes, thus the condition does not apply, and a pair without vector data raises | If vector data proves unusable at first download, stop and put D10 on the table again before more work. The recorded plan stays: grayscale, binarize at 0.5 with `core/lineart.py`, canonical render, input class `raster` on each trial row (the §8 paper-sketch path). |
| D11 | KS implementation | The two-sided statistic with the closed-formula significance value, pure code, no new dependency | One formula does not justify a statistics stack in the default environment. |
| D12 | Fusion weight table shape | `Mapping[ChannelName, float]` in config, value `{"outline": 1.0}`, carried unfitted | R16. Phase 4 fits across labeled data and freezes — this phase only fixes the shape. |

## 20. Acceptance criteria

1. `uv run pytest` completes with zero errors, with no network and no
   GPU.
2. The suite contains all invariant tests of §18, and all of them
   complete with zero errors.
3. A full fake run: `score_trial` on fixture submissions, the V1
   harness on fake pairs, and the V2 harness on fake sketches all
   complete and write the §14 artifact shapes.
4. The development commonness table exists for the plain index and the
   union index, with `POST` and cache-hit counts in `meta.json` (U1).
5. The development V1 run completes against
   `dev-wit-prep-001-efacf7ff` with the D1 dataset: the report prints
   the first-rank fraction, the top-ten fraction, and the reference
   numbers, and the committed harness record carries them with
   verdict fields.
6. The development V2 run completes: the report prints the KS
   statistic and its significance value, and the committed harness
   record carries them with verdict fields.
7. A harness re-run with unchanged config makes zero new `POST`
   operations (U1).
8. No open decision from §19 is implemented without recorded
   agreement.
9. Documentation (this file, docstrings, comments) is Vale-clean at
   error level, with warning decisions noted.
10. Each harness record carries `dev_only: true`, and no number from the
    development pool is published (`CLAUDE.md` §7).
