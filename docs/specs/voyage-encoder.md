# Spec VE1 — the Voyage encoder slot and its bake-off

**Status:** rulings recorded 2026-11-03. The verdict (§6) stays
open until the bake-off records are on file.
**Phase:** before the production pool (spec PP1).
**Architecture sections:** §3 (the invariants), §21 (versioning).
**Working agreement:** `CLAUDE.md` §2 (I3, I4), §3 (no silent
fallbacks), §5, §6, §10.
**Amends:** PP1 ruling 8 (the encoder), with a dated note there.

---

## 1. Purpose

`voyage-multimodal-3.5` is a candidate for each encoder slot: the
curation `encoder`, the preparation `text_encoder` and `image_encoder`,
and the scoring `sketch_encoder` and `text_encoder`. The owner has
credits for 200 M text tokens and 150,000 M pixels on this model.

This spec adds the provider and a gate. It does not put the model in
the production configs.
Scoring quality is the open question: the model is described for
documents, slides, and screenshots, and no published result speaks for
rough sketches against photographs.

**This is one provider, not a pipeline rewrite.** The protocols, the
curation and preparation stages, and the channels do not move. The
describer, the screens, and the generalizer stay on the OpenRouter chat
model, because Voyage has no chat model.

---

## 2. Owner rulings

1. **Bake-off first.** Voyage goes into the production configs
   only if §6 clears. If it does not clear, Gemini stays, and the
   USD 20 plan of PP1 §5a holds.
2. **The key stays out of each transcript.** The owner runs each
   command that touches the network, with `VOYAGE_API_KEY` in the
   environment.

---

## 3. The provider

`providers/voyage/` implements `ImageEncoder`, `SketchEncoder`, and
`TextEncoder` through `POST /v1/multimodalembeddings`.

| Field | Value | Why |
|---|---|---|
| `truncation` | `false` | The default `true` can drop a full image from an input with no error. That is a silent fallback (`CLAUDE.md` §3). |
| `input_type` | `null` | The value `query` or `document` adds a fixed prompt. The instruction text of spec P2c is the item in the test, and one item moves at a time. |
| `output_encoding` | `"base64"` | Accurate float32 values. A cache entry is about 5.5 KB at 1024 dimensions, against 55 KB for JSON floats at 3072. |
| dimension | not sent, config pins 1024 | The model page names values, and the API reference names no field for them. The default is 1024. The provider checks each row against the pinned value. |

An item is `{"content": [...]}`. With an instruction, the text entry is
first and the `image_base64` entry is second, the same sequence as the
OpenRouter slot. The text slot sends one text entry.

**The synchronous endpoint only.** The free credits do not apply to the
Batch API.

**Hash.** The config hash covers the provider name, the slot, the model,
the dimension, the three fields above, and the instruction when one is
set. Voyage publishes no weights revision, thus the hash cannot hold
one as `CLAUDE.md` §6 asks. Gemini has the same limit. `tools/voyage_smoke.py`
compares a canary vector with its last stored value, which finds a
silent change of the model.

**Limits.** One `POST` holds at most 64 items, 8 MB of input, and
320,000 estimated tokens. The estimate is pixels / 560 for an image and
one token for each three characters of text. A `POST` that times out
splits in half, as the OpenRouter slot does.

**Account limits are not config.** The owner's rate limit comes from the
account, as the key does. The defaults are the published
first tier (2,000 `POST`s and 2 M tokens each minute). The environment
values `VOYAGE_REQUESTS_PER_MINUTE` and `VOYAGE_TOKENS_PER_MINUTE`
change them, and no hash moves. The docs give no limit for an account
with no payment method.

**Spend.** The client adds the `image_pixels` and `text_tokens` values
of each response, and each encoder gives them as `usage`.
`tools.voyage_smoke` prints them. The Voyage dashboard is the record of
credit use. The harness records keep their POST and cache-hit counts,
with no new field.

---

## 4. Repairs this slot makes necessary

- **The fake fallthrough.** `validation/harness.py` wired a fake encoder
  for each scoring slot that was not `openrouter`, with no error. With
  `voyage` in the allowed set, that path gives hash-derived vectors
  that look ordinary. Each provider has its own branch at this time, `fake` has
  an explicit branch, and an unknown name raises.
