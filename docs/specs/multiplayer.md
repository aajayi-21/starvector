# Spec M1 — players, access, and the leaderboard

**Status:** ruled, prepared to build.
**Phase:** the multiplayer phase. The server grows player identity
and access control, the day becomes one shared trial with a
leaderboard, and Layer 9 gains the population half that §17 asks
for.
**Architecture sections:** §17 (Layer 9), §22 (protocol integrity),
§7 (the tiers), §21 (versioning).
**Working agreement:** `CLAUDE.md` §2 (I4, I6, I7), §5, §9, §10,
§11.
**Input:** spec S2 is merged. The server holds the contract
surfaces, the app and the operator console are built, and the
deploy files are written. Phases 1 through 5 of the architecture's
build sequence are complete and gated.

---

## 1. Purpose

The system plays one game for one configured person. Below that
surface the parts are prepared for many players: the store keys
submissions and trial rows by player name, and the close path
scores each stored submission in one batch. What is missing is who
the player is, how the server knows, and what a leaderboard across
players means.

This phase adds the three, and closes the Layer 9 hole an audit
found: the aggregation formulas are written and tested, while the
population half of §17 — the fitted population, the eligibility
floor, the discovery-rate adjustment, and the between-player
variation that §17 names the result worth having — has no code.

One measured outcome shapes the statistical part, and §6 carries
it: **the approximation §17 states for the uncertainty of the
skill number breaks the no-skill baseline at the player counts
this game will see.** The correction lands before a leaderboard
is published.

## 2. The rulings of 2026-08-15

1. **Invited players, records in the store.** The operator mints
   an invite. Each invite writes a permanent player record. The
   layout is the one open registration wants, thus opening
   registration subsequently adds an endpoint and moves no data.
2. **One shared daily target, with the send lock.** Each player
   gets the same target and the same decoys, which keeps the daily
   ranking sound. §22's alternative (a target for each player) is
   refused: it makes the daily leaderboard a ranking across
   different tasks.
3. **The daily leaderboard ships in this phase. The skill
   leaderboard is built and gated.** The daily board ranks players
   on one target and wants no population. The skill board turns on
   when the population can hold §17's obligations (§6).
4. **Display names, and each player who plays appears.** No
   opt-out in this phase.
5. **The shape holds thousands.** Layer 9 reads a table of two
   numbers for each player, and the caches are keyed by the
   scoring configuration hash.
6. **The operator plane wants a bearer token** from the deployment
   environment file, checked in constant time, with the SSH
   tunnel and the proxy refusal. Three layers that break
   independently.
7. **With no player record the server behaves as it does today:**
   one configured player and no credentials. Access control turns
   on with the first minted invite.
8. **Ranking is by posterior expected rank** (§6), which wants a
   change to §17 (§10).
9. **The accurate parameterization replaces the approximation** in
   the population arithmetic (§6). This is a correct-answer
   change, not a tuning selection.
10. **Evidence that holds at each look, the baseline check, and
    the stopping monitor ship with the skill board** (§6).
11. **The published skill number rises with skill.** §10 pins the
    convention so no future edit can invert it.

## 3. What the audit found

A layer-by-layer audit against `docs/ARCHITECTURE.md` ran before
this spec. Its verdict: Layers 0 through 6 and Layer 8 are
complete, Phases 1 through 5 are built and gated, and three holes
stay.

| Hole | This phase |
|---|---|
| §17's population half: no fitted population, no eligibility floor, the discovery-rate function written and used nowhere, no between-player variation, no uncertainty on the estimate | **Closed here** |
| Layer 7, the deferred rerank (Phase 6): no protocol, no module, no spec. Its precondition (the V6 recall measurement) passes | Out of scope (§13) |
| §20 frontloading: no tag artifact, no filtered decoys, no floor of 200 decoys | Out of scope (§13) — it wants a preparation run that is not built |

