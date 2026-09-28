# Spec BR1 — the build for a closed beta

**Status:** ruled and built, 2026-09-24. The owner gave four rulings
(§2) and asked for workstreams B, C, D, and E of `docs/final-push.md`
in one build. Workstreams A (the production pool, spec PP1) and F
(hardening, legal, operations) are not in this spec.
**Architecture sections:** §3 (the invariants), §21 (versioning), §22
(integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I6, I7), §3, §5, §10.
**Amends:** S1 (the day statuses and the D8 clock), S2 ruling 3 (the
close instant), M1 §4 (the session cookie), A1 §4 (the door), W1 (the
theme and the screens), S2 §5 (the console, §7). Each carries a dated
note that points here.

---

## 1. Purpose

The plan of `docs/final-push.md` named four blocks between the build
and a closed beta: players who are not the owner cannot keep a
session (§4 there), days do not move on their own (§5), results have
no reader for programs (§6), and a first-time player meets jargon
and no explanation (§7). This spec is the contract for each repair.
None of it touches Layers 0 to 9: the scoring path, the stored
records it reads, and each config hash stay as they are.

---

## 2. The rulings of 2026-09-24

| # | Question | Ruling |
|---|---|---|
| 1 | How does a day stop the sends while it closes? | A `closing` status between `open` and `closed`. |
| 2 | How far does sign-in go in this build? | Beta scope: sessions apart from invites, device codes, and sign-out. No email and no personal data. |
| 3 | How far does the results database go? | A SQLite index made from the store, with an operator reader, a research export, and a player export. The server's own reads stay on the store files. |
| 4 | Which colors change? | The app theme alone: light by default, dark when the device asks. The drawing surface and the stroke palette (spec C1 §5) stay as they are. |

Decisions in the scope of the rulings, each recorded here:

- The day label is the UTC date that holds the larger part of the
  day's 24 hours (§3.3). The rollover hour is the one config value,
  `closes_at_utc`.
- An invite address stays usable until the operator turns it. It
  makes a new session on each device that opens it.
- A cookie that holds an invite token signs nobody in. Testers from
  before this spec open their invite one more time.
- A session lives 180 days. A device code is 8 characters, lives 10
  minutes, and works one time.
- The index is made again as one file, not written row by row (§5.1).
- The home screen is the path `/`, and the drawing screen moves to
  `/today`.

---

## 3. Workstream C — the day cycle

### 3.1 The `closing` status

The store's day statuses are `open`, `closing`, `closed`, and
`revealed` (`service/store.py`). The close runs this sequence
(`service/day.py` `close_day`):

1. Read the day record. The status must be `open` or `closing`.
2. Wire the scoring context and compare the pinned config hash. A
   missing provider key or a moved config refuses here, while the day
   is open and takes sends.
3. When the status is `open`, move it to `closing` with the day's
   write lock held.
4. Read the submissions, encode them in one batch, write each trial
   row.
5. Move `closing` to `closed` and set `closed_at`.

The send path holds the same lock for its last status check and its
write (`service/server.py`, `POST /api/submission`). A send thus lands
before step 4 reads the submissions, or it meets `closing` and gets
the constant `day-closed` refusal. The lock is an advisory file lock
(`store.day_write_lock`), thus it also covers a close from the console
unit or the command line. A close that stops during step 4 leaves the
day in `closing`, and the next close continues from there.

A rescore skips `open` and `closing` days with one count, because a
`closing` day holds no complete set of rows.

### 3.2 The open rule

An open refuses unless the latest stored day is `revealed`, and the
new label must come after the latest one (`_check_open_sequence`). A
closed day cannot stay behind a newer day, as days 14 to 16 of the
local store did. The HTTP open, the command-line open, and the
rollover share the one function.

### 3.3 The calendar

`service/schedule.py` holds the pure calendar. A day runs for 24
hours and ends at the rollover hour `H` in UTC. Its label is the UTC
date with the larger part of those hours:

| `H` | The day labeled D runs | Example |
|---|---|---|
| 12:00 and after | from D − 1 at `H` to D at `H` | `H` = 22:00: the label is the date on which the day closes |
| before 12:00 | from D at `H` to D + 1 at `H` | `H` = 00:00: the label is the full UTC date |

The day view computes `closes_at` from this rule. For an `H` of 12:00
or after, the string is the one S2 served (`<day>T<H>:00+00:00`). With
no `H` configured, the label is the UTC date of the open, and the
development flow keeps its back-to-back days. With an `H`, an open
refuses a label more than one day after the current one.

