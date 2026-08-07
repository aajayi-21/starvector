# Spec P1b — Pool preparation pipeline

**Status:** draft, for review.
**Phase:** 1 — build the pool (`docs/ARCHITECTURE.md` §25), second component.
**Architecture sections:** §5 (pool preparation), §10 (encoders), §11 (the
style bridge), §12 (channels, as consumers), §18 (the tiered element
channel, as a consumer), §21 (versioning).
**Working agreement:** `CLAUDE.md` §5 (interchangeability), §6 (provider
agnosticism), §7 (development build).
**Input:** one released pool version from spec P1a
(`docs/specs/pool-curation.md`).

This spec is written for implementation by an AI agent. It defines
contracts, file layouts, and acceptance criteria. Where the architecture
does not give a value or a rule, this spec says so in §16 and proposes a
default. Do not implement an open decision without agreement.

---

## 1. Purpose

This pipeline turns a released **pool** into the cached artifacts that the
scoring layers read. The architecture defines pool preparation as the
offline work that runs one time for each image and configuration hash
(§5): the element list for each image, the pool **vocabulary** and
**incidence table**, the line drawing for each image, the outline vectors,
the element boxes, and the near-duplicate groups. The interactive path
reads these caches and does not touch an image file.

Preparation does not select images. The pool membership is frozen by the
curation release, and this pipeline computes artifacts for that membership,
all of it, with no additions and no removals. This is the structural
difference from curation: curation decreases a candidate set, preparation
transforms a fixed set.

The development build prepares the released development pool. The code
must not know which pool it prepares — the release record is a config
input.

## 2. Scope

**In scope**

- Intake of a released pool — the release record plus the stored image
  bytes, with checks.
- Element extraction with the fixed schema of §5 of the architecture,
  through a `VlmDescriber` provider slot (OpenRouter first — U2).
- Element normalization, the 20-entry cap, the vocabulary, the vocabulary
  vectors, and the incidence table.
- Line drawings with the post-processing of §11 of the architecture, and
  the canonical re-render.
- Outline vectors: full image plus a crop grid, unit-norm, with the pool
  mean vectors that §10 of the architecture requires when vectors are
  compared.
- Element boxes for the placement channel, through an `ElementBoxDetector`
  provider slot.
- Near-duplicate **grouping** on outline vectors, with a group identifier
  for each image (§5). Layer 8 reads this.
- A preparation release record, committed, attached to the pool version.
- A resumable runner with the same shape as the curation runner.

**Out of scope** — specs that follow cover these.

- Commonness scores: they are calculated from the background set with
  channels in operation (architecture §13.2). Phase 4.
- Tag vectors for frontload filtering (architecture §20).
- The submission side: Layers 0 through 9, rarity weights at scoring time,
  and the validation harnesses V1 through V6. Rarity weights are derivable
  from the p04 artifacts and are computed for each submission, not stored
  here.
- Sketch-side encoding. The sketch encoder is its own slot (`CLAUDE.md`
  §6) and has no pool-side artifact.

## 3. Terms this spec adds

The glossary in `docs/ARCHITECTURE.md` §2 defines all scoring terms
(element, element list, vocabulary, pool). This spec adds pipeline terms
only.

| Term | Meaning |
|---|---|
| **Preparation config** | The frozen parameter object for one full preparation run. Its hash is part of each artifact key. |
| **Preparation version** | The released output: one pool version prepared with one preparation config. |
| **Preparation record** | A small committed file that documents one preparation version. |
| **Image-level cache** | An artifact that depends on one image and one provider config only — element responses, line drawings, outline vectors, box responses. Shared across pool versions. |
| **Pool artifact** | An artifact that depends on the pool membership — capped element lists, vocabulary, incidence table, pool means, near-duplicate groups. Keyed by pool version and preparation config. |
| **Flatten sequence** | The fixed sequence in which the schema fields of one element response become the element list. |
| **Element box** | One rectangle, normalized to [0, 1] in the two axes, that locates one element in one image. |

## 4. Requirements from the architecture

Numbers in this section come from the architecture and are not negotiable.

- **R1** — The artifact set is the §5 table, minus the out-of-scope rows:
  element list, element vectors, element boxes, line drawing, outline
  vectors, near-duplicate group.