- **The server space check.** V1 and the fit compare the sketch slot
  with the pool image slot. The server compared the text slot alone. It
  does the two checks at this time.
- **An explicit model.** The `openrouter` default model is a chat model.
  A `voyage` slot with no `model` is refused at config load.

---

## 5. The near-duplicate threshold is not portable

The value 0.95 applies to the Gemini space alone (mean pair cosine 0.58 at
s06, 0.805 at p08, maximum 0.897 and 0.910). It removed no image on
the working runs, and no positive control shows what it catches.

`validation/neardup_calibration.py` is that control. It makes
duplicate variants of pool images: a new JPEG encode, a small crop,
a resize, and a small brightness change. It reports the cosine
values of each variant against its source, and of pool pairs,
in the s06 space and in the p08 space. **The owner rules on the
thresholds from those numbers.** The tool picks no value.

I3 uses this value, thus the calibration runs before the bake-off
verdict. If p08 groups images at 0.95 in the Voyage space, the bake-off
numbers wait for the ruling.

Sinkhorn `epsilon` 0.1 and its zero-similarity reserve also change with
the cosine scale. The bake-off report gives the similarity quantiles,
and a large change goes to the owner.

---

## 6. The bake-off and the adoption rule

**Pool:** `dev-wit-002`, unchanged. V1 adds the inserted photographs,
thus a first-rank trial is first of 404 images, not 204. **Weights:** `{element: 0.45,
outline: 0.55}`, unchanged, thus the numbers compare directly. These are
Gemini's weights: the verdict compares encoders, and the production fit
replaces the weights in each path.

| Cell | Prep config | Scoring configs |
|---|---|---|
| Voyage, with instructions | `dev-wit-voyage-inst` | `dev-wit-voyage-inst-sym`, `dev-wit-voyage-inst-mixed`, `dev-wit-voyage-text` |
| Voyage, no instructions | `dev-wit-voyage-plain` | `dev-wit-voyage-plain-sym`, `dev-wit-voyage-plain-mixed` |
| Gemini baseline | `dev-wit-photo-inst-2` (committed) | `dev-wit-photo-inst-sym-3`, `dev-wit-mixed-3` (committed), `dev-wit-text-3` |

Spec P2c measured the instruction effect as an interaction on Gemini.
It can be larger or smaller on Voyage, thus the plain cell is in the
set.

**The adoption rule (proposed in the plan of 2026-11-03, accepted with
it).** The image and sketch slots move to Voyage together when one Voyage cell,
on the same 200 pairs as the baseline, clears all of these:

1. Not significantly below the baseline by a paired McNemar test on
   first-rank trials: two-sided p of 0.05 or more, or a higher first-rank
   fraction.
2. First-rank fraction of 0.63 or more (baseline 0.68).
3. V2 KS significance above 0.05 in the sketch mode and the mixed mode.

The text slot moves on its own by rules 1 and 3 on V1 text, because no
channel compares text with images.

**Limit of this test.** 200 pairs give moderate power, and a small loss
can get through rule 1. Rule 2 is the fence for that. The numbers go on
record, and the verdict is the owner's.

`validation/bakeoff.py` reads the `trials.jsonl` of two V1 runs and gives
the paired table. It writes nothing to a config.

**Note, 2026-11-09: what the tool checks.** A read of the tool found
that it accepted evidence that was not the candidate's. It has these
checks at this time:

- **Mode.** The two V1 runs have one submission mode, which comes from
  the `meta.json` of each run. The floor of rule 2 shows for a sketch
  run alone. A text run gets rules 1 and 3. No rule reads a mixed V1
  run, thus the tool gives its table with no rule line.
- **Rule 3 is in each report.** Each V2 mode that rule 3 names gets a
  line. A mode with no `--v2` record gets a line that does not hold.
- **The V2 records are the candidate's.** The tool refuses a V2 record
  with a different `preparation_version_id`. The record of the
  candidate's mode also has the candidate's `scoring_config_hash`.
- **The rows agree with the record.** The first-rank fraction of the
  trial rows equals `first_rank_fraction` in the V1 record. A second V1
  run writes the rows again, and a record with a verdict stays.
