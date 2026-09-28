# Spec PP1 — the production pool at N = 7,500

**Status:** surveyed 2026-09-02. Rulings 1 (the pool count, §2) and
10 (the budget, §5a) are the owner's. Rulings 2 to 9 and 11 (§8) are
open. Not in build.
**Phase:** the production pool — the row after spec B1 in the F1
roadmap (`docs/specs/weight-freeze.md` §7), the architecture's Phase 1
at production scale (`docs/ARCHITECTURE.md` §25).
**Architecture sections:** §4 (the pool), §5 (pool preparation),
§16 (decoy count and resolution), §18 (latency), §21 (versioning),
§23 (validation), §24 (hardware).
**Working agreement:** `CLAUDE.md` §2 (I3, I4, I6), §7 (development
build first), §10, §11.
**Input:** the dev-wit-002 lineage (204 images, release
`dev-wit-002-9644fac1`, funnel tree `dea9c192`), frozen weights
`{element: 0.45, outline: 0.55}`, the adopted encoder
`google/gemini-embedding-2` through OpenRouter, the P5 bench record
`bench-20000-979211dd` (77.33 ms local at 20,000 images), and the
cost model of 2026-08-24 (in §5).

---

## 1. Purpose

Each quantity in the system — rarity, commonness, the decoy count,
the frozen weights — is defined against the pool, and the
development pool is 204 images with a `dev-` tag that the rules keep
off each public surface (spec P1a R13). Public numbers wait for a
production pool: a release without the `dev-` tag, a preparation
record on it, a new fit, new frozen weights, and the full gate set
V1 to V6 with the production thresholds that spec P5 parked.

This spec fixes the one number that sizes all of that work — the
pool count `N` — and gives the arithmetic that follows from it: how
many candidates the funnel must fetch and screen, what that costs in
money, disk, and hours at the provider rate, what the fast path measures at
that count, and what the repository must say. §4 is the check that
the number is sound. §8 is the set of rulings the owner gives before
the build starts, and §9 is the runbook.

---

## 2. Ruling 1 — `N = 7,500`

**The production pool has 7,500 images.** Recorded 2026-09-02.

The architecture writes "around 20,000" and then argues for it as a
ceiling: preparation cost and the element channel limit the pool from
above (§4, "why the pool must be bounded"). The architecture gives no
floor. The two low marks it does give are the frontload resolution
floor `D ≥ 200` (§16) and the "hundreds to thousands" development
range of R13. The
count 7,500 sits in the permitted range with room on each side, and
§4 of this spec walks through what moves with `N` and what does not.

The 20,000 figure stays in `docs/ARCHITECTURE.md` as the ceiling the
tiers of §18 are sized for. The dated note in §4 of the architecture
points here.

---

## 3. The funnel arithmetic

The basis is the dev-wit-002 funnel (tree `dea9c192`, release record
`pool/releases/dev-wit-002-9644fac1.json`), the one run of the working
encoder with each other input pinned. Its stage yields:

| stage | in | out | yield | note |
|---|---|---|---|---|
| s00 snapshot | 78,512 enumerated | 2,409 | 3.07% | `sample_rate` 0.03, 4 shards, 98.7 MB scanned |
| s01 screen | 2,409 | 1,831 | 76.0% | claimed resolution and aspect |
| s02 materialize | 1,216 attempted | 1,036 | 85.2% | 615 stopped by the 500 MB budget, then 128 fetch errors, 50 unsupported media, 2 resolution |
| s03 to s05 | 1,036 | 727 | 70.2% | text 102, class 80, object 127 |
| s06 near-duplicate | 727 | 727 | 100% | zero removals at 0.95 |
| s07 diversity | 727 | 204 | 28.1% | 13 of 15 clusters at the cap |
| s08 review | 204 | 204 | — | verdict `pass` |

Two structural facts set the plan.

- **s07 caps the yield at 30%.** The rule is `k = ceil(n / 50)`
  clusters at cap 15 (P1a D6, D7), thus at most `15 × ceil(n / 50)`
  survivors — 30% of the s06 survivors when each cluster overflows.
  The measured 28.1% is that ceiling with two clusters below the cap.
  A larger pool comes from more candidates, not from a different
  yield, unless ruling 6 changes the cap.
- **The fetched bytes are the budget.** The 1,038 fetched thumbnails
  at width 1,280 came to 420 MB — 405 KB each on average — and the
  500 MB budget (U1) is what stopped s02, not the sample.