- **R2** — The element response is the fixed structure of §5: `objects`,
  `materials`, `colors`, `shapes`, `scale`, `setting`, `ambience` — not
  free text. The field set is frozen (`CLAUDE.md` §5). A schema change
  invalidates each stored element list and each rarity weight.
- **R3** — The element list is capped at 20 entries, and its length is
  kept roughly constant. When there are more than 20, keep the 20 with
  the highest rarity weights (§5).
- **R4** — Vocabulary normalization is light: lowercase, strip articles,
  singularize (§5). The architecture's estimate at full pool scale is
  10,000 to 20,000 entries.
- **R5** — Each vocabulary entry is encoded one time with the text
  encoder, giving a matrix of shape `|V| × d` (§5).
- **R6** — The incidence table is a dense padded array of shape `N × 20`:
  for each pool image, the vocabulary indices its elements occupy (§5).
- **R7** — The line drawing comes from a photo-to-drawing model —
  Informative Drawings is the architecture's verdict (§11) — followed by
  binarize, removal of short segments, and a canonical re-render with the
  same resolution, line width, background, and anti-aliasing parameters
  as player sketches. The architecture says the re-render is easy to skip
  and expensive to skip.
- **R8** — Outline vectors are the image encoder applied to the line
  drawing, full image plus a small crop grid, because the outline channel
  takes a maximum across crops (§12.2, §18).
- **R9** — A provider's output vectors are unit-norm (§10, `CLAUDE.md`
  §6). The pool mean vector of each encoder space is subtracted before
  vectors are compared (§10). Preparation computes and stores those
  means.
- **R10** — Near-duplicate grouping runs on outline vectors at a tight
  threshold, start value 0.95 cosine, and stores a group identifier for
  each image (§5). Layer 8 removes the target's full group from the
  decoy set — this is required by Rule 3.
- **R11** — Element boxes come from an open-vocabulary detection
  capability and are the input of the placement channel (§5, §12.3). The
  channel is optional. The artifact is in scope by user decision
  (2026-08-07).
- **R12** — Each derived artifact is a cache. Its key contains the hash of
  the configuration that made it, and it is possible to make it again
  from the source (§3 Rule 4, §21).
- **R13** — Pool membership is frozen. Preparation must not add an image
  and must not remove an image. An image that cannot be prepared stops
  the run. The fixes are a provider change or a new curation release —
  the two are recorded, deliberate events. A silent skip here changes the
  decoy set and breaks Rule 3.
- **R14** — No silent fallbacks. A provider error, a response that does
  not parse, or an unexpected shape raises (`CLAUDE.md` §3).
- **R15** — A preparation of a development pool is development-only. The
  preparation record carries the `dev_only` flag of its pool release and
  the `dev-` tag prefix rule of P1a §6.

### User constraints

These come from the project owner, not from the architecture. They have
the same weight.

- **U1 — OpenRouter `POST` accounting.** The account has a limit on
  `POST` operations. Each OpenRouter-backed stage reports its `POST`
  count and its cache-hit count in `meta.json`, and the report shows
  them. Responses are cached (R12), thus a re-run or resume makes no new
  `POST` operations for unchanged config. There is no byte budget in
  this pipeline — there is no corpus extraction here.
- **U2 — OpenRouter first, local drop-ins.** The `VlmDescriber` and
  `ElementBoxDetector` slots run through OpenRouter chat completions in
  the development configuration (user decision, 2026-08-07). The
  `TextEncoder` and `ImageEncoder` slots run through the OpenRouter
  embeddings endpoint — `POST /api/v1/embeddings`, with image input
  through content blocks (checked live, 2026-08-07). An earlier version
  of this constraint said no embedding models were served — that is no
  longer so. The development default is the multimodal model
  `google/gemini-embedding-2` (user decision, 2026-08-07). Local
  implementations (SigLIP 2 towers) stay drop-in replacements for the
  encoder slots. The `LineDrawer` slot always runs locally — no
  OpenRouter equivalent exists. This spec introduces `providers/local/`
  at implementation time.

## 5. Pipeline overview

