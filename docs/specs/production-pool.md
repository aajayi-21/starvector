# Spec PP1 — the production pool at N = 7,500

**Status:** surveyed 2026-09-02. Rulings 1 (the pool count, §2) and
10 (the budget, §5a) are the owner's. Rulings 2 to 9 and 11 (§8) are
open. Not in build.
*Note, 2026-11-03:* the plan of 2026-11-03 accepts rulings 2 to 7, 9,
and 11 as proposed, with the changes in §5b. Spec VE1 opens ruling 8
again. Build items B3 and B5 to B8 are built. B1, B2, and B4 are the
tool `tools/production_configs.py`, because their values wait for the
VE1 verdict and the near-duplicate ruling.
*Note, 2026-11-09:* §5c corrects numbers and commands in §3, §8, and
§9, and it gives the tool three steps. The open items at this date are
ruling 8 (the VE1 verdict), the two near-duplicate thresholds, and the
wording of the person rule.
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
   pool. *Correction, 2026-11-03:* `pick_target` draws with replacement,
   thus 20.5 years is the mean wait for one image to come back, and a
   second use of one image is more likely than not by about day 102.
   This rule stays: it keeps the chance guarantee accurate.
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

*Note, 2026-11-03:* the code encodes the s05 survivors, about 26,700,
not 38,000. If spec VE1 moves the encoder slots, the two embedding rows
(USD 8.20) go to the Voyage credits, and USD 10.90 stays. The rule
against images of one person or one face (plan of 2026-11-03) lowers
the yield, and the calibration run
measures by how much.

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

## 5b. Changes of 2026-11-03

**The person rule (owner ruling).** An image of one person or one face
goes out of the pool at s05, with the cause `person-focus`.
A person in a scene stays. The screener answers with one of three roles,
thus the rule has no numeric limit. The wording is the open item:
`validation/screener_check.py` shows what each group holds on the
development images, and the owner rules on it.

**Two new labels.** The s04 set gets `painting or artwork` and `document
or scan`. The classifier had to give one label from the set, and about
7% of the development pool reads as artwork.

**No safety stage (owner ruling).** The pool has no content-safety
stage, and the review stays a sample of 200, 2.7% of the pool. A graphic
image can become a target. The owner accepted this.

**The new normalize rule.** `d8-v1` replaces `d7-v1` for each new
lineage, and `d7-v1` stays for each stored day. On the dev-wit-002 lists,
`d7-v1` gave the non-words `hous`, `hors`, `ros`, `bas`, `len`, `canva`,
`campu`, and `mysteriou`, and `leaves` became `leave`. The encoder reads
atoms as the player wrote them, thus these strings had no matching atom.

**One commonness source.** The served `dev-wit-mixed-3` holds source A,
and the fit and V3 to V5 used source B, thus the V5 slopes did not
describe the served tables. Each `prod-` scoring config holds source B.
V5 measured an element slope of −0.326 on source B, an overcorrection,
thus V5 on the production lineage is the check of this ruling.

**The cost with the person rule.** The yield is not measured. If the rule
removes 20% of s05 survivors, the screening count goes from 38,000 to
about 47,500, which adds USD 2.31 and takes the fetched bytes to about
19 GB. With Voyage the total is about USD 13.2. With Gemini it is above
the USD 20 ruling, thus that path needs the lever of ruling 6 or a lower
count. The calibration run measures the yield before the spend.

**Placement against deferred boxes.** B4 puts placement back in the fit
simplex, and B8 defers the boxes that placement reads. The two do not
agree. The default follows ruling 11: no placement weight in a `prod-`
config, and the boundary refuses a config that names placement against
deferred boxes. If Voyage clears, the boxes (USD 4.72) fit in the budget:
`--boxes bought` writes the configs with them.

**The fast path, measured** (`tools.bench`, 7,500 images, |V| 26,770, `--repeat`
count 5, synthetic vectors, B3 built):

| dimension | local total | similarity table | tier 1 | outline | resident |
|---|---|---|---|---|---|
| 3072, before B3 | 239.32 ms | 208.29 | 10.35 | 23.27 | 1.44 GB |
| 3072 | 94.9 ms | 19.8 | 18.9 | 37.7 | 1.76 GB |
| 1024 | 52.2 ms | 7.4 | 19.3 | 13.3 | 0.59 GB |

