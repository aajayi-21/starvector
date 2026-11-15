# Spec VP1 — the pick after the close: a target that nobody knows during play

**Status:** draft 2026-11-14. The owner chose the protocol on 2026-11-14.
The values in §13 wait for rulings.
**Phase:** protocol hardening before the first public day. It must land
before the player records start again and before the first production
pool, because a day that opened with the first protocol cannot get the
new proof subsequently.
**Architecture sections:** §16 (decoys), §21 (configuration hashes), §22
(protocol integrity).
**Working agreement:** `CLAUDE.md` §1, §2 (I1, I3, I4, I7), §6, §10, §11.
**Input:** spec S1 (`trial-service.md`) R3 to R6, spec BR1 §3 (the day
calendar), spec R1 (`public-database.md`), spec H1 (the send count).

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §13 says so and proposes
a default. Do not implement an open decision without agreement.

---

## 1. Purpose

Today the server picks the target when the day opens, and the target sits
in the store for the full day. The commitment proves that the target did
not change after the open. It does not prove that the pick was random, and
it does not keep the target from the operator or from a person who gets a
copy of the store.

This spec moves the pick to the close. The target comes from a public
randomness beacon at a time after the last send. During play no target
is stored anywhere, so nobody can know it: not the operator, not a
backup, not an attacker. After the reveal, each reader can calculate the
pick again from public data.

The trial becomes precognitive: the player describes a photo that the
beacon selects subsequently. §9 records the change to the architecture.

## 2. What stands today, with evidence

- **The pick.** `open_day` in `service/day.py` makes `pick_seed` with
  `secrets.token_hex(16)` and calls `pick_target(image_ids, day,
  pick_seed)`. The function hashes `day-target:<day>:<seed>` and takes the
  first 64 bits modulo the pool count.
- **The proof.** The open publishes `commitment`, the SHA-256 digest of
  `target_id:secret` (`day_commitment`). The reveal publishes the secret.
  `service/public.py` calculates each commitment again when it builds the
  public database.
- **The seed is not public.** `public-database.md` §7 withholds
  `pick_seed`, because a position in the pool sequence checks nothing
  without the pool. The pool is withheld too, because it names each
  possible target of each day to come.
- **The pool sequence is canonical.** `build_pool_index` in
  `pipeline/context.py` refuses image identifiers that are not ascending
  with no repeats. The operator can change the set of images but not
  their sequence.
- **The send gate reads the status alone.** `POST /api/submission` in
  `service/server.py` refuses when the day status is not `open`. It does
  not read the clock. Between the scheduled close and the close move, a
  send lands.
- **The close is late deliberately.** The rollover timer starts at each hour
  (`deploy/starvector-day.service`), and spec BR1 §3 puts the close at the
  first firing at or after the close instant.
- **The copy says the photo exists.** Five screens say that a photo is
  hidden behind the code: `welcome.tsx`, `how.tsx`, `home.tsx`,
  `today.tsx`, and `reveal.tsx`.

## 3. The protocol

### 3.1 The pool root

The pool root is a commitment to the set of images that a pool version
holds. It makes sure that the operator cannot add or remove an image when
a beacon value is public.

- **Leaves.** For each image in the canonical sequence, at position `i`
  from 0:

  ```
  salt_i = HMAC-SHA256(pool_key, image_id)
  leaf_i = SHA-256("vp1-leaf:" || salt_i || ":" || image_id)
  ```

  `pool_key` is 32 random bytes for each pool version, kept in the data
  root and not in the repository. The salt is necessary: image identifiers
  are names that a person can guess, and without a salt a sibling hash in
  a proof names a different pool image to a reader who tries names.
- **The tree.** A binary Merkle tree on the leaves in sequence. A level
  with an odd count carries its last node up unchanged. An inner node is
  `SHA-256("vp1-node:" || left || right)`.
- **The root.** `pool_root = SHA-256("vp1-root:" || N || ":" || tree_root)`,
  with `N` the pool count in decimal. The count is in the root, so a
  reader can calculate the position without the pool.
- **Publication.** The pool root goes into the repository as
  `configs/pool-roots/<preparation_version_id>.json`, with `N`, the
  preparation version, and the date. That commit must be on the public
  default branch before the first day of that pool version opens. The
  history of the public repository is the timestamp. `GET /api/day` also
  gives the root of the open day.