```
released pool (release record + image store)
      │
      ▼
p00 intake       verify membership and bytes, record dims  ──► records
p01 elements     VlmDescriber, fixed schema                ──► element responses
p02 normalize    lowercase, strip articles, singularize    ──► normalized element lists
p03 cap          keep the 20 highest-rarity entries        ──► capped element lists
p04 vocabulary   vocabulary, TextEncoder matrix, incidence ──► pool artifacts
p05 linedraw     LineDrawer + post-process + re-render     ──► line drawings
p06 outline      ImageEncoder, whole + crops, pool mean    ──► outline vectors
p07 boxes        ElementBoxDetector on capped elements     ──► element boxes
p08 neardup      grouping at 0.95 on outline vectors       ──► group table
p09 release      preparation version + committed record    ──► preparation record
```

No stage rejects an image (R13). Each stage covers the full membership or
raises. Stages p01 through p04 are the element side. Stages p05, p06, and
p08 are the outline side. Stage p07 requires the capped element lists of
p03 and the dimensions of p00. The runner executes in the numbered
sequence — the simple correct path first (`CLAUDE.md` §7).

### Functional core, imperative shell

The split is the same as P1a §5. Decision logic — flattening,
normalization, the cap rule, vocabulary construction, crop geometry, the
grouping rule — is pure functions in `pool/preparation/stages/`, with no
file access, no network, and no clock. The runner in
`pool/preparation/run.py` does all reads, writes, and provider wiring.

## 6. Identity and versioning

### Preparation config hash

`preparation_config_hash` is the SHA-256 hex digest of the canonical JSON
of the full `PreparationConfig` (§9), which contains each provider
`config_hash`. Each parameter change makes a new hash and thus a new pool
artifact tree — no artifact is overwritten (R12).

### Preparation version

```
preparation_version_id = sha256(pool_version_id + preparation_config_hash)
```

Byte layout: the two components are lowercase hex strings, concatenated,
encoded as UTF-8. There is no membership hash — `pool_version_id` fixes
the membership. The release label is `<tag>-<preparation_version_id[:8]>`,
with the `dev-` prefix rule of R15.

### Two cache tiers

Image-level caches are keyed by `image_id` and the producing slot's
`config_hash` only. They do not contain the pool version, thus two pool
versions that share an image share its element response, line drawing,
outline vectors, and box responses. Pool artifacts are keyed by
`pool_version_id` and `preparation_config_hash`. The p07 box response is
image-level but depends on that image's capped element list, thus its key
also contains the hash of that element list (§10).

## 7. Input — the released pool

The config names one committed release record
(`pool/releases/<label>.json`, P1a §10 s09). Intake (p00) must:

- Parse the record and read `pool_version_id`, the membership count, and
  `dev_only`.
- Load the release-stage manifest of that curation run to get the
  `image_id` set, and make sure the count agrees with the record.
- For each `image_id`: load the bytes from the shared image store
  (`data/images/raw/`), make sure that `sha256(bytes) == image_id`,
  decode, and record width, height, and format in its own
  `records.jsonl`. Preparation reads no other file from the curation
  tree — the release record and the image store are the full interface
  between P1a and P1b.
- The stage raises, with the missing or bad identifiers named, when bytes
  are missing or hashes do not agree. The image store is a cache (R12).
  The operator makes it again with a new curation s02 run for that corpus
  and config.

## 8. Model provider slots

Preparation needs five capability protocols in `providers/protocols.py`.
Each follows `CLAUDE.md` §6: batched, config-hashed, output-normalized at
the boundary. `ImageEncoder` exists from P1a. The four other protocols
are new. The fake implementations are required for the test suite.

| Protocol | Contract (shape) | Used by | OpenRouter? |
|---|---|---|---|
| `VlmDescriber` | `Sequence[bytes] -> Sequence[ElementResponse]` — the R2 schema, parsed and validated | p01 | Yes (U2) |
| `TextEncoder` | `Sequence[str] -> Vectors` — unit-norm, `(B, d)` | p04 | Yes — embeddings endpoint (U2) |
| `ImageEncoder` | `Sequence[bytes] -> Vectors` — unit-norm, `(B, d)` | p06 | Yes — embeddings endpoint (U2) |
| `LineDrawer` | `Sequence[bytes] -> Sequence[bytes]` — canonical rendered line-drawing PNG bytes | p05 | No — local only (U2) |
| `ElementBoxDetector` | `(Sequence[bytes], Sequence[Sequence[str]]) -> Sequence[Mapping[str, Box \| None]]` — for each image, each queried element maps to one normalized box or `None` | p07 | Yes (U2) |