Three smaller results ride along. `service/server.py` holds
`POPULATION_MEAN` and `POPULATION_SPREAD` as constants labelled
display-only. `core/aggregate.py` ships `fdr_adjusted` with a
docstring saying it waits for the multiplayer stage. §22's rule
that answer length and timing must not follow the target is
asserted in the code and checked by no test.

## 4. Identity and access

### Player records

The store keys submissions and trial rows by player name today
(`store/days/<day>/submissions/<player>.json`). The player name
stays the identity, thus **no stored play record moves and no
migration runs**. The owner's played days keep working when a
record is minted for the name they hold.

A new permanent directory, `store/players/<player>.json`, with a
strict field set in the manner of the day record:

```
player          the store key, [a-z0-9-]{1,64}, unchanging
display_name    1 to 32 printable characters, the board label
token_hash      sha256 of the invite secret, hex
created_at      the mint time
status          "active" or "revoked"
```

Player records belong in the store, not the data root: they are
raw facts of play, not a rebuildable cache (I4). The record is
written one time at mint. Two guarded edits follow the day
record's precedent — replace the token, and move the status. The
name and the creation time do not move.

### Tokens and sessions

The invite is `<player>.<secret>`, where the secret holds 32
random bytes, URL-safe. The server keeps `sha256(secret)` and not
the secret. A high-entropy random token wants no slow password
hash.

`GET /join/{token}` divides at the separator, reads that one
player record, compares the hashes in constant time, and on
agreement answers 302 to `/` with the session cookie
(`HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age` 180 days). A
refusal is one constant 401 body. **The lookup reads one file and
scans nothing**, which is what makes the shape hold thousands.

The cookie holds the same token. Revocation replaces the hash in
the record, which stops the cookie at the read that follows. No
session table is built, thus nothing accumulates.

### The operator plane

The day lifecycle POSTs and the dev surfaces want
`Authorization: Bearer <token>`, compared in constant time against
the value in the deployment environment file. The proxy refusal
and the SSH tunnel stay.

**The server refuses to start when player records are stored and
the operator token is missing.** A quiet hole is worse than a loud
stop.

### The fallback

With `store/players/` missing or empty the server holds today's
behavior: identity is the configured player and nothing holds
credentials. The switch is the first stored record. Each of the
942 stored tests and the offline runbook keep working with no
edit, and the rollout is one command.

## 5. Multiplayer play

What works today, with evidence: `close_day` walks
`store.list_submissions(root, day)`, encodes the records in one
batch, and writes a trial row for each player. The store paths and
the `write-once` discipline are player-scoped.

What moves: the caller-scoped player replaces the configuration
closure across the player surfaces (the day view's `submitted`
flag, the send, the stored submission, history, the streak, and
me). The leaderboard walks each player with a row for that day.

**No disclosure while a day is open (I7, §22).** No answer says
how many players have sent, or which. The leaderboard keeps its
constant refusal until the day is revealed. This joins the R3
walk.

## 6. Layer 9 — completing the aggregation

Layer 9 sits in the no-change tier: an edit here invalidates
published numbers. Everything below lands before the first
published leaderboard.

### The parameterization defect, measured

§17 states that the uncertainty of `log θ` is about `1/√n`, and
that it does not change with θ. The second half is right. The
approximation is not, and the error grows with the player count.

With `S = −Σ log p` and no skill anywhere, `S` is Gamma with
shape `n` and rate 1. The accurate facts:

- `E[log S] = digamma(n) − log θ`, thus `log(n/S)` sits high by
  about `1/(2n)` — 0.58 at one trial, 0.05 at ten.
- `Var[log S] = trigamma(n)`, and `1/n` understates it by 64% at
  one trial and 18% at three.

The two errors move with the trial count, thus they look like
variation between players. Simulated with no player holding skill,
the between-player test fires at the 5% level:

| players | the approximation | the accurate treatment |
|---|---|---|
| 50 | 22.5% | 7.5% |
| 200 | 57.0% | 6.5% |
| 1000 | **97.3%** | 7.0% |