- A new pool version gets a new key and a new root. The root of the
  previous version stays in the repository.

### 3.2 The beacon and the pulse

- **The beacon.** drand quicknet, run by the League of Entropy. The chain
  hash is
  `52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971`, the
  period is 3 seconds, and the genesis time is 1692803367 (Unix seconds).
  The scheme is `bls-unchained-g1-rfc9380`. Values checked on 2026-11-14
  against `https://api.drand.sh/<chain>/info`.
- **The pulse of a day.** The first pulse with a time at or after the
  scheduled close instant plus a margin:

  ```
  t = closes_at + margin              (Unix seconds)
  round = ceil((t - genesis) / period) + 1
  round_time = genesis + (round - 1) * period
  ```

  The pulse is a pure function of the day label and the configuration, so
  the open publishes it. A player can see on the first minute of the day
  which beacon pulse selects the target.
- **The randomness.** A pulse answer holds `round`, `signature`, and
  `randomness`. For this scheme `randomness` is the SHA-256 digest of the
  signature bytes. A check on 2026-11-14 of pulse 28832419 agreed.
- **The close time of the operator does not move the pulse.** The pulse
  comes from the scheduled instant, not from the moment that the timer
  closes the day. An operator who delays the close does not get a
  different pulse.

### 3.3 The day, step by step

1. **Open.** The record gets `protocol: "vp1"`, `pool_root`,
   `beacon_chain`, and `beacon_round`. No target, no seed, no secret, and
   no commitment. `GET /api/day` gives the trial code, the protocol, the
   pool root, and the beacon pulse.
2. **Play.** `POST /api/submission` refuses when the server clock is at or
   after `closes_at`, with the cause `day-closed`, and also when the status
   is not `open`. The margin of §3.2 holds the time between the last send
   and the pulse time.
3. **Close.** The close moves the day to `closing` as today. It then waits
   until `round_time`, gets the pulse from the beacon, checks it (§3.4),
   and sets:

   ```
   pick_seed = randomness                        (64 hex characters)
   target_id = pick_target(image_ids, day, pick_seed)
   ```

   `pick_target` does not change. The record stores `target_id`,
   `pick_seed`, `beacon_signature`, the position `target_index`, and the
   Merkle proof of that position. Scoring then continues as today.
4. **Reveal.** `GET /api/reveal` gives the target, the pulse, the
   signature, the randomness, `salt` of the target leaf, the position, the
   proof, `N`, and the pool root.

### 3.4 The check of a pulse at the close

- The close gets the pulse from two relays, `https://api.drand.sh` and
  `https://drand.cloudflare.com`, with the path
  `/<chain>/public/<round>`. The two answers must agree byte for byte on
  `signature`.
- `randomness` must equal the SHA-256 digest of `signature`.
- The BLS signature is checked against the chain public key when ruling D3
  adds a library. Until then, the agreement of two relays and the digest
  check are the check at the close, and the reader makes the full check.
- A failure raises. The day stays in `closing`, and the next timer firing
  continues it (§5).

### 3.5 What a reader checks

With the public database or the reveal answer, and no trust in the
operator:

1. The signature of the pulse agrees with the drand quicknet public key
   (with the drand client or a BLS library).
2. `randomness` is the SHA-256 digest of the signature.
3. `index = int(SHA-256("day-target:" || day || ":" || randomness)[0:16],
   16) mod N`.
4. The leaf from `salt` and `target_id`, with the proof at position
   `index`, gives `pool_root`.
5. The commit of `configs/pool-roots/` that holds the root is earlier than
   the open of the day, and `round_time` comes after `closes_at`.

`tools/check_day.py` does checks 2 to 4 for one day or for a database
file, and the public database documentation gives the recipe.

## 4. The margin and the clock

- The send gate reads the server clock. The pulse time reads the drand
  network clock. The margin holds the difference between the two, the
  time of a send in flight, and the time between a send passing the gate
  and its write.
- §13 D2 proposes 60 seconds. With a 3-second period, the pulse time is
  between 60 and 63 seconds after the close instant.
- The server must keep its clock synchronized. The health check of spec
  PL1 gets one more line: the offset of the clock, with a warning above 5
  seconds.

## 5. Failures

- **No local randomness, at no time.** A close that cannot get the pulse
  does not make a seed of its own. A local seed after an outage is a pick
  that the operator controls.
