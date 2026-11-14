# Spec R1 — the public results database

**Status:** ruled 2026-11-13, built on the branch
`feat/r1-public-database`. The owner gave the rulings of §2 and ruled
each decision of §11 on the same date. §16 records what the build
settled.
**Architecture sections:** §3 (the invariants), §21 (versioning), §22
(integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I6, I7), §3, §7, §10, §11.
**Builds on:** spec BR1 §5 (the results index), spec PL1 §7 (the
export), spec A2 (the username), spec P1a R13 (no public number from a
development pool).

This spec is written for implementation by an AI agent. Where a value
is not in §2 or §11, stop and get a ruling.

---

## 1. Purpose

The owner plans to publish the results of the game as a database that
each person can read with SQL. The analysis of the claim that the game
tests is then open to each reader, and not to the operator alone.

Three parts of that plan are in the repository today:

- The store keeps each raw response forever (I4).
- `service/index.py` makes a SQLite file from the store, and
  `docs/querying-results.md` says how to read it (spec BR1 §5).
- The username is the key of each stored result (spec A2 §11).

That file is not a public file. It holds the raw responses of the day
in play, the text of each account, and the days of the development
pool. It has no table for the targets, and no player was told that a
response becomes public.

This spec is the contract for a second file, the **public database**:
what a player is told, what the file holds and does not hold, and the
procedure that publishes it. It also adds the one datum that cannot
come from the store after the fact: the time a player starts a trial.

Layers 0 to 9 do not move. The submission record of Layer 0 stays
frozen, and no config hash changes.

---

## 2. The rulings of 2026-11-13

| # | Question | Ruling |
|---|---|---|
| 1 | How does the public database name a player? | By the username, the name that the boards show. |
| 2 | What does it hold for each response? | Each part: the scores, the typed text, and the sketch strokes. |
| 3 | Can a player keep a response out? | No. Publication is a condition of the account, and the sign-up screen says it in plain words. |
| 4 | Does the server record when a player starts a trial? | Yes, one time for each player and each day. |
| 5 | Who publishes? | The operator. One command makes a dated snapshot, the operator reads it, and the operator sends it out by hand. |
| 6 | What if a response holds text that must not be public? | The operator withholds it. The scores stay in the public database, the text and the sketch do not, and the row says that it is withheld. |
| 7 | What becomes of the trials of a deleted or revoked account? | They stay in each subsequent snapshot, with an anonymous identifier in the position of the username. |
| 8 | Which license? | CC BY 4.0 for the responses and the scores. Each photograph keeps its own license. |

---

## 3. What a player is told

Ruling 3 makes publication a condition. A condition that a player did
not read is not agreement, thus the notice has three rules.

### 3.1 The notice

The sign-up screen shows the notice above the control that makes the
account, in the same card as the username rules of spec A2 §4.3. The
text (D1):

> **Your results are public.** Your username, score, words and
> sketches are published in an open database after each day closes.
> Do not type anything private.

The notice is short by the owner's ruling, thus it does not say each
fact. The account screen has a section, `Public data`, that says the
remaining facts in plain words:

- The database holds the username, each score, the typed words, and
  each sketch of the player.
- Each person can download it and study it.
- A published snapshot stays published, with the username in it, also
  after the account is gone (§8).
- The address of the published snapshots.

### 3.2 The record of agreement

A new record class: `store/consents/<player>/<version>.json`, written
one time for each version of the notice.

```
player         the store key, agrees with the file name
notice         the version of the notice text, an integer
agreed_at      the time of the agreement
```

- `POST /api/signup` gets one more body field, `agrees_public`. With a
  value that is not `true`, the sign-up is refused with
  `{cause: "notice"}` and no account is made. With `true`, the sign-up
  writes the consent record with the account.
- A change of the notice text is a new version number. A player with
  an earlier version gets the new text one time, and
  `POST /api/account/consent` writes the agreement to it (D2). The
  record of the earlier agreement stays: the new one is a second file
  in the directory of the player, thus the store shows which text was in
  force for each trial.
- The owner resets each player of before the production pool (D9).
  Each account of the production pool is thus made at the sign-up
  screen, with the notice. A player record with no consent record is
  then a fault, and the refusal of §3.3 covers it.

### 3.3 No send before the agreement

