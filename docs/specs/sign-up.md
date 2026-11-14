# Spec A2 — sign-up with a username and a password

**Status:** ruled 2026-11-13, built on the branch `feat/a2-sign-up`.
The owner gave the rulings of §2 and ruled each decision of §12 on the
same date. §18 records what the build settled.
**Architecture sections:** §3 (the invariants), §22 (integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I6, I7), §3, §10, §11.
**Amends, when the build lands:** M1 §4 (the player record and the
invite), A1 §4 (the door), BR1 §4 (the paths and the start-up
guards), and `docs/final-push.md` §4.4 item 3 (sign-up with an email
address). Each gets a dated note that points here.

This spec is written for implementation by an AI agent. Where a value
is not in §2 or §12, stop and get a ruling. Do not put a new number in
the code.

---

## 1. Purpose

A player gets an account today when the operator mints a record and
sends a personal address (spec M1 §4). The plan for the public test
was a sign-up with an email address (`docs/final-push.md` §4.4).

The owner wants no email address and no account of a different
company in the sign-up. A person makes an account with a username and
a password, and nothing else. The server then holds no datum that
names a person.

This spec is the contract for that sign-up, for sign-in, and for
recovery. It keeps the sessions of spec BR1 §4: a password is a new
procedure that opens a session, and nothing more.

Layers 0 to 9 do not move. Identity is upstream of nothing in the
scoring path, and no config hash changes.

---

## 2. The rulings of 2026-11-13

| # | Question | Ruling |
|---|---|---|
| 1 | Who can make an account? | Each person who has the address of the app. No sign-up code. |
| 2 | What becomes of the personal invite address? | It goes. No player gets in through a `/join` address. |
| 3 | Which name do the boards show? | The username. One name signs a player in and shows on each board. |
| 4 | What is the minimum password length? | 12 characters. |
| 5 | How does a player get back in with no password? | A recovery code that works one time. |
| 6 | What if the player has no password and no recovery code? | The operator can give a new recovery code. |

The owner also gave one constraint for the work after this spec. A
backend database connects each result to a username. This spec does
not build it, and §11 says how this contract keeps that door open.

---

## 3. What a player does

### 3.1 Make an account

1. The gate screen shows two controls: `Sign in` and `Make an account`.
2. The player types a username and a password. The screen shows the
   rules of §4 and §5 while the player types.
3. The server makes the account and signs this device in.
4. The screen shows the recovery code one time (§6). The player
   copies it and then clicks `I have my code`. The screen says that
   the code does not show again.

### 3.2 Sign in

The player types the username and the password. A good pair opens a
session on this device. A session lives 180 days (spec BR1 §2), thus
a player types the password about two times in one year on one
device.

### 3.3 Get back in with the recovery code

The gate screen has a third control: `I do not have my password`.
The player types the username, the recovery code, and a new password.
The server then does four things:

- It replaces the password.
- It signs each device of the player out.
- It signs this device in.
- It shows a new recovery code one time. The used code is dead.

### 3.4 On the account screen

- `Change password`: the player types the current password and a new
  one. Each other device signs out.
- `New recovery code`: the player types the current password. The
  earlier code is dead, and the screen shows the new one one time.
- The device table and the sign-out controls of spec BR1 §4.2 stay.

### 3.5 What a device code is

A device code is a piece of spec BR1 §4.2, and it is built. A player
who is signed in on one device clicks `Add a device`. The screen
shows a code of 8 characters that lives 10 minutes and works one
time. The player types the code on a second device, and that device
signs in. The player types no password for it.

A device code is not a recovery code. It lives 10 minutes, and only a
device that is signed in can make one. The recovery code has no end
date, and it is for the player with no signed-in device and no
password.

The player's device code does not change. The console control that
makes a device code for a player goes (§12, D13).

---

## 4. The username

The username is the `player` key of the store (spec M1 §4). It is the
one name of a player: the sign-in name, the board label, and the key
of each stored result.

### 4.1 The rule

- The alphabet is `a` to `z`, `0` to `9`, and the hyphen, which is
  the store rule of today. The screen changes capitals to small
  letters before the `POST`, and the server does the same.
- The length is 3 to 20 characters (D1). A record of today with a
  name that is not in that range stays legal.
