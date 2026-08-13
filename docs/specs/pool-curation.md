# Spec P1a — Pool curation pipeline

**Status:** draft, for review.
**Phase:** 1 — build the pool (`docs/ARCHITECTURE.md` §25), first component.
**Architecture sections:** §4 (the pool), §5 (pool preparation), §21 (versioning).
**Working agreement:** `CLAUDE.md` §5 (interchangeability), §6 (provider agnosticism), §7 (development build).

This spec is written for implementation by an AI agent. It defines contracts,
file layouts, and acceptance criteria. Where the architecture does not give a
value or a rule, this spec says so in §16 and proposes a default. Do not
implement an open decision without agreement.

---

## 1. Purpose

This pipeline turns a **source corpus** into a released, versioned **pool**.
The architecture defines the pool as the fixed, curated working set that all
ranking is calculated against (§4). The pipeline applies the curation filter
of §4 as a sequence of stages. Each stage applies one rule, removes the
candidates that do not obey it, and emits a labeled, immutable **manifest**.
The last stage releases a pool version. Its identity comes from the source
corpus, the curation configuration, and the surviving image set.

The development build uses the Hugging Face dataset `wikimedia/wit_base` as
its source corpus. The code must not know this. All corpus details live in
one adapter behind a protocol (§7 of this spec).

## 2. Scope

**In scope**

- Corpus access protocol and two adapters: Hugging Face datasets, and a
  deterministic fake for tests.
- The staged curation filter: architecture §4, steps 1 through 8.
- Manifest, rejection, and metrics artifacts for each stage.
- Content-addressed storage of the selected image files.
- The extraction budget: byte accounting and enforcement (U1).
- OpenRouter-backed providers for the image-understanding slots (U2).
- Pool version identity, the release record, and the human review gate.
- A resumable command-line runner.

**Out of scope** — specs that follow cover these.

- Pool preparation (§5): element lists, element vectors, line drawings,
  outline vectors, tag vectors, vocabulary, incidence table, commonness
  scores, and near-duplicate *grouping* on outline vectors. Curation step 6
  (near-duplicate *removal*) is in scope. It is a different operation with a
  different encoder.
- All scoring layers, the background set, and the validation harnesses.

## 3. Terms this spec adds

The glossary in `docs/ARCHITECTURE.md` §2 defines all scoring terms. This
spec adds pipeline terms only.

| Term | Meaning |
|---|---|
| **Corpus identity** | The tuple that pins one source corpus revision: provider, repository, revision, configuration name, split. |
| **Candidate** | One source-corpus record that entered the pipeline and was not rejected. |
| **Stage** | One pipeline step. It reads the parent manifest, applies one rule, and writes one manifest. |
| **Manifest** | The immutable set of candidates that survived a stage, plus metadata. Each manifest is a labeled version of the pool as the pipeline decreases it. |
| **Materialization** | The retrieval of the image bytes for a candidate, and content-addressed storage of them. |
| **Curation config** | The frozen parameter object for one full pipeline run. Its hash is part of each artifact key. |
| **Pool version** | The released output: the pool membership with a stable identifier. |
| **Release record** | A small committed file that documents one pool version. |

## 4. Requirements from the architecture

Numbers in this section come from the architecture and are not negotiable.
Quotes are from `docs/ARCHITECTURE.md`.

- **R1** — The filter sequence is fixed, cheapest first (§4): resolution,
  aspect ratio, text detection, zero-shot classification, object detection,
  near-duplicate removal, diversity cap, human spot-check.
- **R2** — Resolution: "short side ≥ 512 px" (§4, step 1).
- **R3** — Aspect ratio "between 0.5 and 2.0" (§4, step 2). The limit
  values 0.5 and 2.0 are kept.
- **R4** — Text detection: "reject if text covers > 5% of image area"
  (§4, step 3).
- **R5** — Zero-shot classification: keep `photograph`, reject `diagram`,
  `chart`, `logo`, `map`, `screenshot`, `coat of arms`, `line drawing`
  (§4, step 4).
- **R6** — Object detection: "largest detected object must cover > 15% of
  area" (§4, step 5).
- **R7** — Near-duplicate removal "at 0.95 cosine similarity" (§4, step 6).
- **R8** — Diversity cap: cluster by encoder vector and keep a maximum of
  ~15 images in each cluster (§4, step 7). The architecture warns that this
  is the step that gets skipped, and that it must not be.
- **R9** — Human spot-check "on a random sample of 200" (§4, step 8).
- **R10** — Captions are "a curation signal" and not the element list (§4).
  The pipeline keeps caption and attribution metadata through to the
  release, and does not filter on captions in this version.
- **R11** — The pool is versioned. A pool version is handled like a model
  version: hash it, store it with each trial (§4). Pool growth is a
  deliberate, recorded release — not an automatic background task (§4, §21).