A send on a day that can be published (§5) needs the consent record
of the current notice version.
`POST /api/submission` from a player with no such record gets 409
`{cause: "notice"}` before a store write. Each trial in the public
database thus has an agreement that is earlier than its send.

The refusal reads the consent file of the caller and nothing of the
day's target, thus its bytes and its time are not a function of the target
(I7).

---

## 4. The time a trial starts

The store keeps the time of each send (`received_at`) and nothing
before it. A reader thus cannot calculate how long a player worked,
and no subsequent build can get that datum for a day that is closed.

A new record class: `store/days/<day>/starts/<player>.json`, written
one time.

```
day          the day
player       the store key
started_at   the server's time at the first start of this player
```

- The drawing screen (`/today`) sends `POST /api/day/start` when it
  shows an open day to a signed-in player. The body is empty. The
  server writes the record with its own clock, and a second `POST`
  changes nothing. The home screen does not send it.
- The answer is one constant body in each condition: a first start, a
  second start, a day that is not open. It holds no time and no datum
  of the day.
- The record is not a part of the submission. Layer 0 does not read
  it, no score reads it, and a day with no start records is legal.
- It is a raw fact (I4): it is in the store, it is permanent, and no
  other record gives it.

`started_at` is the time the drawing screen opened, not the time of the
first stroke (D3). The home screen shows the day's code before
that, thus `started_at` is not the first time a player sees the code.

---

## 5. Which trials are public

A trial is in the public database when each of these rules holds:

1. **The day is revealed.** No row of an open, closing, or closed day
   is in the file: no response, no score, no target, and no start
   time (I7).
2. **The day is not a day of a development pool.** The preparation
   record that the day names has `dev_only` `false` (spec P1a R13).
   The build stops if it cannot read that record for a day.
3. **The trial row is the pinned one.** A second scoring of a day with
   a different config is the operator's analysis, and it is not in the
   file.

Nothing else removes a trial. A player below the floor of the daily
board (spec A2 §9.5) is in the file, and so is a player below the
30-trial floor of the skill board: the floors are rules of the
boards, and a database with some trials removed is a biased sample.

---

## 6. What the file holds

One SQLite file. Each table has the rows of §5 alone.

| Table | One row is | Columns |
|---|---|---|
| `meta` | a fact of the snapshot | `key`, `value`: the schema version, the snapshot date, the build time, the code version, the license, the first and the last day, the row counts |
| `players` | a player with one trial or more | `player`, `named`, `first_day`, `trial_count` |
| `days` | a revealed day | `day`, `trial_code`, `target_id`, `commitment`, `secret`, `opened_at`, `closed_at`, `revealed_at`, `scoring_config_hash`, `preparation_version_id`, `pool_label`, `pool_image_count`, `player_count` |
| `targets` | the photograph of a revealed day | `target_id`, `source`, `title`, `page` |
| `configs` | a scoring configuration of a day in the file | `scoring_config_hash`, `path`, `config_json`, `weights_json` |
| `submissions` | a response | `day`, `player`, `received_at`, `started_at`, `seconds_from_start`, `impression_count`, `stroke_count`, `group_count`, `relation_count`, `has_pasted_text`, `withheld`, `record_json` |
| `impressions` | one typed row of the impressions | `day`, `player`, `position`, `text` |
| `strokes` | one sketch stroke | `day`, `player`, `position`, `group_id`, `color`, `point_count`, `points_json` |
| `groups` | one labeled group | `day`, `player`, `group_id`, `label` |
| `relations` | one relation | `day`, `player`, `position`, `relation`, `first_group`, `second_group` |
| `trials` | a trial score | `day`, `player`, `p`, `target_rank`, `decoy_count`, `beaten`, `tied`, `scoring_config_hash` |
| `trial_atoms` | one atom of a trial report | `day`, `player`, `position`, `atom_text`, `element`, `weight`, `similarity`, `rarity` |
| `trial_channels` | one channel of a trial | `day`, `player`, `channel`, `standardized`, `p` |

Notes on the columns:

- **`players.player`** is the username, or the anonymous identifier of
  §8 with `named` 0. `first_day` is the first day with a trial in the
  file. The account text, the avatar, and the creation time of the
  account are not in the file.
- **`record_json`** is the raw response as the store holds it: the
  frozen Layer 0 record. The four tables after it hold the same data
  as rows, for a query with no JSON function.
- **`points_json`** is the point sequence of one stroke, each point an
  `x` and a `y` in the range 0 to 1. A stroke has no time.
