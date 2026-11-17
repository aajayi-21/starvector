# Spec AG1 — the Layer 9 repairs: the corrected score, the hit number, the day-level test

**Status:** ruled 2026-11-16 (§10). Not built.
**Phase:** before the player records start again and before the first
public day. Layer 9 is in the no-change tier of `CLAUDE.md` §5 after a
score is published, and no score is published today. This is the last
time a change here costs nothing.
**Architecture sections:** §15 (Layer 7), §16 (Layer 8), §17 (Layer 9).
**Working agreement:** `CLAUDE.md` §2 (I1, I3, I4, I6, I7), §5, §9, §10,
§11.
**Input:** the review of 2026-11-09, and the simulations of 2026-11-16 on
the production pool `prod-wit-001` (1,393 images, so 1,392 decoys).

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §10 says so and records
the ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

Three defects in Layer 9, and two sentences in the architecture that are
not correct:

1. **A trial score of zero takes control of a skill number.** A target in
   the last position gets a trial score of 0.0, and Layer 9 changes that
   into a term of about 744. One such trial pins the skill number of
   the player. With 1,392 decoys the chance is 1 in 1,393 for each
   trial, which at 877 players is about one trial on each second day.
2. **The statistic does not see occasional strong hits.** `S = −Σ log p`
   gives a perfect trial a term of zero, so some strong hits change it
   by a small value only. The architecture says the opposite.
3. **The baseline check of the population reads the players as samples
   with no connection.** All players of a day have the same target, so their
   trial scores move together on an easy day or a hard day.
4. **ARCHITECTURE §15 step 1** puts the target into the candidate set of
   Layer 7. That breaks I1 and I3 if Layer 7 is built as written.

## 2. What stands today, with evidence

- `core/ranking.py`: `p = (beaten + 0.5 × tied) / D`. A target with no
  decoy below it gets 0.0, and a target above each decoy gets 1.0.
- `core/aggregate.py`, `log_term`: a trial score of 0.0 reads as the
  smallest positive float, a term of 744.44, and the caller counts the
  clamp. A history where each score is 1.0 has `S = 0`, and
  `skill_summary` refuses it. The rollup marks such a pair "degenerate".
- `core/aggregate.py`, `baseline_check`: the two-sided Kolmogorov
  statistic on the chi-squared tail of each player. Each player is one
  sample, with no connection between the samples.
- `ARCHITECTURE.md` §17 says that this statistic detects occasional strong
  hits better than the mean trial score does.

The simulations of 2026-11-16 (`validation/aggregate_null.py` after
build item AG1.6, seed 20261116):

| Condition | Measure | Today | Repaired |
|---|---|---|---|
| 200 players with no skill, 100 days | the variation report fires | 1.000 | 0.030 (corrected score) |
| the same | the baseline check fires | 0.290 | 0.035 (corrected score) |
| 100 trials, 5% of them in the first position | power at 5% | 0.135 | 0.786 (the two directions) |
| 100 trials, a constant edge, Beta(1.25, 1) | power at 5% | 0.714 | 0.596 (the two directions) |
| no skill, the two directions together | rate of alarms | | 0.046 |
| 200 players, 60% attendance, a day correlation of 0.02 | the baseline check fires | 0.220 | the day-level test (§5) |
| the same at 0.10 | the baseline check fires | 0.510 | the day-level test (§5) |
| the same at 0.02 and at 0.10 | the variation report fires | 0.040, 0.035 | no change necessary |

The nominal level of each test is 0.05. The top-tail statistic alone
gets 0.854 on the strong hits and 0.434 on the constant edge, and the mean
trial score gets 0.244 and 0.631.

## 3. The corrected score

Layer 9 reads a corrected score, and not the trial score:

```
p̃ = (beaten + 0.5 × tied + 0.5) / (D + 1)
```

- **Properties.** `p̃` is in (0, 1) at each decoy count. With no skill
  and no equal scores, it takes the D + 1 centers of the unit interval
  with equal chance, so its mean is 0.5. The largest term is
  `log(2(D + 1))`, which is 7.93 at D = 1,392.
- **The clamp goes.** No trial score of 0.0 reaches a logarithm, so
  `log_term` has no clamp, the rollup counts none, and the pair has no
  `clamp_count`. No history has `S = 0`, so the refusal and the
  "degenerate" pair go too.