The arithmetic for 7,500, with a 5% allowance for near-duplicate
removals at scale (the development run removed zero, and a larger
sample of Wikimedia Commons will have some — this is a planning
margin, not a measurement, and the calibration run of §9 replaces it):

| quantity | value | from |
|---|---|---|
| s07 input | 26,700 | 7,500 / 0.281 |
| s06 input | 28,100 | + 5% allowance |
| materialized (s02 survivors) | 40,000 | / 0.702 |
| fetch attempts | 47,000 | / 0.852 |
| sampled rows (s00) | 61,800 | / 0.760 |
| enumerated rows at `sample_rate` 0.03 | 2.06 M | / 0.03 |
| shards at 19,600 rows each | 105 | of the corpus's 6,477,255 rows |
| metadata scan | 2.6 GB | 25 MB for each shard |
| fetched bytes | 16.2 GB | 40,000 × 405 KB |
| `budget_bytes` | 20 GB | scan + fetch + fetch-error bytes, with room |

The `sample_rate` and the shard count trade against each other at the
same sampled count: 0.10 across 32 shards gives the same 61,800 rows
with a 0.8 GB scan. Ruling 2 picks. In the two shapes the sampling rule
(`keep_in_sample`: hash below rate, same salt) keeps the development
sample as a strict subset of the production sample, and the shard
ranking is a hash prefix, thus the 1,036 development candidates and
their s03 to s05 responses stay cache-warm.

---

## 4. Is 7,500 sound?

Six checks. The first four say yes without qualification. The fifth
says yes with a measured caveat that belongs to the vocabulary, not to
`N`. The sixth is a constraint to keep in view.

1. **`N` has no effect on the scoring guarantee.** The trial score
   is a rank fraction. With no information the target lands with
   equal probability at each position of the sorted decoy set, at
   each `N` (architecture §1, §16). The only formulas in the layer
   stack with `N` in them are the resolution `1 / D` and the top of
   the rarity range `ln N`, which moves from 9.9 to 8.9 nats. Rarity,
   commonness, and the frozen weights are all defined against the
   pool and are fitted again on it in each lineage — the same work
   at 7,500 as at 20,000.
2. **Resolution and the frontload floor.** The trial score has 7,499
   different values. The `D ≥ 200` floor for a frontload filter (§16)
   means a frontload tag must cover 2.7% of the pool — 200 images —
   against 1% at 20,000. Coarse tags (`outdoor`, `man-made
   structure`, `animal`) clear that easily. A narrow tag that clears
   it at 20,000 can miss it at 7,500, and the tag menu is drawn from
   the pool's vocabulary at build time, thus this is a menu
   constraint, not a scoring one.
3. **The repetition horizon.** One target for each day: 7,500 days is
   20.5 years before a target repeats. Practice replays revealed
   targets only (P5 ruling 2), thus practice does not consume the
   pool.
4. **Cost, disk, and time.** §5: about USD 45 for one clean run,
   about 23 GB on the build machine, about 0.9 GB on the serving
   box, and about 27 hours of posts at the current provider rate of
   2 POST/s. All of it is 37.5% of the 20,000 plan, and all of it
   is reversible in cache terms (I4: provider caches key on the
   image and the provider hash, not on the pool count).
5. **The fast path, measured.** `tools.bench` on this CPU (Intel
   Core Ultra 7 258V, the machine of the committed records),
   2026-09-02, nine passes, uncommitted until the owner's verdict:

   | count | vocabulary | local total | outline | tier 1 | similarity table | tier 2 | resident |
   |---|---|---|---|---|---|---|---|
   | 20,000 | 1,379 | 77.33 ms | 43.84 | 17.37 | 8.54 | 1.77 | 2.97 GB |
   | 7,500 | 1,379 | 47.83 ms | 23.44 | 8.21 | 10.20 | 2.85 | 1.12 GB |
   | 7,500 | 26,770 | 239.32 ms | 23.27 | 10.35 | 208.29 | 2.97 | 1.44 GB |

   The first row is the committed record `bench-20000-979211dd`. At
   7,500 with the development vocabulary the local total clears the
   50 ms line that the 20,000 run missed — the outline matvec halves
   and tier 1 halves. At the projected production vocabulary the
   similarity table alone is four times the budget, and that term
   has no `N` in it: it is the element-side centering
   of the `|V| × 3072` vocabulary matrix on each score, the
   precompute candidate the P5 bench record named. Heaps fit on the
   development element lists gives `|V| ≈ 26,800` at 7,500 against
   60,000 at 20,000, thus 7,500 makes the open item 2.2 times
   smaller and does not close it. Ruling 7 is the build item that
   closes it (a resident centered vocabulary in `PoolIndex`, the B2
   pattern, byte-equal gate), and the production bench of §9 runs
   after it.
