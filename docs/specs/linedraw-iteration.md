# Spec P2b — the line-drawer sensitivity iteration

**Status:** draft, for review.
**Phase:** after Phase 2 (`docs/ARCHITECTURE.md` §25). Runs in
parallel with Phase 3 — the element channel does not touch the line
drawer, and the two builds go forward without each other.
**Architecture sections:** §11 (the style bridge and its
post-processing), §12.2 (the outline channel, as consumer), §23 (V1
and V2, the measures of success).
**Working agreement:** `CLAUDE.md` §5, §6, §7.
**Input:** the Phase 2 harness records
(`validation/records/v1-dev-wit-9d463458.json`,
`v2-dev-wit-28a7484d.json`, verdicts recorded 2026-08-08) and the
preparation `dev-wit-prep-001-efacf7ff`.

This spec is written for implementation by an AI agent. Where a value
or a rule is not given by the architecture or the result, §9 says so
and proposes a default. Do not implement an open decision without
agreement.

---

## 1. The result this spec addresses

The Phase 2 development runs cleared V1 and V2, and recorded one
result with three measured costs, all with one root:

- **A 43-member near-duplicate group in drawing space.** The p08
  grouping put 19% of the 225-image pool into one component. The
  member line drawings are sparse — median ink fraction 0.067 against
  0.124 for the remaining pool — and their pairwise cosine sits at or
  above 0.95 after encoding.
- **A conditional V2 bias.** Targets in that group rank against 182
  decoys and average p = 0.25 on no-information trials, against 0.56
  out of the group. The pooled KS statistic passes because the two
  biases almost cancel.
- **Part of the V1 weak tail.** The owner's visual review (2026-08-08,
  the committed contact sheet) found the sketches and the photographs
  good while the target line drawings were not recognizable — in the
  worst V1 pairs and in the 43-member group alike.

The working hypothesis, aligned with §11 of the architecture (the
post-processing matters more than the model selection): the binarize
threshold of 0.5 cuts the dim contours the detector emits on
low-contrast photographs, and the detector's working resolution of
512 pixels can drop small structure before the threshold sees it.
The hypothesis is unmeasured — step one of this spec measures it
before one knob moves.

## 2. Scope

**In scope**

- A local scan tool that re-runs the line-drawing stage on a small
  image set across a parameter grid and emits a contact sheet for
  visual review. No pool artifact changes, no network.
- One config extension: the detector's working resolution becomes
  its own `linedraw` field, decoupled from `canvas_px`.
- The iteration loop: a new preparation release with changed
  drawing-side values, the re-pointed scoring config, the V1/V2
  re-runs, and the compared measures the verdict is recorded on.
- A conditional row in the V2 report: mean p split by decoy count,
  thus the result this spec chases stays measured on each future
  run.

**Out of scope**

- A model change (HED, PiDiNet, the coarse variant). That is the
  contingency when the scan shows the raw detector output — not the
  post-processing — drops the structure. It stays one provider
  config change away and needs no new spec, only a D-ruling here.
- The canonical render values: `canvas_px`, `line_width_px`,
  `background`, `antialias` do not move in this iteration. They are
  shared constants with the Layer 0 sketch render (P2 R2), and a
  change there forks the submission side too.
- The curation follow-up (§8): recorded here, built with the next
  pool release, not in this iteration.
- The production pool. Each run in this spec is development-only.

## 3. Requirements

- **R1** — The scan runs the same detector and post-processing code
  path as the p05 provider (`providers/local/lineart.py` and
  `core/lineart.py`), with only the scanned values changed. A scan
  through a different code path measures nothing (Rule 3 in spirit:
  the compared drawings must go through the same pipeline).
- **R2** — The scan is local and offline: no OpenRouter use, no pool
  artifact writes. Its output is a contact sheet plus a small JSON
  summary (ink fractions for each cell), for eyes.
- **R3** — Each iteration of the loop is a full, recorded preparation
  release (P1b rules): a drawing-side change moves the `LineDrawer`
  hash, thus the preparation config hash, thus the artifact tree.
  No artifact is edited where it is.
- **R4** — The measures of an iteration are the Phase 2 harnesses,
  re-run unchanged: V1 first-rank and top-ten fractions, the p08
  member-count histogram, the V2 KS statistic, and the new
  conditional row. Success is a recorded human verdict on those
  numbers — the spec sets directions, not cutoffs (`CLAUDE.md` §10):
  the largest p08 component must shrink materially, the V2
  conditional distance must close to 0.5, and V1 must not regress.
- **R5** — The detector-resolution field defaults to the unchanged
  rule (`canvas_px`), thus the released preparation record stays
  reproducible with the extended config schema.
- **R6** — All new documentation and docstrings are Vale-clean at
  error level.

## 4. The scan tool

```
uv run python -m validation.linedraw_scan \
    [--prep-config configs/preparation/dev-wit.json] \
    [--scoring-config configs/scoring/dev-wit.json] \
    [--data-root data] [--out data/validation/linedraw-scan.html]
```

- **Image set (D2):** the members of the largest p08 group plus the
  target photographs of the twenty worst V1 pairs, read from the
  existing artifacts. Around sixty images.
- **Grid (D1):** `binarize_threshold` × `detect_resolution` across
  the proposed values, plus one `min_segment_px` variant. Around ten
  cells for each image.