Notes:

- `ElementResponse` is a frozen record with the R2 fields. The provider
  parses and validates at the boundary (R14): a response that does not
  parse, an empty field, or a field count not in the configured limits
  raises with the `image_id` named.
- The `ImageEncoder` slot here is the Layer 2 image encoder slot of §10 of
  the architecture. It is not the curation encoder of P1a — that slot has
  its own hash and its own lifecycle. The two can load the same weights —
  each keeps its own configuration and hash (`CLAUDE.md` §6).
- `LineDrawer` output is the finished canonical rendering. Model
  inference, binarize, short-segment removal, and the canonical re-render
  are all internal to the provider, controlled by its config — R7 makes
  the post-processing part of what the artifact *is*. Its `config_hash`
  covers model weights and all post-processing parameters.
- A `Box` is `(x_min, y_min, x_max, y_max)`, each in [0, 1], relative to
  the decoded image. `None` records "not located" and is a permitted
  answer, not an error — §12.3 of the architecture scores only located
  elements.
- The two OpenRouter slots use the P1a §8a client, cache, and rules
  again: one `POST` for each image, temperature 0, fixed instruction
  template, strict JSON output format, validation on cache hits,
  `config_hash` covering model identifier, template, and API parameters.

### Local providers

`providers/local/` arrives with this spec: the SigLIP text and image
towers as drop-in alternatives for the `TextEncoder` and `ImageEncoder`
slots, and the line-drawing model behind `LineDrawer` — the one slot
with no remote implementation (decisions D3, D4). Rules from
`CLAUDE.md` §6 apply: device placement, dtype, and batching are
provider-internal, with deterministic inference parameters. The torch
stack lives in its own dependency groups — `local-cuda` for NVIDIA
machines, `local-xpu` for Intel GPUs through the PyTorch XPU wheels —
thus the default environment and the test suite stay free of it. The
`runtime.device` config value selects the device at wiring time. The implementation must make sure
that wheels for the pinned Python version are available before install.
The test suite must not import the local stack.

## 9. Configuration

One frozen `PreparationConfig` dataclass, loaded from a committed JSON
file (`configs/preparation/dev-wit.json` for the development build), with
the strict validation rule of P1a §9: a missing or unknown field stops the
load (R14). Sections:

- `input`: the release record path.
- `elements`: the field-count contract for the R2 schema (D2),
  `max_elements` (the R3 cap, value 20), and `normalize_rule` — the
  identifier of the D7 rule table (value `d7-v1`), in the config thus a
  rule change moves the hash.
- `linedraw`: binarize threshold, minimum segment length, and the
  canonical render parameters — canvas dimensions, line width,
  background, anti-aliasing (D5). These render parameters are shared
  constants with the future Layer 0 sketch render. The spec that builds
  Layer 0 must read them from one source.
- `outline`: the crop grid definition (D6).
- `neardup`: `similarity_threshold`, start value 0.95 (R10).
- `providers`: the OpenRouter client section (P1a §9 shape), then one
  section for each of the five slots — provider selection, model, and
  instruction template where applicable.
- `runtime`: machine-local execution values — `device`, one of `auto`,
  `cuda`, `xpu`, `cpu`. This is the one section that is not part of
  `preparation_config_hash`: the device is machine-local, and a device
  change must not fork the artifact lineage. The determinism scope of
  §14 stays one machine and environment.
- `release`: `tag`, `dev_only`.

The loaded object is passed as an argument. No code reads global config.

## 10. Stages

Contract for all stages: a stage reads its parent artifacts and writes one
stage directory (§11) with its artifacts and a `meta.json`. Counts must
agree: each stage covers the full membership `N`. All processing, output
sequence, and equal-value decisions use ascending `image_id`.

### p00 intake

The checks of §7. Writes `records.jsonl`: one row for each image with
`image_id`, `width`, `height`, `format`. `meta.json` records the pool
version, the release record path, and `N`.

### p01 elements — R2