6. **Growth is a new lineage, not a trap.** A larger pool after this
   one is a new release, a new preparation, a new fit, and the full
   gate set again (architecture §21) — the same work as this phase,
   with the caches warm for each image the earlier run screened.
   Stored days keep their pinned configs and rescore, they do not
   migrate. Choosing 7,500 at this time costs nothing that a subsequent
   20,000 does not cost anyway.

The verdict: **7,500 is a sound production count.** It changes no
scoring property, it clears the fast-path line at the development
vocabulary and shrinks the vocabulary problem without solving it, and
it buys the production gates at 37.5% of the planned cost.

---

## 5. Cost, disk, and time at 7,500

Scaled from the cost model of 2026-08-24 (the dev-wit-002 funnel and
the recorded `cost` field of each OpenRouter response), which priced
one clean 20,000 run at about USD 105 for 101,600 materialized
candidates. The model is linear in the materialized count for
curation and in the pool count for preparation.

| item | 20,000 plan | 7,500 | basis |
|---|---|---|---|
| curation chat posts (s03, s04, s05) | USD 68 | USD 27 | 3 posts × 40,000 materialized |
| curation encoder (s06, s07) | USD 8 | USD 3 | 40,000 embeddings, batched |
| preparation: describer, boxes | USD 16 | USD 6 | 2 posts × 7,500 |
| preparation: six crop embeddings | USD 14 | USD 5 | 45,000 embeddings |
| generalize table (one post for each vocabulary entry) | — | not measured | about 26,800 short text posts. The dev table of 1,379 entries is the basis |
| **total, one clean run** | **USD 105** | **about USD 45** | range USD 35 to 60 on the near-duplicate rate and the generalize cost |

Time at the committed provider rate (`max_concurrency`
4, `requests_per_second` 2.0):

| step | count | hours |
|---|---|---|
| s02 fetch at 0.37 s each, concurrency 4 | 47,000 attempts | 4.8 |
| s03 to s05 posts | 120,000 | 16.7 |
| preparation posts | 15,000 | 2.1 |
| generalize posts | 26,800 | 3.7 |
| **total** | | **about 27** |

Disk on the build machine, **about 23 GB**: 16 GB of materialized
thumbnails at width 1,280, about 6 GB of embedding cache, and about
0.8 GB of release tree. The embedding cache stores vectors as JSON
text at 55 KB each — 40,000 curation vectors, 45,000 crop vectors,
and 26,800 vocabulary vectors.
The serving copy at 768 px with rejected candidates pruned is about
0.9 GB (the 2026-08-17 estimate of 2.3 GB for 20,000, scaled), and
the resident arrays are 1.1 to 1.4 GB (§4, row 5), thus the droplet
wants the 4 GB plan (`docs/droplet-deployment.md`).

## 5a. Ruling 10 — the budget is USD 20, and what it buys

**The full production pool — curation, preparation, and the
generalize table — costs at most USD 20.** Recorded 2026-09-02.

The prices below, for each `POST`, are measured: the mean of the recorded
`cost` field across the OpenRouter cache for each slot, all on
`openai/gpt-5.6-luna`. The embedding prices are from the cost model of
2026-08-24.

| slot | posts in cache | mean USD for each | prompt tokens |
|---|---|---|---|
| s03 text coverage | 1,046 | 0.000243 | 1,853 |
| s04 classifier | 942 | 0.000246 | 1,880 |
| s05 object fraction | 858 | 0.000238 | 1,823 |
| describer | 1,021 | 0.000169 | 1,056 |
| element boxes | 371 | 0.000629 | 2,768 |
| generalize | 2,230 | 0.000015 | 56 |
| curation embedding | — | 0.000079 for each materialized candidate | — |
| six crop embeddings | — | 0.000695 for each pool image | — |

