# Spec IM1 — the instant trial, the daily challenge, and guest play

**Status:** draft of 2026-11-23. The owner ruled the eight questions of
§2 and the decisions of §22 on that date. D3 and D4 of §22 wait for the
measurement of build item IM1.2. The build is on a new branch,
`feat/instant-mode`.
**Phase:** the growth phase after the production cutover.
**Architecture sections:** §16 (ranking), §17 (aggregation), §18
(latency), §21 (versioning), §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I1, I3, I4, I6, I7), §9, §10, §11.
**Input:** spec VP1 (the pick after the close), spec S1 (the store),
spec R1 (the public database), spec A2 (sign-up), spec PW1 (the proof of
work), spec SS1 (send, then see), spec SC1 (store compatibility), spec
MD1 (deletion), spec AG1 (Layer 9), spec CR1 (close resilience), spec
PL1 (limits), and spec A1 §6 (the practice intake).

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §22 says so and
records the ruling. Do not implement an open decision without
agreement.

---

## 1. Purpose

A new visitor gets no result on the first visit. The daily trial shows
its target after 00:00 UTC, and the site makes no trial without an
account. This spec makes two modes and one new type of player.

1. **The instant trial.** A player sends a sketch and words. A public
   random number, which is not there at the time of the send, picks the
   target some seconds after it. The player then sees the target and the
   trial score. Each player can do it, with no account.
2. **The daily challenge.** The daily trial of today, with its boards.
   It stays the competitive mode and it needs an account.
3. **Guest play.** A visitor with no account plays instant trials. A
   cookie of the browser is the identity of that visitor.

The spec also gives each instant trial a public page, because the
defense against a selected result needs it.

## 2. The rulings of 2026-11-23

| # | Question | Ruling |
|---|---|---|
| 1 | Does the store keep an instant trial, and is it public? | Yes to the two. The store keeps it as it keeps a daily send, and the public database holds it. |
| 2 | How many targets does one pulse pick? | One for each trial. The digest of the send is in the pick, thus two sends of one pulse get different targets. |
| 3 | What becomes of the practice screen? | The instant trial replaces it. The practice screen and its two server paths go. |
| 4 | Can a guest play the daily challenge? | No. The daily challenge needs an account. |
| 5 | How many instant trials does a player get? | 5 on each UTC date for a guest, and 20 for an account. |
| 6 | When does a guest agree to the notice? | Before the first instant trial. The store keeps the agreement. |
| 7 | What becomes of the trials of a guest who makes an account? | They become trials of the account. |
| 8 | Which share pieces are in this spec? | The public page of one trial. The video of a trial is a subsequent spec. |

## 3. What stands today, with evidence

- **The pick code is there.** `service/pulse.py` holds the drand quicknet
  chain, with a period of 3 seconds, and the pure functions
  `pulse_number` and `pulse_time`. `service/beacon.py` gets a pulse from
  two relays, and `checked_pulse` compares the two answers.
  `service/pick_rule.py` holds `pick_index` and the check of a day.
  `service/pool_root.py` makes the proof of a pool position.
- **The practice path scores with no wait and stores nothing.**
  `POST /api/practice/score` scores a draft against the target of a
  revealed day (`practice_score` in `service/scoring.py`). The target of
  a revealed day is public, thus a high practice score is not evidence.
- **Each player path needs an account session.** `_caller` in
  `service/server.py` reads the `sv_session` cookie and gives the
  constant 401 to each other caller.
- **A send needs the agreement.** `POST /api/submission` refuses a
  player with no consent record of the current notice (spec R1 §3.3).
- **A photo is given for a revealed day alone.** `/image/<image_id>`
  refuses each image that is not the target of a revealed day.
- **The limits are windows in memory.** `service/limits.py` holds the
  `WindowLimiter` and the caps of practice and sign-up.
- **The proof of work makes accounts.** `service/proofs.py` and
  `GET /api/signup/challenge` (spec PW1).
- **The store rule.** New data goes in a new directory or in an optional
  field, and a stored play record does not change (spec SC1 §3).

## 4. The two modes

| | The instant trial | The daily challenge |
|---|---|---|
| Who plays | a guest or an account | an account |
| How many | 5 or 20 on each UTC date (ruling 5) | one send on each day |
| The pulse of the pick | the first pulse after the send plus a margin (§5.3) | the first pulse after the scheduled close plus a margin (spec VP1) |
| The result comes | some seconds after the send | at the reveal of the day |
| Boards | none | the daily board and the skill board |
| Statistics | the instant record of §9, of one owner alone | Layer 9 (spec AG1) |
| The store | `store/instant/` | `store/days/` |

Three rules hold the two apart.

- **One pool and one scoring configuration.** An instant trial reads the
  pool and the pinned scoring configuration of the server. The two modes
  thus give trial scores on one scale.
- **No shared statistic.** No rollup, no board, no skill number, no
  streak, and no day-level test reads an instant trial. The instant
  record reads no daily trial.
- **No shared answer.** No instant path reads a day record. No daily
  path reads an instant record. `/image/<image_id>` is the one path that
  reads the two (§12.4).

The **owner** of an instant trial is the account or the guest that made
it. The word is used with this sense in this spec.

## 5. The instant trial

### 5.1 The steps

1. **Start.** `POST /api/instant/start` makes the trial. The server
   mints `trial_id` (32 random hex characters) and `trial_code` (with
   `make_trial_code` of `service/day.py`), and writes the start record.
   The player sees the code and sketches.
