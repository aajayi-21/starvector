# The last push to a public test

**Status:** plan, written 2026-09-24. *Update, same day:* workstreams
B, C, D, and E are built — spec BR1 (`docs/specs/beta-readiness.md`)
records the four rulings of §10 (items 3 to 6) and what landed. A and
F stay open. The remaining text is the plan as written. It surveys `main` at `3b3a660` and the uncommitted spec PP1
draft, then names the remaining work in six workstreams. Each
workstream becomes a spec, or a change to one, with owner
rulings before code — the procedure of each spec in `docs/specs/`.
**Reads with:** `docs/ARCHITECTURE.md` (canonical), `CLAUDE.md` (the
working agreement), `docs/specs/production-pool.md` (spec PP1), and
the two deployment guides.

---

## 1. The short version

The scoring engine, the trial server, the web app, the multiplayer
statistics, and the account surfaces are built and merged. The
offline gates are green. The build has one development pool of 204
images and one player.

Six workstreams are open:

| # | Workstream | What it blocks | Work | Section |
|---|---|---|---|---|
| A | The production pool (spec PP1) | public numbers (rule R13) | moderate code, about 15 hours of provider time, one set of gates | §3 |
| B | Sign-in | each tester who is not the owner | moderate to large | §4 |
| C | The automatic day cycle | a daily game with no operator at the keyboard | small, after three repairs | §5 |
| D | The results database | programmatic access to results, and server reads at scale | moderate | §6 |
| E | The UI | first-time players | moderate | §7 |
| F | Hardening, legal, operations | a public address | moderate | §8 |

The recommended sequence has two releases. First, a **closed beta on
the development pool**: invited testers, numbers labeled as
development numbers, at the time B, C, and the minimum of F land.
Second, the **public test on the production pool**, when spec PP1
meets its acceptance criteria. §9 gives the longest path and §10
the decisions that are yours.

---

## 2. Where the project is

### 2.1 Built and merged

| Area | Where | Status |
|---|---|---|
| Layers 0 to 9 | `core/` | built. Layer 7, the rerank, waits for Phase 6. |
| Pool curation and preparation | `pool/` | built. Dev lineage `dev-wit-002-9644fac1`, 204 images. |
| V1 to V6, the fit, the weight freeze | `validation/`, spec F1 | recorded on the dev lineage. Frozen weights `{element: 0.45, outline: 0.55}`, placement cut. |
| The fast path (spec P5) | `service/scoring.py`, `tools/bench.py` | built. 6.74 ms local at 204 images, 77.33 ms at 20,000. |
| The trial server (specs S1, S2) | `service/` | open, close, reveal, history, boards, reveal by day, stored-submission replay. |
| Multiplayer (spec M1) | `service/rollup.py`, `core/aggregate.py` | invites, cookie sessions, the operator bearer, the daily board, the skill board with the population fit. |
| Accounts (spec A1) | `service/server.py`, `web/src/screens/account.tsx` | description, avatar, the dev-only door, the console roster. Merged in PR #29. |
| The web app (spec W1) | `web/` | React PWA, the player screens, the operator console `dev.html`. |
| Deployment | `deploy/`, the two deployment guides | Caddy edge, hardened systemd units, restic backups. |

### 2.2 The gates on 2026-09-24

| Gate | Result |
|---|---|
| `uv run pytest` | 1139 passed |
| `pnpm exec vitest run` | 125 passed, 17 files |
| `pnpm exec tsc --noEmit` | clean |
| `pnpm exec biome ci .` | 1 warning, 1 info |
| Playwright | not executed for this plan |
| Vale on `docs/specs/production-pool.md` | 0 errors |

### 2.3 What the local store holds

`store/` holds eight days, 2026-08-12 to 2026-08-19. `ade` played
seven of them, and 2026-08-15 has no submission:

- Four days are `revealed`: 12, 13, 17, 18.
- Three days are `closed` and not revealed: 14, 15, 16. Each opened
  before its calendar date through the "next free date" rule, and
  the open of a subsequent day left it behind (§5.2, item 2).
- 2026-08-19 is `open`, since 2026-08-15.

There is no `players/` directory. The local server is thus in the
single-player fallback of spec M1 ruling 7: no sign-in, and each
caller is the configured player.