At a thousand players the approximation announces "the players
are different in skill" almost always, with no skill anywhere.
That is the outcome I6 is written to stop, arriving through
arithmetic rather than through weight fitting.

**The ruling:** the population arithmetic reads
`y = digamma(n) − log S` with variance `v = trigamma(n)`. The two
functions land in `core/aggregate.py` as pure code with no new
dependency, in the manner of the hand-written chi-squared tail
that is there. The player-facing skill number `θ` does not move.

### The population fit

The model is the standard two-level shape: `y_j` around
`log θ_j` with known variance `v_j`, and `log θ_j` around `μ` with
width `τ`. The estimator is **restricted maximum likelihood**, the
current recommendation for this model and the one estimator the
research found free of the documented failures at wide
trial-count ranges. It is a one-dimensional fit costing below
50 ms at a million players.

**A fitted `τ` of zero is a correct answer and stays.** It says
the players are not distinguishable at this time. A prior that
forces a positive value manufactures variation that is not there,
which is the incorrect direction for this system.

**Below 30 eligible players the fit does not run.** The fixed
values stay (`μ = 0.0`, `τ = 0.15`, the constants the server holds
today) and the board is labelled provisional. Simulation puts the
risk of a zero estimate at 66% with five players and 12% with
fifty, thus 30 is where fitting stops being a coin toss. At 200
players the estimate is publishable.

### The ranking rule

Ranks are a non-linear function of the estimates, thus ranking by
the shrunk estimate is not optimal for ranks. The rule is the
**posterior expected rank**: for each player, the sum across the
others of the probability that this player's skill is the greater
one.

The difference that matters is how a player with a small number
of trials is treated. The expected rank puts them at the middle,
which states the uncertainty honestly. A lower bound puts them
last, which asserts they are weak. The shrunk estimate mixes
skill with trial count.

Computation is by simulation: 2000 samples of the skill vector
come from the fitted posterior, each sample is sorted, and the
positions are averaged. This delivers the rank intervals of §9 in
the same operation. §17 offers the two other rules and not this
one, thus §10 carries the change.

### Eligibility

**30 trials**, the architecture's own figure. The research finds
the floor is not needed for a correct ranking — the shrinkage
keeps players who stop after a good run out of the top on its own
— thus the floor is a reliability and fairness statement, and it
stays because §17 asks for it. When the estimate is publishable at
200 players, the floor is recomputed as the trial count at which
the shrinkage weight gets to one half, which is about `1/τ̂²`.

### Reporting the variation

Four numbers, no verdict:

- `τ̂` with its interval, on the `log θ` scale, and `exp(τ̂)` as
  the multiplicative width a player can read.
- The variation statistic on `players − 1` degrees of freedom with
  its significance.
- The prediction interval `μ̂ ± 1.96 τ̂`.
- The population goodness-of-fit check against the Gamma law the
  no-skill baseline predicts.

**No `I²`.** It is a function of precision, thus it climbs when
players simply play more. Each objection to it in the literature
is stronger here, because the trial count is a behavior.

A variation statistic that does not clear its level is not
evidence that the players are the same, and the copy must not say
it is.

### Evidence that holds at each look

The player selects when to stop, thus a fixed-count significance
value is not theirs to read. The e-value from a mixture across
skill values is closed shape in the same two numbers:

```
log E = S + a·log b + lgamma(n + a) − lgamma(a) − (n + a)·log(S + b)
```

with the mixture constants `a = 1` and `b = 1` recorded here. The
value holds at each look and after the player stops at a moment of
their selection, and `1/E` reads as a significance level. This is
the number a player sees. The fixed-count value stays in the
record for the site-wide work.

### Standing monitors

- **The baseline check.** Fit the no-skill law of the evidence
  statistics and compare it against the law the uniformity
  guarantee predicts. Disagreement says the pipeline
  broke V2's uniformity — the invariant that matters most — thus
  this is a live gate and not a curiosity.