2. **Send.** `POST /api/instant/<date>/<trial_id>/send` has the same
   record as `POST /api/submission`. The server checks it, encodes it
   (§5.4), writes the send record with its time, and names the pulse of
   the pick. The answer is a receipt (§12.3).
3. **The pulse.** The server waits for the pulse, gets it from the two
   relays, and checks it as spec VP1 §3.4 says.
4. **The result.** The server calculates the position, the target, and
   the proof. It scores the send against that target and writes the
   result record. `GET /api/instant/<date>/<trial_id>` then gives the
   result (§5.5).

One trial has one send. The send record is a file that is written one
time, thus a second send is refused and no code path edits a send.

### 5.2 The pick rule

```
send_digest = SHA-256 of the canonical JSON of the stored wire record
commitment  = SHA-256("instant-nonce:" || trial_id || ":" || nonce)
index       = int(SHA-256("instant-target:" || trial_id || ":" ||
                  send_digest || ":" || nonce || ":" || randomness)[0:16],
                  16) mod N
target_id   = the image at position index of the pool sequence
```

`randomness` is the randomness of the pulse, and `N` is the pool count
of the committed pool root. `nonce` is 32 random bytes that the server
mints at the send, as 64 hex characters. The receipt holds `commitment`,
and the result holds `nonce`.

| The input | What it does |
|---|---|
| `randomness` | Nobody has it before the pulse time, thus nobody knows the target at the send. |
| `nonce` | A player who gets a pulse before the send, through a clock fault, cannot calculate the position. The device of the player has the commitment before the pulse, thus the server cannot change the nonce after it. |
| `send_digest` | A stored send that changes gives a different target. The send and its target are thus one fact. |
| `trial_id` | Each trial has its own target (ruling 2). |

- The pure functions `instant_index`, `instant_commitment`, and
  `instant_faults` go in `service/pick_rule.py`, adjacent to the
  functions of a day. The modulo bias is below `N / 2**64`, as it is for
  `pick_index`.
- **The pick reads the full pool each time.** A pick that removes the
  targets that an owner saw is refused. With such a pick, an owner knows
  that the target is one of the images not seen, and a send that scores
  the seen images low gets an expected trial score above 0.5. Spec VP1
  §14 gives the same rule for the days.
- A target can thus come to one owner a second time. That is correct,
  and §18 gives the numbers.

### 5.3 The margin and the clock

- **The pulse of a send.** With `received_at` the server time of the
  write of the send record, in Unix seconds:

  ```
  beacon_round = pulse_number(ceil(received_at) + margin, chain)
  ```

  The margin is 3 seconds (§22 D1). The pulse comes from the stored time and
  the margin alone.
- **The clock guard.** Each read of a pulse compares the server clock
  with the `Date` header of one of the relays (`clock_offset` in
  `service/beacon.py`). While the last measured offset is above the
  bound of §22 D2, each send is refused with 503 `{"cause":"clock"}`
  and no store write. The server also measures at its start.
- **What the margin is for.** The nonce stops a player who knows a
  pulse. The margin and the guard make the public times correct: the
  pulse time comes after the send time for each stored trial.

### 5.4 The work before the pulse

Spec CR1 puts the blind work of a day before its pick. The instant
trial follows that rule.

- The send path encodes the send before it writes the send record. A
  provider that refuses gives 503 `{"cause":"encoder"}`, and nothing is
  stored. The player sends again.
- The encoded vectors go to the provider cache, which has the provider
  configuration hash in its key (I4). The result step reads them there.
- After the write of the send record, the one network step is the read
  of the pulse. No trial thus stops for a cause that follows its target.
- The encode is the one step that costs money, thus the limits of §6
  come before it.

### 5.5 The result

The owner gets, from `GET /api/instant/<date>/<trial_id>`:

- Before the result: `{"status":"pending"}` with `beacon_round` and
  `pulse_time`. The body is the same for each trial of one pulse.
- After the result: the answer of `practice_score` today (the target,
  the five trial numbers, the head of the ranking with no image names,
  and the report), and the pick facts: the pulse, its signature, its
  randomness, the nonce, the position, the salt of the target leaf, the
  proof, `N`, and the pool root.

Rules of the result:

- **Layer 8 alone reads the target.** The result step validates,
  encodes from the cache, standardizes, fuses, and then gives the target
  to `rank` with `decoy_set`, as the close of a day does.
- **No hit mark.** The answer holds the trial score and the counts. It
  holds no boolean and no cutoff (I2, `CLAUDE.md` §10).
- **The trial row.** The result record holds the trial row of spec S1
  with the scoring configuration hash. A second scoring configuration
  writes an adjacent row (spec SC1 rule 4).
- **Who does the work.** One loop of the server process settles each
  send with a pulse time that is not in the future. It does not wait for
  a `GET` of the owner, thus the trial of a closed tab gets its result
  too. At its start the server reads the store and continues each send
  with no result.

### 5.6 Failures

| The condition | What the server does |
|---|---|
| The relays do not have the pulse | The trial stays pending. The loop tries again with the backoff of `fetch_pulse`. |
| The two relays do not agree | The trial stays pending, and the operator journal gets a line. |
| The beacon is down for a long time | Each send is refused with 503 `{"cause":"beacon"}` while the count of pending sends is above the bound of §22 D3. Stored sends wait. |
| The pool key is missing | The server refuses to start with instant mode on, as the close of a day does. |
| The encoder is down at the result step, with an empty cache | The trial stays pending and the loop tries again. No default score is written. |