- **Layer 8 does not change.** The trial score `p` stays the number
  that a player reads as "you beat X%", and the daily board sorts by
  it. Trial rows hold `beaten`, `tied`, and `decoy_count` today, so
  Layer 9 calculates `p̃` from the stored rows and no row changes (I4).
- **The interface.** `core/aggregate.py` gets `corrected_score(beaten,
  tied, decoy_count) -> float`, and the functions that read a sequence
  of trial scores read a sequence of `TrialCounts` (`beaten`, `tied`,
  `decoy_count`), a frozen record in `core/types.py`.

## 4. The hit number and the evidence of the two directions

- **The second statistic.** `T = −Σ log(1 − p̃)`. With no skill, `T` has
  the same law as `S`: a Gamma value with shape n and rate one.
- **The hit number.** `h = T / n`. It is 1.00 at chance and it rises as
  more trials land near the top. It is an unbiased estimate of the mean
  term. The skill number `θ` does not change.
- **The fixed-count evidence.** Each statistic has its own tail: the
  bottom tail of `2S` and the top tail of `2T`, at 2n degrees of
  freedom. The evidence value of a player is two times the smaller of
  the two tails, with a maximum of one (a Bonferroni split at half the
  level for each direction). `evidence_p` holds this value.
- **The evidence at each look.** `e_S` is the mixture value of today. `e_T`
  is the same mixture on the hit side, with the mixture cut to the side
  where trials sit near the top, in the manner of the 2026-08-16 ruling.
  The player's value is `(e_S + e_T) / 2`. The mean of two values that
  each have a mean of one at no skill has a mean of one, so the bound
  that holds at each look survives. The significance is
  `min(1, 2 / (e_S + e_T))`.
- **The board and the population.** The leaderboard ranks by the
  steadied skill number, as today. The population fit, the variation
  report, the expected ranks, and the stopping monitor read `S` of the
  corrected scores. The discovery report reads the evidence value of
  the two directions.

## 5. The day-level test

- **The rule.** For a revealed day, for each candidate image t of the
  pool, calculate the corrected score that each player of the day gets
  if t is the target, with the decoys of t (the pool minus the
  near-duplicate group of t, as `decoy_set` gives). The day number of t
  is the mean of these scores:

  ```
  A(t) = mean over the day's players of p̃(t)
  u    = (#{t : A(t) < A(target)}
          + 0.5 × #{t ≠ target : A(t) = A(target)} + 0.5) / N
  ```

- **Why it needs no approximation.** With no skill, the submissions have
  no connection with the target, and the pick makes the target an equally likely member of
  the pool, with no connection to the submissions. So `u` is an equally likely
  value of its N steps, whatever the correlation of the players. With
  spec VP1 the target is a pulse after the close, which makes the
  independence literal. A `commit-v1` day picks with a seed before the
  play, and the same statement holds with no skill.
- **The check.** The baseline check of the population becomes the
  two-sided Kolmogorov statistic of the `u` values of the revealed days
  against the flat law. It replaces the check on the tails of the
  players.
- **Where it runs.** `u` reads the identity of the target, so the
  function that calculates it is in `core/ranking.py` (Layer 8):
  `day_rank(scores, target, index) -> float`, with `scores` the
  pool scores of the day's players (players × N). Layer 9 receives the
  `u` values and names no target, as the I1 test asks.
- **The pool scores.** The close calculates the fused pool scores of
  each send today. It keeps them as a cache:
  `data/day-scores/<scoring hash8>/<day>.npy` (float32, players × N,
  rows in the sequence of the sorted player names) with an index file of
  the names. The key holds the scoring hash (I4), and a rescore from the
  stored submissions makes the file again. A rollup that finds no file
  raises and names the command that makes it. It does not skip the day.
  The file is about 4.9 MB for each day at 877 players and 1,393 images.
- **What it publishes.** The rollup stores `u` for each revealed day. The
  public database gets a `day_rank` column in `days`. The value is
  calculated at the reveal and not before (I7).

## 6. The store and the wire

- **Trial rows and day records.** No change.
- **The rollup pair.** It holds `s_statistic` and `t_statistic` from the
  corrected scores. `clamp_count` and `degenerate` go. The prepared
  boards get a new format version, so a board of the previous format is
  made again from the trial rows.
- **`GET /api/history`.** `skill` adds `hit_number`. `evidence_p` is the
  value of the two directions.