- **R12** — Each derived artifact is a cache. Its key contains the hash of
  the configuration that made it, and it is possible to make it again
  from the source (§3, Rule 4).
- **R13** — The development pool is small — in the range of hundreds to
  thousands of images — with "its own pool version identifier". Development
  results are not published (`CLAUDE.md` §7).
- **R14** — No silent fallbacks. A provider error or an unexpected shape
  raises. A record-level failure that must not stop
  a bulk task becomes an explicit, labeled rejection — not a silent skip
  (`CLAUDE.md` §3).

### User constraints

These come from the project owner, not from the architecture. They have
the same weight.

- **U1 — Extraction budget.** Corpus extraction has a byte budget. The
  shipped development value is 500 MB (`500_000_000` bytes, set
  2026-08-07) for all data retrieved for the corpus: the metadata scan
  plus all materialized image bytes. The budget is a config value (`budget_bytes`, §9), is part
  of `curation_config_hash`, and is tunable for each iteration. The
  pipeline must report bytes retrieved, and must stop fetching — with
  explicit accounting — when the budget is reached.
- **U2 — OpenRouter for the image model.** The image-understanding model
  runs through OpenRouter (§8a). *Changed by owner ruling 2026-08-12:*
  the OpenRouter embeddings endpoint serves image-embedding encoders
  (checked live 2026-08-07, `configs/preparation/README.md`), thus the
  `ImageEncoder` slot for s06 and s07 can run through OpenRouter or
  through the fake for tests. The "local only" clause is withdrawn.

## 5. Pipeline overview

```
source corpus (Hugging Face, pinned revision)
      │
      ▼
s00 snapshot      pin identity, enumerate, sample      ──► manifest
s01 screen        claimed resolution + aspect          ──► manifest + rejections
s02 materialize   fetch bytes, decode, store,
                  authoritative resolution + aspect    ──► manifest + rejections + records
s03 text          text coverage ≤ 5%                   ──► manifest + rejections
s04 class         zero-shot: photograph only           ──► manifest + rejections
s05 object        largest object > 15% of area         ──► manifest + rejections
s06 neardup       cosine ≥ 0.95 removal                ──► manifest + rejections
s07 diversity     cluster cap, ≤ 15 per cluster        ──► manifest + rejections
s08 review        sample of 200, human verdict         ──► review record
s09 release       pool version + committed record      ──► pool version
```

Stage-to-architecture mapping: s01 and s02 together implement §4 steps 1
and 2. s01 checks claimed metadata. s02 checks decoded pixels — the
authoritative check. Stages s03 through s08 map one-to-one to §4 steps 3
through 8. Stages s00 and s09 are pipeline bookkeeping.

Each stage is independently runnable, resumable, and deterministic. A stage
does not change the output of a stage before it. Survivors of stage *n* are
always a subset of survivors of stage *n−1*. Each removal is recorded with
its cause and the measured value.

### Functional core, imperative shell

Each stage splits into a pure decision function and a thin runner:

- The decision logic is a pure function of in-memory values (records,
  arrays, config). It lives in `pool/curation/stages/`. No file access, no
  network, no clock, no memory between calls. Seeds are explicit config
  values.
- The runner in `pool/curation/run.py` does all reads, writes, provider
  wiring, and status reporting. Providers are injected at wiring time from
  configuration (`CLAUDE.md` §6).

## 6. Identity and versioning

The user-facing requirement: pool versioning depends on the source corpus.
Two pools from different corpora, or from different revisions of one
corpus, are different lineages. They must not share an identifier.

### Corpus identity

```python
class CorpusIdentity(NamedTuple):
    provider: str            # "huggingface" | "fake"
    repo_id: str             # "wikimedia/wit_base"
    revision: str            # resolved commit hash — never a branch name
    config_name: str | None  # datasets config, if any
    split: str               # "train"
```

The adapter must resolve a branch name (for example `main`) to a commit
hash at snapshot time, and must record the hash. `corpus_id` is the SHA-256
hex digest of the canonical JSON of this tuple.

### Image identity

`image_id` is the SHA-256 hex digest of the stored image bytes. It is set
at materialization (s02) and is the primary key for all stages after s02.
`source_key` (§7) records provenance back to the corpus.

### Curation config hash

`curation_config_hash` is the SHA-256 hex digest of the canonical JSON of
the full `CurationConfig` (§9). That JSON contains each provider
`config_hash` and each seed and salt. Each parameter change makes a new
hash and thus a new artifact tree — no artifact is overwritten (R12).

### Stage labels

Each manifest gets the label
`<corpus_slug>-<corpus_id[:8]>-c<curation_config_hash[:8]>-<stage>` — for
example `wit_base-3fa9c2d1-c7be04a6-s04-class`. These labels are the
different labeled versions of the pool as the pipeline decreases the set.