The server does not use local randomness in each of these conditions
(spec VP1).

## 6. The limits

| The limit | The value | The source |
|---|---|---|
| Sends of a guest on one UTC date | 5 | ruling 5 |
| Sends of an account on one UTC date | 20 | ruling 5 |
| Sends of all owners on one UTC date | open | §22 D4 |
| New guests of one client in 24 hours | 10 | §22 D5 |
| New guests of all clients in 24 hours | 1,000 | §22 D5 |
| Starts with no send, for one owner | 1 | §12.2 |

- **The date** of a send is the UTC date of `received_at`.
- **The count comes from the store.** The server counts the stored sends
  of the date, thus a start of the server does not give a new allowance.
  A send with no result is in the count.
- **A claimed guest.** The count of an account also holds the sends of
  the guest that the account claimed (§7.4).
- **The refusals.** An owner at the cap gets 429
  `{"cause":"instant-limit"}`. The cap of all owners gives 503
  `{"cause":"instant-full"}`. The two come before the encode.
- **The cap of all owners is the money cap.** One send is one encode.
  The cost of one day is thus below the cap times the cost of one send.
  The cap counts sends, thus no provider datum goes to the server code
  (`CLAUDE.md` §6).
- One client can thus cause no more than 50 guest sends on one date:
  10 guests with 5 sends each.

The constants go in `service/limits.py`.

## 7. Guest play

### 7.1 The guest record and the cookie

- **The identifier.** `guest-` and 16 random hex characters. It has 22
  characters, and a username has no more than 20, thus the two do not
  collide. `guest` joins the reserved names of `service/names.py`.
- **The record.** `store/guests/<guest>/guest.json`, written one time:

  ```
  guest         the identifier, agrees with the directory name
  token_hash    the digest of the cookie secret
  created_at    the server time
  ```

- **The cookie.** Its name is `sv_guest`, and its value is
  `<guest>.<secret>` with the token shape of `service/auth.py`. It has
  the attributes of the session cookie: `HttpOnly`, `Secure`,
  `SameSite=Lax`, and `Path=/`. Its life is 180 days (§22 D6).
- The server keeps the digest alone and compares it in constant time,
  as it does for a session.
- The identifier is a public label. The secret is not in a public
  answer.

### 7.2 The first visit

`POST /api/guest` makes a guest. Its body has `proof` and
`agrees_public`. The server does these steps in sequence:

1. The `Origin` check and the media-type check of spec A2 §8.
2. A caller with an account session or with a good guest cookie gets
   that identity, and no record is made.
3. The guest caps of §6 (429).
4. The proof, as spec PW1 §3.2 step 3 says (400 `{"cause":"proof"}`).
   One proof makes one guest or one account, and not the two: the
   ledger of spent proofs is shared.
5. `agrees_public` must be `true` (400 `{"cause":"notice"}`).
6. The server writes the guest record and the consent record, and sets
   the cookie.

`GET /api/guest/challenge` gives a challenge as
`GET /api/signup/challenge` does. With guest play off (§12.5), the two
guest paths give one constant 404.

The consent record is `store/guests/<guest>/consents/<version>.json`,
with the fields of spec R1 §3.2. A send of a guest with no consent
record of the current notice version gets 409 `{"cause":"notice"}`.

### 7.3 What a guest can do

- A guest plays instant trials, reads the instant paths of §12.3, and
  gets the photo of a target of its own trials.
- Each account path and each daily path gives a guest the constant 401
  of today: the day, the send, the boards, the history, the sends of
  the day, and the account.
- `GET /api/about`, `/about`, `/releases`, and the public trial page of
  §10 are open with no identity.

### 7.4 The claim

Ruling 7. `POST /api/signup` with a good `sv_guest` cookie does one more
step after the account is made:

- It writes `store/guests/<guest>/claim.json` one time, with `guest`,
  `player`, and `claimed_at`.
- It clears the `sv_guest` cookie. The token of a claimed guest opens
  nothing after that.

Rules of the claim:

- **No trial file changes.** The reader of an instant trial gets its
  owner through the claim record (spec SC1 rule 3).
- **One guest has one claim, and one sign-up claims one guest:** the
  guest of its browser.
- **A sign-in does not claim.** §22 D7 gives the rule and its cause.
- **A deleted account.** The claim stays. The trials show the anonymous
  identifier of the account (spec MD1 D3).

### 7.5 Who the caller is

`_instant_caller` in `service/server.py` gives the owner for each instant path:

1. An `sv_session` cookie that names a session gives the account.
2. If there is none, an `sv_guest` cookie with a correct secret and no
   claim gives the guest.
3. Each other caller gets the constant 401.

A box that plays alone, with no player record, keeps the configured
player (spec M1 ruling 7). The owner is a frozen record with two
fields, `kind` and `key`, and scoring code does not read it.

## 8. The daily challenge

**What stays.** One send for each account and each day, the pick after
the close (spec VP1), the notice gate, send then see (spec SS1), the
daily board, the skill board, the streak, and each Layer 9 number (spec
AG1). No code of this spec changes a daily record or a daily score.

**What changes.**

- **The name.** The app says `Daily challenge` where it says `Today`
  (§22 D8).
- **The Play screen** holds the daily challenge and the instant trial.
  Practice goes (§15).
- **A guest** sees the daily challenge as a closed door: one sentence
  that says what it is, and the control `Make an account`. The app
  sends no daily `GET` for a guest.
- **The invitation.** The result of an instant trial of a guest shows
  the same control (§16).