- **The stopping monitor.** The precision-weighted correlation
  between a player's estimate and the logarithm of their trial
  count. With clean play it sits at zero. With stopping after a
  good run it moved to +0.34 and +0.54 in simulation and fired in
  each replication, where the variation statistic saw nothing.
- **The site-wide claim** ("N players are above the baseline")
  reads the
  `fdr_adjusted` function that is written, at level 0.05, and is
  published as a natural frequency: *"47 players are flagged.
  About 5 of those are flagged by luck alone."*

## 7. Scale

Layer 9 reads two numbers for each player, `n` and `S`, and **the
two are additive**: a new trial adds one and `−log p`. The pair is
a cache rebuildable from the stored trial rows, thus it belongs in
the data root keyed by the scoring configuration hash, and a
assemble command restores it.

| Artifact | When | Cost |
|---|---|---|
| `data/skill/<player>.<hash8>.json` — the pair | Each reveal, for players with a row | One read and one write for each player who played |
| `data/leaderboards/<day>.<hash8>.json` — the daily board | Each reveal | One read across that day's rows |
| `data/skill-board.<hash8>.json` — the fit, the ranks, the intervals | Each reveal | One read across the pairs, then the sampling |

Measured in the research and cited here: the fit costs below 50 ms
at a million players, and the sampling for ranks costs seconds at
ten thousand. The interactive endpoints read a prepared file.
Nothing in the read path walks the store.

## 8. The wire additions

Shapes are typed in `web/src/api/types.ts`. The system of record
is `service/server.py`.

- `GET /join/{token}` — 302 with the session cookie, or one
  constant 401.
- `GET /api/leaderboard?day=` — revealed days alone. One row for
  each player with a stored row that day, sorted by trial score
  down: display name, trial score, rank, decoy count.
- `GET /api/leaderboard/skill` — the skill board when it is
  active, else a body saying it is not active with the count of
  eligible players. Rows: display name, skill number, shrunk
  value, trials, expected rank, rank interval, evidence.
  Alongside: the population values, the variation report, the
  eligibility floor, and the provisional flag.
- `GET /api/me` — display name with the fields it holds today.
- `POST /api/players` (operator) — mint an invite, answering the
  URL one time. The console reads it. A command-line path is built
  for the box.

## 9. The player surfaces

- **The invite gate.** A 401 renders a screen that says an invite
  URL is the procedure. The cookie rides `same-origin` calls, thus
the
  client handles no credential.
- **The leaderboard screen.** The nav's Leaderboard item leaves
  the reveal screen for a screen of its own with the daily board
  and the skill board. The daily board is a plain table. The
  skill board shows the rank, the rank interval, and the trial
  count with equal weight, and its primary chart plots the skill
  number against the trial count with the bands the no-skill
  baseline predicts — the shape that makes "the low-trial outliers
  are noise" plain with no sentence.
- **Display names** in the nav, the account card, and each board.
- The reveal screen's leaderboard card serves the day's rows.

## 10. Changes to `docs/ARCHITECTURE.md`

Drafted here, for the owner's approval before they land. The
canonical document stays the owner's.

1. **§17, the ranking rule.** The text offers the shrunk estimate
   or its lower bound. The change adds the posterior expected rank
   as the rule, keeps the two earlier options as the simpler
   alternatives, and records why.
2. **§17, the uncertainty statement.** "The uncertainty in
   `log θ` is approximately `1/√n`" becomes the accurate statement
   with `digamma` and `trigamma`, with the measured table of §6 as
   why. This is the correct-answer item.
3. **§17, the convention.** One sentence pinning that the trial
   score is the fraction of decoys beaten, that the skill number
   rises with skill, and that the evidence direction is the small
   tail. The code agrees today. The document does not say it, and
   a future edit could invert it with no notice.
4. **§11, a dated note.** The section describes the line drawing
   as the mechanism of the style bridge. Spec P2c retired that
   bridge for the live lineage in favor of the instructed
   photograph. The note records the divergence rather than
   rewriting the section.

## 11. Build items