### 3.4 The rollover

`python -m service.rollover` moves the latest day as far as the
calendar says (`service/rollover.py`):

| Latest day | Step |
|---|---|
| none | open |
| `open`, before its close instant | nothing |
| `open` at or after its close instant, or `closing` | close |
| `closed` | reveal |
| `revealed` | open |

It reads the store again before each step, drives the server's
operator endpoints on the loopback address with the bearer, opens one
day at most, and holds a file lock. A provider failure on the close
gets retries with a doubling wait. A 409 means a second process moved
the day, and the command reads the status again. The optional
`STARVECTOR_HEALTHCHECK_URL` gets a ping at the end, with `/fail` on a
failure. `--plan` prints the next step and moves nothing.

`deploy/starvector-day.service` (one shot) and
`deploy/starvector-day.timer` (daily at `H`, no catch-up at boot) run
it. The deployment guides, section 14, have the procedure.

---

## 4. Workstream B — sign-in

### 4.1 Sessions

A session is one signed-in device. Its cookie value has the invite's
shape, `<player>.<secret>`, and the store keeps
`store/sessions/<player>/<digest>.json` with the device label and the
creation time. The digest of the secret is the file name, thus a read
finds a session with no walk and the store holds no secret.

`_caller` reads the session for each answer. None of these sign
anybody in: a value that does not parse, no session by that digest, a
session older than 180 days, a player with no record, a revoked
player. Each answers the constant 401.

### 4.2 The paths

| Path | What it does |
|---|---|
| `GET /join/{token}` | Checks the invite and makes a session for that device. A browser that holds a live session of the same player keeps it. |
| `POST /api/session/signout` | Deletes this device's session and clears the cookie. The same answer with a session, a dead one, and none. |
| `GET /api/sessions` | The caller's devices: an id (the digest), the label, the start, and which one asks. |
| `DELETE /api/sessions/{id}` | Signs one of the caller's devices out. An id that is not the caller's answers the constant 404. |
| `POST /api/sessions/others/signout` | Signs each other device out. |
| `POST /api/device-code` | An 8-character code for the caller, 10 minutes, one use. A server with no player records refuses. |
| `POST /api/device-code/redeem` | Trades a code for a session on this device. One constant 400 covers each code that does not work. |

The alphabet of the device code has no 0, O, 1, I, or L. Capitals,
spaces, and hyphens do not count, thus "abcd efgh" and "ABCD-EFGH"
are one code. The redemption claims a code by removing its file, thus
two devices that type one code get one session.

`service/limits.py` counts redemptions that do not succeed, for each
client address and for the process, in a 10-minute window: 10 for an
address and 200 in total. At a cap the answer is 429 before the store
is read. Behind Caddy, the address is the last entry of
`X-Forwarded-For`.

### 4.3 What else moved

- **The door** (spec A1 §4, dev servers alone) makes a new session and
  turns no token. A sign-in on a second device leaves the first
  signed in.
- **`rotate`** turns the invite and keeps each session. **`revoke`**
  also deletes each session file. **`restore`** gives a new invite and
  no device of before.
- **New operator commands:** `service.players sessions <name>`,
  `signout <name>`, and `prune` (expired sessions and device codes).
- **Start-up guards** (`service/server.py` `main`): with no player
  record and no `--dev`, the server refuses to start unless it gets
  `--single-player`: with no record, each visitor plays as the
  configured player. `--cookie-insecure` drops the `Secure` flag for a test box on
  plain HTTP and needs `--dev`.

---

## 5. Workstream D — the results index

### 5.1 The file

`service/index.py` builds `data/index/results-v1.sqlite` from the
store: players, accounts, days, submissions, trial rows, and the atom
report of each trial row. A build writes a new file and `os.replace`
puts it in position. A reader thus holds the earlier file or the new
one, and nothing writes the index row by row, thus the index cannot
fall out of step through a missed write. The store files stay the
source of truth (I4), and the index needs no backup.

A fingerprint of the name, length, and change time of each record
file goes in the `meta` table. `ensure_current` builds again when the
store's fingerprint differs. At beta scale the fingerprint costs one
directory walk.

### 5.2 The fences

- **I7.** Trial rows enter for `revealed` days alone, and a day's
  `target_id` and `secret` stay NULL until its reveal. An index copied
  off the box holds no score of a day that is not public.
- **I6.** A test scans `core/`, `pipeline/`, `pool/`, `providers/`,
  and `validation/` and refuses each import of `service`.
