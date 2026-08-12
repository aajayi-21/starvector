# Spec P2c — the photograph-embedding bridge experiment

**Status:** runs recorded with owner verdicts (§9b, 2026-08-11).
The two §9b cells and the adoption ruling stay open.
**Phase:** after the P2b iteration (`docs/specs/linedraw-iteration.md`).
Runs in parallel with the Phase 4 fit work — the experiment changes no
frozen artifact and the two builds go forward without each other.
**Architecture sections:** §10 (encoders), §11 (the style bridge),
§12.2 (the outline channel, as consumer), §23 (V1 and V2, the
measures of success).
**Working agreement:** `CLAUDE.md` §5, §6, §7.
**Input:** the committed prep-002 records
(`validation/records/v1-dev-wit-99c8b508.json`,
`v2-dev-wit-ab193017.json`) and the preparation
`dev-wit-prep-002-f24e0b9e`.

This spec is written for implementation by an AI agent. Where a value
or a rule is not given by the architecture or a result, §9 says so
and proposes a default. The owner runs each live command (the
OpenRouter key stays out of the session), thus each §9 default gets
an owner checkpoint before it spends anything.

---

## 1. The question this spec answers

The style bridge (§11 of the architecture) exists because of one
measured claim: a sketch and a photograph of one scene sit far apart
in encoder space, thus the pool photographs go through a line-drawing
model before the outline encoding. The claim was measured on
contrastive image encoders. The build encodes with
`google/gemini-embedding-2`, a multimodal embedding model that
accepts instructions, and the owner's tests on a different pool
suggest that for this model the bridge is not a help — the raw
photograph embeddings ranked better than the line-drawing
embeddings.

The architecture treats the bridge as replaceable, and §11 rules
that the bridge is measured, not trusted. The same rule applies in
the opposite direction: measure also if the bridge helps at all. This spec
measures the bridge against four photograph-side conditions, on this
pool, with the committed harnesses:

- **`linedraw`** — the control: photograph → line drawing → outline
  vectors. The prep-002 build, recorded.
- **`photo`** — the raw condition: photograph → canonical
  photograph render → outline vectors. No line-drawing model.
- **`photo-instructed`** — the joint condition: the same photograph
  path, with an instruction string sent with the image in one
  embedding item, so the model represents the photograph for
  retrieval against freehand sketches. One embedding comes back for
  the joint item.
- **`photo-gray`** — ruled in on 2026-08-11 (§9a): the raw condition
  with a grayscale canonical render, removing the largest
  photograph-against-sketch difference with no instruction.
- **`photo-instructed-sym`** — ruled in on 2026-08-11 (§9a): the
  `photo-instructed` pool side unchanged, plus a sketch-side
  instruction, the two-sided query-and-document shape.

The conditions climb a ladder in which each step changes one thing
against the step below it (§8): the bridge, then color, then the
photograph instruction, then the sketch instruction. A measured
difference at each step names its cause.

## 2. Scope

**In scope**

- Two preparation config extensions: `outline.source`, selecting the
  photograph path of stage p06, and `outline.photo_render`,
  selecting its color or grayscale render (§9a). The default values
  keep the unchanged rule and the unchanged config hash.
- One embedding provider extension: an optional instruction on the
  image slots, hashed and cached as part of the slot configuration.
  The scoring config reads a sketch-side instruction on the
  sketch_encoder slot (§9a). The text slots keep the must-be-null
  rule (R7).
- The V1 union path for a photograph-source preparation (Rule 3: the
  inserted photographs go through the same path as the pool).
- Three development preparation releases and the four condition
  runs (§7): V1 and V2 for each, in sketch mode, on the FS-COCO
  pairs and splits the control used.
- The compared measures and the record notes (§8). The verdicts stay
  the owner's.

**Out of scope**

- The element channel. It reads no outline vector, and sketch mode
  keeps it silent — the element side of each new preparation rebuilds
  from the same image-level caches at zero posts.
- A pool release or a production change. Each run here is
  development-only, and a kept bridge change goes through the usual
  promotion path (architecture §21) with a new spec ruling.
- The fast-path budget. Dropping p05 makes preparation cheaper, not
  scoring — the scoring path stays one matrix operation in each
  condition.

## 3. Requirements

- **R1** — The conditions run the same harness code, the same
  FS-COCO revision, the same split salt, and thus the same 200 V1
  pairs and 500 V2 trials. Only the preparation config and its
  scoring config move between conditions.
- **R2** — The photograph path is one code path (Rule 3): stage p06
  and the V1 union builder read the same canonical photograph
  function and the same crop geometry, and the V1 provider-hash guard
  keeps rejecting a photograph path that does not equal the pool
  path.