- The first character is a letter. The last character is not a
  hyphen. Two hyphens do not sit together.
- A name in the reserved set of D2 is refused.

The alphabet has no capitals and no letters of a second script. The
look-alike names of other scripts thus cannot occur.

### 4.2 One name, one person

Two names that look the same let one player show as a different
player on a board. The server thus compares a folded shape of each
name, and not the name itself:

- Each hyphen is removed.
- `0` becomes `o`, and `1` becomes `l`.

A sign-up is refused when the folded shape of its name is equal to
the folded shape of a name that is claimed. `no-one` and `n0one` are
thus one name.

### 4.3 A name is permanent

- A player cannot change the username. Each stored result has the
  name as its key (§11).
- A claimed name stays claimed. A revoked account and a deleted
  account keep the claim, thus no second person gets the results of
  the first.
- The screen tells the player this before the account is made. It
  also tells the player that the name shows to each other player, and
  that the name of a person is a bad username.

---

## 5. The password

### 5.1 What the server accepts

The rule follows NIST SP 800-63B-4 and the OWASP guidance (§17):
length and a refusal table, with no rule on character classes.

- The length is 12 to 128 code points (ruling 4, and D3 for the
  maximum). The server counts after Unicode normalization to NFKC.
- Each printable character is legal, and the space is one of them.
  The server does not cut a password short.
- The server refuses a password that holds the username.
- The server refuses a password that is in the table of usual
  passwords (D4). The table is a file in the repository. The
  server sends no password, and no digest of one, to a different
  company.
- No rule asks for a capital, a digit, or a symbol. No rule asks for
  a new password after some months.
- The screen lets a password manager fill the fields, and it lets the
  player paste. It has a control that shows the typed password.
- The server has no password hint and no question about the life of
  the player.

### 5.2 How the server keeps it

The server does not keep a password. It keeps one slow digest for
each player.

- **The algorithm** is Argon2id with 19 MiB of memory, 2 iterations,
  and 1 lane, which is a configuration of the OWASP table (D5).
  Each digest has its own random salt of 16 bytes.
- **The stored value** is the standard text shape of Argon2, which
  holds the algorithm, the parameters, the salt, and the digest. A
  change of the parameters thus does not break an earlier digest.
  When a player signs in with a digest of weaker parameters, the
  server writes a new digest from the typed password.
- **The pepper** (D6). Before Argon2id, the server puts the
  password through HMAC-SHA-256 with a key that is not in the store.
  The key is `STARVECTOR_PASSWORD_PEPPER` in the environment file of
  the deployment. A copy of the store or of its backup then holds no
  digest that a person can attack offline.
- **The cost.** One digest is 19 MiB and some tens of milliseconds.
  The server computes it away from the loop thread, with a cap on how
  many it computes at one time: 2 (D7). Sign-in thus cannot stop
  play.

### 5.3 Where a password can go

- A password travels in the body of a `POST` on HTTPS, and in no
  other position. It is not in an address and not in a query string.
- No output line of the server or the edge holds a password, a
  recovery code, or a digest of one.
  A test pins this (§15).
- No answer of the server holds a password or a password digest.
- The results index, the research export, the player export, and the
  operator console hold no credential (§11).

---

## 6. The recovery code

- **Shape.** 24 characters from the device-code alphabet, which has
  no `0`, `O`, `1`, `I`, or `L` (D8). The screen shows six
  groups of four. Capitals, spaces, and hyphens do not count when the
  player types it.
- **Strength.** 31 symbols and 24 positions give about 119 bits. No
  person can find the code by trial. A digest with no slow work
  (SHA-256) is thus sufficient for the store, as it is for a session secret (spec M1
  §4).
- **One time.** The server shows a code when it makes one, and not
  again. A code works one time: the recovery of §3.3 removes it and
  gives a new one.
- **One code of the player.** A player has at most one live code of
  the player's own. A new one replaces the earlier one.

### 6.1 The operator's code (ruling 6 and D9)

The operator makes a recovery code for a username, from the console
or the command line, and gives it to the player by hand. The server
holds no datum that proves who wants the code. A person who is not the player
can thus get one with an untrue story, and the code has three guards.

- **A second slot.** The operator's code does not replace the code of
  the player. It does not change the password and does not end a
  session. A player who did not want it loses nothing.
