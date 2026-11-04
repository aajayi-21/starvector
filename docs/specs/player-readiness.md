# Spec PL1 — player readiness

Status: built on `feat/player-readiness`, 2026-11-03. Four items wait on
owner rulings (section 10).

A code audit on 2026-11-03 found eight groups of defects. This spec
records what each repair does and each number it adds. It does not restate
the architecture: see `docs/ARCHITECTURE.md` for the layers and `CLAUDE.md`
section 2 for the invariants.

Nothing here touches Layer 0, Layer 1, the atom types, the element
schema, or a stored byte of a submission.

---

## 1. Limits

**Defect.** A `POST` had no byte limit before its handler read it, the
number of strokes and points had no limit, Layer 0 ran on the loop thread,
and practice scoring had no limit. One `POST` could stop the server for
each player, and practice could spend the provider quota that a close
needs.

| Limit | Value | Where | Why this value |
|---|---|---|---|
| Body bytes | 1 MiB | Caddy `request_body`, and `limits.BodyCap` | The stroke cap at about 40 bytes for a point fits, and so does the avatar cap of `store.py` |
| Body read time | 30 s | `limits.BodyCap` | A slow client holds no memory for longer |
| Strokes | 2,000 | `limits.record_caps_refusal` | Far above a sketch by hand |
| Points in a record | 20,000 | `limits.record_caps_refusal` | Measured: a worst-path zigzag costs 0.08 ms for each point in Layer 0, thus 1.6 s at most |
| Practice for each player | 30 scores in one hour | `limits.practice_limiter` | A person can practice and a script cannot spend the quota |
| Practice in total | 600 scores in one hour | `limits.practice_limiter` | The sum that protects the close at about 20 active players |

These values are mine and not from an earlier spec. Each one is a named
constant in `service/limits.py`, and the owner can move each one with one
edit.

**The caps sit at the server and not in `core/intake.py`.** Layer 0 is
frozen, and a stored submission must validate forever. A close and a
rescore read stored submissions with Layer 0 alone, thus a cap cannot
refuse a record that the store holds. The caps guard only the two paths
that accept new records.

The middleware `limits.BodyCap` reads the full body before the app runs,
and answers `413` with `{"cause":"body-too-large"}` above the cap. The
avatar path keeps its own stream check, with its own refusal and its own
cap. JSON parsing and Layer 0 run in a worker thread, thus a large body
costs the loop thread nothing. The write of a send runs there too, because
section 5 adds an fsync to it.

---

## 2. The stale tab

**Defect.** `POST /api/submission` named no day, and the server read
`store.latest_day`. A tab from yesterday thus put yesterday's sketch on
today's target, and spent today's only send.

The `POST` names its day in the query string:
`POST /api/submission?day=2026-11-03`.

| Condition | Answer |
|---|---|
| No day stored | `404`, the constant `_NO_DAY` body, as before |
| No `day` in the query | `400` with `{"cause":"day-required"}` |
| `day` is not the latest stored day | `409` with `{"cause":"day-moved","day":"<latest>"}` |
| `day` is the latest stored day | The earlier checks and the write |

The day is not in the stored record, thus the stored bytes do not change.
The acknowledgment adds `day`. The `day` value is compared with the latest
label and does not enter a path. The `409` body names a label that
`GET /api/day` gives each player, thus it says nothing about a target (I7).

The `day` is required and not optional, because an optional value keeps
the defect for each client that leaves it out. The cost is one reload for
a tab that holds an earlier bundle, and that tab sees a plain refusal.

---

## 3. Close resilience

**Defect.** The rollover stopped its retries after about 7.5 minutes, and
the timer fired one time a day. A failure thus left the day in `closing`
for 24 hours.

- `deploy/starvector-day.timer` fires each hour at minute 00, with
  `Persistent=true`. `plan_step` answers `wait` when nothing is due, thus
  a firing that is not at the close hour moves nothing. This supersedes
  the rule of spec BR1 section 3 that a box that was down does not catch
  up: the catch-up is safe because the rollover closes only a day that is
  due.
- A close hour with a minute other than 00 closes at the next firing
  after it. The guides say so.
- A firing with nothing due writes no run record. At 24 firings a day the
  records with no move can push each move out of the console's recent
  runs. A `Do what is due` press that finds nothing writes its record as
  before, because the operator reads for it.
- **The failure signal.** The health check URL gets a `/fail` ping on a
  failure, as before. `deploy/starvector-day-failed.service` is new, and
  `OnFailure=` starts it, thus a rollover that dies or times out before
  its own ping gets a signal too. Exit status 2, a second start that met
  the lock, is not a failure. The health check period changes from 25
  hours to 2 hours.

### 3.1 Quarantine: a proposal for the owner, not built

**Defect.** One submission that does not score stops the close for each
player (`service/day.py`, `close_day`). The hourly timer tries again, thus
a fault that goes away heals itself. A fault that stays holds the day in
`closing` until a person acts, and that person has no tool at this time
but an edit of the store.

Skipping a player's trial must be explicit and recorded, and a skip must
have no connection to a score. The proposal:

1. **The close names the player.** A scoring error names the player
   and the layer. This is a one-line change, and it gives the failure
   signal a useful message.
2. **The decision is an operator command.** `service.day quarantine
   --date D --player P --note TEXT` writes a permanent record at
   `store/days/D/quarantine/P.json`, with the player, the trial id, the
   submission digest, the error text, the note, and the time. The close
   does nothing by itself.
3. **The close honors only a record.** It skips each player with a
   record, and counts them in its answer. The submission file stays in
   the store forever (I4).
4. **The skip comes before Layer 8.** The command reads no target and no
   score, and accepts only a day in `closing`, thus nobody can quarantine
   a trial after seeing its result. That keeps the rule of I3 and I6: no
   filter that sees the outcome.
5. **The player reads it.** The reveal says `We could not score your send
   this day`, with the note. The history shows the day with no result,
   and no streak breaks. The index gets a `quarantined` table and the
   console a row.
6. **A repair is possible.** `service.day rescore` gives a quarantined
   submission a score when the fault is gone, and the row lands adjacent
   to the record. The record stays, because it is history.

**Questions for the owner**

- Is an operator command correct, or must a close quarantine by itself
  after a count of failures? I recommend the command: automatic skips can
  turn a provider outage into silent missing trials.
- Does a skipped day count against a streak? I recommend no.

---

## 4. Refresh

**Defect.** The frontend had no polling, thus the closing screen said
`check back` and nothing moved. A refetch across a rollover remounted the
workspace through `key={view.day}` and blanked a sketch that was not done.

- **Polling.** `web/src/api/day-query.ts` holds the one `["day"]` query.
  The interval is a pure function of the day view and the clock
  (`dayPollMs`):

  | Condition | Interval |
  |---|---|
  | `closing`, `closed`, or no day | 20 s |
  | `open`, at 5 minutes or less to the close, or after it | 20 s |
  | `open`, at more than 5 minutes to the close | 5 min |
  | `revealed` | 1 min |

  A hidden tab does not poll. When the day or status moves, the screens
  that read results refetch.
- **The draft.** The workspace is no longer keyed by day. It holds the day
  that its draft belongs to. When that day is no longer the current one,
  the sketch stays on the canvas and a notice offers `Keep it for today`
  or `Start clean`. Send and the canvas wait for that selection. A draft
  saved on an earlier day gets the same notice when the screen next opens,
  thus a player who closes the tab and comes back the next day keeps it
  too. The player makes this decision, because a sketch made for a different
  code must not move to a new target with no word from them.

---

## 5. Hardening

- **`POST /api/door`** goes through the same gate as the other dev
  surfaces, `dev_mode and _operator_ok`, because the dev unit shares the
  production store. A typed name was a sign-in as each player. A refused
  caller gets the constant 404. The name sign-in card has a field for the
  operator token. With no player record stored, ruling 7 of spec M1 keeps
  the door open for the first name.
- **Fsync.** `store.write_once_json` and the replacing write sync the file
  before the claim and the directory after it. A power cut thus leaves
  each stored record full or missing, and a torn file cannot stop a close.
- **Headers.** The Caddyfile sets `Strict-Transport-Security`,
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and a `Content-Security-Policy`. A Playwright test
  applies that policy to the built app and finds no violation: the app
  holds no inline script and no external source. Caddy is not installed on
  the build box, thus Caddy itself did not check the text. `caddy validate`
  is a deployment step.
- **Invite tokens in access records.** Caddy holds no `log` directive, thus
  it writes no access record. Uvicorn does, and a filter
  (`limits.RedactInvitePaths`) replaces the token in each `/join/` line.
- **Pool memory.** `open_day` takes a `wired` value in the manner of
  `close_day`, and `_day_move` gives it the resident context when one is
  there. A process that holds a resident context thus loads no second copy
  of the pool at open. With none there, the open continues to wire warm with
  no provider key (spec S1 R5), and frees that copy at its end. This and not
  mmap, because it changes no array and no load path, thus scores stay
  byte-equal with nothing to prove. The different process of `service.day
  open` does not change.
- **Invite expiry.** No code change. Invites have no end date and work
  again until `rotate`. The guides said `one-time invites`, which was
  incorrect, and they are corrected. The ruling is the owner's (section 10).

---

## 6. Load test

`tools/load.py` starts the server on a fake-provider world, and drives it
from a closed loop at rising concurrency, with a traffic mix that follows
one active player. Section 9 holds the method and the number.

---

## 7. Export

- **Scores for each channel.** `report.channel_scores: true` in a scoring config
  adds a `channel_scores` field to each trial row: for each active
  channel, the standardized score at the target and the trial score of
  that channel alone. The flag enters the config hash only when it is on,
  thus each existing hash, each stored row, and each rescore stays
  byte-equal (I4). No committed config sets it. The production configs
  of spec PP1 set it from their first day. The shell computes the values
  after Layer 8, and no player surface reads them.
- **The index** builds again at the end of each reveal. A build that stops
  writes to the journal and leaves the reveal as it is, and the next read
  builds it.