- **The notice** gets version 3 (§14).

The daily challenge is the competitive mode because the boards read it
alone, and because it has one send for each account on each day. A
player cannot do it again for a better result.

## 9. The instant record

Each owner has an instant record. It is the one statistic of the mode.

```
sent        the sends of the owner
settled     the sends with a result
mean_p      the mean of the trial scores of the settled trials
hit_number  the hit number of spec AG1 §4, on those trials alone
```

- The record holds each trial of the owner. No trial is removed, and an
  owner has no control that removes one.
- For an account, the record also holds the trials of the guest that
  the account claimed.
- `core/aggregate.py` gives the numbers. No new statistic is made.
- The record is for one owner. No path gives a sequence of owners by
  their records, thus there is no instant board.
- The server keeps the record of each owner in memory. It builds that
  cache from the store at its start, and each result adds to it (I4).
  The time of the start scan grows with the count of trials. Build
  item IM1.6 measures it.

## 10. The public trial page

Ruling 8. Each settled instant trial has a public page.

- **The address.** `/t/<date>/<trial_id>`, with no session. `<date>` is
  the UTC date of the start, and it is the directory name of the trial.
  The date is a public fact and says nothing of a target.
- **The path.** `GET /api/trial/<date>/<trial_id>`. One constant 404
  answers an identifier with no trial, a trial with no result, and a
  trial of a pool with the `dev_only` flag.
- **What it gives.**

  ```
  owner          the username, the anonymous identifier, or the guest
  kind           account or guest
  started_at     the time of the start
  received_at    the time of the send
  state          sketch, words-only, or withheld
  strokes        the sketch of spec SS1 §5
  words          the count of the typed rows, and no text
  target_id      the target
  trial          the five trial numbers
  pick           the pick facts of §5.5
  record         the instant record of the owner, and the position of
                 this trial in the sends of the owner
  ```

- **The sketch alone.** The page follows ruling 2 of spec SS1: a second
  person gets the sketch and no words. The words are in the public
  database.
- **The record is live.** The page shows the record at the time of the
  answer. A reader sees `trial 37 of 50` and the mean of the 50. This is
  the defense against a selected result: the page of one good trial
  shows all the other trials of its owner.
- **The check.** The page shows the command of `tools/check_instant.py`
  for the trial, and the address of the pulse at one of the drand relays.
- **Headers.** `Cache-Control: no-store` and `X-Robots-Tag: noindex`
  (§22 D9).
- **A withheld trial.** The operator withholds the response of an
  instant trial with the command of spec R1 §9. The page then has the
  `state` value `withheld` and no strokes. The score, the target, and
  the pick facts stay.

## 11. The chain of the sends

The time of a send is the word of the server. The chain makes a change
of the stored sequence show.

```
link_n = SHA-256("instant-chain:" || link_(n-1) || ":" || trial_id ||
                 ":" || send_digest || ":" || commitment || ":" ||
                 received_at || ":" || beacon_round)
```

- `link_(-1)` is 64 zero characters. The send record holds
  `chain_position` (from 0), `chain_previous`, and `chain_link`.
- The server writes the sends one at a time, with a lock on the write.
- `GET /api/instant/head` needs no identity. It gives the position, the
  `chain_link` value, and the time of the last send.
- The receipt of a send holds those two values. A player who
  keeps the receipt can show that the trial was in the chain.
- **What it shows.** A send that the operator removes, adds, or changes
  after a head was seen does not agree with that head.
- **What it does not show.** That `received_at` is the correct time. An
  external timestamp of the head does that, and §22 D10 puts it in a
  subsequent phase with spec VP1 D7.

The chain starts with the first instant trial. It cannot be made for
earlier trials, thus it is in the first build.

## 12. The store and the wire

### 12.1 The directories

```
store/instant/<date>/<trial_id>/start.json
store/instant/<date>/<trial_id>/send.json
store/instant/<date>/<trial_id>/secret.json
store/instant/<date>/<trial_id>/result.json
store/guests/<guest>/guest.json
store/guests/<guest>/consents/<version>.json
store/guests/<guest>/claim.json
```

Each file is written one time with `write_once_json`. Each one is a raw
fact (I4) and is in each backup. The `README.md` of the store names the
two new directories.

### 12.2 The records

**The start record.**

```
trial_id      32 hex characters
owner_kind    account or guest
owner         the player or the guest
trial_code    the code that the player sees
started_at    the server time
```

An owner has no more than one start with no send. A second
`POST /api/instant/start` gives the same trial. A start is good on its
own UTC date and on the subsequent date. After that, a send to it gets
409 `{"cause":"instant-expired"}` and the owner starts again.

**The send record.**

```
trial_id, owner_kind, owner
received_at               the server time of this write
record                    the wire record, as the player sent it
send_digest, commitment   §5.2
beacon_chain, beacon_round
preparation_version_id, pool_root, pool_count
scoring_config_path, scoring_config_hash
notice                    the notice version of the agreement
chain_position, chain_previous, chain_link
```

**The secret record.** `trial_id` and `nonce`. No answer reads it before
the result record is there. It stays after the result.

**The result record.**

```
trial_id
beacon_signature, randomness, nonce
target_index, target_id, target_salt, target_proof
settled_at
row                       the trial row of spec S1
```

### 12.3 The paths