`VlmDescriber` on each image, through the response cache (U1). The stage
stores the parsed response as one canonical JSON row for each image. The
flatten sequence is fixed (D8): `objects`, then `materials`, `colors`,
`shapes`, `scale`, `setting`, `ambience`. The flatten step runs in p02.
This stage stores the structured response, thus a flatten-rule change
does not force new VLM requests (R12).

### p02 normalize — R4

Pure function on each element string: Unicode NFC, lowercase, replace
each internal whitespace run with one space, strip one leading `a`, `an`,
or `the`, singularize the last word with the fixed rule table of D7. No
model — the rule is deterministic and versioned by the config hash. The
architecture accepts a fixed rule where a model version must not move
stored boundaries (§6), and that argument applies here. After
normalization, duplicate strings in one image keep the first occurrence
in the flatten sequence. The stage writes each image's normalized,
deduplicated, uncapped element sequence.

### p03 cap — R3

Pool-level pure function. With `df(e)` = the count of images with `e` in
their p02 sequence, each entry's capping rarity is `−log(df(e) / N)`,
with the natural logarithm — the project measures rarity in nats.
For each image, keep the `max_elements` entries with the highest capping
rarity. Break equal values by the flatten sequence position, first
position first (D8). Kept entries keep their p02 relative sequence —
selection is by rarity, presentation stays in flatten sequence. The stage records what was cut, for each image, with
the measured `df` values — this is the §5 rule "keep the 20 with the
highest rarity weights" applied with the document frequency the pool
itself defines.

### p04 vocabulary — R4, R5, R6

Pool-level. The vocabulary is the sorted set of the deduplicated strings
from all capped element lists — ascending lexicographic sequence fixes
the indices. Writes:

- `vocabulary.jsonl`: index, string, `pool_frequency` (the count of
  images with the string in their capped element list). Rarity weights
  at scoring time derive from `pool_frequency / N` — nothing more is
  needed from this pipeline (architecture §12.1).
- `vocabulary_vectors.npy`: the `TextEncoder` applied to each entry
  (template rule D12), shape `|V| × d`, float32, unit-norm rows (R5, R9).
- `incidence.npy`: shape `N × max_elements`, integer, rows in ascending
  `image_id` sequence, entries in the capped element sequence, padded
  with `−1` (R6).
- `element_space_mean.npy`: the mean of the vocabulary vectors (D11),
  stored for the R9 subtraction when vectors are compared.

### p05 linedraw — R7

`LineDrawer` on each image, through the image-level cache. The provider
returns finished canonical PNG bytes (§8). The stage stores them
content-addressed in the line-drawing cache and writes one row for each
image: `image_id`, `line_drawing_key`, byte count.

### p06 outline — R8, R9

Pure crop geometry plus `ImageEncoder`. For each line drawing: the full
image and the crop grid of D6 become individual images, encoded in one
batch, giving `(1 + crops) × d` unit-norm float32 rows for each image.
Row layout, fixed: row 0 is the full image, rows 1 through 5 are the
crops in the sequence center, top-left, top-right, bottom-left,
bottom-right. Crop pixel dimensions use the floor of canvas times
fraction.
Writes the pool-level stacked array `outline_vectors.npy` of shape
`N × (1 + crops) × d`, rows in ascending `image_id` sequence, plus
`outline_space_mean.npy` (D11). Image-level vectors are also cached with
the encoder and line-drawer hashes in the key, thus a pool re-release
uses them again.

### p07 boxes — R11

`ElementBoxDetector` on each image with its capped element list as the
query set. The response cache key contains `image_id`, the slot
`config_hash`, and the hash of the queried element list (§6). Writes one
row for each image: for each element, one box or `null`. Box coordinates
must be in [0, 1] with `x_min < x_max` and `y_min < y_max` — the
provider validates at the boundary (R14).

### p08 neardup — R10

Pool-level pure function on the full-image outline vectors (crop rows
are not read — D9). Build the graph with one edge for each pair at cosine
similarity at or above `similarity_threshold`. The groups are the
connected components (D9). Writes `groups.jsonl`: `image_id`,
`group_id`, member count of the group. `group_id` is the smallest
`image_id` in the component — stable and content-derived. For the
development pool the full `N × N` computation is required. Approximate
methods are a full-scale optimization and must not change results at the
threshold (`CLAUDE.md` §7). `meta.json` reports the histogram of group
member counts — a giant component is a signal that the threshold or the
bridge is not correct, and the report must show it before Layer 8 finds
it.