- **`GET /api/leaderboard/skill`.** Each row adds `hit_number`, and the
  evidence fields hold the values of the two directions. The population
  part replaces `baseline_check` with `day_check`: the day count, the
  statistic, and its significance.
- **The public database.** `days.day_rank`, a schema version step, and
  the README gives the two formulas of §3 and §4.

## 7. The screens

- **History.** The hit number shows below the skill number, in the same
  plain words: 1.00 is chance, and higher means more trials near the
  very top. The sentence about luck reads the evidence of the two
  directions.
- **The skill board.** A hit number column, not sorted.
- **How it works.** One paragraph says what each number rewards: the
  skill number a constant edge, the hit number occasional strong hits.

## 8. The changes to the architecture

The owner agreed to these edits on 2026-11-16 (§10, D4).

- **§17.** The incorrect sentence goes. The section names the corrected
  score as the input of Layer 9, the hit number, the evidence of the two
  directions, and the day-level test, and it says which pattern each
  statistic detects, with the numbers of §2.
- **§16.** One sentence: Layer 9 reads the corrected score, and the trial
  score stays the player-facing number.
- **§15, step 1.** The candidate set is the top 25 of the fast ranking,
  selected with no knowledge of the target. The target is not put into
  it: a candidate set that depends on the target treats the target and
  the decoys differently (I3), and it puts the target upstream of Layer 8
  (I1). The ranking that comes from the stitch is a full sequence of the
  pool made with no target, so the trial score keeps its flat baseline.

## 9. Testing

- **Unit.** `corrected_score` at the two ends and with equal scores. `T`
  and the hit number on fixed vectors. The evidence of the two
  directions is at most one, and it equals two times the smaller tail.
- **Null.** `validation/aggregate_null.py` gives the rows of §2 from a
  seed, and a test runs a short version of it: with no skill, the variation
  report, the evidence of the two directions, and the day-level check
  fire at the nominal level in a stated interval.
- **The mean at each look.** The mean of `(e_S + e_T) / 2` at no skill is one,
  measured on 200,000 draws, as the test of today measures `e_S`.
- **The day-level test.** Simulated days with a correlation of 0.10:
  the check on `u` fires at the nominal level. A target that is the best
  image of the day for each player gets `u` near one. The I1 test
  stays green, because `day_rank` is in `core/ranking.py`.
- **Rollup.** A board of the previous format is made again. A missing
  pool-score file raises with the command in the message.
- **Prose.** Vale on this spec, the architecture edits, and each
  docstring that the build writes.

## 10. Decisions, ruled 2026-11-16

- **D1 — the zero score.** Layer 9 reads the corrected score of §3, from
  the stored counts. Layer 8 does not change.
- **D2 — what the evidence detects.** The two directions, each at half
  the level (§4).
- **D2a — the display.** A hit number adjacent to the skill number, with one
  evidence value for the two.
- **D2b — the board.** It ranks by the steadied skill number, as today.
  No second board.
- **D3 — the shared day.** The day-level test of §5 replaces the
  baseline check of the population.
- **D3a — the day number.** The mean corrected score of the day's
  players.
- **D4 — the architecture.** The edits of §8.

## 11. Build items

1. **AG1.1.** This spec, Vale-clean.
2. **AG1.2.** `corrected_score`, `TrialCounts`, `T`, the hit number, and
   the evidence of the two directions in `core/aggregate.py`, with unit
   tests.
3. **AG1.3.** The rollup pair, the board format, the history and skill
   board wire, and the discovery report.
4. **AG1.4.** The pool-score cache at the close, `day_rank` in
   `core/ranking.py`, the day check in the rollup, and `days.day_rank`
   in the public database.
5. **AG1.5.** The screens of §7.
6. **AG1.6.** `validation/aggregate_null.py` and its short test.
7. **AG1.7.** The architecture edits of §8 and the notes on specs S1 and
   M1 that this changes.

Each item is one commit, green and Vale-clean on the touched prose.

## 12. Out of scope, with causes

- **A change to the trial score of Layer 8.** D1 keeps it. A player sees
  the same percentage as today.
- **A second board for the hit number.** D2b.
- **Layer 7.** It is not built. §8 corrects its text, and a build then
  starts from a correct procedure.
- **The test-season days.** The player records start again before the
  first public day, so no published number changes. The boards of the
  test season are made again from their trial rows with the new rules.