The first row is the §4 record, at `--repeat` 9 on a different day.
B3 removes the similarity-table problem. At 1024 dimensions the total is
2.2 ms above the 50 ms line, and tier 1 is the largest term.

**The runbook with these changes.** The steps of §9 stay, with these
edits:

1. Before step 2: rule on the VE1 verdict and the thresholds, then write
   the configs:
   `uv run python -m tools.production_configs curation --encoder voyage
   --curation-threshold <ruled> --preparation-threshold <ruled>`.
   *Note, 2026-11-09:* §5c makes this two steps, `calibration` and
   `curation`.
2. After step 3: write the lineage configs with the same command, the
   step `lineage`, and `--release-record <the new record>`.
3. Step 6 comes before step 5: V1 and V2 read source-B tables, and these
   tables read the generalize table. V1 also runs on `prod-wit-mixed`.
4. After step 3: `uv run python -m tools.prune_candidates`, then with
   `--apply`, to free the rejected candidates.

---

## 5c. Corrections of 2026-11-09

A read of the code against this spec found text that the code does not
agree with. The code is correct in each of these, and the older text
stays above as the record.

**The tool has three steps.** `tools/production_configs.py` wrote the
calibration config and the production curation config in one step. The
calibration run measures the yield, and the owner rules the production
shard count, byte budget, and cap after it, thus the production file
could not be correct at that time. The steps are:

- `calibration` writes `configs/curation/dev-wit-3.json`.
- `curation` writes `configs/curation/prod-wit.json`. It takes
  `--scan-shards` (default 105), `--budget-bytes` (default 20 GB), and
  `--materialize-cap` (default 38,000), the proposed values of rulings
  2 and 3.
- `lineage` writes the preparation, fit, and scoring configs. The fit
  config gets the production V6 widths, 500 for tier 1 and 25 for
  tier 2 (§9 step 7, §10 item 3). It held the development widths of
  spec P4 decision D10. `--v6-tier1-widths` and `--v6-tier2-widths`
  change them.

Give the same `--encoder`, `--cell`, and threshold values to each step.
The calibration answers are the production cache only when the screener
and the encoder are equal in the two files.

**The fit config has more development values.** `fit_count` 300,
`holdout_count` 150, `v3_trials_for_each_level` 200, and the split
salts come from `configs/fit/dev-wit-2.json` with no change. No spec
gives production values for them. The fit config hash covers them, thus
the owner rules on them before the fit.

**Counts in §9.**

| Where | The text | What the code does |
|---|---|---|
| Step 3 | about 120,000 chat posts across about 17 hours | The screener of B7 sends one `POST` for each s02 survivor: 38,000 at the cap, about 5.3 hours at 2.0 `POST`/s. |
| Step 4 | about 15,000 posts | With deferred boxes (B8) the describer sends 7,500. |
| Step 8 | `tools.bench` with no dimension | The default is 3072. Add `--dimension 1024` for the Voyage space. |
| Step 6 | `validation.generalize` | The command wants `--config configs/fit/prod-wit.json` and `--scoring-config configs/scoring/prod-wit-b.json`. |

**Keys.** §9 names `OPENROUTER_API_KEY` alone. With the Voyage encoder,
s06, the preparation, and each gate also read `VOYAGE_API_KEY`. The
curation run reads the OpenRouter key at s03 and the Voyage key at s06,
thus a key that is not in the environment stops the run after the
fetch. Put the two keys in the environment before step 2.

**No response is in the cache at the start.** §3 says that the s03 to
s05 responses of the 1,036 development candidates stay in the cache. The
screener of B7 has a new config hash and no stored response, thus each
candidate gets one new `POST`.

**The scan has no cache.** Ruling 2 says that the scan is done one time.
`max_scan_shards` is in the corpus hash, and the scan result is in the
tree of one curation hash alone. The corpus adapter reads the shards
from the hub and keeps no file. The calibration config and the
production config thus each scan their shards.