- **R3** — Each condition is a full recorded preparation release
  (P1b rules). `outline.source` and the image-slot instruction are
  part of the preparation config hash, thus each condition owns its
  artifact tree and nothing is edited where it is.
- **R4** — A preparation with `outline.source` = `"photo"` runs
  with no line-drawing model and no torch stack: stage p05 records a
  skip and wires no provider.
- **R5** — A config document without the new fields parses to the
  unchanged behavior and keeps its hash byte-for-byte, on the
  preparation side and on the embedding slot (the P2b R5 rule). The
  released prep-002 lineage does not move.
- **R6** — The embedding cache separates the conditions by
  construction: the instruction sits in the slot config hash, thus a
  cached raw-photograph row cannot answer a joint-item `POST`.
- **R7** — No silent thinning: a text-encoder slot with an
  instruction is a config error, not an ignored field, and the
  OpenRouter text encoder refuses an instruction at construction.
- **R8** — The measures of §8 are reported as numbers, recorded in
  the harness records' notes, and set against the committed prep-002
  records. Success is a recorded human verdict — the spec sets
  directions, not cutoffs (`CLAUDE.md` §10).

## 4. The `outline.source` config extension

The preparation `outline` section gains one field:

```json
"source": "photo"
```

- A missing field and the `"linedraw"` value give the unchanged
  rule. The document shape omits the field at `"linedraw"`, thus the
  hash of a config released before the field stays unchanged (R5).
- With `"photo"`, stage p05 writes its stage directory with a skip
  meta — no drawings, no wired drawer, zero posts (R4) — and stage
  p06 builds each outline stack from the photograph:

  1. Read the pool image bytes.
  2. Make the canonical photograph render (§9 D2): decode, convert
     to RGB — or to eight-bit grayscale when
     `outline.photo_render` is `"grayscale"` (§9a) — scale so the
     long side equals `linedraw.canvas_px`, encode as PNG. PNG text
     chunks stay in the output — the offline harness scripts its
     cosine structure in them, and a live photograph's metadata is
     inert to the encoder.
  3. Cut the same five crops with the same `outline.crop_fraction`
     and encode the six images through the image-encoder slot.

- The image-level vector cache keys the photograph path as
  `sha256(encoder_hash + "photo-canonical-v1:{canvas_px}")` — with a
  `":grayscale"` suffix on the gray render — in the position the
  drawer hash holds on the `linedraw` path. No two render rules can
  share a cached vector.
- Stage p08 grouping and the p06 space mean read the stacked vectors
  as before — grouping simply moves to photograph-embedding space.
  The 0.95 threshold stays (§9 D5) and the V2 conditional row is the
  standing check on what it groups.
- The `linedraw` section stays required in a photograph-source
  config: `canvas_px` and `line_width_px` are the Layer 0 sketch
  render values (R2 of spec P2), read through the context loader.

## 5. The joint image-instruction embedding

`EmbeddingSlotConfig` gains one optional field, `instruction`,
default `None`.

- The config hash document omits the field at `None`, thus each
  released embedding hash — and each warm cache tree — stays
  unchanged (R5).
- With an instruction, the image encoder sends each item as two
  `content` entries, the instruction text first and the image
  second, the entry sequence the chat slots use. One embedding row
  comes back for the joint item. The cache entry records the
  instruction.
- The text encoder does not implement instructions and refuses one
  at construction (R7).
- The preparation `image_encoder` slot feeds its
  `instruction_template` into the slot config. A preparation
  `text_encoder` slot with an instruction is a config error (R7).
- The scoring `sketch_encoder` slot reads its
  `instruction_template` with the same rule (§9a): the instruction enters
  the slot hash, thus the scoring lineage and the sketch embedding
  cache fork by construction. The scoring `text_encoder` slot keeps
  the must-be-null rule (R7).

In `photo-instructed` the photograph side alone gets an instruction
— the query-and-document instruction shape of retrieval embedding
models. In `photo-instructed-sym` the sketch side gets one too
(§9a D6). R7 of spec P2 (one shared vector space) holds in each
condition: the model and dimension agree, and the instructions move
where photographs and sketches land in that space, which is the
bridge being tested.

## 6. The V1 union path

`build_union_index` reads `outline.source` from the preparation
config the record names:

- `linedraw`: unchanged — the p05 provider's `draw_lines` runs on
  each inserted photograph, then the crops encode.
- `photo`: no drawer is wired (R4). Each inserted photograph goes
  through the same canonical render, crop, and encode path as stage
  p06 (R2), into the same photograph-keyed vector cache.