| The path | The caller | What it does |
|---|---|---|
| `GET /api/guest/challenge` | each browser | A proof challenge (§7.2). |
| `POST /api/guest` | each browser | Makes a guest (§7.2). |
| `GET /api/instant` | an owner | The type and the label of the owner, the sends that are left today, the open trial, the instant record, and the last trials. |
| `POST /api/instant/start` | an owner | Makes a trial or gives the open one. |
| `POST /api/instant/<date>/<trial_id>/send` | the owner of the trial | Stores the send and gives the receipt. |
| `GET /api/instant/<date>/<trial_id>` | the owner of the trial | Pending, or the result (§5.5). |
| `GET /api/instant/head` | each reader | The head of the chain (§11). |
| `GET /api/trial/<date>/<trial_id>` | each reader | The public page data (§10). |

The send path does these steps in sequence:

1. The owner (401).
2. The agreement to the notice (409 `notice`).
3. The trial: a start of this owner, with no send, that is not expired
   (the constant 404, 409 `instant-sent`, or 409 `instant-expired`).
4. The limits of §6 (429 or 503).
5. The clock guard and the beacon guard (503).
6. The caps, the whitespace check, and Layer 0, with
   `_checked_submission` (400).
7. The encode (503 `encoder`).
8. With the write lock: the time, the pulse, the nonce, the chain fields,
   the secret record, and then the send record.

The receipt:

```
trial_id, received_at, beacon_round, pulse_time
send_digest, commitment
chain_position, chain_link
```

`GET /api/practice` and `POST /api/practice/score` go (§15).
`GET /api/about` gets one field, `instant`, with the value of §12.5.

### 12.4 The photo of a target

`/image/<image_id>` also gives the target of a settled instant trial.
The set of those targets is a cache in memory, built with the instant
records.

Each image of the pool thus becomes public with time. That is accepted,
and §17 gives the argument.

### 12.5 The configuration

The server configuration gets one optional field, `instant`:

| The value | Who plays instant trials |
|---|---|
| `off` (the default) | nobody. Each instant path and each guest path gives the constant 404. |
| `accounts` | accounts alone. The guest paths give the constant 404. |
| `open` | accounts and guests. |

Start-up guards: a value other than `off` needs a beacon configuration
and the pool key. The value `open` also needs `STARVECTOR_ALTCHA_KEY`.
The refusal names what is missing, as the guards of spec A2 §10.2 do.

## 13. The public database

- **New tables.** Each response table and each trial table of spec R1
  §6 gets a twin with the prefix `instant_` and the key `trial_id`. No
  row of an instant trial goes in a daily table. `instant_trials` also
  holds the pick facts and the chain fields. `instant_owners` holds the
  owner, its type, and `named`.
- **Which trials.** A trial with a result, of a pool with `dev_only`
  `false`, with the drand quicknet chain, and its pinned row. A trial of
  a fake chain does not go public (spec VP1 §15).
- **The chain is full.** `instant_chain` holds the chain fields of each
  send, also of a send with no result. Those fields hold no response
  and no target.
- **A guest** is in the file with its identifier and `named` 0. A
  claimed guest is in the file as the account.
- **The check.** The build does `instant_faults` for each trial and
  walks the chain. It stops on a difference.
- **The withhold table** of spec R1 §9 covers an instant trial.
- The schema number goes up by one, and `querying-results.md` gets the
  recipe of the check.

## 14. The notice, version 3

Version 2 says that the sketches are public after each day closes. An
instant trial is public when its result comes, thus the text changes
(§22 D11):

> **Your sketches and results are public.** An instant trial is public
> when its result comes: each person with its address can see your
> sketch, your score and your name. After you send to a daily
> challenge, each player who sent that day can see your sketch. After
> each day closes, each person can see your username, score and
> sketches on your public page, and your words in an open database. Do
> not sketch or type anything private.

- `NOTICE_VERSION` becomes 3 in `service/notice.py` and in
  `web/src/signin/notice.ts`. `SHOWING_VERSION` stays 2.
- A player who agreed to version 2 gets the new text one time. A daily
  send needs the agreement to version 3, and so does an instant send.
- A guest agrees to version 3 at `POST /api/guest`.
- The `Public data` section of the account screen says the new fact.

## 15. Practice goes

Ruling 3.

- `GET /api/practice`, `POST /api/practice/score`, `practice_limiter`
  and its three constants, the practice precompute of the server, and
  `web/src/screens/practice.tsx` go, with their tests.
- `practice_score` in `service/scoring.py` becomes the builder of the
  instant result. Its answer shape does not change.
- The load test of spec PL1 (`tools/load.py`) gets an instant trial
  where it has a practice score.
- Dated notes go in spec A1 §6, spec VP1 §14, spec R1 §15, spec PL1,
  and architecture §18.

## 16. The web app

- **The first screen** (`welcome.tsx`) gets one more control,
  `Try an instant trial`, with the account controls.
- **The guest gate.** One card with the notice text, the proof widget
  of spec PW1 §4, and the control `I agree`. It sends `POST /api/guest`.
- **The instant screen** has five conditions:

  | The condition | What the player sees |
  |---|---|
  | before a trial | The sends that are left today, and `Get a code`. |
  | sketching | The code, the canvas, and the intake cards of `web/src/intake/`. `Send`. |
  | waiting | The receipt, the pulse number, and a count of the seconds to the pulse time. |
  | result | The photo, the trial score, the report, the pick facts, `Share`, and `Again`. |
  | at the limit | One sentence, and the time of the subsequent UTC date. |

- **`Share`** gives the address of the public trial page to the share
  sheet of the browser, with the procedure of `web/src/share/share.ts`.