**The unchanged pipeline costs USD 0.0053 for each pool image**: 5.08
materialized candidates for each pool image (yield 0.197), three
screening posts at 2.73 posts for each candidate, one embedding,
then the describer, the boxes, the crops, and the generalize share.
At 7,500 that is USD 40, and USD 20 buys about 3,770 images. The
budget and ruling 1 agree only with two changes to the pipeline, and
the two are the proposed ruling 11:

- **One screening `POST` for each candidate, not three.** The three
  s03 to s05 slots each send the same image with a short instruction,
  and the image is the cost: about 1,800 of the 1,850 prompt tokens.
  One slot that returns the three fields — text fraction, label,
  object fraction — from one cached response cuts the screening cost
  from USD 0.000661 to about USD 0.000243 for each candidate. The
  thresholds, the labels, and the R4 to R6 rules do not move. The
  three protocols stay as they are — the new provider answers all
  three from the one response. This is a code change (B7) and a
  config-hash change, in a lineage that is new anyway.
- **The boxes are deferred.** Placement is cut on the current lineage
  (spec F1), thus the boxes supply nothing until a fit reopens it. The value
  `deferred` on the `element_boxes` slot skips p07 (B8). The
  boxes cost USD 4.72 at 7,500 and can be bought after the fact —
  provider caches are additive — if the production fit asks for
  placement.

With the two changes and the diversity rule unchanged:

| item | count | USD |
|---|---|---|
| screening posts | 38,000 materialized | 9.23 |
| curation embeddings | 38,000 | 2.99 |
| describer | 7,500 | 1.27 |
| crop embeddings | 45,000 | 5.21 |
| generalize | 26,800 | 0.40 |
| **total** | | **19.10** |

The materialize cap 38,000 is the cost fence: 38,000 × 0.197 gives
7,490 pool images, and the cap stops the fetch before the screening
spend can go above USD 12.2. The margin is USD 0.90, thin. Two
margins are available and are not counted:

- The screener can send the 512 px canonical image (`input_canvas_px`,
  as the encoder slot does). The token saving is not measured — the
  describer's 1,056 prompt tokens against the screens' 1,850 says the
  accounting is not linear in area — and the calibration run
  measures it at no added cost.
- `cluster_cap` 18, not 15, lifts the s07 yield from 30% to
  36%, cuts the materialized count to 29,700, and lands at USD 16.4
  with an 18% margin. That moves the pool's structure (ruling 6) and
  is the owner's decision, not the default.

Time at 2 `POST`/s falls with the post count: about 5.3 hours of
screening posts, down from 16.7.

**The parameters, `configs/curation/prod-wit.json`** (B1), read
against `dev-wit-2.json`:

| field | value | change |
|---|---|---|
| `corpus.revision` | `ff6d4fb3…` | pinned, unchanged |
| `corpus.max_scan_shards` | 105 | from 4 |
| `corpus.materialization.thumbnail_width` | 1280 | unchanged |
| `sampling.sample_salt` | `dev-wit-001` | unchanged — the dev sample stays a subset |
| `sampling.sample_rate` | 0.03 | unchanged |
| `extraction.budget_bytes` | 20,000,000,000 | from 500,000,000 |
| `extraction.materialize_cap` | 38,000 | from `null` — the cost fence |
| `screen`, `text`, `classify`, `objectsize`, `neardup` | 512 / 0.5–2.0 / 0.05 / eight labels / 0.15 / 0.95 | unchanged |
| `diversity` | divisor 50, cap 15, 100 iterations | unchanged (cap 18 is the margin lever) |
| `review.sample_size` | 200 | unchanged |
| `providers.openrouter` | `openai/gpt-5.6-luna`, concurrency 4, 2 `POST`/s | unchanged |
| `providers.screener` | one slot for the three screens, `input_canvas_px` 512 | new (B7) |
| `providers.encoder` | `google/gemini-embedding-2`, 3072, `input_canvas_px` 512 | unchanged |
| `seeds` | 20260806 / 20260807 | unchanged |
| `release` | tag `prod-wit-001`, `dev_only` `false` | from `dev-wit-002`, `true` |

The calibration config `dev-wit-3.json` (B2) is the same file with
`max_scan_shards` 20, `materialize_cap` `null`, tag `dev-wit-003`,
`dev_only` `true`. Its about 7,600 materialized candidates cost about
USD 2.3 and are the cache-warm prefix of the production run, thus the
USD 19.10 above holds them.

The preparation config `prod-wit-photo-inst.json` (B4) is
`dev-wit-photo-inst-2.json` with the new release path and
`providers.element_boxes.provider` set to `deferred`. Each other field
is unchanged.