- **Credentials.** No `token_hash`, no session, and no device code
  enters the index.

### 5.3 The readers

| Reader | Path | What it gets |
|---|---|---|
| The operator, by hand | `sqlite3 -readonly` on the file, or `python -m service.index build` and `verify` | each table |
| The operator's scripts | `GET /api/ops/trials?from=&to=&player=`, with the bearer, blocked at the edge | the pinned trial rows of revealed days, with each player's label |
| Research | `python -m service.index export --out <dir> --format csv\|jsonl --salt <secret>` | revealed days alone, each player as a salted digest, no label and no description |
| The player | `GET /api/me/export` | the player's own submissions, and for revealed days the trial row and the target — read from the store |

---

## 6. Workstream E — the app

### 6.1 The theme

`web/src/theme.css` defines semantic tokens (surface, text, muted
text, the primary action) with a light set and a dark set for
`prefers-color-scheme: dark`. Each text token clears WCAG AA (4.5:1)
on each surface it sits on. The measured ratios, light and dark:

| Token | On the card surface, light | Dark |
|---|---|---|
| text | 17.4 | 14.3 |
| secondary text | 8.1 | 9.0 |
| quiet text | 5.9 | 6.4 |
| links | 7.0 | 8.4 |
| white on the primary button | 6.5 | 7.7 (dark text) |

The drawing surface stays `#1f2430` in the two themes. The stroke
palette of spec C1 §5 is unchanged, thus the scorer reads the colors
it read before, and each stroke color clears 3:1 on that surface. The
operator console keeps `nocturne.css`.

### 6.2 The screens

- **Home (`/`)** holds one primary button, and it follows the day:
  start, sent, closing, results in, or no day. Below it: the last
  result against the 50% line, the streak, and practice. A player with
  no result also sees how the game works.
- **The landing page** replaces the invite gate on a 401: what the
  game is, three steps, and two ways in — the invite address, or a
  device code typed in.
- **Today (`/today`)** puts the canvas and one send button in view.
  Words sit adjacent to the canvas, and labeling parts and notes fold
  away.
  The canvas column fits the window height.
- **Results** leads with the share of the other photos beaten and a
  meter with the 50% guessing mark, then the photo with its credit
  adjacent to the sketch, the words that connected, and the day's
  board.
  The fairness check folds away.
- **Your results** fixes the two display defects of the plan: the best
  result is the best share beaten, and the median of a count that
  divides by two is the mean of the two middle values. The chart holds the 50% line.
- **Account** adds the devices, "Add a device", sign-out, and "Download
  my data".
- **How it works (`/how`)** says the rules in plain words.
- Below 760 px the top navigation hides and a bottom tab bar replaces
  it.

The copy rules of spec M1 §9 hold on each screen: no medals, no
"good match" wording, fractional ranks, and the rank, its range, and
the result count at equal weight.

### 6.3 Two server additions