- **The invitation.** The result of a guest shows `Make an account`,
  with one sentence on the daily challenge. The sign-up then claims the
  guest (§7.4).
- **The Play screen** shows the daily challenge and the instant trial.
  A guest sees the closed door of §8.
- **The trial page** at `/t/<date>/<trial_id>`: the sketch adjacent to
  the photo, the trial score, the owner, the record line, and the check.
- **The mock world** of the web tests gets a guest and an instant trial.

The screens follow the night-sky theme of today. The owner picks the
layout from mock screens before build item IM1.10.

## 17. Integrity

- **I1.** No target is there before the pulse. The send path has no
  target in its scope. The result step gives the target to `rank` and to
  the report of the target, as the close of a day does.
- **I2.** No answer holds a cutoff or a hit mark (§5.5).
- **I3.** The decoy set comes from `decoy_set` for the picked target,
  with the same function as a day.
- **I4.** The seven files of §12.1 are raw facts. The instant records
  in memory, the set of targets, and the encoded vectors are caches.
  A second scoring of a stored send gives the stored trial row byte for
  byte, and the invariant test of `CLAUDE.md` §9 covers instant trials.
- **I5.** An instant send has the intake of a daily send. No scoring
  code reads the owner or the mode.
- **I6.** No module of `core/`, `pipeline/`, `pool/`, `providers/`, or
  `validation/` reads `store/instant/`. The import fence of spec BR1
  covers it, and a test looks for the directory name in those trees.
  Instant trials are live player trials: they do not fit a weight.
- **I7, the daily challenge.** No instant path reads a day record, thus
  no instant answer follows a daily target. The two-world test and the
  length walk of `tests/service/test_protocol_integrity.py` get each new
  path.
- **I7, the instant trial.** Each answer before the result is a
  function of the send time alone. No target is there to follow.
- **Chance is 0.5.** For one fixed send, the rank of an image that is
  picked with equal chance from the pool is equally likely at each
  position. This holds for each send that a player can make, also for a
  player who knows each image of the pool. A player thus gets no
  expected advantage from pool knowledge, from many words, or from a
  generic sketch. Ties and the near-duplicate rule of I3 make it
  approximate, and V2 measures it.
- **The pool becomes public.** Architecture §22 forbids suggestions
  that show the pool composition to a player. Instant results
  show pool images one at a time, thus a player learns the pool with
  time. The chance argument above holds with full pool knowledge,
  because the pick comes after the send. §19 proposes a note in §22.
- **Spec SC1.** Two new directories, no changed record class, and no
  changed stored file. The builder makes a new frozen store adjacent to
  `frozen-store-2026-11`, with instant trials and guests in it.

## 18. The remaining risk

What limits an incorrect claim:

- No strategy changes the expected trial score (§17).
- The public page shows the full record of the owner (§10).
- No owner can remove a trial. A trial of a closed tab gets its result.
- The pick is checked by each reader, and the chain shows a changed
  sequence.

What does not limit it:

- **A selected trial.** A player with 50 trials shares the best one.
  The page says `trial 37 of 50`, and a picture of the result with no
  address says nothing. The mode has no board for that cause.
- **More identities.** A browser with no cookies is a new guest. The
  proof of work and the caps of §6 are the cost. A player can thus make
  guests until one has a good record, and then claim it.
- **The time of a send** is the word of the server until an external
  timestamp is built (§11).
- **Content of a guest.** A guest makes a public page with a sketch on
  it, with no account. The page shows no words, it has the `noindex`
  header, and the operator withholds a response. No player control
  reports a page.
- **Targets that come again.** With a pool of 1,393 images, an owner
  sees about 96 different targets in 100 trials, and about 420 in 500.
  This changes no score. A larger pool is the remedy (spec PP1).
- **The cost.** The cap of all owners (§22 D4) is the one bound on the
  money of a day.

## 19. Changes to the architecture and the working agreement

The owner agreed to each change below on 2026-11-23, and the edits
were made on that date.

- **Architecture §22.** A dated note: the instant trial, its pulse, and
  its pick rule. A second note at the paragraph on suggestions: pool
  images become public through instant results, with the argument of
  §17.
- **Architecture §18.** A dated note at the practice row: the instant
  trial replaces practice mode, and the fast path does its scoring.
- **Architecture, the glossary.** Two terms: `instant trial` and
  `daily challenge`.
- **`CLAUDE.md` §1.** The first sentence says `a daily remote-viewing
  game`. It gets the instant trial in one clause.
- **`CLAUDE.md` §8.** The line of `store/` names the two new
  directories.

## 20. Testing

- **The pick rule.** Known vectors for `instant_index` and
  `instant_commitment`. `instant_faults` finds a changed send, a changed
  nonce, a changed pulse, and a changed proof.
- **The pulse of a send.** The pulse time is at or after the send time
  plus the margin, for send times at each offset in a period.
- **One send.** A second send, a send of a different owner, and a send
  after the two dates are refused, and the store does not change.
- **Nothing before the pulse.** With a fake beacon that holds the pulse,
  each answer is the pending body, and the store has no result record.
- **Two worlds of the daily target.** Each instant path and each guest
  path has the same bytes for two pick seeds of the open day.
- **Two worlds of the instant trials.** Each daily answer (the boards,
  the history, the skill numbers, the rollups, the day-level test) has
  the same bytes with and without instant trials in the store.
- **The limits.** The fifth and the sixth send of a guest, the caps of
  an account with a claimed guest, the cap of all owners, and a count
  that survives a start of the server.