### Pool version

```
pool_version_id = sha256(corpus_id
                         + curation_config_hash
                         + sha256(newline-joined sorted image_id values))
```

Byte layout: each component is a lowercase hex string. The inner hash is
SHA-256 of the sorted `image_id` values joined with `\n`, with no `\n`
at the end. The outer input is the plain concatenation of `corpus_id`,
`curation_config_hash`, and the inner hex digest, encoded as UTF-8.

The release label is `<tag>-<pool_version_id[:8]>`. `tag` is a human-chosen
name from config, for example `dev-wit-001`. A development pool must use a
tag with the `dev-` prefix, and its release record sets `dev_only: true`
(R13).

## 7. The source corpus protocol

Location: protocol in `providers/protocols.py`, implementations in
`providers/corpora/huggingface.py` and `providers/corpora/fake.py`. This
extends the `providers/` layout of `CLAUDE.md` §8 with a `corpora/`
subpackage. Data sources follow the same agnosticism rule as model
providers: code in other directories does not know the corpus is Hugging
Face.

```python
class SourceRecord(NamedTuple):
    source_key: str                 # stable within a pinned revision
    claimed_width: int | None       # from corpus metadata, may be absent
    claimed_height: int | None
    captions: tuple[str, ...]       # curation signal only (R10)
    attribution: Mapping[str, str]  # license and credit fields, passed through


class MaterializedImage(NamedTuple):
    source_key: str
    image_bytes: bytes
    retrieval_note: str             # URL and parameters actually used


class MaterializeFailure(NamedTuple):
    source_key: str
    reason: str                     # "fetch-error" | "decode-error" | ...
    detail: str


class SourceCorpus(Protocol):
    @property
    def identity(self) -> CorpusIdentity: ...

    @property
    def config_hash(self) -> str: ...

    @property
    def bytes_retrieved(self) -> int: ...   # monotone transport-byte counter (U1)

    def iter_records(self) -> Iterator[SourceRecord]: ...

    def materialize_many(
        self, records: Sequence[SourceRecord]
    ) -> list[MaterializedImage | MaterializeFailure]: ...
    # Result list is index-aligned with the input records.
```

Rules, aligned with `CLAUDE.md` §6:

- Batching is part of the contract. The adapter owns chunking, concurrency,
  retries, backoff, and rate limits. Callers do not loop on single fetches.
- A `MaterializeFailure` is an explicit value, recorded as a rejection with
  its cause (R14). If the adapter cannot get access to the corpus at all,
  it raises.
- `config_hash` covers all parameters that change the returned bytes: the
  identity tuple plus the materialization parameters.
- Adapters can supply more corpus metadata in `attribution`, but stages
  must read only the protocol fields.

### The Hugging Face adapter

Built on the `datasets` library with `streaming=True`, plus
`huggingface_hub` for revision resolution. Configuration: `repo_id`,
`revision`, `config_name`, `split`, column mapping, and materialization
parameters.

The adapter must read only the configured columns during enumeration,
through pyarrow ranged reads on the repo parquet shards, thus shipped
image bytes are not transferred during the scan. The corpus stores
columns as one chunk in each shard, thus one enumerated shard costs
the full column chunks for that shard (measured 2026-08-07: ≈ 25 MB and
≈ 19,600 rows for each `wit_base` shard, 330 shards, ≈ 6.5 million rows
in total). A full-corpus scan thus costs multiple GB. The config
field `max_scan_shards` limits the scan for U1: the adapter ranks the
shard files by the SHA-256 of the shard name — deterministic and
salt-free — and enumerates only the first `max_scan_shards` of that
ranking. The subset is part of the corpus config hash, thus a different
subset is a different pool lineage. The pool then samples a corpus
slice, and the slice is recorded — Rule 3 holds because the target and
the decoys come from the same released pool in all conditions.

The adapter counts the bytes it retrieves at its transport layer and
reports them through its `bytes_retrieved` property (U1).
`materialize_many` takes full records, not bare keys — the adapter
needs the claimed dimensions and the URL extension to select a safe
fetch mode.

### `wikimedia/wit_base` mapping (development corpus)

Check these against the dataset card at implementation time.

| Protocol field | Dataset column |
|---|---|
| `source_key` | `image_url` |
| `claimed_width` / `claimed_height` | `original_width` / `original_height` |
| `captions` | `caption_attribution_description` only, in the development configuration. `wit_features` is not read — it is large in each row, and R10 needs only a caption signal (U1). |
| `attribution` | `image_url`, `metadata_url`, `caption_attribution_description`, license note (CC BY-SA 4.0) |