The Rule 3 guard keeps its shape: each wired slot hash must equal
the preparation record's hash, with the line-drawer row dropped when
the source is `photo`. V2 reads the prepared index as committed and
does not change.

## 7. The run plan

Three new preparation configs, each pointing at the committed pool
release `dev-wit-001-b89d8614`, and the four conditions:

| Condition | Preparation config | Scoring config |
|---|---|---|
| `photo` | `dev-wit-photo.json` | `dev-wit-photo.json` |
| `photo-gray` | `dev-wit-photo-gray.json` | `dev-wit-photo-gray.json` |
| `photo-instructed` | `dev-wit-photo-inst.json` | `dev-wit-photo-inst.json` |
| `photo-instructed-sym` | the `photo-instructed` release | `dev-wit-photo-inst-sym.json` |

Each preparation config is the prep-002 document plus the §4 fields
— and for `photo-instructed`, the D1 instruction on the
`image_encoder` slot. `photo-instructed-sym` adds no preparation: it
scores the `photo-instructed` release with the D6 instruction on the
scoring `sketch_encoder` slot. Each scoring config is the committed
sketch-mode config with the preparation record, the tag, and — for
`-sym` — the sketch instruction changed, and nothing else (R1).

The owner runs, for each condition in turn (the `-sym` condition has
no preparation step and must follow the `photo-instructed` one):

```
uv run python -m pool.preparation --config configs/preparation/dev-wit-photo.json
uv run python -m validation.v1 --config configs/scoring/dev-wit-photo.json --report
uv run python -m validation.v2 --config configs/scoring/dev-wit-photo.json --report
```

Expected spend: about 1,350 pool embedding items (225 images, six
rows each) plus about 1,200 inserted-photograph items for each of
the three preparations and their V1 runs — the element side, the
describer, and the sketch side answer from cache at zero posts. The
`-sym` condition spends no image items and about 1,700 sketch items
(the 200 V1 and 500 V2 sketches plus the 1,000 background sketches,
embedded again behind the new sketch-slot hash). The preparations
run with no GPU (R4). Commit the preparation record and the harness
records after each condition, verdicts filled by the owner.

## 8. Measures and the baselines

For each condition, set against the committed prep-002 sketch-mode
records (`v1-dev-wit-99c8b508`, `v2-dev-wit-ab193017`):

| Measure | Control (prep-002) | Direction |
|---|---|---|
| V1 first-rank fraction | 0.405 | must increase materially for a kept change |
| V1 top-ten fraction | 0.735 | must increase, and the buried tail (rank above 50, 19 of 200) must shrink |
| V1 median rank | 2 | must not regress |
| V2 KS statistic (significance) | 0.0405 (0.385) | must stay a passing fit to `Uniform(0, 1)` |
| V2 conditional row | 0.248 at D=219 against 0.516 at D=224 | the distance to 0.5 must not widen |
| p08 member histogram | largest component 6 of 225 | report — grouping moves to photograph space |

Rules for the read:

- A V2 failure in a photograph condition is a Rule 3 audit before
  V1 is read: the likely cause is the group structure of the new
  embedding space, not the bridge itself.
- The commonness leak the committed records name (the standing
  measurement of `v2-dev-wit-ab193017` and `v2-dev-wit-c46466de`)
  has its own shape in photograph space. The conditional row and the
  KS numbers hold that measurement — record them, do not tune around
  them.
- The ladder localizes each effect. `photo` against the control
  measures the bridge. `photo-gray` against `photo` measures color.
  `photo-instructed` against `photo` measures the photograph
  instruction. `photo-instructed-sym` against `photo-instructed`
  measures the sketch instruction. Read the steps in that sequence
  before you set one condition against the control alone.
- V1 is the deciding measure. If no photograph condition beats the
  control, that is a recorded negative result and prep-002 stays
  the Phase 4 base. The releases stay on disk and in git in each
  outcome.
- No weight is fitted in this spec (I6). Sketch mode activates the
  outline channel alone, and the fusion weights stay the committed
  equal, unfitted values.

## 9. Open decisions — agreement required before the live run