- **The guest.** The proof, the notice, the cookie attributes, a bad
  secret, a claimed guest, and the constant 401 on each daily path.
- **The claim.** The record of the account holds the guest trials, and
  no trial file changes.
- **The result loop.** Relays with no pulse, two relays that do not
  agree, a server start with pending sends, and an encoder that refuses
  with an empty cache.
- **The chain.** The head after each send, and a check that finds a
  removed send and a changed send.
- **The public page.** No text field of a record is in the answer
  (the sentinel test of spec SS1 §13), a withheld trial, a pending
  trial, and a deleted account.
- **The invariants.** A second scoring gives each stored row byte for
  byte. No scoring module names `store/instant/`. The new frozen store
  reads and comes out of each reader unchanged.
- **The public database.** The twin tables, the full chain, and a build
  that stops on a fault.
- **The web app.** The guest gate, the five conditions of the instant
  screen, the closed door, the trial page, and one Playwright flow: a
  guest plays a trial, sees the result, makes an account, and sees the
  trial in the account.
- **The live check.** `python -m service.beacon <pulse>`, by hand, as
  spec VP1 §15 says. The test suite uses the fake beacon and no
  network.

## 21. Build items

The sequence of the items is the sequence of the build. Each item ends with its tests green,
Vale clean on its prose, and one commit on `feat/instant-mode`.

- **IM1.1 — the documents.** This spec with its rulings, the dated
  notes of §15, and the changes of §19, which are made.
- **IM1.2 — the cost of one send.** Measure the provider cost and the
  time of one encode from the provider cache records. The owner then
  rules §22 D4. No code of the server changes.
- **IM1.3 — the pure rules.** `instant_index`, `instant_commitment`,
  and `instant_faults` in `service/pick_rule.py`. A new module,
  `service/instant.py`, with the pulse of a send, the send digest, the
  chain digest, the allowance arithmetic, and the frozen owner record.
- **IM1.4 — the store.** `service/instant_store.py`: the four trial
  records, the paths of §12.1, the write lock, and the readers. The
  `README.md` text of the store.
- **IM1.5 — the configuration and the guards.** The `instant` field,
  the start-up guards, and the constants of §6 in `service/limits.py`.
- **IM1.6 — the trial paths for accounts.** The start, the send, the
  owner view, the result loop (`service/settle.py`), the instant
  records in memory, the head, and the photo rule. With
  `instant: "accounts"` an account plays a full trial. Measure the start
  scan.
- **IM1.7 — practice goes** (§15), and the load test of spec PL1 runs
  again with instant trials.
- **IM1.8 — guest play.** `service/guests.py`: the guest record, the
  cookie, the challenge, `POST /api/guest`, `_instant_caller`, and the
  claim at sign-up. The value `open` of the configuration.
- **IM1.9 — the notice, version 3** (§14).
- **IM1.10 — the screens.** The mock screens for the owner, then the
  guest gate, the instant screen, the Play screen, and the closed door.
- **IM1.11 — the public trial page.** `GET /api/trial/...`, the screen,
  the withhold command for an instant trial with its command-line twin
  (spec OC1), and `tools/check_instant.py`.
- **IM1.12 — the public database.** The twin tables, the chain table,
  the check, the schema number, and `querying-results.md`.
- **IM1.13 — the frozen store and the invariants.** The new frozen
  store, the guard tests, and the two-world tests of §20.
- **IM1.14 — the deployment notes.** `deploy/README.md`: the `instant`
  field, the sequence `off`, `accounts`, `open`, and what a backup
  holds.

Items IM1.3 to IM1.7 give instant trials to accounts and can go to the
production box with `instant: "accounts"` before guest play is built.

## 22. Decisions, ruled 2026-11-23

The owner went through the decisions one at a time and accepted each
proposal. D3 and D4 have no value: they wait for the measurement of
IM1.2.

- **D1 — the margin of a send.** 3 seconds, one period of the
  chain. The pulse time is then between 3 and 6 seconds after the send.
  The nonce stops a player who knows a pulse, thus the margin can be
  short.
- **D2 — the bound of the clock guard.** The margin of D1. The
  `Date` header has a resolution of one second, thus a smaller bound
  fires on measurement noise.
- **D3 — the bound of pending sends.** Open. It follows the cap of D4.
- **D4 — the cap of all owners on one date.** Open, by the ruling of
  the owner. IM1.2 measures the cost of one send, and the owner then
  gives a budget in USD for one day. The cap is the budget divided by
  that cost. Instant mode does not go to `accounts` or `open` on the
  production box before this ruling.
- **D5 — the caps of new guests.** 10 for one client and
  1,000 for all clients in 24 hours, the values of the sign-up caps of
  spec A2 §9.2, with a counter of their own.
- **D6 — the life of the guest cookie.** 180 days, the value
  of `SESSION_MAX_AGE`. The guest record has no end.
- **D7 — a sign-in does not claim.** The sign-up alone claims
  a guest, and each sign-up claims the one guest of its browser. A
  sign-in to an earlier account keeps the guest apart, and the account
  is the caller while its session is there. The cause: with a claim at
  each sign-in, a player makes guests until one is good and adds that
  one to the account.
- **D8 — the names.** The app says
  `Daily challenge` and `Instant trial`. The path `/today` stays.
- **D9 — the trial page has the `noindex` header.**
  `X-Robots-Tag: noindex`, and no limiter on the path in this phase.
  The answer costs two file reads.
- **D10 — an external timestamp of the chain head.** A
  subsequent phase, built with spec VP1 D7.