**Warning: the shipped `image` column is a thumbnail with a width of
300 px.** Applied to the shipped pixels, R2 (short side ≥ 512) rejects the
full corpus. The metadata columns `original_width` and `original_height`
describe the full-resolution source file, and `image_url` points at it.
Materialization must fetch from `image_url` and must not read the shipped
column. See open decision D9 for the fetch mode. The adapter records the
URL and parameters used in `retrieval_note`. That note is part of the
stored provenance. For `wit_base`, corpus extraction spans the Hugging
Face metadata scan plus the Wikimedia fetches — the two count against U1.

The dataset also ships a precomputed `embedding` column. Do not use it.
Curation vectors must come from a provider with a tracked `config_hash` —
if they do not, the pool membership silently depends on an untracked model
(R12).

### The fake adapter

`providers/corpora/fake.py` generates deterministic images from the
`source_key` alone: seeded dimensions, aspect ratio, and content class
(photograph stand-in, text-heavy, diagram-like, near-duplicate pairs,
cluster families). Each curation stage must have fixtures it can reject and
fixtures it can accept. No network, no GPU, no files in other directories.

## 8. Model provider slots

Curation needs four capability protocols in `providers/protocols.py`. Each
follows `CLAUDE.md` §6: batched, config-hashed, output-normalized at the
boundary. The contract of each slot is the quantity the stage rule needs —
not a model type — thus one slot can hold a local model or an OpenRouter
model (§8a). Concrete model choices are open decisions (§16). The fake
implementations are required for the test suite.

| Protocol | Contract (shape) | Used by | OpenRouter? |
|---|---|---|---|
| `ImageEncoder` | `Sequence[bytes] -> Vectors` — unit-norm, `(B, d)` | s06, s07 | Yes — the U2 change of 2026-08-12 |
| `ZeroShotImageClassifier` | `(Sequence[bytes], labels) -> FloatArray (B, L)` — probability values on the closed label set | s04 | Yes |
| `TextCoverageEstimator` | `Sequence[bytes] -> FloatArray (B,)` — fraction of image area that text covers, in [0, 1] | s03 | Yes |
| `SalientObjectEstimator` | `Sequence[bytes] -> FloatArray (B,)` — fraction of image area that the largest object covers, in [0, 1] | s05 | Yes |

A box-based local implementation of the two estimator slots calculates the
fraction from detected boxes. For text this is the area of the union of
the boxes, thus boxes that overlap are not counted two times. That
geometry is a shared pure helper that the provider uses — the protocol
contract is the fraction. A VLM-based implementation asks the model for
the fraction (§8a).

The `ImageEncoder` slot here is the curation encoder. It can load the same
weights as the Layer 2 image encoder, but it is its own configuration slot
with its own hash. A change to it changes the pool membership — a new pool
version, not only a cache (compare `CLAUDE.md` §6 on the sketch and image
encoder slots).

### 8a. OpenRouter providers

`providers/openrouter/` holds the implementations, in the layout that
`CLAUDE.md` §6 and §8 give. Rules:

- One HTTP client. Concurrency, rate limits, retries, and backoff are
  provider-internal. Callers see the same batched protocols as for local
  models.
- The provider sends one `POST` for each image, with temperature 0, a
  fixed instruction template from provider config, and a fixed JSON
  output format. The provider parses and validates each response at the
  boundary. A response that does not
  parse, or a fraction out of [0, 1], raises (R14) — no silent defaults.
- `config_hash` covers the OpenRouter model identifier, the instruction
  template, and all API parameters. The API key is not part of the
  hash. It lives in the environment, not in config files.
- Each response is cached in the data root, with `image_id` and the
  provider `config_hash` in the key (R12). Re-runs and resume read the
  cache, thus the determinism contract of §14 holds through the cache. A
  cold recomputation with a remote model can give different bytes — the
  same trade-off
  the architecture accepts for the Layer 7 judge, which is also logged,
  not re-derived (architecture §15).
- Cost: with one `POST` for each image and each slot, a 20,000-image run
  at middle-tier VLM prices lands in the $10–$30 range — the same scale
  the architecture gives for element lists through OpenRouter (§24). The
  funnel report includes the `POST` count.

## 9. Configuration

One frozen `CurationConfig` dataclass, loaded from a committed JSON file
(`configs/curation/dev-wit.json` for the development build). It contains:

- the corpus section: identity fields plus adapter parameters,
- the sampling section: `sample_salt`, `sample_rate` (s00),
- the extraction section: `budget_bytes` (development default
  `5_000_000_000` — U1) and an optional `materialize_cap` (a limit on the
  fetched image count),
- one section for each stage with that stage's thresholds — the R2–R8
  constants are written in the file, not in code,
- provider selection and provider config for the four slots of §8,
- seeds: `cluster_seed`, `review_seed`,
- the release section: `tag`, `dev_only`.

Loading validates the config at the boundary. A missing or unknown field
stops the load with an error (R14). The runner gives the loaded object to
each function as an argument — no code reads global config (`CLAUDE.md`
§5).