The owner runs each live command, thus each default below sits
behind an owner checkpoint. Editing a config value before the run
moves the config hash and forks the lineage cleanly — no code change
follows.

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | The instruction text | `Represent this photograph for retrieval against rough freehand line sketches of the same scene. Encode the salient objects, their shapes, and their arrangement, not the photographic style, colors, or textures.` | The one free-text parameter. It sits in the config document and the config hash, not in code. |
| D2 | Canonical photograph render | RGB, long side scaled to `canvas_px` (512), PNG, no EXIF transform, text chunks kept | The photograph analog of the P2 canonical sketch render: one deterministic rule, shared by the pool and the inserted photographs (R2). |
| D3 | Condition names and tags | `photo` and `photo-instructed`, tags `dev-wit-prep-photo` and `dev-wit-prep-photo-inst` | Config files in §7. |
| D4 | Sketch-side instruction | none in this iteration | Holds the sketch side constant, thus the conditions change one step. The follow-up contingency if the instructed condition helps but does not close the style split. |
| D5 | Near-duplicate threshold in photograph space | keep 0.95 | The p08 histogram and the V2 conditional row measure what it does there. A threshold ruling can be its own iteration. |

## 9a. Rulings (2026-08-11)

The owner ruled on the §9 decisions on 2026-08-11:

- **D1, D2, D5** — each at its proposed default.
- **D3** — the defaults, extended with the ruled-in conditions:
  `photo-gray` (tag `dev-wit-prep-photo-gray`) and
  `photo-instructed-sym` (scoring tag `dev-wit-photo-inst-sym`).
- **D4** — overruled: the first live run includes a sketch-side
  instruction condition rather than holding it as a follow-up. The
  grayscale variant of the D2 render joins in the same ruling. The
  §8 ladder keeps each added condition one step from its neighbor,
  thus the one-cause-for-each-difference property survives the wider
  set.

The ruling opens two values with proposed defaults of their own,
behind the same owner checkpoint as D1 (the owner runs each live
command, and an edit before the run forks the lineage cleanly):

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D6 | The sketch-side instruction text | `Represent this rough freehand line sketch for retrieval against photographs of the scene it shows. Encode the salient objects, their shapes, and their arrangement.` | In `configs/scoring/dev-wit-photo-inst-sym.json`, on the sketch_encoder slot. The mirror of D1, without the ignore clause — a sketch has no photographic style to ignore. |
| D7 | The grayscale render rule | eight-bit grayscale, the other D2 values unchanged, cache token suffix `:grayscale` | In `configs/preparation/dev-wit-photo-gray.json` as `outline.photo_render`. |

## 9b. Rulings (2026-08-11, after the runs)

The four conditions ran on 2026-08-11 and the owner recorded eight
`pass` verdicts — the four V1 records and the four V2 records, each
with its compared measures in the notes. The headline: each
photograph condition beats the control on each §8 measure, the
`photo-instructed-sym` condition leads (first-rank 0.690 against the
control 0.405, top-ten 0.975 against 0.735, zero pairs above rank
50 against 19), and each V2 keeps its fit to `Uniform(0, 1)`.

The same ruling adds the two factorial cells the §8 ladder left
open. Each is one scoring config against a released
preparation — no new preparation, and each embedding they read is
in cache from the recorded runs:

| Cell | Scoring config | What it isolates |
|---|---|---|
| `photo-sym` | `configs/scoring/dev-wit-photo-sym.json` | The photograph-side instruction in the winning recipe: if this cell equals `photo-instructed-sym`, the photograph instruction contributes nothing and the simpler config wins. |
| `photo-gray-sym` | `configs/scoring/dev-wit-photo-gray-sym.json` | If the suggestive grayscale increase stacks with the decisive sketch-instruction effect. |

The adoption ruling — which condition becomes the Phase 4 base —
waits for these two cells.

## 10. Acceptance criteria

1. `outline.source` and `outline.photo_render` parse, default to
   the unchanged rule, keep the missing-field hash byte-for-byte,
   and move the preparation config hash when set (hash-sensitivity
   tests). A render variant without the photo source is a config
   error.
2. `EmbeddingSlotConfig` without an instruction hashes as before,
   an instruction moves the hash, the `POST` item holds the two
   `content` entries, and the text slot refuses an instruction —
   offline tests with the mock transport. The scoring sketch slot
   reads its instruction into the slot hash and the wiring. The
   scoring text slot keeps the must-be-null rule.
3. A photograph-source preparation runs end to end on fake
   providers with no drawer wired, and its p06 vectors come from
   the photograph bytes — in the color and the grayscale renders,
   each behind its own cache token.
4. The V1 harness runs on a photograph-source preparation with fake
   providers, keeps its Rule 3 guard, and ranks the scripted pairs
   as the linedraw fixture does — in each of the four conditions.
5. `uv run pytest` stays green offline. Vale reports zero errors on
   changed files.
6. The four conditions are run by the owner, the records committed,
   and the §8 measures recorded in the record notes with verdicts —
   or a recorded stop names what stood in the path.
7. No §9 or §9a decision is implemented against a different value
   without a recorded ruling.