- **`seconds_from_start`** is `received_at` minus `started_at`, or NULL
  for a response with no start record.
- **`commitment` and `secret`.** The server makes the commitment from
  the target and the secret when the day opens, before a player sends.
  A reader calculates it again from `target_id` and `secret`, and thus
  sees that the target did not move after the play. The build does
  this check for each day and stops on a difference.
- **`targets.page`** is the file page of the photograph at its source,
  where the author and the license are named
  (`service/credits.py`). The file holds no photograph.
- **`config_json`** is the text of the scoring config file, and
  `weights_json` is its fusion weights. The repository is public, and
  `meta` has the code version of the build.

Two views make the usual questions short:

- `trial_facts`: one row for each trial, with the day's `trial_code`
  and `target_id`, the response counts, and `seconds_from_start`.
- `player_summary`: for each player, the trial count, the mean of
  `p`, and the first and the last day.

---

## 7. What the file does not hold

Each row is a fence, and a test pins each one (§13).

| Not in the file | Why |
|---|---|
| a row of a day that is not revealed | I7. A score, a response, or a start time of a day in play is feedback before the window closes. |
| a day of a development pool | Spec P1a R13: a development number is not a public number. |
| the pool: the image identifiers that were not a target, the element vocabulary, the decoys of a trial | A reader with the pool knows each possible target of each subsequent day. `decoy_count` and `target_rank` are in the file, and the identities are not. |
| `pick_seed` of a day | It names a position in the pool sequence. With no pool sequence it checks nothing. |
| a credential: a password digest, a recovery digest, a session, a device code, a name claim | Spec A2 §5.3. The build does not open those directories. |
| the account text and the avatar | The player wrote them for the account page, not for a dataset. |
| the consent record's text | The file is the outcome of the agreement. `meta` names the notice version. |
| a client address, a device label | The store has no address, and the device label is in the session record, which the build does not open. |
| the text and the sketch of a withheld response | §9. |
| a trial row that is not pinned | §5. |

---

## 8. A player with no name

Ruling 7: the trials of a deleted or revoked account stay in each
subsequent snapshot, with no username.

- Such a player has an identifier record,
  `store/public/identifiers/<player>.json`, written one time: the
  player, the time, and the identifier, which is `anon-` and 16 random
  hexadecimal characters (D4). The identifier comes from no datum of
  the player, thus no reader can go from it to the username. It is in
  the store and in each backup, thus one player has one identifier in
  each subsequent snapshot.
- `revoke` writes the record, and so does the account deletion when it
  is built. `python -m service.public identifiers` writes the record
  of each such player that has none.
- The build writes nothing to the store. It stops on such a player
  with a trial in the file and no identifier record, and it names the
  command.
- A player that the operator puts back shows by the username again.
  The identifier record stays, and a second revoke uses it.
- `players.named` is 0 for that player. Each other table has the same
  identifier in `player`.
- The responses stay as the player typed them. A response that names
  its own author is a condition for the withhold table of §9.

An earlier snapshot has the username, and nobody can get it back.
The `Public data` section of the account screen says so (§3.1).

Account deletion is not built (workstream F of `docs/final-push.md`).
A revoked account is the one such condition today.

---

## 9. A withheld response

Ruling 6. A new record class:
`store/public/withheld/<day>/<player>.json`.

```
day           the day
player        the store key
withheld_at   the time of the decision
note          1 to 200 characters: the cause, for the operator
```

- The operator writes it with `python -m service.public withhold <day>
  <player> --note <text>`, and removes it with `release`. The store's
  response does not change (I4).
- In the public database, the `submissions` row of a withheld response
  has `withheld` 1 and NULL in `record_json`. It has no row in
  `impressions`, `strokes`, `groups`, or `relations`, and its
  `trial_atoms` rows have NULL in `atom_text`. The counts, the times,
  and each score stay.
- `meta` has the count of withheld responses. The note is not in the
  file.

A withheld response in an earlier snapshot stays public there. The
operator thus reads a snapshot before it goes out (§10).

---

## 10. The procedure that publishes

Ruling 5: the operator publishes, by hand.

```
python -m service.public build --service-config <path> --out <dir>
python -m service.public check <dir>
```

`build` writes one directory:

| File | What it is |
|---|---|
| `starvector-public-<date>.sqlite` | the public database of §6 |
| `README.md` | what each table and column means, the rules of §5 and §7 in plain words, the license, how to cite, and the I6 rule of `docs/querying-results.md` |
| `LICENSE.txt` | CC BY 4.0 for the responses and the scores, and a line that each photograph has its own license at `targets.page` |
| `SHA256SUMS` | the digest of each file |
| `release.json` | the snapshot date, the schema version, the code version, the row counts, the first and the last day, the count of withheld responses |

`check` opens a built directory and proves each fence of §7 again
from the file alone. It prints the row counts and the days of the
withheld responses for the operator to read.

- **A snapshot is cumulative.** It holds each public trial from the
  first day to its date. A reader wants one file, not a chain of
  files.
- **The build reads the store.** It does not read the private index,
  thus a stale index cannot put a row of an earlier build in a
  public file.
- **The build writes nothing to the store** and nothing to the data
  root. A snapshot is a cache: the same store and the same key give
  the same rows (I4).
- **Where the snapshot goes** is the operator's decision, out of this
  spec (§15).

---

## 11. The decisions, ruled 2026-11-13

The owner ruled each row on 2026-11-13. D1, D4, D8, and D9 are not the
values that the draft proposed.

| # | Decision | Ruling | Notes |
|---|---|---|---|
| D1 | The notice text | The short text of §3.1 | The draft proposed a longer text. The `Public data` section of the account screen holds the facts that the short text does not say. A check of the text by a lawyer is out of this spec (§15). |
| D2 | A new notice version and an earlier agreement | The app shows the new text one time, and a send needs the new agreement | |
| D3 | What `started_at` measures | The first time the drawing screen shows the open day, by the server's clock | The first stroke needs a time from the client. |
| D4 | The anonymous identifier | A random identifier in a store record (§8) | The draft proposed a digest with a secret key. A record in the store has no key to keep, and it does not change. |
| D5 | Times in the file | The full times as the store has them, in UTC | |
| D6 | More file types | SQLite alone | DuckDB reads the SQLite file with no change. |
| D7 | The schema version | 1, in `meta` and not in the file name | The snapshot date is in the file name. A change of a table or a column is a new schema version, and `README.md` records each one. |
| D8 | The first snapshot | No rule. The operator decides the date of each snapshot | The draft proposed a wait of 30 revealed days. A first file of a small number of days invites a strong claim from weak data, and the `README.md` of each snapshot says how many days it holds. |
| D9 | The players of before | The owner resets each of them before the production pool | The draft proposed a notice for such a player. Each account of the production pool comes from the sign-up screen. The procedure for that is not in this spec. |

---

## 12. Integrity

- **I1, I2, I3, I5.** No scoring code moves.
- **I4.** The consent record, the start record, and the withhold
  record are raw facts in the store. The public database is a cache
  of the store.
- **I6.** No module of `core/`, `pipeline/`, `pool/`, `providers/`, or
  `validation/` imports the new module, and the import test of spec
  BR1 §5.2 covers it. The `README.md` of each snapshot says why a
  reader must not fit scoring weights on this data.
- **I7.** §5 rule 1, §3.3, and the constant answer of §4.
- **R13.** §5 rule 2.
- **The pool stays closed.** §7 row 3.
- **No quiet fallback.** The build stops on a day with no readable
  preparation record, on a commitment that does not agree, on a
  response that Layer 0 does not read, and on a missing identifier
  record of §8. It does not write a file with rows left out.

---

## 13. Testing

- **The fences.** One world has a revealed production day, a revealed
  development day, an open day with responses, a withheld response, a
  revoked player, an account text, a credential, and a second scoring.
  The test builds the snapshot and reads it: each row of §7 is not
  there, as rows and as bytes of the file.
- **The contents.** Each row of §6 agrees with its store record. The
  row tables agree with `record_json`. `seconds_from_start` agrees
  with the two times.
- **The commitment.** The check of each day agrees, and a changed
  target stops the build.
- **The same store, the same file.** Two builds give equal rows. The
  build time is in `meta` and out of the compare.
- **The anonymous identifier.** A revoke writes the record. Two builds
  show one identifier, and no table holds the username of that player.
  A revoked player with no record stops the build. A player that is
  put back shows by the username.
- **The notice.** A sign-up with no `agrees_public` makes no account.
  A send with no consent record of the current version gets the
  constant 409 and writes nothing. The 409 is byte-equal across four
  targets. A new version asks one time, and the earlier record stays.
