# Scoring configuration files

Each file here is the full parameter surface of the trial scoring path
and the V1/V2 harnesses. The loader (`pipeline/config.py`) validates in
full: an unknown or missing field stops the run with an error that
names the JSON path. JSON has no comments, thus this file documents the
fields.

**Each edit changes the scoring config hash.** The hash keys the
commonness tables and the validation artifacts, thus an edited config
starts a new artifact lineage — see `docs/specs/scoring-path.md`
section 6. Sketch-encode responses are cached by the slot hash alone,
thus a config edit that does not touch the slot reuses each response
at zero cost (U1).

**There is no render section, on purpose.** The canonical render
values (canvas, line width, background, anti-aliasing) come from the
preparation config named by the preparation record — one source (R2).
A render field here is an unknown-field error.

## The headline knobs

- **Input preparation** — `input.preparation_record` names the
  committed preparation record. The pool index, the render values,
  and the near-duplicate groups come from its artifact tree, with
  digest checks on each file read.
- **Intake gates** — the D3 values. The architecture names the gates
  and gives no numbers, thus they live here, and each move forks the
  hash.
- **Sketch encoder** — `providers.sketch_encoder` must name the same
  model as the preparation image encoder (R7): the outline channel
  compares the two vector spaces. A local sketch encoder thus
  requires a local pool re-encode and a new preparation. `provider`
  can be `fake` for tests.
- **Dataset** — `commonness.dataset` selects the sketch-pair source
  (D1: FS-COCO). Two pin-at-first-download sentinels start as null:
  - `archive_sha256` — the first download raises with the observed
    digest, and the operator writes it here. The archive cache is
    addressed by the digest, thus pinning costs no second download.
  - `coordinate_extent` — the first parse raises with the observed
    value ranges, and the operator writes the dataset's canvas
    dimensions here.
  The `url` value is unconfirmed until the first download — the
  adapter raises rather than guesses on a layout it does not know.
- **Splits** — `split_salt` plus `split_fractions` divide the pairs
  into background, V1, and V2 sets (D8): hash-based, disjoint,
  enumeration-free. `background_count` (D6), `v1_pair_count` (R17),
  and `v2_trial_count` (D9) say how many each run draws.
- **Runtime** — machine-local, not part of the hash.
- **Report** — `report.dev_only` must agree with the `dev-` prefix of
  `validation.tag` (R15). Development numbers are not published.