- **D11 — the text of notice version 3.** The text of §14. One
  version number covers the two modes, thus each player of today gets
  the notice screen one time.
- **D12 — the hit number in the instant record.** Yes, with the
  function of spec AG1 §4.
- **D13 — a start with no send.** Good on its own UTC date
  and the subsequent one (§12.2), thus no new time value is in the code.

## 23. Out of scope, with causes

- **The video of a trial**, and a preview picture for a shared address.
  Ruling 8: a subsequent spec.
- **A guest in the daily challenge.** Ruling 4.
- **An instant board.** A board gives a prize to the player with the
  most tries (§18).
- **One target for each pulse.** Ruling 2.
- **A pick with no second visit of a target.** §5.2.
- **A larger pool.** Spec PP1 holds the 7,500-image lineage.
- **A reminder of the reveal, a donation control, and a native app.**
  They are growth work with their own specs.
- **A report control for a page.** The operator withholds (§10).
- **The BLS check of a pulse on the server.** It stays as spec VP1 D3
  has it. `tools/check_instant.py` does the checks that
  `tools/check_day.py` does.

## 24. What the build settled

- **IM1.2 is not done, and it needs a network run.** The cache records
  of the embedding slots hold the vector and no cost datum, thus the
  cost of one send is not in the provider cache. The measurement is one
  live encode of sample sends, and the owner does each network command.
  D3 and D4 stay open until then.
- **The cap of all owners is a configuration value.** D4 is the budget
  of the owner, thus it is the field `instant_day_cap` of the server
  configuration and not a constant of `service/limits.py`. A value of
  `instant` other than `off` with no `instant_day_cap` does not parse.
  No instant trial can thus start on a server before the owner sets the
  cap.
- **The margin and the clock bound** are constants of
  `service/instant.py`, adjacent to the functions that read them. The
  two day caps and the guest caps are in `service/limits.py`.
- **Built on 2026-11-23:** IM1.1, IM1.3, IM1.4, and the configuration
  part of IM1.5. The start-up guard is a pure function,
  `instant.start_refusal`. The server reads it when IM1.6 adds the
  paths.
- **Built on 2026-11-23, IM1.6:** `service/instant_book.py` (the
  instant records in memory), `service/settle.py` (the start, the send,
  the result, and the loop), and the five paths of an account in
  `service/server.py`.
- **A read scores nothing.** The result answer of §5.5 has no head of
  the ranking. Each of its values comes from the three stored records
  of the trial, thus a `GET` does no encode and costs no money. The
  trial numbers hold `target_rank`.
- **The caps are also read at the start,** thus a player at a cap gets
  no code for a send that the server then refuses.
- **The loop.** One turn each second settles the sends that are due.
  The start-up path of the server starts it, and a test asks for one
  turn. A clock measurement that does not come is tried again after 30
  seconds, the largest pause of the beacon reads.
- **The last trials** of `GET /api/instant` are 24, the page count of
  spec SS1 D2.
- **Faults go to the process journal** with the name
  `starvector.instant`. A line in the operator journal for two relays
  that do not agree (§5.6) is not built.
- **The beacon guard of §5.6 is not built.** D3 is open. The cap of
  all owners is the bound on the pending sends until then.
- **A pending send holds its configuration.** A server that changes the
  pool or the scoring configuration with a send pending gives that send
  no result, and writes a journal line. Make such a change when no send
  is pending.
- **For subsequent items:** the web types of `GET /api/about` (IM1.10),
  the two-world test of the daily answers, and the frozen store
  (IM1.13).
- **Built on 2026-11-24, IM1.8:** `service/guests.py` (the guest
  record, the cookie, the consent, and the claim), the two guest paths,
  the guest as an owner of an instant trial, and the claim at the
  sign-up.
- **The consent record of a guest** has the field `guest` where the
  record of spec R1 §3.2 has `player`.
- **A new notice version.** A browser with a guest sends
  `POST /api/guest` with `agrees_public`, and the server writes the
  agreement to the current version with no second proof.
  `GET /api/instant` says `needs_agreement` for the caller.
- **The map of the claims is a cache.** The server reads the claim
  records at its start, and a sign-up adds to the map.
- **A start with no send of a claimed guest** is the open trial of the
  account. Its send keeps the guest as the owner in the record, as its
  start does.
- **Built on 2026-11-24, IM1.7, IM1.9, and IM1.10:** practice is gone,
  the notice is at version 3, and the web app has the instant screen,
  the guest gate, the guest shell with the closed door, and the switch
  between the two modes of Play.
- **The layout.** The owner ruled on 2026-11-24 to build in the Studio
  layout with no mock screens first. The instant screen has the canvas
  and the side of the practice screen.
- **The row of days.** The owner ruled on 2026-11-24 that a step back
  from today opens the results of that day. The row stands on the view
  of the daily challenge alone.
- **The listing of the revealed days stays,** with a new address:
  `GET /api/days`. The row of days and the leaderboard read it. The two
  practice paths give 404.
- **`practice_score` is gone.** The result answer comes from the stored
  records, thus no builder of a practice answer is necessary.
- **The load tool** (`tools/load.py`) plays an instant trial where it
  had a practice score: one start and one send for each turn.
- **`Share` is not on the result.** It gives the address of the public
  trial page, which is build item IM1.11.
- **One Vitest failure is from before this branch.** The first test of
  `web/tests/component/home.test.tsx` is red in a full run and green
  alone, on the commit before the web changes also.