- **A hold of 24 hours.** The code works from 24 hours after the
  operator made it. Before that time, a recovery with it gets the
  constant 401 of §8.
- **A notice.** While an operator's code is live, each signed-in
  device of the player shows a notice with the time of the code and a
  `Stop this` control. The control removes the code. It asks for no
  password, because a session is sufficient to remove a code.

After the hold, the player uses the code in the procedure of §3.3.
That recovery removes the two codes and gives a new code of the
player.

A player with no signed-in device sees no notice. The hold is then
the one guard, and the credential record keeps the time of each
operator's code for the operator to read.

The operator has no second procedure into an account: the console
device code goes (D13).

---

## 7. What the store holds

### 7.1 The credential record

A new record class: `store/credentials/<player>.json`, with a strict
field set.

```
player               the store key, agrees with the file name
password_digest      the Argon2id text, or null
password_set_at      the time of the last password write, or null
recovery_digest      sha256 hex of the player's live code, or null
recovery_issued_at   the time of that code, or null
operator_digest      sha256 hex of the operator's live code, or null
operator_issued_at   the time of that code, or null
operator_usable_at   operator_issued_at plus 24 hours, or null
updated_at           the time of the last write
```

- **Its own directory.** `store/players/` holds one file class, and
  each reader of it walks the directory (spec A1 §3). The credential
  record is also the one record that no reader but sign-in opens. Its
  own directory makes that a rule of paths.
- **The write.** The record is replaceable, in the manner of the
  account record: a temporary sibling, then `os.replace`.
- **I4.** The record is a raw fact, not a cache. It is in the store
  and in each backup. The pepper is not in the store (§5.2).

### 7.2 The name claim

A new record class: `store/names/<folded>.json`, with the folded
shape of §4.2 as the file name.

```
folded       the folded shape, agrees with the file name
player       the username that holds the claim
claimed_at   the time of the claim
```

The sign-up writes the claim with an exclusive open. Two sign-ups for
one folded shape thus cannot make two accounts: the second open
stops. The lookup reads one file and scans nothing. A claim is not
removed (§4.3).

### 7.3 The player record

The player record keeps its field set (spec M1 §4), with two
changes:

- `token_hash` is the digest of an invite, and the invite goes. A new
  record writes `null` there. An earlier digest stays in its record
  and opens nothing.
- `display_name` is equal to the username in a new record. The boards
  read `player` (ruling 3).

No stored play record moves, and no migration changes a file.

### 7.4 What the server knows about a player

| Datum | Where | Why |
|---|---|---|
| the username | `store/players/`, each result | identity, the board label |
| the password digest and the recovery digest | `store/credentials/` | sign-in and recovery |
| each session: a digest, the start, a device label from the browser name | `store/sessions/` | the device table of the player |
| the description and the avatar, if the player gives them | `store/accounts/` | the account page |
| each submission and each trial row | `store/days/` | play |

The server asks for no email address, no telephone number, no name of
a person, and no account of a different company. The limiter of §9
holds client addresses in memory for its window, and the store does
not get them. The access file of the edge (`access.log`) holds client
addresses, and its lifetime is a decision of workstream F.

---

## 8. The paths

Each body is JSON. Each credential `POST` wants
`Content-Type: application/json` and an `Origin` header that agrees
with the host, thus a page of a different site cannot sign a browser
in. An answer that holds a recovery code has `Cache-Control: no-store`.

| Path | Body | What it does |
|---|---|---|
| `GET /api/signup` | | `{open: true}` when the server makes accounts, and the constant 404 when it does not. The gate screen reads it one time. |
| `POST /api/signup` | `username`, `password` | Makes the account, signs this device in, and answers 201 with the recovery code. *Note, 2026-11-13 (spec R1 §3.2):* the body also needs `agrees_public` `true`, and the answer of `GET /api/signup` has `notice_version`. |
| `POST /api/signin` | `username`, `password` | Opens a session on this device. |
| `POST /api/recover` | `username`, `recovery_code`, `password` | The procedure of §3.3. Answers 200 with the new recovery code. |
| `POST /api/account/password` | `current_password`, `password` | Replaces the password and ends each other session. |
| `POST /api/account/recovery-code` | `current_password` | Makes a new recovery code and answers with it. |
| `POST /api/account/recovery-code/stop` | | Removes the operator's code of this player. The same answer with a code and with none. |
| `POST /api/dev/players/{name}/recovery-code` | | Makes the operator's code of §6.1. Needs the operator bearer. |