**The calibration cost.** Ruling 5 says about USD 6, and §5a says about
USD 2.3. The §5a value is the one-`POST` screener, and it is the
current estimate.

**The cap against the count floor.** With the yield of §3 and its 5%
near-duplicate allowance, a cap of 38,000 gives about 7,110 images.
The floor of §10 item 1 is 7,125. The calibration run replaces the two
estimates with measured values, and the owner rules the cap after it.

**Steps that are not in §9.** Before step 2: steps 3 to 7 of spec
VE1 §8, then `validation.screener_check` on the development s02
manifest for the wording of the person rule. A change of that wording
moves the screener hash, thus it comes before the calibration run.

**A stop in the fetch.** s02 holds one fetch batch in memory and
continues from its journal after a stop (`docs/specs/pool-curation.md`,
the s02 note of 2026-11-09). A change of a provider rate or a retry
count starts a new tree, because the curation hash covers those values.
Set them before the run.

**Small differences.** The B5 guard is in
`tests/unit/test_production_tools.py`. The tool also writes
`configs/scoring/prod-wit-b.json`. It is to the fit and to V3 to V6
what `dev-wit-b-2` is on the development lineage, and it is equal to
`prod-wit-mixed.json` in each field but the tag. No command makes the
768 px serving copy of step 9.

## 5d. Rulings of 2026-11-11 — a first pool of about 1,000

**The count (owner ruling).** The first production pool has about
1,000 images. The 7,500 of ruling 1 stays the count of a subsequent
lineage, by §4 row 6. For this lineage, §10 item 1 reads against the
count that the run gives, and the owner's `review.json` accepts it.

**What moves in §4.** The chance guarantee has no `N` in it and does
not move. The trial score has about 1,000 different values. A frontload
tag must cover 20% of the pool to keep `D ≥ 200`. A second use of one
image as the target is more likely than not by about day 38. The top of
the rarity range is 6.9 nats.

**The encoder (owner ruling).** Gemini is in each encoder slot, the
sketch slot also (spec VE1 §9). Ruling 8 closes.

**No batch model.** OpenRouter has `google/gemini-embedding-2:batch` at
half the standard cost, USD 0.225 for each million image tokens. Its
batch API accepts text input alone for embeddings, and its docs say
that multimodal input is not available there. Image vectors are almost
all of the embedding cost, thus each slot keeps
`google/gemini-embedding-2`. At this count the two embedding rows of
§5a come to about USD 1.

**No calibration run apart from the production run.** Ruling 5 sized
the calibration run at 20 shards, and a pool of about 1,000 is that
scale. The production run is thus its own measurement: it stops at the
s08 gate, and the owner reads the funnel report before the review.

**Proposed values.** The owner rules on them when the owner runs the
`curation` step of `tools.production_configs`:

| value | proposed | from |
|---|---|---|
| `--scan-shards` | 20 | ruling 5: about 11,800 sampled rows, about 7,600 materialized |
| `--materialize-cap` | 8,000 | above the 7,600 of ruling 5, thus it stops the fetch only for a sample that is larger than the estimate. The screening cost stops at about USD 1.95 |
| `--budget-bytes` | 5,000,000,000 | 0.5 GB of scan and about 3.1 GB of fetched images, with room |
| the two thresholds | 0.95 | the control of spec VE1 §9. A variant that s06 does not catch at 0.95 goes into its p08 group, thus I3 holds |

At the yields of §3, 7,600 materialized candidates give about 1,400
images. The person rule and the two new labels have no measured yield.
If the two remove 25% of the s05 survivors, the count is about 1,050.
The expected count is thus 1,000 to 1,400.

**Cost and time.** About USD 3.5 at the standard cost: about USD 1.85
of screening, about USD 0.4 of curation embeddings, about USD 0.2 for
the describer, about USD 0.9 for the crop embeddings, and about USD 0.1
for the generalize table. About one hour of fetch and one hour of
screening at 2.0 `POST`/s.

**The sequence.** `validation.screener_check` with the production
curation config on the development s02 manifest comes first. Its 1,036
answers have the production screener hash, thus the production run
reads them from the cache.