- **B1 — the player record.** The store module grows the record,
  the strict read, the mint, the guarded replace and revoke, and
  the listing. Tests: the field set, the `write-once` mint, the
  guarded edits, and a name that is not a legal store key.
- **B2 — tokens and the session.** Minting, the constant-time
  check, `GET /join/{token}`, the cookie attributes, and the
  constant 401. Tests: agreement, refusal two times with equal bytes,
  a revoked player, a replaced token, and the cookie attributes.
- **B3 — caller-scoped identity.** The configuration closure
  yields to the resolved player across the player surfaces,
  with the fallback of ruling 7. Tests: the fallback path answers
  as today, an unknown cookie meets the constant 401, and two
  players see their own submitted flags, histories, and streaks.
- **B4 — the operator plane.** The bearer check on the lifecycle
  POSTs and the dev surfaces, and the refusal to start with
  players stored and no token. Tests: the refusal bytes, the
  accepted read, and the start-time refusal.
- **B5 — the parameterization and the fit.** `digamma`,
  `trigamma`, the restricted maximum likelihood fit, the variation
  report, and the goodness-of-fit check, each pure. Tests: the two
  functions against known values, a recovered population on
  simulated data, the zero estimate kept, and the baseline held at
  its nominal level with the numbers of §6 as the fixture.
- **B6 — ranks and evidence.** The posterior expected rank with
  intervals, the eligibility floor, the e-value, the
  discovery-rate use, and the stopping monitor. Tests: a known
  sequence recovered, the low-trial player at the middle, the
  e-value
  bounded in expectation at the baseline, and the monitor firing
  on a simulated stopping pattern.
- **B7 — the rollups and the boards.** The pair for each player,
  the daily board, the skill board, the assemble command, and the
  cache keys. Tests: the additive path agrees with a full
  assembly,
  a configuration change forks the cache, and the rescore
  invariant holds.
- **B8 — the endpoints.** The four of §8, with the R3 walk grown,
  the R4 two-world property, and the store snapshot unmoved.
- **B9 — the player surfaces.** The invite gate, the leaderboard
  screen with the chart, display names, and the reveal card.
- **B10 — integrity.** The open-day non-disclosure test, and the
  answer-length test §22 asks for and no test performs: the bytes
  of the refused and pre-reveal answers do not follow the target.

## 12. Testing

Each new endpoint joins the three standing disciplines: the R3
walk (no target, no secret, and no score bytes before the reveal,
with refusals equal across statuses), the R4 two-world property
(answers are a function of revealed days alone), and the store
snapshot (the store is byte-equal around each read).

The statistical work carries its own gate: **the baseline
calibration fixture**. Simulated play with no skill anywhere must
keep the variation test at its nominal level. The table in §6 is
the acceptance criterion, and the fixture is permanent, in the
manner of the byte-equality gate on the batched matcher.

The suites stay green: the Python suite, the web unit and
component tests, and the Playwright flows offline.

## 13. Out of scope, with reasons

- **Layer 7, the deferred rerank (Phase 6).** Not built, and its
  precondition passes, thus it is unblocked and cheap to start —
  but it is a quality improvement, and this phase is about who can
  play and what the ranking means. It wants its own spec.
- **§20 frontloading.** Blocked upstream: it wants a tag artifact
  that pool preparation does not write, which means a preparation
  run and a new configuration hash. It belongs with the production
  pool. One effect to hold in mind: §20 asks for a
  leaderboard for each frontload level, and the population fit is
  then fitted for each level, because the score distributions
  are different.
- **Shadow scoring (§21).** It belongs with the changeover to the
  production pool, where a component is replaced.
- **Open registration, password recovery, and mail.** Ruling 1
  keeps the record layout prepared for them.

## 14. Runbook

Build sequence (§11) on branch `feat/multiplayer`, each commit
green (`uv run pytest -q`, the web gates) and Vale-clean on
touched prose. The owner mints the first invite for the player
name that is stored, which wants no data migration. The review
closes the phase.