`GET /api/me` gets two fields. `operator_code` is `null`, or it holds
`issued_at` and `usable_at`, and the notice of §6.1 reads it. It holds
no code and no digest. `has_password` says if the player has a
password, thus the account screen shows `Set a password` or
`Change password`.

The refusals:

| Condition | Answer |
|---|---|
| a name or a password that the rules of §4 and §5 refuse, at sign-up | 400 with the cause: `name-rule`, `name-reserved`, `password-rule`, `password-usual` |
| a name with a claimed folded shape, at sign-up | 409 `{cause: "name-taken"}` |
| a pair that does not sign in: no account, a bad password, a revoked account | one constant 401, byte-equal in each condition |
| a recovery that does not work: no account, a bad code, a used code, an operator's code in its hold, a revoked account | one constant 401, byte-equal in each condition |
| a bad `current_password` on the account paths | one constant 403 |
| a cap of §9 | 429, before the store is read |

`POST /api/account/password` has one more path. A player who is
signed in and has no password sets the first one with no
`current_password`, and gets a recovery code in the answer. This is
the door for the players of today (§10.3).

---

## 9. Limits and refusals

### 9.1 What each defense is for

| A person tries to | The defense |
|---|---|
| find a password by trial through the server | The caps of §9.2, the constant answers of §8, and the slow digest. |
| use a table of passwords from a different site | The same caps. The 12-character minimum and the table of usual passwords remove the weak ones. |
| read a copy of the store or its backup and attack the digests offline | Argon2id with a salt for each digest, and the pepper, which is not in the copy. |
| learn which usernames have an account | Sign-in and recovery give one answer and use equal time (§9.3). A username shows on the boards by ruling 3, thus the username is not a secret. The password is the one secret. |
| make accounts in bulk | The sign-up caps of §9.2, and the operator's `signup` switch (§10.2). The skill board needs 30 trials (spec M1 §6), and the daily board needs 3 played days (§9.5). |
| show as a different player | The folded shape of §4.2, and the rule that a name is permanent. |
| get a code from the operator for the account of a different player | The hold and the notice of §6.1. |
| use a cookie that a different site sends | `SameSite=Lax`, `HttpOnly`, and `Secure` on the session cookie (spec M1 §4), and the `Origin` check of §8. |

### 9.2 The caps

`service/limits.py` has the window limiter of spec BR1 §4.2. This
spec adds four counters. Each one counts in memory and answers 429
before the store is read.

| Counter | Key | Cap |
|---|---|---|
| sign-in and recovery `POST`s that do not succeed | the client address | 10 in 10 minutes, the cap of spec BR1 |
| the same | the username | 10 in 10 minutes (D10) |
| the same | the process | 200 in 10 minutes, the cap of spec BR1 |
| accounts made | the client address | 10 in 24 hours (D11) |
| accounts made | the process | 1,000 in 24 hours (D11) |

A cap on a username has a cost: a person can type bad passwords for a
name and stop its sign-in for the window. The player who is signed in
does not see it, because a session needs no sign-in. The owner
accepted that cost (D10).

The two sign-up caps have no measurement behind them (D11). Players
behind one shared address share the first one. The counters are in
memory, thus a start of the server sets them to zero.

### 9.3 Equal answers and equal time

- For a username with no account, the server computes one Argon2id
  digest against a fixed value and then answers the constant 401. The
  two conditions thus have equal work.
- The server compares each digest in constant time.
- Sign-up is the one path that tells a caller that a name is claimed.
  That is necessary, and the boards show the names.

### 9.4 I7

No answer of this spec depends on the target of a day. The length and
the time of each answer are functions of the credentials and the
limiter alone.

### 9.5 The floor of the daily board (D12)

Sign-up is open, thus accounts that play one day can fill a daily
board. The public daily board of a day thus shows a player only when
the store holds a submission of that player on 3 or more earlier
days.

- A player below the floor sees the player's own row and its
  position, with a line that says when the row becomes public.