- `GET /api/about`, with no session: `test_season` (the preparation
  record's `dev_only`), `photo_count`, and `closes_at_utc`. Each screen
  says a test season is a test season (spec P1a R13).
- `credit` on `/api/reveal` and on the practice answer: the source, the
  title, and the Wikimedia Commons file page of the target, from the
  release manifest (`service/credits.py`). It comes after the reveal
  gate alone, thus no answer about an open day holds it (R3). A server
  with no manifest serves `null` and prints a warning at start.

---

## 7. The operator console

The owner asked on 2026-09-24 for the console to show each surface of
§3 to §5 and to move each of them: the automatic days, the results
database, and the players with their devices and invites. This
section is the contract for that growth of spec S2 §5.

### 7.1 The four tabs

The console (`web/dev.html`) reaches the dev unit alone, thus each
new path is below `/api/dev/`. Each answers the constant 404 without
`--dev` or with a bearer that does not agree, and the edge refuses the
prefix.

| Tab | What it shows | What it moves |
|---|---|---|
| Days | the day picker, the day record with its times and close instant, the target with its credit, and each player's send with its trial row | open, close, and reveal of the latest day, as before |
| Automatic days | the rollover hour, the next run and its steps, the pause, and the recent runs | pause, resume, and `Do what is due now` |
| Players | each player with devices, the last sign-in, and sends. For one player: the account, devices, device codes, and history | mint, a new invite address (`rotate`), `revoke`, `restore`, a device code, sign-out of one device or all, and the prune |
| Results database | the index file, its build time, if it agrees with the store, and the row count of each table | a build, a compare with the store, and read-only SQL |

The tabs stay mounted when hidden, thus a tab switch loses no loaded
data. A blur of the token field reloads each tab.

### 7.2 Automatic days

The rollover and the console share three records in
`store/rollover/`:

- `control.json`: the pause, its time, and a note. With no file,
  automatic days are not paused.
- `runs/`: one record for each rollover. It holds the start and the
  end, the source (`timer`, `command-line`, or `console`), the outcome
  (`moved`, `nothing due`, `paused`, or `failed`), the steps, and the
  lines the rollover printed.
- `.lock`: the rollover lock. It moves from `/run` into the store,
  thus a rollover from the console and one from the timer hold the
  same lock. The day unit gets `ReadWritePaths` on the store, and its
  `ExecStart` names the source `timer`.

A paused rollover moves no day. It writes a `paused` run and pings the
health check as a success, because the operator sets the pause and
the console shows it. The Days tab controls and the `Do what is due
now` button do not read the pause. That button does
what the timer does at this moment, in the dev unit's process, with
no retries, thus the operator sees a failure immediately.

The next run is the first rollover hour at or after the current
instant (`schedule.next_rollover_at`), and `rollover.planned_steps`
gives its steps. The console cannot see systemd: it shows the hour of
`closes_at_utc`, and the timer must agree with it. With no
`closes_at_utc`, the tab says automatic days are off and offers no
control.

### 7.3 The results database

The query path takes one SQL statement and answers 1,000 rows at
most, with a flag when more rows agree with the query. A statement
that runs for more than 5 seconds stops, and the text is 10,000
characters at most. A value is 10,000,000 bytes at most. Three
layers keep the path read-only:

1. The file opens with `mode=ro`.
2. `PRAGMA query_only` is on.
3. An authorizer lets reads, `SELECT`, functions, and `WITH
   RECURSIVE` through, and refuses each other action.
   A write, `ATTACH`, and `PRAGMA` thus refuse.

A query first makes the index current. That build writes the cache
file and not the store. The fences of §5.2 hold: the index holds no
trial row of a day before its reveal, and no credential.

### 7.4 Players

- A device code from the console is for a player with no signed-in
  device. The iPhone home-screen app keeps its own cookies, and an
  invite address opens in Safari, thus the code is the one path into
  that app. The code prints one time.
- A new invite address from the console is the `rotate` of §4.3: the
  sessions stay. The printed address starts with the site address
  that the mint panel holds.
- The console reads the avatar with the bearer and shows it from
  memory, because an image element cannot send a header.

### 7.5 The paths

| Path | What it does |
|---|---|
| `GET /api/dev/day?day=` | One day record, its close instant and credit, and each send with its trial row |
| `GET /api/dev/schedule` | The rollover hour, the current instant and label, the latest day, the steps due at this instant, the next run and its steps, the pause, if a rollover holds the lock, and the last 20 runs |
| `POST /api/dev/rollover/pause` | Sets the pause from `{"paused": true or false, "note": ""}`. The note is 200 characters at most |
| `POST /api/dev/rollover/run` | Does the steps due at this instant. 409 when no hour is configured or a rollover holds the lock |
| `GET /api/dev/players` | The roster, and for each player the live devices, the last sign-in, the device codes that wait, and the send count |
| `GET /api/dev/players/{name}` | One player's record, account, devices, and device codes. No secret and no digest of an invite |
| `GET /api/dev/players/{name}/avatar` | The avatar bytes |
| `POST /api/dev/players/{name}/rotate`, `/revoke`, `/restore`, `/signout`, `/device-code` | The commands of `service.players` and a device code |
| `DELETE /api/dev/players/{name}/sessions/{id}` | Signs one device out |
| `POST /api/dev/prune` | Removes expired sessions and device codes |
| `GET /api/dev/index` | The index file: its build time, if it agrees with the store, and each table with its columns and row count |
| `POST /api/dev/index/build` and `/verify` | A build, and the compare of `python -m service.index verify` |
| `POST /api/dev/index/query` | Read-only SQL, `{"sql": "..."}` |

---

## 8. Gates at hand-off

| Gate | Result |
|---|---|
| `uv run pytest` | 1280 passed (1139 before this spec, 1256 before §7) |
| `pnpm exec vitest run` | 176 passed (125 before, 154 before §7) |
| `pnpm exec playwright test` | 17 passed (14 before, 15 before §7) |
| `pnpm exec tsc --noEmit` and `biome ci` | clean |
| Vale, error level, on the lines this spec adds | 0 |