### p09 release

Calculate `preparation_version_id` (§6). Write the preparation record to
`pool/preparations/<label>.json`, **committed to the repository** (R12,
P1a R11 analog). Contents: pool version reference (label, id, record
path), `preparation_config_hash`, config file path, `N`, the artifact
inventory with content hashes of each stage data file (`meta.json` and
`timings.json` excluded — meta content includes `POST` counts, which
are different between a cold and a warm run), provider config
hashes, `POST` and cache-hit counts for each OpenRouter slot (U1),
`dev_only`, pipeline code version, and creation timestamp.

## 11. Artifacts and storage layout

The data-root rules of P1a §11 apply: bulk artifacts in `data/` are
caches, small durable records are committed.

```
data/
  preparation/<pool_version_id[:8]>/<preparation_config_hash[:8]>/
    p00-intake/     records.jsonl  meta.json
    p01-elements/   elements.jsonl  meta.json
    p02-normalize/  normalized.jsonl  meta.json
    p03-cap/        capped.jsonl  cuts.jsonl  meta.json
    p04-vocabulary/ vocabulary.jsonl  vocabulary_vectors.npy
                    incidence.npy  element_space_mean.npy  meta.json
    p05-linedraw/   drawings.jsonl  meta.json
    p06-outline/    outline_vectors.npy  outline_space_mean.npy  meta.json
    p07-boxes/      boxes.jsonl  meta.json
    p08-neardup/    groups.jsonl  meta.json
    p09-release/    meta.json
  images/
    raw/<image_id[:2]>/<image_id>                 # from P1a, read only here
    linedraw/<linedrawer_config_hash[:8]>/<image_id[:2]>/<image_id>.png
  cache/
    openrouter/<provider_config_hash[:8]>/        # P1a layout, shared
    vectors/<encoder_config_hash[:8]>/            # image-level outline vectors

pool/preparations/<label>.json                    # committed
configs/preparation/dev-wit.json                  # committed
```

File formats follow P1a §11: canonical JSON, one object on each line in
`.jsonl`, deterministic `meta.json`, and `timings.json` as the one file
determinism comparisons do not read. Array artifacts are `.npy`, float32
or int32, with shapes and row sequence documented in `meta.json`.

## 12. Runner

```
uv run python -m pool.preparation --config configs/preparation/dev-wit.json \
    [--through p06] [--force-from p04] [--report]
```

Same contract as P1a §12: resume on complete `meta.json`, `--force-from`
deletes forward in this config's tree only, `--report` prints coverage,
artifact counts, and the U1 `POST` counts for each stage. The runner is
a library function first (`run_preparation(...) -> PreparationReport`)
with the CLI as a thin wrapper, because a UI will use it. There is no
review gate in this pipeline. Exit code 0 is a complete tree.

## 13. Code layout

```
pool/
  preparation/
    __init__.py
    __main__.py        # CLI entry
    types.py           # frozen records; re-exports ElementResponse and Box
                       #   from providers/protocols.py (the parse boundary owns them)
    config.py          # PreparationConfig, loading, preparation_config_hash
    manifest.py        # artifact read and write (I/O)
    run.py             # imperative runner, provider wiring, resume logic
    stages/
      intake.py        # p00 verification rules, pure parts
      elements.py      # p01 response validation glue (pure parts)
      normalize.py     # p02 string rules
      cap.py           # p03 rarity cap
      vocabulary.py    # p04 vocabulary, incidence construction
      linedraw.py      # p05 bookkeeping (the work is in the provider)
      outline.py       # p06 crop geometry
      boxes.py         # p07 validation rules
      neardup.py       # p08 graph grouping
      release.py       # p09 record content
providers/
  protocols.py         # + VlmDescriber, TextEncoder, LineDrawer,
                       #   ElementBoxDetector (ImageEncoder exists)
  local/               # SigLIP encoders, line-drawing model (U2)
  openrouter/          # + describer and box-detector slots (§8)
  fake/                # + fake describer, encoders, line drawer, box detector
```