- The floor reads the store alone. It is a rule of the board answer
  (`GET /api/leaderboard`), and it changes no trial score: a trial
  score is a rank against the decoys and not against other players.
- The skill board keeps its 30-trial floor (spec M1 §6). Layer 9 does
  not move.
- The players of today have their history, thus the floor counts
  their earlier days.

---

## 10. What goes, and what the operator keeps

### 10.1 The invite goes (ruling 2)

- `GET /join/{token}` answers the constant 404.
- `service.players` drops `mint` and `rotate`, and the console drops
  the two controls. The `POST` that mints a player goes.
- `revoke` stays. It ends each session, and a revoked account cannot
  sign in and cannot use a recovery code.
- `restore` changes. It makes the account active and gives the
  operator a recovery code with the hold of §6.1, not an invite.
- A new command and a new console control give the operator's code of
  §6.1.
- The console control and the `POST` that make a device code for a
  player go (D13). `POST /api/dev/players/{name}/device-code` answers
  the constant 404.
- The filter that hides invite paths in the server output stays,
  because earlier lines hold them.

### 10.2 The `signup` switch and the start-up guards

The server config gets one optional field, `signup`, with the values
`"open"` and `"closed"`. A config with no field reads as `"closed"`,
thus each config of today keeps its behavior.

- `"open"`: `GET /api/signup` answers `{open: true}`, and the server
  makes accounts. The server starts with no player record. It does
  not start with no operator token. The fallback of spec M1 §4 is
  off: a caller with no session is signed out, and no caller plays as
  the configured player.
- `"closed"`: the sign-up paths answer the constant 404. Sign-in and
  recovery work for each account that the store holds. The operator
  moves the switch to stop new accounts with no code change.

`--single-player` and `--dev` keep the meaning of spec BR1 §4.3. The
door of spec A1 §4 stays for dev servers, and a door record has no
password.

### 10.3 The players of today

- A player with a live session opens the account screen and sets a
  password (§8). The username is the `player` name that the operator
  gave.
- A player with no session asks the operator for a recovery code, and
  uses it after the hold of §6.1.
- The folded shapes of the names of today get their claims from one
  command, `service.players claim-names`. It refuses to continue when
  two names of today have one folded shape, and it prints the pair.
- The boards show `player` from the date of the build. A display name
  of today stays in its record and shows on no board.

---

## 11. The results database, kept in mind

The owner wants a backend database that connects each result to a
username. It is not in this build. Four rules of this spec keep it
simple:

- **One key.** The username is the `player` key of each submission
  and each trial row today, and of the `players` table of the results
  index (spec BR1 §5). A database connects results to players through
  that one column, with no map between two identities.
- **The key does not move.** A username does not change and a claim
  is not removed (§4.3). A result of last year thus names the same
  person as a result of today, and no query gives the results of one
  person to a second person.
- **No credential crosses.** The index builder does not read
  `store/credentials/` or `store/names/`. A test pins this, in the
  manner of the credential fence of spec BR1 §5.2.
- **The store stays the truth.** The store files are the raw record
  (I4), and a database is made from them. Sign-up writes store files
  alone.

One decision waits for that database: what a deleted account leaves
behind. This spec holds the claim of the name and says nothing more.
The deletion ruling is in workstream F.

---

## 12. The decisions, ruled 2026-11-13

The owner ruled each row on 2026-11-13. D11, D12, and D13 are not the
values that the draft proposed.