## 10. Stages

Contract for all stages: a stage reads its parent manifest and writes one
stage directory (§11) with `manifest.jsonl`, `rejections.jsonl` (can be
empty), and `meta.json`. Counts must agree:
`parent survivors = survivors + rejections`. From s02 on, all processing,
output sequence, and equal-value decisions use ascending `image_id`.
Before s02, manifest rows are sorted by ascending `source_key`. Thus no
stage depends on the corpus enumeration sequence.

### s00 snapshot

Resolve and record the corpus identity. Enumerate `iter_records()`. Apply
the development sampling rule: keep a record when
`uint64(sha256(sample_salt + source_key)[:8]) / 2**64 < sample_rate`.
This rule is deterministic and streaming-safe, and the enumeration
sequence has no effect on it. Excluded records are counted in `meta.json`, not
written out row by row. Output rows contain `source_key`, claimed
dimensions, captions, and attribution. The scan reads only the configured
metadata columns (§7), and `meta.json` reports the bytes retrieved (U1).
A production run sets `sample_rate = 1.0`.

### s01 screen — R2, R3 on claimed metadata

Cheap rejection before bytes move. Reject when claimed dimensions are
available and do not obey R2 (`resolution-metadata`) or R3
(`aspect-metadata`). Records without claimed dimensions go through to the
authoritative check in s02.

### s02 materialize — R2, R3 authoritative

Use `materialize_many` on the survivors. For each result:

- `MaterializeFailure` → rejection with the failure's cause.
- Store the retrieved bytes content-addressed (§11). Set `image_id`.
- If two source keys give the same bytes, keep the one with the smaller
  `source_key` and reject the other (`duplicate-bytes`).
- Decode, read the decoded pixel dimensions, and apply R2 (`resolution`)
  and R3 (`aspect`) again. The decoded check is authoritative — claimed
  metadata is a hint, not a replacement. A file that does not decode as a
  raster image is rejected (`decode-error`). This is how SVG and other
  vector files exit.

Budget enforcement (U1): survivors of s01 are fetched in ascending
sequence of their sampling hash
(`uint64(sha256(sample_salt + source_key)[:8])`) — deterministic, and
free of selection bias, because it is the same quantity s00 sampled
with. Fetches go out in batches of `fetch_batch_size`. The decision
total starts at the s00 scan bytes, as frozen in the s00 `meta.json`,
and grows by the payload bytes of each fetched result. The byte count
of a fetch is not knowable before the fetch, thus the check comes first: a
batch is issued only while the decision total is less than
`budget_bytes` and the fetched count is less than `materialize_cap`.
Each fetched result goes on to the decode checks. When the decision
total is `budget_bytes` or more, or the count is at `materialize_cap`,
no more batches are issued, and each candidate that was not fetched
exits with rejection cause `extraction-budget`. Retrieved bytes can be
more than the budget by at most one batch of payloads, and `meta.json`
reports the totals as measured. The counts and byte totals go into
`meta.json`, and the funnel report shows them.

The stage also writes `records.jsonl`: one row for each survivor with
`image_id`, `source_key`, `width`, `height`, `format`, captions, and
attribution. The stages after s02 read image metadata from this file and do
not decode the image files again.

### s03 text — R4

`TextCoverageEstimator` on the survivor images: one fraction for each
image (§8). Reject when the fraction is more than `0.05`
(`text-coverage`, measured value stored).

### s04 class — R5

`ZeroShotImageClassifier` on the closed label set of R5, with the prompt
template from config. Keep a candidate only when `photograph` is the
argmax label. Rejection cause `class-<winning label>`, with the winning
label's probability stored. Spaces in the label become hyphens, for
example `class-coat-of-arms`. The argmax rule and the template are open
decisions D1 and D2.

### s05 object — R6

`SalientObjectEstimator` on the survivor images: the fraction of image
area that the largest object covers (§8). Reject when the fraction is at
or below `0.15` (`object-size`, fraction stored). A fraction of zero (no
detected object) means rejection — that is the R6 rule applied
literally, not a fallback.

### s06 neardup — R7

Encode all survivors with the curation `ImageEncoder` (batched, vectors
cached with the encoder `config_hash` in the key). Calculate pairwise
cosine similarity. For a development pool, the full `N × N` computation is
required — a correct slow path first (`CLAUDE.md` §7). Approximate
nearest-neighbor methods are an optimization for the full-scale pool and
must not change results at 0.95.

Keep rule (open decision D5): sort candidates by pixel area, largest
first, then by ascending `image_id`. Walk this sequence. If a candidate's
cosine similarity to a candidate that was kept before it is `0.95` or
more, reject it (`near-duplicate`) and store the kept neighbor's
`image_id` and the similarity.

### s07 diversity — R8