Import direction rules of `CLAUDE.md` §8 apply. There are shared
atomic-write and canonical-JSON helpers (`core/canonical.py`,
`pool/curation/manifest.py`) — lift the generic write helpers into a
shared module, do not copy them. Flagged here so the copy is not made
silently.

Dependencies to add at implementation time (with `uv add`): the local
model stack from D3 and D4 (torch and model weight libraries). Make sure
that wheels for the pinned Python version are available before install.
The test suite must not import the local stack.

## 14. Determinism

Two runs with the same config against the same released pool must give
byte-for-byte the same artifacts (`timings.json` excluded). Concretely:

- All sequencing is by ascending `image_id`. The vocabulary index is
  fixed by lexicographic sequence.
- The normalize and cap rules are pure and seed-free. Equal-value
  decisions have written rules (D7, D8).
- Remote responses are cached with the slot `config_hash` in the key.
  Re-runs and resume read the cache and get the same bytes (P1a §8a).
- Local encoders and the line drawer run with deterministic inference
  parameters. The guarantee scope is one machine and environment, as
  with P1a clustering.
- Grouping is connected components — no seed, no iteration count, and no
  sensitivity to input sequence.
- `.npy` writes are single-shot with fixed dtype and layout. All other
  files are canonical JSON.

## 15. Testing

All tests run offline with the fake providers — no GPU, no network
(`CLAUDE.md` §7, §9). Tests build a small released pool fixture directly
(release record plus image store), not by a curation pipeline run.

**Unit tests** — each pure stage function against fixed fixtures:
flattening and the flatten sequence, normalization rules on the D7 table
(articles, plurals, idempotence: normalizing a normalized string changes
nothing), the cap boundary at 21 entries with an equal-`df` pair,
incidence padding, crop geometry against known rectangles, box validation
limits, grouping on a hand-built similarity matrix with a chain A–B–C
(transitive components, not cliques).

**Invariant tests** — gate merges:

1. Coverage: each stage's artifact covers the full membership — no
   additions, no omissions, rows in ascending `image_id` sequence.
2. R13: a fake provider that errors on one image stops the run with that
   `image_id` named. After it, there is no artifact tree with a silent
   omission.
3. Element lists after p03 have at most `max_elements` entries.
4. Incidence agreement: each row's non-pad entries decode, through the
   vocabulary, to that image's capped element list, in sequence.
5. All stored vectors are unit-norm. `outline_vectors.npy` has shape
   `N × (1 + crops) × d`.
6. Grouping is a partition: each image is in one group. Each pair at or
   above the threshold shares a group.
7. Determinism: two full runs give byte-for-byte the same artifacts and
   preparation record (timestamps excluded).
8. Hash sensitivity: a change to one config value changes
   `preparation_config_hash` and thus the pool artifact tree path. A
   template change on one OpenRouter slot changes that slot's cache key.
9. Resume: delete stage directories from p04 forward, run again,
   byte-for-byte the same result.
10. Lineage: two different pool versions cannot give the same
    `preparation_version_id`. The same pool version with the same config
    always does.

Not in CI: the run against the released development pool. It is a
deliberate, recorded operation. Its counts go into the preparation
record.

## 16. Open decisions — agreement required before implementation

