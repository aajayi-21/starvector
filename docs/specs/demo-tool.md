# Spec T1 — the one-trial demo tool

**Status:** side development tool, not a build phase.
**Architecture sections:** §12 (channels), §13.2 (source B), §16
(ranking). Nothing here changes a layer or a stored artifact.
**Working agreement:** `CLAUDE.md` §2 (I1, I2, I7), §7 (dev numbers
stay unpublished).

## 1. Purpose

A short procedure to *see* one trial: the tool makes one synthetic
submission with the Phase 4 generator, scores it against each pool
image on the production path, and writes one self-contained HTML
report. The report shows the submission, the fused ranking, each
fused channel's standardized scores, and — because the submission is
synthetic and its label is known by construction — the source
image's rank and trial score.

The audience is the developer and the owner. The tool answers "what
does the engine do with a submission, and why did this image rank
high" in one page, with no server, no GPU, and no network in fixture
mode.

## 2. What this tool is not

- **Not player-facing, not deployable.** No endpoint serves it, and
  no score leaves the machine (I7). The report carries a dev-only
  banner, and its numbers stay unpublished (`CLAUDE.md` §7).
- **Not a leaderboard, and not a judge.** The report shows ranks and
  scores. It prints no threshold, no cutoff, and no "match" label —
  the output is a rank, not a similarity (I2).
- **Not part of the scoring path.** The tool lives in `tools/`, and
  no module in `core/`, `pipeline/`, `providers/`, `pool/`, or
  `validation/` imports it. A deleted `tools/` directory changes
  nothing downstream.

## 3. How the tool works

### 3.1 Inputs

| Input | Meaning |
|---|---|
| `--config` | A committed scoring config. The pool, the channels, the weights, and the commonness lineage come from here, as in each harness. |
| `--fit-config` | The fit config that holds the generator level table and the generalization slot. |
| `--level` | The degradation level of the one synthetic submission (D1 row index). |
| `--seed` | The generator seed. One seed, one submission, byte-stable (R12). |
| `--top` | How many ranked pool images the report shows in full. |
| `--out` | The report file path. |
| `--fixture` | Build a small fake-provider pool in a scratch directory and run against it — no GPU, no network, no stored data. |

### 3.2 Wiring

The tool reuses the harness machinery verbatim and adds no new
provider surface: `load_pool_index`, `wire_encoders`,
`ensure_commonness_tables`, `ensure_table`, and `synthetic_set`. A
warm lineage makes the run read-only. A cold lineage builds tables
through the same keyed artifacts the harnesses use — the tool cannot
make an artifact that no harness makes.

Scoring mirrors the production prefix: validate, encode, one raw
score for each weighted active channel, commonness correction,
standardization, fusion across the weighted subset. The label enters
at the end alone, through `decoy_set` and `rank` — the Layer 8 rule,
as in each harness (I1).

### 3.3 The report

One HTML file, no external assets:

1. **The submission** — the impressions, the stated relations with
   their group labels, and the canvas strokes as an SVG.
2. **The ranking** — the top pool images by fused score. Each image
   shows as its element-box map: the p07 boxes with their vocabulary
   labels, so the reader sees *why* a stated relation fires there.
   No pool image bytes go into the report.
3. **The scores** — for each shown image, the standardized score of
   each fused channel and the fused value, as signed numbers.
4. **The label** — the source image highlighted in the ranking, its
   rank, and its trial score, with the note that a no-information
   submission scores level across [0, 1].
5. **Identity** — the scoring config hash, the commonness hash, the
   generator hash, the seed, and the level, so a report is
   reproducible bytes, not a screenshot.

### 3.4 Fixture mode

`--fixture` builds the 40-image fake pool the integration tests use
(`tests.conftest.build_direct_prepared_pool`), a fake-provider stack,
and a small built-in fit document with the fake generalizer. This is
the demo-anywhere path: it runs on a clean checkout with no data
directory. The import from `tests.conftest` is a reviewed dev-tool
allowance and stays behind the flag — production wiring must not
follow it.

## 4. Guardrails

The red flags of `CLAUDE.md` §10, applied to this tool:

- The target identifier appears only in the Layer 8 step and the
  report labels — nothing upstream takes it.
- No modality branch: the report *shows* what the submission holds,
  and scoring stays the shared path.
- No threshold and no "good match" boolean anywhere in the output.
- No caching: the tool writes one report file and nothing in
  `data/`. Each stored artifact it touches goes through the existing
  keyed `ensure` paths.
- The report is a local file. Publication of dev numbers stays out of
  scope, as everywhere (`CLAUDE.md` §7).

## 5. Layout and tests

```
tools/
  __init__.py
  demo.py            # wiring, scoring prefix, HTML rendering, CLI
tests/integration/
  test_demo_tool.py  # fixture-mode smoke test: the report builds
```

One smoke test runs the fixture path end to end and checks the
report holds the banner, the ranking, and the trial score. The tool
follows the repository style rules and its prose passes Vale.

## 6. How to run it

Fixture mode, from a clean checkout:

```
uv run python -m tools.demo --fixture --level 0 --seed 7 \
    --out demo-report.html
```

Against the dev pool, after the owner's live runs warm the
lineage (the generalization table and the source B commonness build):

```
uv run python -m tools.demo \
    --config configs/scoring/dev-wit-b.json \
    --fit-config configs/fit/dev-wit.json \
    --level 1 --seed 20260814 --out demo-report.html
```

A cold lineage in live mode builds commonness tables first, which
spends encoder work — run the demo after the gate runs, not before.