Cluster the survivor vectors, then cap each cluster at `15` members. The
clustering method, granularity, and in-cluster keep rule are open
decisions D6 and D7. The agreed method must use `cluster_seed`, must run
on the CPU in float32, and must give byte-for-byte the same result each
time. Rejection `diversity-cap`, with the cluster identifier stored.

### s08 review — R9

Select a seeded random sample of `min(200, survivors)` with `review_seed`
on the sorted `image_id` values. Write `sample.jsonl` and a self-contained
`contact_sheet.html` with embedded thumbnails for human inspection. The
sheet shows each image with its caption and its `image_id` — a caption
of `Coat of arms of Bergheim`, for example, shows a curation miss
immediately.

The stage then requires `review.json` in the same directory:

```json
{
  "verdict": "pass",
  "reviewer": "<name>",
  "date": "<ISO 8601>",
  "notes": "<free text>"
}
```

`verdict` is `pass` or `fail`. The runner does not start s09 until there
is a `pass` verdict. The review is also required for development pools —
it is minutes of work with a contact sheet, and if it is skipped, a pool
full of coats of arms can be released.

### s09 release

Calculate `pool_version_id` (§6). Write the last pool membership manifest,
and write the release record to `pool/releases/<label>.json`. This file is
**committed to the repository** — it is the durable release artifact
(R11). Contents: corpus identity, `curation_config_hash`, config file
path, image count, survivor and rejection counts for each stage, review
reference, `dev_only` flag, pipeline code version (git hash), and creation
timestamp.

## 11. Artifacts and storage layout

All bulk artifacts live in a configurable data root (default `data/` at
the repository top level — add `data/` to `.gitignore`). All content in it
is a cache that can be rebuilt, with content and config hashes in the keys
(R12). Small durable records (release records, config files) are
committed.

```
data/
  curation/<corpus_id[:8]>/<curation_config_hash[:8]>/
    s00-snapshot/   manifest.jsonl  meta.json
    s01-screen/     manifest.jsonl  rejections.jsonl  meta.json
    s02-materialize/manifest.jsonl  rejections.jsonl  records.jsonl  meta.json
    s03-text/       ...
    s04-class/      ...
    s05-object/     ...
    s06-neardup/    ...
    s07-diversity/  ...
    s08-review/     sample.jsonl  contact_sheet.html  review.json  meta.json
    s09-release/    manifest.jsonl  meta.json
  images/raw/<image_id[:2]>/<image_id>          # original bytes, shared across configs
  cache/vectors/<encoder_config_hash[:8]>/      # curation vectors, npy
  cache/openrouter/<provider_config_hash[:8]>/  # remote responses, JSON (§8a)

pool/releases/<label>.json                      # committed
configs/curation/dev-wit.json                   # committed
```

File formats:

- `manifest.jsonl` — one JSON object on each line: `source_key` (all
  stages) and `image_id` (s02 on). Sorted by ascending `image_id` from
  s02.
- `rejections.jsonl` — `{key, stage, reason, measured, detail}`.
  `measured` is the numeric value the rule examined, when there is one.
- `meta.json` — stage name, label (§6), parent stage, input, survivor, and
  rejection counts, the stage's config echo, provider config hashes, byte
  totals (retrieved by this stage, and cumulative — U1), and the pipeline
  code version. Fully deterministic: two equal runs give equal bytes.
- `timings.json` — stage start and stage end times. This is the one
  file that determinism comparisons do not read.

## 12. Runner

```
uv run python -m pool.curation --config configs/curation/dev-wit.json \
    [--through s07] [--force-from s04] [--report]
```

- Runs the stages in sequence. The runner skips a stage that has a
  directory with a complete `meta.json` — this lets a stopped run
  continue. `--force-from sNN` deletes that stage and the stages after it
  in this config's tree only, and calculates them again.
- `--report` prints the funnel for each stage: input, survivors,
  rejections by cause, survival rate. The same numbers go into
  `meta.json`. Report results with numbers (`CLAUDE.md` §11).
- The runner is the imperative shell: it wires providers from config,
  moves bytes, and applies the pure stage functions. Stage logic does not
  touch the disk.

## 13. Code layout

```
pool/
  curation/
    __init__.py
    __main__.py        # CLI entry
    types.py           # frozen records: CandidateRecord, Verdict, Rejection, ...
    config.py          # CurationConfig, loading, curation_config_hash
    manifest.py        # manifest and records file read and write (I/O)
    run.py             # imperative runner, provider wiring, resume logic
    stages/
      screen.py        # s01 pure rules
      materialize.py   # s02 pure parts: decode checks, duplicate-bytes rule
      text.py          # s03 coverage geometry + rule
      classify.py      # s04 argmax rule
      objectsize.py    # s05 largest-box rule
      neardup.py       # s06 sequence + greedy keep, pure on arrays
      diversity.py     # s07 clustering + cap, pure given seed
      review.py        # s08 sample selection, contact sheet HTML generation
      release.py       # s09 pool_version_id, release record content
providers/
  protocols.py         # + SourceCorpus, ZeroShotImageClassifier,
                       #   TextCoverageEstimator, SalientObjectEstimator
  corpora/
    huggingface.py
    fake.py
  local/               # encoder, and optional local estimators
  openrouter/          # VLM-backed classifier and estimators (§8a)
  fake/                # stub classifier, estimators, encoder
```