### 2.4 Loose ends in the working tree

- Spec PP1 is untracked, and its six dated notes in other documents
  are uncommitted. Commit them as one change before a PP1 build
  branch starts.
- Many spec status lines are stale: merged specs say "draft,
  for review" or "in build". One edit to each keeps the spec set
  honest.
- 26 local branches are merged. Pruning them is optional.

---

## 3. Workstream A — the production pool

Spec PP1 holds the arithmetic. This section is the plan to do
it.

### 3.1 Rulings first

Rulings 1 (`N = 7,500`) and 10 (a USD 20 cap) are made. The open
ones, with a recommendation for each:

| Ruling | Proposed in PP1 | Recommendation |
|---|---|---|
| 2, sampling | `sample_rate` 0.03 across 105 shards | accept |
| 3, bytes and cap | `budget_bytes` 20 GB, `materialize_cap` 38,000 | accept. The cap is the cost fence. |
| 4, tag | `prod-wit-001` | accept |
| 5, calibration | 20 shards, tag `dev-wit-003` | accept. It replaces the 5% near-duplicate allowance with a measurement. |
| 6, diversity | unchanged, cap 15 | accept. Keep cap 18 as the lever if calibration shows a tight budget. |
| 7, vocabulary | build B3 before the bench | accept. It is the one item that can miss the 50 ms line. |
| 8, encoder | `google/gemini-embedding-2` | accept |
| 9, provider rate | 2 `POST`/s | increase it if the OpenRouter account permits. Wall-clock time falls in proportion. |
| 11, the two budget changes | one screening `POST` for each candidate, boxes deferred | accept. Without it, USD 20 buys about 3,770 images. |

### 3.2 Build items (offline, one branch each)

PP1 §7 lists B1 to B8. Six are configs, guards, and a prune command.
Two have code risk:

- **B3, the resident centered vocabulary.** The similarity table
  measured 208 ms of a 239 ms total at the projected vocabulary. The
  byte-equality gate test against the current computation is the
  acceptance line, in the pattern of spec P5 B2.
- **B7, the one screener slot.** One OpenRouter provider answers
  three protocols from one cached response. A fake twin keeps the
  suite offline.

### 3.3 Execution

You type each command that touches the network. The key stays in
your environment and out of each transcript.

| Step | Command | USD | Provider time |
|---|---|---|---|
| Calibration | `uv run python -m pool.curation --config configs/curation/dev-wit-3.json` | about 2.3, in the total below (a cache-warm prefix) | some hours |
| Production curation | the same with `prod-wit.json`. It stops at s08. Write `review.json` and start the command again for s09. | about 12.2 | about 10 hours: fetch 4.8, screening 5.3 |
| Preparation | `uv run python -m pool.preparation --config configs/preparation/prod-wit-photo-inst.json` | about 6.5 | about 1 hour plus embeddings |
| Baseline gates | V1 (sym), V2 (sym, mixed), v2c on the Nord palette | cents | less than 1 hour |
| Generalize, fit, freeze | `validation.generalize`, then the F1 sequence | about 0.4 | about 3.7 hours |
| Production gates | V3 to V6, with V6 at the 500/25/90% line | cents | less than 1 hour |
| Bench | `uv run python -m tools.bench --count 7500 --vocabulary <measured> --write` | 0 | minutes |
| Re-point and deploy | `configs/service/`, the 4 GB droplet plan, the serving copy at 768 px | 0 | — |

The PP1 §5a total is USD 19.10, with a margin of USD 0.90.

### 3.4 Risks to monitor

- **The thin margin.** The calibration step measures the yield
  before the large spend. Cap 18 lands at USD 16.4 but changes the
  pool's structure (ruling 6).
- **The measured vocabulary.** `|V|` can come in above the Heaps
  projection of 26,800. B3 lands before the bench, not after.
- **The inherited standing items.** The level-4 generator premise
  (V3 `control_at_half`), the element background composition (the V5
  element slope at −0.326), the V5 hotspot monitor, and placement
  back in the fit simplex.
- **Image credit.** Curation keeps `image_url`, `metadata_url`, and a
  license note for each image. No screen shows them (§8.3).