| # | Decision | Ruling | Notes |
|---|---|---|---|
| D1 | Username length | 3 to 20 characters | The store rule permits 1 to 64. A board row has room for about 20. |
| D2 | Reserved names | A table in the code: the words for the operator and the app (`admin`, `operator`, `moderator`, `staff`, `support`, `system`, `root`, `starvector`), the path words (`api`, `join`, `me`, `dev`), and `null` and `undefined` | The owner adds words. No table of rude words: the operator revokes such an account. |
| D3 | Password maximum | 128 code points | NIST asks for a maximum of 64 or more. A cap is a limit on the work of one digest. |
| D4 | The table of usual passwords | A file in the repository: the entries of 12 characters or more of a public table of breached passwords | Ruled 2026-11-13: `Pwdb_top-1000000.txt` of the SecLists repository, MIT license. §18 has the commit and the count. No online breach check. |
| D5 | The digest | Argon2id, 19 MiB, 2 iterations, 1 lane, through the `argon2-cffi` package | A new dependency, accepted. |
| D6 | The pepper | Yes, HMAC-SHA-256 before Argon2id, the key in the environment file | If the key is gone, each password is dead. Each player then recovers with a code, because the recovery digest has no pepper. The operator keeps a copy of the key away from the box. |
| D7 | Digests at one time | 2 | The droplet has 1 vCPU. A third sign-in waits. |
| D8 | Recovery code length | 24 characters, about 119 bits | |
| D9 | A guard on the operator's code | A hold of 24 hours and a notice with a `Stop this` control (§6.1) | The hold costs the correct owner one day. |
| D10 | The cap on a username | 10 in 10 minutes | §9.2 gives the cost. |
| D11 | The sign-up caps | 10 accounts in 24 hours for a client address, and 1,000 in 24 hours for the process | The draft proposed 3 and 200. No measurement stands behind the values. The load test of spec PL1 measured 877 active players. |
| D12 | The daily board and new accounts | A player shows on the public daily board after 3 played days (§9.5) | The draft proposed no floor. |
| D13 | Device codes from the console | They go | The draft proposed that they stay. With D9, a console device code is a procedure around the hold. The player's own device codes stay. |

---

## 13. Integrity

- **I1, I2, I3, I5.** No scoring code moves.
- **I4.** The credential record and the name claim are raw facts in
  the store. The pepper is a deployment secret and not a store fact.
- **I6.** `service/` gets the new code. The import fence of spec BR1
  §5.2 stays: no module of `core/`, `pipeline/`, `pool/`,
  `providers/`, or `validation/` imports it.
- **I7.** §9.4.
- **No quiet fallback.** A credential record that does not parse
  stops the sign-in of that player with a logged error and the
  constant 401. It does not read as "no password".

---

## 14. Build items

Each lands on a branch, green offline, with Vale at zero errors on
the changed prose.

- **B1 — the pure rules.** Username check, folded shape, reserved
  table, password check with NFKC and the table of usual passwords,
  recovery code make and normalize. Pure functions with unit tests.
- **B2 — the digest module.** Argon2id with the pepper, the check
  of a typed password, the weaker-parameters check, and the fixed value of §9.3. The fake
  for the tests is a digest with no slow work and the same interface,
  thus the suite keeps its speed.
- **B3 — the store.** The credential record and the name claim, with
  the strict readers and the exclusive claim. The player record reads
  `token_hash` `null`.
- **B4 — the paths** of §8, with the limiter counters of §9.2 and the
  `Origin` check.
- **B5 — the config and the guards** of §10.2.
- **B6 — the invite goes** (§10.1), with the operator's command and
  the console control, the hold and the notice of §6.1, the end of the
  console device code, and `claim-names`.
- **B7 — the screens.** The gate screen with its three controls, the
  recovery-code screen, and the two controls of the account screen.
  The boards read `player`, and the daily board has the floor of §9.5.
- **B8 — the documents.** The dated notes in M1, A1, BR1, and
  `docs/final-push.md`, and the deployment guides: the pepper in the
  environment file, the `signup` field, and no invite step.

---

## 15. Testing

- **Unit:** each rule of §4 and §5 with its refusals. The folded
  shape. The recovery code: one use, replaced by a new one, typed
  with spaces and small letters.
- **The store:** two sign-ups for one folded shape make one account.
  A torn sign-up, with a claim and no player record, does not sign
  in.
- **The paths:** each row of the two tables of §8. The constant
  answers are byte-equal across their conditions. A recovery ends
  each earlier session.
- **Limits:** each counter of §9.2 answers 429 at its cap and reads
  no store file after it.
- **The operator's code:** it gets the constant 401 in its hold and
  works after it. It leaves the code of the player, the password, and
  each session as they are. `Stop this` removes it. The console device
  code path answers the constant 404.
- **The daily board:** a player with 2 earlier played days is not on
  the public board and sees the player's own row. A player with 3 is
  on it. Each trial score is byte-equal with and without the floor.
- **No credential in the server output, an answer, or the index.** A test signs
  up, signs in, and recovers with marker strings. It then scans the
  captured server output, each answer body, the results index, and the two
  exports for the markers.