The import direction rules of `CLAUDE.md` §8 apply: `pool/curation/stages/`
is pure and imports protocols only for type annotations.

Dependencies to add at implementation time (with `uv add`): `datasets`,
`huggingface_hub`, `pillow`, `numpy`, `httpx` (for
`providers/openrouter/`), plus the local model stack from the open
decisions. The test suite must not import the model stack.

## 14. Determinism

Two runs with the same config on the same pinned corpus must give
manifests that are byte-for-byte the same. Concretely:

- Revision pinning at s00 — a branch name is resolved one time and stored.
- Hash-based sampling (s00): the enumeration sequence has no effect on
  the result.
- All sequencing from s02 on is by ascending `image_id`.
- Near-duplicate keeping is the deterministic greedy walk of s06.
- Clustering runs on the CPU, in float32, seeded from config.
- The review sample is seeded from config.
- JSON is written canonically: sorted keys, fixed float format, `\n` line
  endings.
- Remote responses are cached with `image_id` and the provider
  `config_hash` in the key. Re-runs and resume read the cache and get the
  same bytes (§8a).
- Provider nondeterminism is contained by the provider `config_hash`. The
  local curation providers (encoder, optional local estimators) must run
  in deterministic inference modes.

## 15. Testing

All tests run offline with the fake providers and the fake corpus — no
GPU, no network (`CLAUDE.md` §7, §9).

**Unit tests** — each pure stage function against fixed fixtures: boundary
values at 512 px, aspect 0.5 and 2.0, coverage equal to 5%, object
fraction equal to 15%, similarity equal to 0.95, a cluster at the cap,
and a budget boundary at the last fetch that fits.

**Invariant tests** — gate merges:

1. Subset chain: survivors of each stage are a subset of the parent's
   survivors.
2. Accounting: input count equals survivor count plus rejection count, for
   each stage, and each rejection has a cause.
3. Determinism: two full runs against the fake corpus give byte-for-byte
   the same manifests, rejections, and release record (timestamps
   excluded).
4. Hash sensitivity: a change to one config value changes
   `curation_config_hash` and thus the artifact tree path.
5. Corpus lineage: two different corpus identities cannot give the same
   `pool_version_id`. The same identity with the same config and survivors
   always does.
6. Resume: delete the stage directories from s04 on, run again, and the
   result is byte-for-byte the same.
7. The runner refuses to run s09 without a `pass` review verdict.
8. Budget: with a small `budget_bytes` against the fake corpus, s02 stops
   at the budget, each candidate that was not fetched has an
   `extraction-budget` rejection, and invariant 2 holds.

Not in CI: runs against `wit_base` itself. The first `wit_base` run is a
deliberate, recorded operation. Its funnel numbers go into the release
record and the report.

## 16. Open decisions — agreement required before implementation

The architecture gives the thresholds used above, but not the items below.
These are flagged, not silently chosen (`CLAUDE.md` §1). Each has a
proposed default.

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | Zero-shot decision rule for R5 | Keep only when `photograph` is the argmax on the closed label set | The architecture gives the labels, not the rule. Argmax is what the words of R5 say. |
| D2 | Zero-shot prompt template | `"a {label}"` | Template text changes results and is part of the config hash. |
| D3 | Curation encoder | *Ruled 2026-08-12:* `google/gemini-embedding-2` through OpenRouter, dimension 3072, no instruction | The first release ran this slot on the fake encoder — s06 removed nothing and s07 cut at random. The U2 change opens the slot to the OpenRouter embeddings endpoint. `configs/curation/dev-wit-2.json` is the re-run configuration, with the corpus revision pinned to the recorded resolution, thus the one change against the first release is the working encoder. A local SigLIP checkpoint stays an applicable slot filler in a build that follows. |
| D4 | VLM for the OpenRouter slots, and its instruction templates | One vision model for `ZeroShotImageClassifier`, `TextCoverageEstimator`, and `SalientObjectEstimator` — proposed `google/gemini-2.5-flash`, temperature 0, fixed JSON output | U2. A VLM-estimated fraction replaces a box-based local detector for s03 and s05 — a change of measurement method for §4 steps 3 and 5. Box-based local implementations of the estimator slots stay applicable. Check the fraction quality at the s08 spot-check. |
| D5 | Near-duplicate keep rule | Greedy, best first: pixel area, largest first, then ascending `image_id` | The architecture gives only the 0.95 threshold. |
| D6 | Clustering method and granularity for R8 | k-means, `k = ceil(n / 50)`, seeded, CPU | "Cluster" is unspecified. Granularity changes which images the cap removes. |
| D7 | In-cluster keep rule | Farthest-point traversal from the medoid, keep the first 15 | Keeps in-cluster diversity, not in-cluster typicality. |
| D8 | Development sampling target | `sample_rate` set for ≈ 10,000 candidates before the screen | Recorded decision, 2026-08-06. At ≈ 300 KB for each fetch, ≈ 10,000 fetches come to ≈ 3 GB — in the U1 limit with room for the scan. Adjust after the first funnel report. |
| D9 | `wit_base` materialization mode | Fetch a Wikimedia thumbnail rendition of the source file at a width that keeps the short side ≥ 512 px. Wikimedia serves only standard thumbnail widths, and 1280 px is the smallest standard width that satisfies each aspect ratio that R3 allows. Descriptive User-Agent, bounded concurrency | Source files can be as large as 27,000 px — full downloads are wasteful. A 1024 px fetch gets HTTP 400 (checked live, 2026-08-06). The fetched rendition becomes the permanent raw bytes, and `retrieval_note` records the URL used. Each fetch counts against U1. |
| D10 | Caption-based boilerplate filter | Not in this version — captions go through unchanged | R10 permits the signal and defines no rule. Examine again with measured funnel data. |