- For each image and cell: run the detector one time at the cell's
  resolution, apply the cell's threshold and pruning, render the
  canonical 512-pixel drawing, and record the ink fraction. The
  detector output for each (image, resolution) pair is computed one
  time and shared across threshold cells.
- Output: one contact sheet (photo, then each cell's drawing, one row
  for each image) plus `scan.json` with the ink fractions. The sheet
  answers the deciding question: **does the structure survive in the
  raw detector output** (then the threshold or resolution is the
  correction) or not (then the model is — the §2 contingency).
- Needs the local torch stack (`local-xpu` or `local-cuda` group).
  The tool raises with a clear message when torch is missing.

## 5. The config extension

`linedraw` gains one field:

```json
"detect_resolution_px": null
```

`null` keeps the unchanged rule (`detect_resolution = canvas_px`).
An integer sets the detector's working resolution while the
canonical render stays at `canvas_px` (R5). The field is part of the
preparation config hash — a resolution change forks the lineage, as
each drawing-side change must (R3).

## 6. The iteration loop

One iteration, end to end:

1. Rule the new values (from the scan sheet) into a **new** config
   file (`configs/preparation/dev-wit-2.json`): `binarize_threshold`,
   `min_segment_px`, `detect_resolution_px`. A released config file
   is not edited, ever — the committed record's hash check reads it,
   thus each release owns its file (recorded 2026-08-08).
2. Run the preparation pipeline on the machine with the local stack.
   Element-side stages read their image-level caches again. p05,
   p06, and p08 recompute. Commit the new preparation record.
3. Point `configs/scoring/dev-wit.json` at the new record. The
   scoring config hash moves, thus the commonness tables and the
   harness artifacts get new keys.
4. Re-run V1 and V2. The photograph drawings and vectors recompute
   through the image-level caches (new drawer hash, new entries).
   The render values do not move, thus each sketch embedding stays
   response-cached. Expected cost: minutes of local GPU work plus
   about one hundred embedding `POST` operations for the new pool
   and photograph crops (measured reasoning recorded 2026-08-08).
5. Record the compared numbers in the new harness records' notes:
   the four R4 measures, earlier against new. The verdicts stay
   human.
6. Keep the better preparation as the Phase 3 base. An iteration
   that does not help is a recorded negative result, not a rollback
   — the earlier release stays on disk and in git.

## 7. The V2 conditional row

`validation/v2.py` gains one aggregate in its report and record:
mean p for trials at the minimum decoy count against mean p at the
maximum. On a pool with no giant component the two agree near 0.5
and the row is boring — which is the point. The row makes the §1
result a standing measurement, not a one-time analysis.

## 8. The curation follow-up (recorded, deferred)

The structural lesson: the s07 diversity cap runs in photograph
space, and this cluster only forms in drawing space. The next pool
release must see drawings before it releases. Options for that
spec, in rising sequence of change: an ink-fraction floor on p05
output that reports (not rejects — R13 of P1b forbids preparation
removals), a drawing-space near-duplicate check in curation before
release, or a curation-stage line-drawing step. This is a
curation-spec change and is out of scope here — recorded so it does
not get dropped.

## 9. Open decisions — agreement required before implementation

All five decisions were agreed individually with the project owner on
2026-08-08, each at its proposed default. The owner also
pre-approved the §6 iteration: the D3 selection applies the stated
criteria to the scan sheet, the reasoning goes into the records, and
the V1/V2 verdicts stay the owner's.

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| D1 | Scan grid | `binarize_threshold` in {0.30, 0.40, 0.50} × `detect_resolution_px` in {512, 768, 1024}, plus one cell at threshold 0.40 with `min_segment_px` 5 | Ten cells for each image. The 0.50 column is the unchanged behavior — the control. |
| D2 | Scan image set | The largest p08 group's members plus the target photographs of the twenty worst V1 pairs, deduplicated | Around sixty images — the ones the §1 result names. A small seeded set of stable images joins as a regression control. |
| D3 | First iteration values | Ruled after the scan sheet review — not before | The scan exists so this ruling is measured, not guessed. |
| D4 | Scan tool home | `validation/linedraw_scan.py`, CLI in the module, output below `data/validation/` | It is review instrumentation with V1 and V2, not a pool stage. |
| D5 | Model contingency start | If the scan's raw detector output at 1024 pixels stays unrecognizable on the group members, stop and rule on a model change (coarse variant, HED, PiDiNet) before more parameter cells | §11 of the architecture lists the alternatives. A model change is one provider config away (P1b D4). |

## 10. Acceptance criteria

1. The scan tool runs offline on the local stack and writes the
   contact sheet and `scan.json`. A machine without torch gets a
   clear error, not a stack dump.
2. `detect_resolution_px` parses, defaults to the unchanged
   behavior, and moves the preparation config hash when set
   (hash-sensitivity test).
3. The V2 report and record hold the conditional row, covered by an
   offline test.
4. `uv run pytest` stays green offline. Vale stays at zero errors
   on changed files.
5. One full iteration of §6 is run and recorded with the R4
   measures in the new harness records — or the D5 contingency is
   started and recorded as the outcome.
6. No open decision from §9 is implemented without recorded
   agreement.