The architecture gives the structures and thresholds cited above, but not
the items below. All twelve decisions were agreed individually with the
project owner on 2026-08-07, with the concretizations recorded in the
table. The "Proposed default" column is the agreed value.

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | `VlmDescriber` model and instruction template | The OpenRouter `default_model` in use (`openai/gpt-5.6-luna`), one fixed template asking for the R2 schema, strict JSON output format | Make sure of structured-output capability for the schema shape at implementation time. A slot-level override stays available (P1a §9). |
| D2 | Element count contract | The response format pins counts for each field: 3 `objects`, 3 `materials`, 3 `colors`, 2 `shapes`, 1 `scale`, 1 `setting`, 3 `ambience` — 16 entries | This is how "keep the length roughly constant" (R3) is enforced by construction rather than repaired after. The §5 example of the architecture has this same shape. Normalization dedup can shrink an element list below 16. The cap handles more than 20 if the contract changes. |
| D3 | Encoder slots | Agreed 2026-08-07: the OpenRouter embeddings endpoint with `google/gemini-embedding-2` for the two slots — one multimodal model, thus text and image vectors share one space. Config permits `openrouter`, `local` (a SigLIP 2 checkpoint), or `fake` for each slot | §10 of the architecture suggests SigLIP or CLIP. A multimodal embedding model gives the same shared-space property. The expected dimension is a config value, and a response with a different width raises (R14). The first development run confirms the served dimension. |
| D4 | Line-drawing implementation | Informative Drawings weights, reached through the `controlnet_aux` lineart interface (§11 of the architecture). Wheels for the pinned Python checked live 2026-08-07 (`controlnet-aux` 0.0.10, torch 2.13) | If that package does not run on the pinned Python and torch versions, vendor the generator inference directly from the released weights — the architecture names the model, not the package. |
| D5 | Canonical render parameters | Canvas 512 × 512, white background, black strokes, line width 3 px, no anti-aliasing. Binarize threshold 0.5. Minimum segment length 10 px | These are shared constants with the future Layer 0 sketch render (R7). V1 iterates on them. Each change is a new `LineDrawer` hash and a pool artifact recalculation — cheap at development scale. |
| D6 | Crop grid | Full image plus 5 crops — center plus the 4 corners, each crop 60% of each side | §12.2 of the architecture asks for the full image plus a small crop grid of approximately five crops. The §18 memory table counts 5 vectors for each image. The two readings are different by one vector — this spec follows §12.2 and flags the table as approximate. |
| D7 | Singularization rule table | Rule identifier `d7-v1` (the §9 config value). Last word only: `-ies → -y`. Remove `-es` after `s`, `x`, `z`, `ch`, `sh`. Keep `-ss`. Drop one last `-s` in other cases. Words of 3 characters or fewer are kept as-is | Deterministic, no model, imperfect on irregular nouns — accepted, because the same rule applies to atoms at scoring time, and agreement between the two sides matters more than correct English plurals. |
| D8 | Flatten sequence and the equal-value rule | Flatten in the R2 field sequence. Break equal capping rarity by flatten position, first position kept | Position in the flatten sequence is unique in one image, thus the sequence is total and deterministic. |
| D9 | Grouping method | Connected components on the at-or-above-0.95 graph, full-image vectors only, `group_id` = smallest member `image_id` | §5 of the architecture says "cluster ... at a tight threshold" without a method. Components are parameter-free and agree with the Layer 8 requirement: each image that encoder noise could put at the target's rank exits the decoy set with it. |
| D10 | `ElementBoxDetector` provider and output format | OpenRouter first (U2): one `POST` for each image, the capped element list in the instruction, strict JSON with one box or `null` for each element, coordinates normalized to [0, 1] | A local open-vocabulary detector stays a drop-in replacement. Box quality is unmeasured until the placement channel is built. The artifact is cheap to calculate again (R12). |
| D11 | Pool mean formula | Outline space — the mean of all stored rows (full image and crops). Element space — the mean of the vocabulary vectors. The raw mean is stored, not a unit-norm copy | §10 of the architecture names the subtraction but not the population. Layer 2 code applies the means when vectors are compared, not this pipeline. |
| D12 | Text-encoder input for vocabulary entries | The bare normalized string, no prompt template | A template is one config string away and changes the hash. Start plain and let V-harness data argue for more. |

## 17. Acceptance criteria

1. `uv run pytest` completes with zero errors, with no network and no
   GPU.
2. The suite contains all invariant tests of §15, and all of them
   complete with zero errors.
3. A full run against the fake released-pool fixture makes the complete
   artifact tree of §11 and a preparation record in the committed format.
4. The development run: p00 through p09 complete against the released
   development pool with `configs/preparation/dev-wit.json`, and the
   report prints coverage and `POST` counts.
5. An OpenRouter-backed stage run again with unchanged config reads the
   cache and makes zero new `POST` operations (U1).
6. No open decision from §16 is implemented without recorded agreement.
7. Documentation (this file, docstrings, comments) is Vale-clean at error
   level, with warning decisions noted.
8. The preparation record for the development pool carries
   `dev_only: true` and a `dev-` tag (R15).