- **The beacon is late or unreachable.** The close waits until
  `round_time` plus a grace of 30 seconds, then tries again with backoff
  for 10 minutes. After that, the close stops with a clear error, and the
  day stays in `closing`. The next timer firing continues it. The pulse
  number does not change, so a late close gets the same value.
- **A long outage.** §13 D4 asks the owner for a rule. The proposal is to
  wait. drand pulses are kept, so the value exists when the network is
  back. A pre-declared second beacon (NIST, `pulse/time/<ms>` at the same
  instant) is the alternative.
- **A day is not discarded after the pick.** A closed day stays in the
  store and in the public database, also when a defect stops its scoring.
  An operator who removes days after seeing their targets selects targets
  by deletion. A missing day in the sequence of the public database is a
  fault that each reader can see.

## 6. The store and the wire

- **The day record.** New fields: `protocol`, `pool_root`, `beacon_chain`,
  `beacon_round`, `beacon_signature`, `target_index`, `target_salt`, and
  `target_proof` (a sequence of hex digests with a side flag). On a `vp1`
  day, `target_id`, `pick_seed`, and the proof fields are empty until the
  close. `secret` and `commitment` are empty on a `vp1` day.
- **Earlier days do not change.** A day without `protocol` reads as
  `commit-v1` and keeps its commitment check (I4: raw records are
  permanent).
- **`GET /api/day`.** Adds `protocol`, `pool_root`, `beacon_chain`, and
  `beacon_round`. On a `vp1` day, `commitment` is `null`.
- **`GET /api/reveal`.** Adds the fields of §3.3 step 4. `check` holds the
  command of the protocol of the day.
- **The pool key.** `pool_key` sits in the data root adjacent to the pool
  index, mode 600, with the backups. Without it, a new close can
  pick, but it cannot make a proof. The close refuses to start when the key
  is missing.

## 7. The public database

- The `days` table gets the columns of §6 and `round_time`. On a `vp1` day
  `pick_seed` is public: it is the beacon value and names nothing.
- The build checks each `vp1` day with the steps of §3.5 2 to 4 and stops
  on a difference, as it does today for the commitment.
- The withheld rows of §7 of spec R1 change. `pick_seed` of a `commit-v1`
  day stays out. `pool_key` and each salt of an image that was not a target
  stay out.
- `querying-results.md` gets the recipe of §3.5.

## 8. The copy

The screens must not say that a photo exists before the close. §13 D6 asks
the owner for the words. The proposal:

| Screen | Today | Proposed |
|---|---|---|
| Welcome | `Each day a photo is hidden behind a short code.` | `Each day a photo is picked at random after the session closes, and nobody knows it while you play.` |
| How it works | `Each day a photo is picked at random and hidden behind a short code.` | `After the session closes, a public random number picks the photo. You describe it before anyone, us included, can know it.` |
| Home | `Today's photo is hidden behind this code` | `Today's photo is picked after the close` |
| Today | `A photo is hidden behind this code.` | `The photo for this code is picked when the session closes.` |
| Reveal | `The hidden photo` | `The photo` |

The reveal screen also replaces the commitment check with a short
explanation of the beacon check and a control that copies the command of
§3.5.

## 9. Changes to the architecture and the working agreement

These texts are canonical, so they change with agreement and in the same
branch as the code.

- **`ARCHITECTURE.md` §22, the commitment paragraph.** Proposed text: the
  target comes from a public randomness beacon at a pulse after the close,
  from a pool fixed by a published root. No target exists during play, so
  there is nothing to commit to or to leak. The reveal publishes the pulse
  and the proof.
- **`ARCHITECTURE.md` §22, shared-target leakage.** This becomes moot: a
  target that is not stored anywhere cannot leak.
- **`ARCHITECTURE.md` §1 and `CLAUDE.md` §1.** "Describing a hidden image"
  becomes "describing an image that the beacon picks after the close."
- **Spec S1 R4 and R6.** R4 becomes "a published pulse and pool root
  before play." R6 keeps the equally likely pick and names the beacon
  value as the seed.

## 10. Integrity

- **I1.** Stronger than today: no target is stored upstream of the
  close. No channel, no open step, and no player surface can read it.
- **I3.** No change. The decoy set is the pool minus the near-duplicate
  group of the target, through `core/ranking.py`.