---

## 6. What the repository says after this ruling

Changed with this spec, each as a dated note that points here:

- `docs/ARCHITECTURE.md` §2 glossary entry for the pool, §4 table and
  a dated note below "why the pool must be bounded", §18 budget
  line.
- `docs/droplet-deployment.md` §3 and `docs/home-deployment.md` §2
  "room for what follows".
- `docs/specs/fast-path.md` ruling 3: the 50 ms line applies at 7,500
  from 2026-09-02, with the measurement.
- `docs/specs/pool-preparation.md` R4: the vocabulary projection.
- `docs/specs/pool-curation.md` §8a: the cost pointer.

Not changed: the committed bench records (dev numbers, owner
verdicts), the 20,000 worked numbers of architecture §18 and §27
(the sizing ceiling), each stored config (stored days rescore
against them).

---

## 7. Build items

Each lands before the runbook of §9 starts, each on a branch, each
green offline.

- **B1 — the curation config** `configs/curation/prod-wit.json`:
  the §5a parameter table. One config hash, one lineage.
- **B2 — the calibration config** `configs/curation/dev-wit-3.json`:
  the same file at the ruling-5 shard count with a `dev-` tag and
  `dev_only` `true`. Its caches are the production run's caches.
- **B3 — the resident centered vocabulary** (ruling 7): `PoolIndex`
  carries the centered and normalized vocabulary matrix, filled by
  `build_pool_index`, with the channel's fallback kept and a
  byte-equality gate test against the current computation — the B2
  pattern of spec P5. The bench reports the similarity table after
  it.