- **The color gate comes first.** `validation/colorize.py` holds the
  palette of 2026-08-12, and the web app sends the Nord values of
  spec C1 §5. Spec C1 asks for v2c on the Nord values before the
  first day played in color on the production app. That is a
  closed-beta item on the dev lineage (§9, phase 1), and the
  production gates of §3.3 do it again.
- **The serving box.** Resident arrays are 1.1 to 1.4 GB, thus the
  4 GB plan.

---

## 4. Workstream B — sign-in

### 4.1 How it works today

The app is invite-only (spec M1 §4):

1. The operator mints a player with `python -m service.players mint`
   or the console, and sends `/join/<player>.<secret>`.
2. The server compares the secret against the stored sha256 digest
   and sets the `sv_session` cookie. The cookie holds the invite
   token itself, with `Secure; HttpOnly; SameSite=Lax` and a 180-day
   age.
3. Each `POST` and `GET` checks the token again (`_caller` in
   `service/server.py`). A new invite (`rotate`) or `revoke` stops
   each session of that player at its next read.

The door (`/api/door`, spec A1 §4) mints or turns a token by a typed
name, on a `--dev` server alone. Without `--dev` it answers 404.

With no player records stored, the server has no sign-in at all:
each caller is the configured player.

### 4.2 What was tested

The test used a scratch copy of the store. The working `store/` did
not change. A player was minted and its invite opened through the Vite
dev proxy, at `http://localhost` and at `http://127.0.0.1`. The two
signed in, and the Today screen loaded. The `/join` answer was a 302
with the cookie flags above.

The core invite path thus works on loopback, and the failure you see
is most likely one of §4.3. The symptom (the screen, the device, the
address) pins it down.

### 4.3 Failure modes, most likely first

| # | Symptom | Cause | Evidence |
|---|---|---|---|
| 1 | A phone with the app on its home screen shows "This browser is not signed in", after the invite opened correctly in the browser | iOS gives a home-screen web app its own cookie store. The invite opens in Safari, not in the installed app, and the gate has no field to type in. | `web/src/ui/invite-gate.tsx` says "nothing to type here". `web/src/ui/install-hint.tsx` sends iOS players to Add to Home Screen. A test on a device settles the platform behavior. |
| 2 | Sign-in works, then the next screen shows the gate again, on a LAN address or a bare IP address | The `Secure` flag. A browser drops that cookie on plain HTTP away from loopback, and `main()` in `service/server.py` has no switch for it. | `session_cookie_header` in `service/auth.py`. `docs/home-deployment.md` §12 warns about it. |
| 3 | A new device, a cleared browser, or an invite that nobody can find has no path back in | Production has no sign-in screen, only the invite address. A new invite (`rotate`) signs out each other device. | `rotate_player` in `service/players.py` |
| 4 | A sign-in through the dev door on a second device signs out the first | The door turns the token of an active name. | `door_enter` in `service/server.py` |
| 5 | The server does not start again after the first mint | With player records stored, `create_app` refuses to start without `STARVECTOR_OPERATOR_TOKEN`. | `create_app` in `service/server.py` |
| 6 | Each visitor plays as the owner | A public box with no player records is in the fallback. | spec M1 ruling 7 |
| 7 | `/join/...` shows the app and sets no cookie | An edge or an app-shell worker that does not send `/join` to the server: a worker installed before the denylist, or a Caddyfile with no `handle /join/*` section. | `web/vite.config.ts`, `deploy/Caddyfile`. `curl -sI https://<domain>/join/bogus` must answer 401 JSON. |

Two more gaps: there is no sign-out, and the invite address is a
permanent credential that lives on in browser history and chat logs.

### 4.4 The recommended solution — a new spec, "A2 sign-in"

Three changes, in this sequence:

1. **Sessions apart from credentials.** The cookie holds a random
   session id. The store keeps its digest with the player, the
   creation time, and a device label. Sign-out deletes one session,
   and "sign out on each device" deletes all of them. A new invite
   then stops only the invite, not each device.
2. **Device codes.** The account screen gets "Add a device", which
   shows an 8-character code with a 10-minute life. The gate gets one
   field to type it. This closes failures 1 and 3 with no email and
   no personal data. It is the minimum for the closed beta.