- **Schema 2.** `trial_atoms` gains `pinned`, and `trial_channels` is new.
  The file name holds the schema version, thus the file moves to
  `data/index/results-v2.sqlite`. A `results-v1.sqlite` from before is an
  unread cache, and you can delete it.
- **The console example** `Words that connected` counts pinned rows alone.
- **`/api/ops/trials`** adds `truncated` and `row_cap`. A caller that gets
  `truncated: true` continues with `from` set to the last day it read.
- **`docs/querying-results.md`** holds the schema, examples for
  `sqlite3 -readonly` with `json_each`, and DuckDB, and it states I6. A test
  runs each SQL example of the document against a built index, through
  Python's `sqlite3` module and DuckDB 2.0.0. The `sqlite3` command is not
  installed on the build box.

---

## 8. Interface

| Defect | Repair |
|---|---|
| One tap sent with no check | `Review and send` opens a panel with the words, the counts, and the notes, and then `Send today's session` |
| A typed word that was not added was left out | The panel offers it with a box, on by default. Practice adds it at the check |
| One stroke enabled Send and then refused | `/api/day` and `/api/practice` give `min_strokes`, and the button waits with a sentence that says why |
| The premise was not on a screen | `How it works` and the landing page give the question the game tests. The term `remote viewing` waits on section 10 |
| `1.00 is chance` adjacent to 50% | Each skill number also shows its average: skill `s` is an average result of `s / (s + 1)`, thus 1.00 is 50% |
| `theta` and `exp(shrunk)` were each called `skill` | The board column reads `Steadied skill`, and a sentence says why it differs from the plain number on the results page |
| `Evidence score` | `A fair bet against pure luck would have turned 1 point into X points` |
| `degrees of freedom` | `Variation test: score X, and luck alone gives about Y` |
| Three meanings of `rank` | A photo has a `place` in the set, a player has a `place` on the board and a `likely range`. The code keeps its field names |
| Practice had no draft | A draft saves on the device, and `Start over` clears it |
| The countdown gave no clock time | It adds the local time |
| The UTC label could read as tomorrow | The two `today` headers name the local close time. A label on an earlier day stays the UTC day |
| `on the right` on a phone | The copy names the section and no side |
| `Score and rank` showed the target at one tap on an open day | A second step says what it shows, in the day browser and the roster, and the button waits for a yes |

The mean of `s / (s + 1)` comes from the model of architecture section 17:
a trial score with skill `s` has the density `s p^(s-1)`. The display adds
no formula to Layer 9, and it computes on the client.

---

## 9. Load test results

**The number: about 880 active players** (877), at no error and a 95th
percentile at or below 500 ms. This replaces the estimate of `low hundreds`
from the audit. It comes from `uv run python -m tools.load`, on 2026-11-03,
and the record is `validation/records/load-2026-11-03.json`.

**Method.** One server process, as deployed. The world holds 3,000 players,
14 revealed days, and a fake-provider pool of 1,000 images, on a laptop with
8 CPUs. A closed loop steps through concurrency levels. Each client sends the
mix of one active player in the busiest 10 minutes of a day, which is 35 calls,
or 0.0583 for each second:

| What | Calls in the 10 minutes |
|---|---|
| Poll of `/api/day`, at 20 s near the close, and one app load | 31 |
| `/api/me` and `/api/history`, one app load | 2 |
| One send, with its fsync | 1 |
| One practice score | 1 |

A level passes with no error and a 95th percentile at or below 500 ms. The
capacity is the rate at the highest concurrency that passes, divided by
that 0.0583. The highest concurrency and not the highest rate, because
this server gives fewer answers each second as more calls wait:

| Clients | Calls/s | p50 ms | p95 ms | p99 ms | Errors | Result |
|---|---|---|---|---|---|---|
| 1 | 132.9 | 7.1 | 9.8 | 22.7 | 0 | in budget |
| 2 | 173.5 | 10.6 | 17.6 | 32.3 | 0 | in budget |
| 4 | 92.6 | 43.5 | 57.6 | 67.3 | 0 | in budget |
| 8 | 51.2 | 168.4 | 206.1 | 259.3 | 0 | in budget |
| 16 | 46.3 | 366.7 | 546.0 | 642.9 | 0 | above budget |

The test stored 130 sends. Their close took 2.8 s and the reveal 0.4 s, and
the peak resident memory of the server was 151 MiB.

**What the number leaves out.** A fake encoder costs no network time, and
this pool holds 1,000 images where spec PP1 holds 7,500, thus practice and
the close cost more on the deployed world. The rate falls from 2 clients to
8 because one Python process does the work of each thread, thus a faster CPU
helps and more CPUs do not. Do this test again on the deployed box before
a public date.

---

## 10. What waits on the owner

1. **Quarantine** (section 3.1): the operator command, or an automatic
   skip after a count of failures? Nothing is built until the ruling.
2. **Invite expiry** (section 5): do invites end, are they good for one
   use, or do they stay good until `rotate`? The guides give what the code
   does at this time.
3. **The words `remote viewing`** (section 8): does the copy use them? The
   copy says what the game tests and leaves the term out.
4. **The limit values** (section 1): are the six values satisfactory?