- **The start.** A first `POST` writes the record, a second one
  changes nothing, and each answer is byte-equal. A day with no start
  record builds.
- **`check`** finds each planted fault: a row of an open day, a
  development day, a withheld text, a credential string.
- **The examples.** Each SQL example of the snapshot's `README.md` runs
  against a built file.
- **The invariant tests** of `CLAUDE.md` §9 stay green with no edit.

---

## 14. Build items

Each lands on a branch, green offline, with Vale at zero errors on
the changed prose.

- **B1 — the consent record and the notice.** The store record, the
  `agrees_public` field of sign-up, `POST /api/account/consent`, the
  send refusal of §3.3, and the screens: the notice on the sign-up
  card, the one-time notice of a new version, and `Public data` on
  the account screen.
- **B2 — the start record.** The store record, `POST /api/day/start`,
  and the `POST` from the drawing screen.
- **B3 — the withhold record** and its two commands.
- **B4 — `service/public.py`.** The build of §6 from the store, the
  rules of §5, the fences of §7, the identifier record of §8 with its
  command and the write at `revoke`, and the files of §10.
- **B5 — `check`.**
- **B6 — the documents.** The `README.md` template of a snapshot, a
  dated note in `docs/querying-results.md` and in spec BR1 §5, and
  the deployment document: the commands of §8, §9, and §10.

---

## 15. Out of scope, with reasons

- **Where a snapshot is published,** and a permanent identifier for
  it. The operator's decision, after the first build.
- **A check of the notice by a lawyer,** the privacy policy, and the
  terms. Workstream F of `docs/final-push.md`.
- **Account deletion.** Workstream F. §8 fixes what a snapshot does
  with such an account.
- **Practice.** The practice screen says that nothing is saved, and
  nothing is.
- **Drafts.** The store keeps the send alone. A record of each draft
  is a different decision of the owner.
- **A public query server.** A file that each reader downloads has no
  server to attack and no cost for each query.
- **The photographs.** The file points at each source page. A copy of
  each photograph in a snapshot is a license question for each one.

---

## 16. What the build settled

The build settled these points that the text above did not cover.
Each is a record, and a change to one of them is a new ruling.

1. **The version number of the notice.** `service/notice.py` has it,
   and the text is in `web/src/signin/notice.ts` with the same number.
   A test reads the two and stops if they are not equal.
   `GET /api/signup` answers `notice_version`, and the screen does not
   make an account when its own number is a different one.
2. **`GET /api/me` gets `notice`:** `version`, `agreed`, and
   `required`. `required` is `true` on a server with a production
   pool. With `required` and no agreement, the app shows the notice
   and `I agree` in the position of each screen.
3. **The agreement names its version.** The body of
   `POST /api/account/consent` holds the version that the screen
   showed. A different number gets 409 `{cause: "notice-version"}`.
4. **Sign-up wants the agreement on each server,** also on a server
   with a development pool. The send refusal of §3.3 is for a
   production pool alone, and it comes before each read of the day.
5. **A start after the send writes nothing.** A second device that
   opens the drawing screen after the send thus does not give a start
   time that is after the send.
6. **`submissions` has one more column, `pasted_text`.** It is NULL for
   a response with no pasted text and for a withheld one.
7. **`players` holds each player with a response in the file.**
   `trial_count` counts the trial rows, which can be 0 for a response
   that has no trial row.
8. **A player with no player record** is a player with no username in
   the file, in the manner of a revoked one. The `identifiers` command
   writes the record of each such player.
9. **A target needs its source page.** The build stops when the
   release manifest of the pool is not below the data root. The
   manifest thus goes to the box with the pool.
10. **`build` does `check`.** The build command proves the fences of
    the directory that it wrote, prints what the operator reads, and
    answers a fault as an error.
11. **`check` reads the files alone.** It proves the digests, the
    schema, each commitment, each row key, the withheld rows, the
    anonymous names, and that no credential text is in the bytes. A
    development day shows by a `pool_label` that starts with `dev-`.
    The compare against the store is the build's own work and the
    tests of §13.
12. **The address of the snapshots** is one optional field of the
    server config, `public_data_url`. `GET /api/about` answers it, and
    the account screen shows it.
13. **`configs.config_json` is the text of the config file at the build
    time.** The build does not calculate the config hash again: an
    earlier config file does not change, by the working agreement.