3. **Self sign-up for the public test.** The player gives an email
   address and types the one-time 6-digit code it gets. A typed code
   works in an iOS home-screen app, and a clicked address does not.
   An optional invite code caps the cohort. This brings an email
   provider (for example Postmark, Resend, or Amazon SES), a privacy
   policy, and rate limits on the code endpoints. Passkeys are a
   possible next step.

The scoring invariants do not move: identity is upstream of nothing
in Layers 0 to 9. Each new refusal keeps the constant-body pattern
of R3, and no sign-in answer carries a byte that depends on the
target (I7).

Three small items that do not wait for A2:

- A `--cookie-insecure` flag that the server refuses without `--dev`,
  for LAN test boxes.
- In production, the server refuses to start with zero player
  records. This closes failure 6.
- A sign-out endpoint and a button on the account screen.

---

## 5. Workstream C — the automatic day cycle

### 5.1 The lifecycle today

Three statuses: `open`, `closed`, `revealed` (`service/store.py`).

- **Open** picks the target from a random seed, writes the
  commitment `sha256(target:secret)`, and makes a 6-character trial
  code. No network.
- **Close** scores each stored submission. It **needs
  `OPENROUTER_API_KEY` and the network**, because each new atom goes
  through the encoder. With a 120-second timeout and retries, a bad
  provider hour can hold a close for minutes. A second close after a
  stop is safe: rows that agree are kept.
- **Reveal** moves the status, then the multiplayer roll-up writes
  the boards in `data/`. No network.

Three controls move a day: the operator console through the tunnel,
`curl` with the bearer at `127.0.0.1:8000/api/day/{open,close,reveal}`,
and the command line `python -m service.day {open,close,reveal,status}`.
Caddy blocks the three paths from the internet. `closes_at_utc` in
the server config sets the countdown and closes nothing (spec S2
ruling 3). There is no timer in `deploy/`.

### 5.2 Three repairs before a timer

1. **Late submissions during close.** `close_day` reads the stored
   submissions, encodes (network, possibly minutes), then moves the
   status. The `submit` handler accepts until the status moves. A
   submission in that interval gets stored with no trial row. On
   that day `rescore` then stops with "a closed day has no stored
   trial row". A fixed daily close hour makes this likely. The
   repair is one of:
   - a server-side cutoff: the `submit` handler refuses at or after
     `closes_at`, or
   - a `closing` status, set before the scores start.

   Each is a spec change. Spec S2 ruling 3 makes `closes_at`
   display-only, and the status set is in the store's frozen shape.
   Your ruling.
2. **Open does not wait for the reveal.** The HTTP open refuses only
   when the latest day is `open`. It accepts a latest day that is
   `closed`. The HTTP reveal acts on the latest day alone, thus the
   earlier day stays closed until a `reveal --date` on the command
   line. Your local store holds three such days. The repair: open
   refuses unless the latest day is `revealed`.
3. **Two clocks.** The open reads the box's local date
   (`datetime.date.today()` in `service/day.py` and in the open
   endpoint), and `closes_at_utc` is UTC.
   - The countdown shows the label date at `closes_at_utc`, thus the
     label must be the date on which the day closes.
   - The "next free date" rule gives that label at a rollover: a
     latest day labeled with today's date makes the new label the
     next day. That holds only when the box clock is UTC.
   - The repair: the box and the unit on UTC (or the date read in
     UTC in the code), and a production open that refuses a label
     more than one day after the UTC date.

   The back-to-back test flow of spec S1 §14b is what opened days 14
   to 16 in your store before their calendar dates.

One more: the guarded status moves write through a fixed `.tmp`
name (`pool/artifacts.py`), which is not safe with two concurrent
writers. A timer and a console click at the same moment are two
writers. The cycle script holds an `flock`.

### 5.3 The proposed cycle

One rollover each day at a fixed UTC hour `H`, the value of
`closes_at_utc`:

1. Close the open day. On a network error, retry with backoff.
   Submissions stop at `H` through repair 1.
2. Reveal it.
3. Open the next day. With the box on UTC, the "next free date"
   rule labels it with tomorrow's date, the date on which it closes,
   and the countdown agrees with the timer.