- **The guards:** the start-up matrix of §10.2.
- **The players of today:** a stored record with a `token_hash`
  reads, sets a first password with a session, and does not get in
  through `/join`.
- **The invariant tests** of `CLAUDE.md` §9 stay green with no edit.

---

## 16. Out of scope, with reasons

- **The results database.** The owner's instruction: keep it in
  mind, do not build it (§11).
- **Passkeys.** They use no password and no email address. The
  recovery and the move to a second device are harder, and they come
  after this spec, if at all.
- **Two-step sign-in with an authenticator app.** It holds no datum of
  a person, and it fits this contract as a subsequent spec.
- **Account deletion.** Workstream F has the ruling. This spec fixes
  one piece of it: the name stays claimed.
- **A human check at sign-up** (a puzzle from a different company).
  It sends data of each visitor to that company, which the owner does
  not want.
- **The lifetime of the access file of the edge.** Workstream F.

---

## 17. Sources

- OWASP Cheat Sheet Series, "Password Storage Cheat Sheet", read
  2026-11-13: Argon2id first and scrypt second, the parameter tables,
  and the pepper.
  <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
- NIST SP 800-63B-4 (2025), the password rules: length and a refusal
  table, no character-class rule, no change by the calendar, a
  maximum of 64 or more. Its figure for a password with no second
  proof is 15 characters, and ruling 4 sets 12. Read the section
  again at build time.
  <https://pages.nist.gov/800-63-4/sp800-63b.html>

---

## 18. What the build settled

The build settled these points that the text above did not cover.
Each is a record, and a change to one of them is a new ruling.

1. **The table of usual passwords.** `service/data/usual-passwords.txt`
   has 29,951 entries. `tools/usual_passwords.py` makes it from
   `Pwdb_top-1000000.txt` at SecLists commit `12274c98`, and the file
   `usual-passwords.source.json` has the SHA-256 of the input and of
   the table. The MIT license text is adjacent to the table. The
   compare ignores capitals: each entry and each typed password is in
   its casefold shape.
2. **The reserved check reads the folded shape.** `r00t` and `ad-min`
   are refused with `root` and `admin`.
3. **Two refusals of a credential `POST`.** An `Origin` header that is
   not there or does not agree with the host gets 403
   `{cause: "origin"}`. A media type that is not JSON gets 415
   `{cause: "content-type"}`.
4. **The answer bodies.** The constant 401 of sign-in is
   `{"cause":"sign-in"}`, and of recovery `{"cause":"recovery"}`. The
   constant 403 is `{"cause":"password"}`. The 429 is the body of spec
   BR1, `{"cause":"too-many-attempts"}`.
5. **A new password is checked before the recovery code.** A recovery
   with a password that the rules refuse gets 400 with the cause. The
   check reads the typed values alone, thus it says nothing about the
   account, and it does not use up the code.
6. **The account paths have the caps too.** A bad `current_password`
   counts as one failure for the client address and for the username,
   thus a stolen session cannot find the password by trial.
7. **A server with no pepper.** With no pepper the server has no
   password paths: each of them answers the constant 404. The server
   does not start with no pepper when sign-up is open, or when the
   store holds a credential record. A dev box with door records alone
   starts with no pepper.
8. **Open sign-up needs each claim.** The server does not start with
   sign-up open while a stored player has no name claim. The message
   names `service.players claim-names`.
9. **`restore` keeps the password.** A revoke does not remove the
   credential record. After `restore`, the password of before works
   again, and the operator also gets a code with the hold.
10. **The operator's code is for an active player.** The command and
    the console path refuse a revoked player.
11. **The daily board answer.** Each row gets `public`, and the answer
    gets `floor` with `played_days` (3) and `caller_played_days`. A
    played day is a day with a stored submission of the player.
12. **The wire keeps `display_name`.** Each answer that had the field
    has the username in it, thus each screen reads one name.
13. **Code that went with the invite.** The token mint, the secret
    compare, and the guarded token edit of the store are removed. The
    `POST /api/players` path is removed.
14. **A password that holds the username.** The check ignores capitals.
    A username of 3 characters refuses each password that holds those 3
    characters in sequence, which the screen says.