**A contradictory screener answer (owner ruling).** The screener gave
`photograph` with confidence 0.05 for a line diagram, the 508th image of
the check. With ten labels, a confidence at or below 0.1 puts the stated
label below each other label of its row. That was an error, and it
stopped the check.

The ruling: such an answer is not an error. Its row
has no winner, and s04 puts the image out with the cause
`class-no-winner` (`docs/specs/pool-curation.md`, the s04 note of this
date). The answer goes to the cache, thus a second start gives the same
decision with no `POST`, and the funnel report counts the cause. The
classifier slot with three `POST`s keeps its error.

**The answers of a group that stops.** A refused answer stopped its
group before the good answers after it were in the cache. In the check,
528 answers had their cost and were not stored. The provider
stores each good answer of a group first and then gives the error.

**Open before the fit.** The V6 widths 500 and 25 of §5c and the
`tier2_count` of 500 are values for 7,500 images. The fit counts of
§5c are also open. The owner rules on them before the `lineage` configs
go to the fit.

---

## 5e. Ruling of 2026-11-12 — the boxes are bought for the first pool

**What the first preparation gave.** The run of 2026-11-11 gave the
release `prod-wit-001-ba15d5b3` with 1,393 images and the preparation
`prod-wit-photo-inst-1e921f6b` with 6,079 vocabulary entries. That
preparation deferred its boxes (B8), thus no element of the pool has a
box.

**The fit stops on that preparation.** `validation.fit` asks for a
placement commonness table when a generator level names a relation. The
generator makes a relation from two located elements. With no box, no
synthetic submission has a relation, and no background submission
activates placement. The fit then stops at the D13 check.

A run on the fake providers with the located slots empty gave that
stop. V4 reads the same data and stops there also. This is the
disagreement between B4 and B8 that §5b records.

**The ruling (owner).** The boxes are bought for this pool. The cause
of B8 was the cost at 7,500 images. At 1,393 images the boxes are
about 1,330 `POST`s. The development mean of USD 0.000627 for each
`POST` gives about USD 0.85. The describer cost on this pool was 3.2
times its development mean, thus the estimate is USD 1 to 3.

**What changes.** The `lineage` step ran again with `--boxes bought`:

- `configs/preparation/prod-wit-photo-inst.json` names the OpenRouter
  boxes slot. Each other slot hash is equal to the first preparation,
  thus the boxes are the only new `POST`s.
- The three `prod-wit` scoring configs name the record
  `prod-wit-photo-inst-fff3dddd` and have a placement weight in the
  candidate table.
- `configs/fit/prod-wit.json` does not change.

The preparation `1e921f6b` is not the input of a gate, a fit, or a
day. Its record is not in `pool/preparations/`, and its tree stays on
disk as a cache. The release record does not change.

---

## 5f. Rulings of 2026-11-13 — the fit, the placement cut, the freeze

**The second preparation.** `prod-wit-photo-inst-fff3dddd` has a box
for 96.8% of its elements (21,538 of 22,255). The generalization table
has 6,079 entries.

**The baseline gates (owner verdicts: `pass`).** Candidate weights, not
fitted.

| gate | config | result |
|---|---|---|
| V1 | `prod-wit-photo-inst-sym` | first rank 0.600 and first ten 0.940 on 200 pairs, in 1,593 images |
| V2 | `prod-wit-photo-inst-sym` | KS significance 0.943, mean 0.497, 500 trials |
| V2 | `prod-wit-mixed` | KS significance 0.818, mean 0.496, 500 trials |

**The fit (owner verdict: `pass`).** Record `fit-prod-wit-43b3ca6a`.
The winner is element 0.45, outline 0.50, placement 0.05. Its
objective is 0.906632 on the fit trials and 0.900987 on the holdout
trials. The winner is not an endpoint. One synthetic fit record was
below the min-ink gate and is not a trial
(`docs/specs/fuse-and-validate.md` §17a item 2, the note of this
date).

**V4.** Record `v4-prod-wit-1ca044b8`, on the holdout trials:

| channel removed | weights of the second fit | holdout objective | cost |
|---|---|---|---|
| element | outline 0.05, placement 0.95 | 0.830205 | 0.070782 |
| outline | element 0.90, placement 0.10 | 0.886000 | 0.014987 |
| placement | element 0.50, outline 0.50 | 0.901114 | −0.000127 |

**The placement ruling (owner).** The cost of placement is below the
0.01 line of spec F1 ruling 2, thus the channel is cut for this
lineage. `placement_signal` is 0.949, thus the channel itself works.
Relations stay stored, and a subsequent pool reads the ruling again.

**The freeze.** `configs/scoring/prod-wit-mixed.json` and
`configs/scoring/prod-wit-photo-inst-sym.json` have the weights that V4 gives with
no placement channel: element 0.5, outline 0.5. `fusion.fit_record`
names the fit record. `configs/scoring/prod-wit-b.json` keeps the
candidate table, because the fit record and the V4 record name its
scoring hash.

**The config of V3, V5, and V6.** §9 step 7 puts these gates on the
frozen weights, and §5c says that `prod-wit-b` is their config. The
two texts do not agree after a cut, because `prod-wit-b` has a
placement weight that no player gets. The gates run with
`--scoring-config configs/scoring/prod-wit-mixed.json`. A run on the
fake providers shows that V3, V5, and V6 complete with relation levels
and no placement weight.

**The gates on the frozen weights (owner verdicts: `pass`).**

| gate | record | result |
|---|---|---|
| V1 | `v1-prod-wit-photo-inst-sym-55e1fa23` | first rank 0.600, first ten 0.940, equal to the baseline |
| V2 | `v2-prod-wit-photo-inst-sym-201dc698` | KS significance 0.943, equal to the baseline |
| V2 | `v2-prod-wit-mixed-8c4176f4` | KS significance 0.818, equal to the baseline |
| V3 | `v3-prod-wit-f2dbb94e` | monotone: 1.000, 0.999, 0.939, 0.739, 0.449. `control_at_half` is `false` |
| V5 | `v5-prod-wit-b120e769` | slopes: outline +0.279, element −0.244. 83 images above the 3.0 line |
| V6 | `v6-prod-wit-5aaabf80` | tier-1 recall 1.0 at width 500, tier-2 recall 0.995 at width 25 |

Three standing items stay open, and each is in the notes of its
record:

- **V3, level 4.** The interval is 0.409 to 0.490. It is the
  anti-informative control of the ruling of 2026-08-13, and the
  redesign of level 4 waits for the next generator revision.
- **V5, the element slope.** It is negative, as on the development
  lineage (−0.326). The V2 marginal stays in agreement with `Uniform(0, 1)`.
- **V5, the tail.** 83 of 1,393 images (6.0%) hold 29.6% of the
  top-ten places of the background. The highest image has 108
  appearances, and the equal share is 7.2. The development pool had
  1 image of 204 above the line.

**The bench.** `bench-1393-39f1ad67`: `local_total` is 28.3 ms at
1,393 images and 6,079 vocabulary entries, with the similarity table at
15.4 ms. The 50 ms line is the owner's verdict.

**The color gate.** `validation/colorize.py` has the palette of spec
C1 §5 (the set of 2026-08-14), and each v2c record names its palette.
The gate runs on `configs/scoring/prod-wit-photo-inst-sym.json`,
because the production preparation renders in color.

**The server config.** `configs/service/prod-wit.json` names
`configs/scoring/prod-wit-mixed.json`. The warm start of the server
reads the pool and the two commonness tables with no `POST`. The
deployed server moves to this config after the color gate has its
verdict.

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

*Note, 2026-11-03 (spec PL1 §7):* the `prod-wit` scoring configs set
`report.channel_scores` to `true` from their first day, thus each trial row of the
production lineage stores each channel's score at the target.

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
| 8 | Encoder | `google/gemini-embedding-2` through OpenRouter, unchanged. *Note, 2026-11-03: open again. Spec VE1 compares `voyage-multimodal-3.5` by a bake-off on the development pool, and the verdict there decides this row.* | The P2c ladder adopted it. A local encoder reopens the end-to-end 50 ms question (P5 ruling 3) and is a lineage of its own. Park. |
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