Players get a 24-hour window, and the reveal and the new target
come at the same moment. Keep `H` clear of 04:30 (the
unattended-upgrade reboot) and 05:00 (restic).

### 5.4 How to set it up

`deploy/` does not have these files today. They land after the
three repairs.

`/etc/systemd/system/starvector-day.service`:

```ini
[Unit]
Description=Starvector day rollover (close, reveal, open)
After=starvector.service
Requires=starvector.service

[Service]
Type=oneshot
User=starvector
WorkingDirectory=/srv/starvector/app
EnvironmentFile=/etc/starvector/env
ExecStart=/srv/starvector/app/deploy/day-cycle.sh
TimeoutStartSec=45min
RuntimeDirectory=starvector-day
```

`/etc/systemd/system/starvector-day.timer`:

```ini
[Unit]
Description=Starvector day rollover at the close hour

[Timer]
OnCalendar=*-*-* 22:00:00 UTC
Persistent=false
AccuracySec=1s

[Install]
WantedBy=timers.target
```

`deploy/day-cycle.sh`, in outline:

```bash
#!/usr/bin/env bash
set -euo pipefail
exec 9>/run/starvector-day/lock
flock -n 9 || { echo "a rollover holds the lock"; exit 1; }
api() {
  curl --fail --silent --show-error --max-time 900 -X POST \
    -H "Authorization: Bearer ${STARVECTOR_OPERATOR_TOKEN}" \
    "http://127.0.0.1:8000/api/day/$1"
}
.venv/bin/python -m service.day --service-config /etc/starvector/service.json status
api close    # retry loop with backoff goes here
api reveal
api open
curl -fsS --max-time 10 "${HEALTHCHECK_URL}" >/dev/null   # a missed ping alerts you
```

Three notes on the outline:

- The script reads the status first and skips a step that is done.
  A second start after a stop then continues from the step that
  stopped, and a second close is safe.
- The lock stops two rollovers at the same moment. The console does
  not hold it, thus do not move a day by hand in the minutes around
  `H`.
- `HEALTHCHECK_URL` goes in `/etc/starvector/env` with the key and
  the token.

`Persistent=false` matters: a box that was down at `H` must not fire
a stale close at boot. Close by hand in that condition. The next-free-
date rule then opens today's date, with a shorter window that day.