- **I7 and R3.** No change to the rule. The open-day answers hold no
  target value, because none exists. The tests that compare two worlds
  with different targets compare two worlds with different beacon values
  at the close.
- **The pick stays equally likely.** The beacon value is 256 bits. The
  modulo bias of `pick_target` is below `N / 2^64`, as today.
- **What this does not stop.** An operator who works with a player can
  accept a late send after the pulse and give it an earlier `received_at`.
  The server writes that field. §13 D7 proposes an external timestamp of
  the set of sends before the pulse time. Without it, this one risk makes
  trust in the operator necessary.

## 11. Testing

- **Pure.** The pulse formula at the genesis time, at a pulse boundary,
  and one second after it. The leaf, node, and root digests against fixed
  vectors. A proof for the first, the last, and a middle position, with an
  odd and a count that divides by two. A proof with one changed byte fails.
- **Beacon.** A fake beacon in the tests answers fixed pulses. Two relays
  that disagree stop the close. A digest that does not agree raises. A late pulse
  waits and then continues. An unreachable beacon leaves the day in
  `closing`, and a second close continues it.
- **The gate.** A send one second before `closes_at` lands. A send at
  `closes_at` refuses with `day-closed` while the status is `open`.
- **The lifecycle.** An open stores no target. A close stores the target
  that `pick_target` gives for the fake pulse. The reveal answer holds a
  proof that `tools/check_day.py` accepts. A `commit-v1` day in the same
  store keeps its commitment check.
- **Public database.** A changed proof, a changed salt, or a changed
  randomness stops the build.
- **One live check.** A test marked as network, not in the default
  suite, gets pulse 28832419 from the two relays and checks the digest.
- **Prose.** Vale on this spec, the changed architecture text, and each
  docstring that the build writes.

## 12. Build items

1. **VP1.1.** The rulings of §13 and the text of §9.
2. **VP1.2.** The pure pieces in `core/`: the pulse formula, the Merkle
   tree, the proof check. Unit tests with fixed vectors.
3. **VP1.3.** The pool key and root tool, and the first root file for the
   production pool.
4. **VP1.4.** The beacon client in the shell (a protocol, a drand client,
   a fake), the clock gate, and the lifecycle change.
5. **VP1.5.** The wire, the reveal screen, and the copy.
6. **VP1.6.** The public database columns, the build check, the reader
   recipe, and `tools/check_day.py`.

Each item is one commit, green and Vale-clean on the touched prose.

## 13. Open decisions

- **D1 — the beacon.** Proposed: drand quicknet through the two relays of
  §3.4. drand has some operators that work independently and a threshold
  signature,
  so one party cannot bias or withhold a pulse. NIST runs its beacon alone,
  with a 60-second period.
- **D2 — the margin and the waits.** Proposed: 60 seconds after the close
  instant, a grace of 30 seconds after the pulse time, and 10 minutes of
  backoff before a close stops (§5).
- **D3 — the signature check at the close.** Proposed: a BLS library that
  supports BLS12-381 with the RFC 9380 hash to G1, chosen after a test
  before VP1.4. No such library is in the dependencies today. The
  alternative is the agreement of the two sources alone at the close, with the full
  check left to readers.
- **D4 — a long outage.** Proposed: wait, with a warning, because the pulse
  stays available. The alternative is a pre-declared NIST pulse at the
  same instant after a set number of hours.
- **D5 — the pool key at retirement.** Proposed: publish `pool_key` when a
  pool version retires. Then each reader can calculate each leaf and the
  full root.
- **D6 — the words of §8.**
- **D7 — an external timestamp of the sends.** Proposed for a subsequent
  phase: at the close instant, a digest of the set of sends goes to a
  public timestamp server before the pulse time. It closes the last risk
  of §10.
- **D8 — the first `vp1` day.** Proposed: the first day after the player
  records start again, on the first production pool. Earlier test days
  keep `commit-v1`.

## 14. Out of scope, with causes

- **Pick without replacement.** The pick stays equally likely on the
  full pool on each day, as spec S1 R6 says. A target can come back on a
  subsequent day, and with this protocol that leaks nothing.
- **Hiding the pool count.** `N` is in the root and public from the open.
  It says how many photos the pool holds and nothing about which.
- **The practice screen.** It replays revealed days and does not change.