## 17. Acceptance criteria

1. `uv run pytest` completes with zero errors, with no network and no GPU.
2. The suite contains all invariant tests of §15, and all of them complete
   with zero errors.
3. A full run against the fake corpus makes the complete artifact tree of
   §11, a release with a `pass` review, and a release record in the
   committed format.
4. The development run: s00 through s08 complete against
   `wikimedia/wit_base` with `configs/curation/dev-wit.json`, the funnel
   report prints, and the contact sheet renders.
5. The released development pool is in the R13 range (hundreds to
   thousands of images). If it is not, adjust D8 and run again, before
   preparation work starts.
6. No open decision from §16 is implemented without recorded agreement.
7. Documentation (this file, docstrings, comments) is Vale-clean at error
   level, with warning decisions noted.
8. The development run retrieves at most `budget_bytes` (U1, default
   5 GB) for the corpus, and the funnel report shows byte totals for
   each stage.

## 18. The dev-wit-2 re-run (owner runbook, ruled 2026-08-12)

The first release ran s06 and s07 on the fake encoder: s06 removed 0
of 728, and s07's cut of 728 to 225 was 15 clusters times cap 15 on
seeded random vectors — a random subsample, with no working
near-duplicate removal and no working diversity cap. The ranking-time
near-duplicate rule (I3) was not touched: the decoy groups come from
preparation p08 on the working gemini vectors. The re-run puts a
working encoder in the slot with each other input pinned.

The owner runs each command, with the key in the environment.

1. `uv run python -m pool.curation --config
   configs/curation/dev-wit-2.json` — a new artifact tree below
   `data/curation/f655d713/`. What to look for: s00 scans about
   100 MB of metadata. s02 fetches about 400 MB — the fetch
   sequence is salt-seeded, and small drift from transient fetch
   errors is expected and recorded. s03 through s05 make about zero
   posts (response caches key by image id and slot hash). s06 makes
   about 12 to 60 embedding posts for 728 images (batched) and
   removes a nonzero count this time. s07 makes zero posts. The run
   stops at the s08 review gate with exit code 3.
2. Review `s08-review/contact_sheet.html` in the new tree, then
   write `review.json` there with the verdict.
3. The same command again — s09 writes
   `pool/releases/dev-wit-002-<hash8>.json`. The release count lands
   near 130 to 210: with the divisor 50 rule, fewer than 701
   survivors give at most 14 clusters, and clusters of the working
   encoder do not all overflow the cap. A count below about 150 goes against acceptance
   criterion 5 — a D8 adjustment is an owner ruling and a new
   lineage, not an inline tune.
4. Preparation: a new config
   `configs/preparation/dev-wit-photo-inst-2.json` names the new
   release record, plus `linedraw.stroke_color` from the spec C1
   gate verdict. `uv run python -m pool.preparation --config
   configs/preparation/dev-wit-photo-inst-2.json`. Cold cost is the
   newly admitted images alone: about one describer post and one box
   post for each new image, the image encoder at six rows for each
   new image (batched), and a small element text-encoder tail.
5. Migration and gates: re-point the scoring configs and
   `configs/service/dev-wit.json` at the new preparation record, run
   V1 and V2 (about 30 posts), record the verdicts, and start the
   trial server again. Stored days keep their pinned configs — rescore, do not
   migrate (architecture section 21).