The commands:

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now starvector-day.timer
```

```bash
systemctl list-timers starvector-day.timer
```

```bash
journalctl -u starvector-day -n 50
```

Set `closes_at_utc` in `/etc/starvector/service.json` to the same `H`
and start the server again. One value in two files can drift. A
start-up check that compares them, or a timer file written from the config,
closes that.

Until the repairs land, the manual day of
`docs/droplet-deployment.md` §14 is the safe procedure: close, reveal,
then open, in that sequence, each day.

---

## 6. Workstream D — the results database

### 6.1 What stores results today

The store files are the source of truth (I4). Five record classes:
day, submission, trial row, player, account. A trial row holds `p`,
`target_rank`, `decoy_count`, `beaten`, `tied`, the atom report, and
the config hashes. It holds no score for each channel. A rescore
with a new config writes a sibling row, and the pinned row must
render again byte-equal (R8). Reveal writes the boards in `data/`.

Some read paths walk each day: `/api/history`, the streak, the
revealed-target set behind `/image`, and practice. Spec M1 §7 says
nothing in the read path walks the store.

### 6.2 Recommendation: SQLite as a derived results index

- **Not the source of truth.** The store files stay canonical. The
  database is a cache that a command makes again from `store/` at
  each moment, thus I4 holds. A database as the source of truth
  breaks R8 and the byte-level recovery drill. Not recommended.
- **SQLite in WAL mode**, one file, the standard-library `sqlite3`
  module. The server is one process on one box (spec S2 ruling 1):
  no second daemon, no Postgres. Postgres is the step up when the
  server grows to more than one process.
- **A projector writes it** after each store write — submission,
  close, reveal, mint, account edit — and two commands keep it
  honest: `python -m service.index rebuild` and `verify`, which
  compares the index with the store row by row.

Schema sketch:

```sql
CREATE TABLE players (
  player TEXT PRIMARY KEY, display_name TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE days (
  day TEXT PRIMARY KEY, trial_code TEXT NOT NULL, status TEXT NOT NULL,
  commitment TEXT NOT NULL,
  target_id TEXT, secret TEXT,          -- NULL until revealed
  scoring_config_hash TEXT NOT NULL, preparation_version_id TEXT NOT NULL,
  opened_at TEXT, closed_at TEXT, revealed_at TEXT);

CREATE TABLE submissions (
  day TEXT NOT NULL REFERENCES days, player TEXT NOT NULL REFERENCES players,
  trial_id TEXT NOT NULL, received_at TEXT NOT NULL,
  impression_count INTEGER, stroke_count INTEGER, group_count INTEGER,
  relation_count INTEGER, has_pasted_text INTEGER,
  record_json TEXT NOT NULL,            -- the raw wire record
  PRIMARY KEY (day, player));

CREATE TABLE trials (
  day TEXT NOT NULL, player TEXT NOT NULL, scoring_config_hash TEXT NOT NULL,
  pinned INTEGER NOT NULL,              -- 1 = the day's own config
  trial_id TEXT NOT NULL, p REAL NOT NULL, target_rank INTEGER NOT NULL,
  decoy_count INTEGER NOT NULL, beaten INTEGER NOT NULL, tied INTEGER NOT NULL,
  commonness_config_hash TEXT, preparation_version_id TEXT NOT NULL,
  PRIMARY KEY (day, player, scoring_config_hash));

CREATE TABLE trial_atoms (
  day TEXT, player TEXT, scoring_config_hash TEXT, atom_id TEXT,
  atom_text TEXT, element TEXT, weight REAL, similarity REAL, rarity REAL);

CREATE VIEW revealed_trials AS
  SELECT t.* FROM trials t JOIN days d USING (day)
  WHERE d.status = 'revealed' AND t.pinned = 1;
```

### 6.3 Access

| Who | Path | What they get |
|---|---|---|
| Operator, by hand | `sqlite3 -readonly` on the box, or a copy of the file. DuckDB and pandas read it. | each table |
| Operator, scripted | `GET /api/ops/trials?from=&to=` with the bearer, tunnel-only, blocked at Caddy | JSON rows |
| Research export | `python -m service.index export --revealed-only --format parquet`, player names replaced by a salted hash | revealed days only |
| Player | `GET /api/me/export` | the player's own submissions and own revealed trial rows, as JSON |

An interim with no new write path: DuckDB reads the JSON files where
they are, for example
`SELECT * FROM read_json_auto('store/days/*/trials/*.json')`. It is
good for analysis this week. It does nothing for the server reads.

### 6.4 Fences

- **I6.** Fit and validation code must not touch the index. Extend
  `tests/unit/test_fit_isolation.py` to refuse an import of the
  index module from `pool/`, `validation/`, and `core/`.
- **I7.** Trial rows are in the store from close, before reveal.
  Each player path and each export filters on `days.status = 'revealed'`, and the
  index holds `target_id` and `secret` only after reveal.
- **Operator fields.** `_OPERATOR_ONLY` fields and `token_hash` stay
  out of the player and research views.
- **Backups.** The index needs no backup, because the store makes it
  again. Do not include it in restic, or copy it with
  `sqlite3 .backup`.

### 6.5 Server reads, the second step

Move `/api/history`, the streak, the revealed-target set, and the
name and avatar lookups on the boards to the index. A missing or
stale index stops loudly, with no silent fallback (`CLAUDE.md` §3),
and the server makes it again at start.

---

## 7. Workstream E — a critique of the UI

The screens were checked at 1366 × 860 and at 375 × 812, on the
scratch store.

### 7.1 What works

- The trial code, front and center. The canvas with the Nord
  palette and the `Undo` and `Redo` buttons. The send summary
  ("0 impressions · 2 strokes · 0 groups · 0 relations") and the
  one-send lock.
- The reveal: a large trial score, "You beat 164 of 203 decoys —
  rank 40 of 204", and the target adjacent to the sketch.
- Practice says in plain words that nothing is stored.

### 7.2 Bugs, confirmed in the code

1. **History, "Best rank".** It shows the best rank against the newest
   day's pool count: "3 of 204", where that day was "3 of 225"
   (`web/src/screens/history.tsx:75`, `view.days[0]?.decoy_count`).
   Ranks from pools of different counts do not compare. The best
   `p` is the better statistic.
2. **History, "Median score".** With four scores it takes the third
   value, not the mean of the two middle values: it shows 0.969, and
   the median of the four scores is 0.888
   (`web/src/screens/history.tsx:73`).

### 7.3 Blocks a first-time player

1. **No explanation of the game.** A signed-in player sees a
   6-character code and an empty canvas. Nothing says that a hidden
   photo exists, what to sketch, or how the score works. Add one
   first-visit screen and a "How it works" page (onboarding is one of
   the W1 deferred items).
2. **The signed-out screen is a dead end** (§4.3), and a visitor with
   no invite gets no landing page.
3. **Placeholder copy in production:** `Daily reminder — not wired
   yet` (`web/src/screens/history.tsx:178`).
4. **No image credit on the reveal** (§8.3).
5. **No development-numbers label** while the pool has a `dev-` tag
   (R13).

### 7.4 Clarity

- **Jargon on player screens:** "commitment a8f2…", "Enter commits",
  "How things sit", "shrunk 1.013 · evidence 0.258", "rarity 4.62",
  and "−0.161 vs median" (the median of what?). Put the commitment
  and the `printf … | sha256sum` check behind a "Check that this
  day was fair" disclosure. Give each number one line of
  explanation.
- **No chance line.** The one fact that makes a trial score readable
  — 0.5 is chance — is on no chart. Add a 0.5 rule to the History
  chart and one sentence to the reveal.
- **The reveal explains text alone.** "What matched" lists the
  impressions. The sketch, which feeds the outline channel at 55% of
  the weight, gets no line of feedback.
- **The skill board mixes two floors in one sentence:** "opens when a
  player has 30 trials", then "0 of 30 eligible players". Say the two
  floors: 30 players with 30 trials each. During the beta the board
  stays empty for 30 days or more. Say so, with a date.
- **The "Open" status badge** sits alone at the right edge and looks
  like a button.

### 7.5 Layout

- **Desktop.** The square canvas is taller than a 1366 × 860 window.
  Its bottom is below the fold, and the right column stops at the
  middle of the page. Set the canvas height from the window height,
  or pin the right column.
- **Mobile.** The navigation wraps to two rows, about 155 px of 812.
  A bottom tab bar (the 1f mockup) or an overflow menu keeps one
  row.
- The account screen and the leaderboard are mostly empty at beta
  scale.

### 7.6 Look and access

- Muted text on Nord surfaces has low contrast: placeholders, the 9
  to 10 px uppercase kickers, and the table headers. Measure each
  against WCAG AA (4.5:1 for body text).
- The W1 device matrix (iOS Safari, Android touch, iPad pencil) has
  no recorded result. Playwright tests Desktop Chrome alone.
- No countdown today: `configs/service/dev-wit.json` sets no
  `closes_at_utc`.

---

## 8. Workstream F — hardening, legal, operations

### 8.1 Abuse and limits

- **Rate limits: none.** `POST /api/practice/score` spends OpenRouter
  money for each new sketch. Add limits for each player in the
  server, and limits for each address on the sign-in endpoints — in
  the server, or at Caddy with its rate-limit plugin (the standard
  Caddy build has none).
- **Body caps.** Layer 0 caps atoms (64) and text (200 characters),
  not strokes, points, or bytes. Put a byte cap at the edge (Caddy
  `request_body max_size`) and in the server, not in Layer 0: Layer 0
  is in the tier of `CLAUDE.md` §5 that does not change.
- **Moderation.** Display names, descriptions (500 characters), and
  avatars show on the boards with no content check. The minimum: an
  operator command that clears a description or an avatar, adjacent to
  the existing `revoke`.

### 8.2 Headers

The Caddyfile sets none. Add HSTS, a `Content-Security-Policy`
header for the built app, `X-Content-Type-Options: nosniff`, and
`Referrer-Policy: same-origin`.

### 8.3 Legal

- **Image credit and license.** Wikimedia Commons images want an
  author credit and a license notice. Curation keeps `image_url`,
  `metadata_url`, and a license note, but `/api/reveal` does not send
  them and the reveal screen shows none. Add a credit line with a
  pointer to the Commons file page.
- **A privacy policy and terms**, before a public address, and more
  so with email sign-in.
- **Account deletion against I4.** Raw inputs are permanent. One
  possible ruling: deletion removes the player record, the account,
  the avatar, and the name on each board, and keeps the raw strokes
  and text with a pseudonym. It touches an invariant, thus it is
  your ruling.

### 8.4 Operations

- **Monitoring.** An uptime check on `/api/day` (with no cookie it
  answers 401, and a 401 means the server is up), the day-cycle ping
  of §5.4, disk space, and the OpenRouter spend cap as the hard
  ceiling.
- **The recovery drill.** `deploy/README.md` has it. Do it one time
  on the deployed box before the beta.
- **The box clock on UTC** (§5.2).

---

## 9. The sequence and the longest path

```
rulings (§10)
  ├─ A: PP1 B1–B8 ─ calibration ─ curation ─ preparation ─ gates ─ fit ─ bench ─┐
  ├─ C: three day repairs ─ timer ────────┐                                     │
  ├─ B: sessions, device codes, sign-out ─┤                                     │
  ├─ E: two bugs, onboarding, copy ───────┼─ closed beta (dev pool, labeled)    │
  ├─ F: headers, limits, image credit ────┤        │                            │
  └─ v2c on the Nord palette (dev) ───────┘        │                            │
                                                   ├─ D: results index          │
                                                   ├─ B: email sign-up          │
                                                   └─ F: legal pages ───────────┴─ public test
```

**Phase 0, this week.** Commit the PP1 draft. Give the rulings of
§10. Repair the two History bugs, which are small and self-contained.

**Phase 1, closed-beta readiness.**

- The three day-cycle repairs and the timer (C).
- Sessions, device codes, and sign-out (B, items 1 and 2).
- The development-numbers label, the first-visit screen, and the
  copy edits (E).
- Headers, limits, and image credit (F).
- The v2c gate on the Nord palette, on the dev lineage (§3.4).
- Then a week of manual days on the deployed box, then the timer.

**Phase 2, the production pool, in parallel.** PP1 B1 to B8, then the
runbook of §3.3. The provider hours dominate the wall-clock time, not
the code.

**Phase 3, the public test.** The results index (D). Email sign-up
(B, item 3). The privacy policy, the terms, and the deletion ruling
(F). The re-point to the production lineage, the first production day,
and the R13 gate opens.

**A note on beta data.** Trials on the dev lineage stay dev numbers.
The skill board keys on the scoring config hash, thus it starts at
zero on the production lineage.

---

## 10. Decisions that are yours

1. PP1 rulings 2 to 9 and 11 (§3.1).
2. The beta shape: a closed beta on the development pool first
   (recommended), or a wait for the production pool.
3. The close cutoff: a server-side cutoff at `closes_at`, or a
   `closing` status (§5.2, item 1).
4. The day boundary and the rollover hour `H`, in UTC (§5.3).
5. Sign-in: device codes for the closed beta, and email one-time codes
   for the public test (§4.4).
6. The results database: SQLite as a derived index (recommended), or
   DuckDB on the files alone (§6).
7. Account deletion against I4 (§8.3).
8. The moderation minimum (§8.1).

---

## Appendix — how this plan was checked

- **Read:** each spec in `docs/specs/`, `docs/ARCHITECTURE.md` §20 to
  §25, `service/`, `deploy/`, the web screens, and the two deployment
  guides.
- **Executed:** the gates of §2.2. The server itself, with `--dev`,
  on a scratch copy of the store, with the Vite dev server in front, for
  the sign-in test of §4.2 and the screen tour of §7.
- **Confirmed in the code:** the close race (§5.2, item 1), the
  stranded closed days (item 2), the two History bugs (§7.2), no body
  cap and no rate limit (§8.1).
- **Not confirmed here:** the iOS cookie-store behavior of failure 1
  (a device test settles it), the Playwright suite, and the deployed
  box.