- **B4 — the preparation, fit, scoring, and server configs** for the
  new lineage: `configs/preparation/prod-wit-photo-inst.json` (rgb,
  the Nord palette of spec C1 §5), `configs/fit/prod-wit.json` with
  placement back in the weight simplex (the F1 cut was "for this
  lineage"), `configs/scoring/prod-wit-mixed.json` and
  `prod-wit-photo-inst-sym.json`, and the server re-point held back
  until the freeze.
- **B5 — the committed-config guard** (`tests/unit/test_committed_configs.py`)
  extended to the `prod-` files: no `dev_only` release feeds a
  `prod-` scoring config, and no `prod-` config names a `dev-`
  release.
- **B6 — a prune command** for the build machine: the deployment docs
  name 25 GB free and no command removes rejected candidates from
  the materialized tree. Dev-only tooling, not a scoring change.
- **B7 — the screener slot** (ruling 11): one OpenRouter provider
  that answers `TextCoverageEstimator`, `ZeroShotImageClassifier`,
  and `SalientObjectEstimator` from one cached response with three
  fields, one instruction template, one `config_hash`, and the
  encoder's `input_canvas_px` rule. The three protocols and the
  stage code do not move. A fake twin for the tests.
- **B8 — the deferred boxes slot** (ruling 11): `element_boxes.provider`
  `deferred` skips p07, the record says so, and a scoring config that
  names placement against such a record is refused at the boundary.

---

## 8. Open rulings — agreement before the build

| # | Decision | Proposed | Notes |
|---|---|---|---|
| 2 | Sampling geometry | `sample_rate` 0.03, `sample_salt` `dev-wit-001` unchanged, `max_scan_shards` 105 | One knob moves from the development config, the development sample stays a subset, and the 2.6 GB scan is one-time and cached. The 0.10 × 32 shape spreads the sample across fewer shards. |
| 3 | Byte budget and cap | `budget_bytes` 20 GB, `materialize_cap` 38,000 | The cap is the cost fence of §5a: it stops the screening spend at USD 12.2. |
| 4 | Release tag | `prod-wit-001`, `dev_only` `false` | The label shape of P1a §6. The first release without the `dev-` prefix. |
| 5 | The calibration run | 20 shards (392,000 rows, about 11,800 sampled, about 7,600 materialized, about USD 6), tag `dev-wit-003` | Measures the near-duplicate rate and the s07 yield at 10 times the development count before the full spend. Its pool of about 1,400 is a dev pool, and it is not prepared. Replaces the 5% allowance of §3 with a measurement. |
| 6 | Diversity rule | Unchanged: divisor 50, cap 15 | A higher cap raises the yield and changes the pool's structure — the property V1 and V2 were gated on. Fund the funnel and keep the rule. |
| 7 | The vocabulary term | Build B3 before the production bench | §4 row 5. The other levers — device placement, half precision on the outline matrix — stay standing items. |
| 8 | Encoder | `google/gemini-embedding-2` through OpenRouter, unchanged | The P2c ladder adopted it. A local encoder reopens the end-to-end 50 ms question (P5 ruling 3) and is a lineage of its own. Park. |
| 9 | Provider rate | 2.0 `POST`/s, unchanged, or raised if the account allows | Sets the hours of §5 and §5a. Provider config, not a scoring change. |
| 11 | The two budget changes | Merge the three screens into one `POST` (B7) and defer the boxes (B8) | §5a. Without the two, USD 20 buys about 3,770 images on the unchanged pipeline, and the config-only path to 7,500 is a cluster cap near 50, which switches the diversity rule off. |

---

## 9. Runbook

The owner runs each command that touches the network, with the key
in the environment (`OPENROUTER_API_KEY`). Each step ends with a
committed record.

1. **Build items B1 to B8** merged, suite green offline, Vale at zero
   errors on touched prose.
2. **The calibration run** (ruling 5): `uv run python -m pool.curation
   --config configs/curation/dev-wit-3.json`. Read the funnel report:
   the s06 removal rate and the s07 yield at scale. Put the measured
   yields into §3, and move `max_scan_shards` in B1 if the projected
   count is not in 7,500 ± 5%. Stop at the s08 gate. No release is
   necessary.
3. **The production curation run**: the same command with
   `prod-wit.json`. Expected: about 105 shards scanned, about 47,000
   fetch attempts across about five hours, about 120,000 chat posts
   across about 17 hours, one embedding batch sequence, the stop at
   s08 with exit code 3. Review the contact sheet, write
   `review.json`, run the command again: s09 writes
   `pool/releases/prod-wit-001-<hash8>.json`. The count lands in
   7,500 ± 5% or the run is a new ruling, not an inline tune.
4. **Preparation**: `uv run python -m pool.preparation --config
   configs/preparation/prod-wit-photo-inst.json`. About 15,000 posts
   plus the crop and vocabulary embeddings. The record names the
   vocabulary count — the measured `|V|` replaces the Heaps
   projection in §4.
5. **Baseline gates**: V1 (sym), V2 (sym and mixed), and v2c on the
   Nord palette (spec C1 §5 asks for it before the first day with
   color on the production app). Verdicts recorded.
6. **Generalize, fit, freeze**: `validation.generalize` (about 26,800
   posts), then the F1 sequence — fit with placement in the simplex,
   the placement ruling read again on this lineage, freeze into
   `prod-wit-mixed` and `prod-wit-photo-inst-sym`, the guard test
   updated.
7. **The production gates**: V3 to V6 on the frozen weights, with the
   P5-parked thresholds live — tier widths 500/25 and the 90% recall
   line for V6. The inherited standing items go on the record where
   they bite: the level-4 generator premise (V3 `control_at_half`),
   element background composition (V5), the V5 hotspot monitor.
8. **The production bench**: `uv run python -m tools.bench --count
   7500 --vocabulary <measured |V|> --write`, after B3. Verdict on the
   50 ms line, recorded.
9. **Re-point and deploy**: `configs/service/` at the frozen
   production scoring config, the serving copy at 768 px on the 4 GB
   plan, the deployment smoke of spec B1 §9 step 4, then the first
   production day. The R13 gate on public numbers opens here.

---

## 10. Acceptance criteria

1. A release record without the `dev-` tag, `image_count` in
   7,500 ± 5%, verdict `pass`, in `pool/releases/`.
2. A preparation record on that release, with the vocabulary count
   on it.
3. V1, V2 (two modes), v2c, V3, V4, V5, V6 records with owner
   verdicts on the production lineage, V6 at the 500/25/90% line.
4. A fit record and frozen weights in the production scoring configs,
   the guard test green.
5. A bench record at 7,500 with the measured vocabulary, with the
   owner's verdict on the 50 ms line.
6. The server on the production config, and one production day played,
   closed, and revealed.
7. Suite green offline during the full phase. Vale at zero errors on
   touched prose.

---

## 11. Out of scope

- A local encoder and the end-to-end 50 ms (ruling 8).
- Device placement and half precision (standing items, ruling 7).
- Layer 7, the deferred rerank (Phase 6).
- Pool growth to more than 7,500 — a new lineage by §4 row 6.
