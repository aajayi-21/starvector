# Curation configuration files

Each file here is the full parameter surface of one curation pipeline
run. The loader (`pool/curation/config.py`) validates in full: an
unknown or missing field stops the run with an error that names the
JSON path. JSON has no comments, thus this file documents the fields.

**Each edit changes the curation config hash.** The hash keys the
artifact tree and the pool version, thus an edited config starts a new
pool lineage. That is correct behavior, not an accident — see
`docs/specs/pool-curation.md` section 6.

## The two headline knobs

- **OpenRouter model** — `providers.openrouter.default_model`. One
  string, for example `"google/gemini-3.1-flash-lite"`. A slot can
  override it: set `providers.<slot>.model` to a model identifier, and
  that slot uses it, not the default. `openai/gpt-5.6-luna` is a
  good lower-cost alternative.
- **Hugging Face dataset** — `corpus.repo_id`, plus the `corpus.columns`
  mapping that names the dataset columns for each protocol field. Set a
  column name to `null` when the dataset has no such column.

## Field notes

- `corpus.revision` — a branch name is permitted and is resolved to a
  commit hash at snapshot time. Pin a commit hash before the first run
  that matters, and the lineage stays fixed.
- `corpus.materialization.thumbnail_width` — Wikimedia serves only
  standard thumbnail widths (250, 330, 500, 960, 1280, 1920, 3840).
  1280 is the smallest that keeps the short side at or above 512 px for
  each aspect ratio the screen permits.
- `corpus.max_scan_shards` — limits the metadata scan (U1). The corpus
  stores columns as one chunk in each shard, thus one enumerated
  shard costs the full column chunks (measured: ≈ 25 MB and ≈ 19,600
  rows for each `wit_base` shard). The adapter selects the subset by a
  hash ranking of the shard names — deterministic, and part of the
  config hash. `null` enumerates all shards, which costs multiple GB
  at `wit_base` scale.
- `sampling.sample_rate` — the fraction of enumerated records that
  enter the funnel. The rule is hash-based and deterministic. Set it
  against `max_scan_shards` × rows for each shard, and adjust after
  the first funnel report.
- `extraction.budget_bytes` — the U1 extraction budget. The scan plus
  all image fetches count against it. Tunable for each iteration.
- `providers.<slot>.instruction_template` — the fixed instruction the
  OpenRouter provider sends. The classifier template must contain the
  placeholder `{label_phrases}`, which the provider replaces verbatim
  with the rendered label phrases. The classifier answer shape is one
  label plus one confidence — the response schema pins the label to the
  requested set, thus an out-of-set answer cannot occur.
  `classify.label_template` must contain `{label}` one time.
- `providers.encoder` — `"openrouter"` or `"fake"` (the U2 change of
  2026-08-12). An openrouter encoder is an embeddings slot: `model` and
  `dimension` are required, `instruction_template` stays `null`, and the
  chat `default_model` does not apply. The fake stays for tests.
  `dev-wit.json` released the first pool with the fake encoder — s06
  removed nothing and s07 cut at random — and `dev-wit-2.json` is the
  re-run with `google/gemini-embedding-2` and the corpus revision pinned
  to the recorded resolution. Switching the encoder changes the config
  hash and thus starts a new pool lineage.
- `release.tag` — must start with `dev-` when `dev_only` is `true`,
  and only then. Development pools are not published (R13).