- **Decoy counts.** V1 groups near-duplicates across the pool and the
  inserted photographs, in the encoder space of each run. The Gemini
  baseline has such groups: its decoy count is 403 on 175 pairs, 402
  on 18, 401 on 3, and 400 on 4. The sentence in §5 about no removed
  image is about the pool alone. The tool prints the counts of the two
  runs, and a line that holds only when each pair has equal counts. It
  also prints a lower bound for the candidate's first-rank fraction.
  The bound counts each first rank on a pair with fewer decoys as not
  first. When the counts move, the numbers wait for the threshold
  ruling of §5.

**Estimated cost:** less than 2,000 M pixels from the credits (0.11
for each pool preparation, about 0.4 of inserted photographs, about
0.4 of sketches in each V1 and V2 pair). Describer and box responses come
from the cache, thus the OpenRouter spend is about zero.

---

## 7. What the move to Voyage changes

These land on the build branch of the pool, not in this spec:

- `configs/curation/prod-wit.json` and the preparation and scoring
  configs name `voyage` and the measured thresholds.
- PP1 §5 and §5a get the new costs: USD 8.20 of embeddings go out of
  the budget, thus USD 10.90 of the USD 19.10 plan stays.
- The server environment gets `VOYAGE_API_KEY`. Each close and each
  practice score then posts to Voyage, and not to OpenRouter.
- The privacy text names Voyage. MongoDB can use data sent to this API
  to make models better. The owner checks the training control of the
  account before player data goes there.
- The backup holds the production vector cache. If the model retires,
  a stored day can rescore from that cache alone.

---

## 8. Runbook

Each step ends with numbers. The owner runs them with the key in the
environment, and the key stays out of each transcript.

1. **The account.** Find the rate limit on the dashboard, and add a
   payment method if the limit is low. The credits apply first.
2. **Smoke:** `uv run python -m tools.voyage_smoke`.
3. **The Voyage preparations:**
   `uv run python -m pool.preparation --config configs/preparation/dev-wit-voyage-inst.json`,
   then the same with `dev-wit-voyage-plain.json`. Read the p08 group
   count of each. These commands also wire the describer and the box
   slot, thus `OPENROUTER_API_KEY` must be in the environment with
   `VOYAGE_API_KEY`. The two slots answer from the cache.
4. **Calibration:** `uv run python -m validation.neardup_calibration
   --config configs/preparation/dev-wit-voyage-inst.json
   --curation-config configs/curation/dev-wit-voyage.json`. Record a
   ruling if p08 grouped images. For the first positive control of the
   Gemini space, give `dev-wit-photo-inst-2.json` and
   `configs/curation/dev-wit-2.json` to the same two options, with the
   OpenRouter key.
5. **Gates:** `validation.v2` and `validation.v1`, each with `--config`
   and `--report`, on each new scoring config, and V1 on `dev-wit-text-3`
   and `dev-wit-mixed-3`. V1 wires the describer, thus each V1 command
   wants the two keys. The sketch baseline record is on file:
   `validation/records/v1-dev-wit-sym-3-d4f8019b.json`.
6. **The tables:** `uv run python -m validation.bakeoff --baseline
   <v1 record> --candidate <v1 record> --v2 <v2 record> --v2 <v2 record>`,
   one time for each line of this table. The `--v2` records are the
   candidate's.

   | Table | Baseline V1 | Candidate V1 | `--v2` modes |
   |---|---|---|---|
   | Image and sketch slots, with instructions | `dev-wit-sym-3` | `dev-wit-voyage-inst-sym` | sketch, mixed |
   | Image and sketch slots, no instructions | `dev-wit-sym-3` | `dev-wit-voyage-plain-sym` | sketch, mixed |
   | Text slot | `dev-wit-text-3` | `dev-wit-voyage-text` | text |
   | Mixed, for the record | `dev-wit-mixed-3` | `dev-wit-voyage-inst-mixed` | none |

   The text table and the mixed table are the ones that print the
   similarity quantiles of §5. Read the decoy lines of each table before
   the rule lines.
7. **The verdict:** the owner's, with the numbers, in §9 of this spec.

---

## 9. Verdict

Open.
