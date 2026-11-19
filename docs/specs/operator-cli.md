# Spec OC1 — the operator command line

**Status:** ruled 2026-11-19 (§11), and built on branch
`feat/operator-cli` with the changes of §12.
**Phase:** before the first public day. The operator's tools are a browser
console that needs a second server and an SSH tunnel, and a set of module
commands that do not cover the console.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I7), §3, §10, §11.
**Input:** spec S1 (the day lifecycle), spec S2 (the dev surfaces), spec M1
(the operator token), spec BR1 (the console and the rollover), spec PL1,
spec A2 (the operator's recovery code), spec MD1 (moderation and
deletion), spec CR1 (the quarantine), spec VP1 (the pick after the close),
spec R1 (the results database).

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §11 says so and records
the ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

1. **One command.** The operator signs in to the server computer with SSH
   and types `sudo sv <group> <command>`. That one command does each
   thing that the console does, and each thing that the module commands
   do.
2. **The same rules.** The console shows a question before a change that
   cannot be put back, and it hides the target of a day that is not
   revealed. The command gives the same question and hides the same
   target.
3. **A record.** Each command that changes the store writes who did it,
   when, and what came of it.

## 2. What stands today, with evidence

- **Two servers.** The public unit (`deploy/starvector.service`, port
  8000) starts with no `--dev`. The operator paths in it are
  `POST /api/day/open`, `POST /api/day/close`, `POST /api/day/reveal`, and
  `GET /api/ops/trials`. Each `/api/dev/*` path is in the dev unit alone
  (`deploy/starvector-dev.service`, port 8001), which the operator starts
  by hand and opens through an SSH tunnel.
- **Module commands.** `service.players`, `service.day`,
  `service.rollover`, `service.index`, `service.public`, `service.rollup`,
  and `service.pool_keys` each have a `main`. They read and write the
  store in the process of the command. `service.rollover` alone sends the
  day moves to the server, with the bearer token.
- **Ten console functions have no command.** They are: the pause of the
  automatic days, the full view of a day with its sends, the history of a
  player, the view of a stored send, the score and rank of a send, the
  photo of the target, the full view of an account, the sign-out of one
  device, the read-only query, and the status of the results index.
- **The browser holds the rules.** Each question before a change is in the
  web app (`web/src/dev/controls.tsx`, `days-tab.tsx`,
  `player-account.tsx`, `schedule-tab.tsx`). The server asks for a typed
  username at a deletion and for nothing more. The server gives
  `target_id` on `GET /api/dev`, `/api/dev/days`, `/api/dev/day`, and
  `/api/dev/history`, and the web app does not show it until the operator
  opens the row.
- **The token.** `STARVECTOR_OPERATOR_TOKEN` is in `/etc/starvector/env`,
  which `root` alone can read. The same file holds the provider key and
  the password pepper.
- **File owners.** Each store write makes a file that its writer alone can
  read. A command that `root` or the SSH user starts thus writes records
  that the server, as the user `starvector`, cannot read.
- **Records of operator changes.** The rollover writes a record of each
  move in `store/rollover/runs/`. Spec MD1 §9 names a journal,
  `starvector.moderation`, for the moderation edits. Only the console
  paths write to it, no handler is set for it, and `service.players`
  writes no line. No other operator change has a record.

## 3. The commands

The groups are `status`, `days`, `day`, `schedule`, `players`, `db`, and
`log`. Each command takes `--service-config`, `--json`, and `--yes`.

### 3.1 Commands that read

They work on the store in the process of the command. They write no journal
entry.

| Command | Shows | Console path that it covers |
|---|---|---|
| `sv status` | the latest day, the schedule, the player counts, and if the public server answers | none |
| `sv days` | each stored day with its code, status, and send count | `GET /api/dev/days`, `GET /api/dev` |
| `sv day show [DAY]` | the times of one day and each of its sends | `GET /api/dev/day` |
| `sv day send DAY PLAYER` | one stored send | `GET /api/dev/submission` |
| `sv schedule` | the rollover hour, the pause, the steps that are due, and the recent moves | `GET /api/dev/schedule` |
| `sv players list` | the roster | `GET /api/dev/players` |
| `sv players show NAME` | one account, its devices, and the times of a live operator code | `GET /api/dev/players/<name>` |
| `sv players history NAME` | the days of one player | `GET /api/dev/history` |
| `sv players avatar NAME --save PATH` | writes the avatar to a file | `GET /api/dev/players/<name>/avatar` |
| `sv db status` | the results index and its tables | `GET /api/dev/index` |
| `sv db verify` | if the index agrees with the store | `POST /api/dev/index/verify` |
| `sv db query` | the answer of one read-only `SELECT`, as text or CSV | `POST /api/dev/index/query` |
| `sv db trials` | the revealed trial rows | `GET /api/ops/trials` |
| `sv log` | the operator journal of §7 | none |

- `sv db query` reads the statement from an argument, from `--file`, or
  from the standard input. It uses `index.read_only_query`, thus the
  limits of spec BR1 §7.3 apply: 1,000 rows and 5 seconds.
- Each text that a player wrote goes through a function that changes each
  control character into a printable code. A terminal obeys such
  characters, and a browser does not.

### 3.2 Commands that change

Each one writes a journal entry (§7).

| Command | Does | Confirmation (§6) |
|---|---|---|
| `sv day open` | opens the day that is due | no, as in the console |
| `sv day close [DAY]` | closes a day and scores each send | yes |
| `sv day reveal [DAY]` | reveals a closed day | yes |
| `sv day quarantine DAY PLAYER --note` | the operator skip of spec CR1 §6 | yes |
| `sv schedule pause [--note]` and `resume` | stops and starts the automatic days | no |
| `sv schedule run` | does the steps that are due at this moment | yes |
| `sv players recovery-code NAME` | makes the operator's recovery code | yes |
| `sv players restore NAME` | makes a revoked account active, with a code | yes |
| `sv players revoke NAME` | revokes an account | yes |
| `sv players signout NAME [--session ID]` | ends each device, or one | yes for each device |
| `sv players describe NAME` | sets or clears the description | no |
| `sv players avatar-set NAME --file F`, `avatar-clear NAME` | replaces or removes the avatar | no |
| `sv players delete NAME` | the two steps of spec MD1 §4.4 | the typed username |
| `sv players prune`, `claim-names` | as the module commands | no |
| `sv db build` | builds the index again | no, it is a cache |

### 3.3 The target and the rank

- One pure function gives the answer for each output: does this output
  show the target of this day? Its inputs are the day status, the pick
  protocol, and the flag `--show-target`.
- With no flag, a day that is not revealed shows no `target_id` and no
  image credit, in text and in JSON.
- A `vp1` day before its close has no target (spec VP1 §3). The command
  says `no target until the close`, and it does not say that a photo is
  hidden (spec VP1 §8).
- `sv day target [DAY] [--save PATH]` prints the image identifier and the
  credit of a revealed day. `--save` writes the image to a new file that
  the operator alone can read. A terminal shows no image.
- `sv day rank DAY PLAYER` scores one stored send and prints the fused
  sequence with the target row marked, as `GET /api/dev/rankings` does.
- For a day that is `open` or `closing`, §11 D2 rules what `sv day rank`
  and `--show-target` do.

### 3.4 Commands that go to a module command

`sv day rescore`, `sv day migrate`, `sv day day-scores`, `sv db export`,
`sv public <command>`, `sv rollup assemble`, and `sv pool-keys make` give
their arguments to the `main` of the module, with no change. `--json`
refuses on these commands, because the module prints text.

### 3.5 Console path with no command

`POST /api/dev/players/<name>/device-code` answers the constant 404 in
each mode (spec A2 §10.1). The command has nothing for it.

## 4. The two paths of a command

- **The store path.** The player, schedule, and database commands use the
  functions that the console paths use: `service.players`,
  `service.console`, `service.index`, `access.prune`, and
  `store.write_rollover_control`. The server reads the sessions, the
  player records, the accounts, and the pause from the disk at each
  `GET` and `POST`, thus a change by the command shows immediately. These
  commands work with the dev unit stopped.
- **The server path.** `sv day open`, `sv day close`, and `sv day reveal`
  send a `POST` to the public server on the loopback address, with the
  bearer token. The server thus is the one process that moves a day, and
  the close uses the scoring context that the server holds.
- **The loopback rule.** `--base-url` accepts a loopback host alone. The
  token does not go to a different computer.
- **The lock.** A day move gets the rollover lock of spec BR1 §7.2 with
  no wait. When a rollover holds the lock, the command stops with the
  exit code 2, as `service.rollover` does.
- **A named day.** The public server has no path that moves a day that is
  not the latest one. §11 D1 rules how `sv day close DAY` and
  `sv day reveal DAY` go to the server.
- **`sv schedule run`.** It uses `rollover.run_and_record` with the
  source `command-line`. §11 D6 rules the pause and the retries.
- **Two small moves of code.** The bodies of the day listing and of the
  player history move from `service/server.py` to `service/console.py`,
  thus the server and the command share them. `rollover.http_post` gets a
  companion that sends a JSON body.

## 5. The operator's identity

- **The start.** A script, `deploy/sv`, goes to `/usr/local/sbin/sv` with
  the owner `root`. The operator starts it with `sudo`. The permission to
  use `sudo` on the server computer is thus the operator's key, as the
  token is in the browser.
- **What the script does.** It refuses a caller that is not `root`. It
  reads `/etc/starvector/env`. It gives the command the operator token,
  the provider key, and the login name. It gives no other value of the
  file: the password pepper stays behind. It then becomes the user `starvector`
  with no procedure to get more rights, and starts
  `python -m service.operator_cli`.
- **No secret in an argument.** The token is not a command argument, and
  the command does not print it. An argument shows to each user of the
  computer.
- **The store owner.** The command refuses when the user that it has is
  not the owner of the store folder. Thus `root` and the SSH user cannot
  write a record that the server cannot read.
- **The login name.** The script reads the login identifier that the
  kernel keeps for the SSH sign-in, and uses `SUDO_USER` when there is
  none. The journal entry holds that name and where it came from. In
  development, with no script, the entry holds the name of the user of
  the process.
- **The limit.** A person who can become `starvector` can change the journal
  files. The backup of spec BR1 §8, which only adds, is the copy that
  such a person cannot change.

## 6. Confirmations

- A command with `yes` in §3.2 prints the question of the console, word
  for word where the words fit a terminal. It continues on the typed
  word `yes` alone.
- `--yes` gives the answer for a script.
- With no terminal on the standard input and no `--yes`, the command
  refuses before it changes a thing.
- **Deletion.** `sv players delete NAME` prints the preview and changes
  nothing. `sv players delete NAME --confirm NAME` deletes. `--yes` does
  not replace `--confirm` (spec MD1 §8, D4).
- **The recovery code.** The command prints the code one time, to a
  terminal. It checks for the terminal before it makes the code, because
  a new code replaces the earlier one and starts the notice on each
  device (spec A2 §6.1). The question holds the text of the 24-hour hold.
  The code is not in the journal, not in an argument, and not in the
  environment. §11 D9 rules a code that goes to a pipe.
- **Exit codes.** 0 for done, 1 for a refusal or a failure, 2 for a lock
  that a rollover holds, and 3 for a change that completed with no end
  record (§7).

## 7. The operator journal

- **Where.** `store/operator-log/`, in the permanent store. §11 D3 rules
  the shape of the files.
- **Two records for each command.** A `start` record goes in before the
  change. When it cannot be written, the command refuses and changes
  nothing. An `end` record goes in after, with the outcome `done`,
  `refused`, or `failed`. A `start` with no `end` shows in `sv log` as an
  outcome that is not recorded.
- **The fields.** The journal version, an identifier that the two records
  share, the phase, the time, the login name and its source, the command,
  the player, the day, the outcome, a small set of machine facts (the
  steps of a move, the count of trial rows, the count of ended sessions,
  the name of the changed field, the pause value, the exit code), and
  the type of an error.
- **What the journal does not hold.** A recovery code. The token. The text of
  a description. The note of a pause or of a quarantine. A query. The
  message of an error, because a provider refusal can hold the words of
  a send.
- **A deleted player.** The journal keeps the username of a deleted player,
  as the name claim does (spec MD1 §4.1).
- **A read that goes in the journal.** `--show-target` on a day that is not
  revealed writes an entry, because it ends a blind view of that day.
- `sv log` filters by time, player, day, and command.
- With this journal the command line obeys the sentence of spec MD1 §3:
  each moderation edit writes one line with the player and the field,
  and with no text.

## 8. Integrity

- **I1.** No code upstream of `core/ranking.py` changes. The command adds
  no target identifier to a scoring function.
- **I4.** The journal is a permanent record, and no raw record changes.
- **I7 and spec S1 R3.** Spec S1 says that no surface shows score
  information while a day is open, and it names the terminal. The
  console's rank of an open day is a `--dev` procedure with a second
  question (spec PL1 §8). §11 D2 rules if the terminal gets it.
- **Spec VP1.** No target is stored before the close, and the server
  refuses a close of a `vp1` day before its scheduled time. The command sends the move and
  prints the server's refusal.
- **Spec CR1.** `sv day quarantine` keeps the rule of §6 there: the blind
  score of that one send comes first, and the command refuses a send that
  scores.
- **Spec A2 §6.1.** The operator code keeps its own slot, the hold of 24
  hours, and the notice. A revoked player gets no code. The command is
  not a second procedure into an account.
- **Spec BR1 §7.3.** The query stays read-only in three layers, with its
  limits.
- **Spec M1 §4.** The server compares the bearer in constant time, as
  today. The command adds no path with a different gate.

## 9. Testing

- **The pure functions.** Each one with fixed inputs: the target answer
  for each pair of status and protocol, the text of each question, the
  loopback check, the login name, and the change of control characters.
- **The commands.** `main` on a fixture store, with the output captured.
  The server commands use a test client of the app as the sender, as
  `tests/service/test_rollover.py` does.
- **Each refusal.** A user that is not the store owner. No terminal and
  no `--yes`. A confirmation of a deletion that does not agree. A code
  for a revoked player. A lock that a rollover holds. A server that does
  not answer. A bearer that the server refuses. A base address that is
  not loopback. A code that goes to a pipe. The target of a day that is
  not revealed. A close of a `vp1` day before its scheduled time.
- **The journal.** One test for each command of §3.2 reads its `start` and
  `end` records. One test puts a marker text in a description, a note,
  and a send. It makes sure that no journal file holds the marker or a
  printed code.
- **Parity.** A test reads the paths of the app in dev mode. It does not
  succeed when an operator path has no command and is not in §3.5.
- **The script.** A test reads `deploy/sv` and makes sure that it does
  not give the pepper to the command.
- **Prose.** Vale on this spec, and on each comment and docstring that
  the build writes.

## 10. Build items

1. **OC1.1.** This spec, Vale-clean.
2. **OC1.2.** The operator journal in `service/store.py`.
3. **OC1.3.** The pure modules: `service/operator_plan.py` and
   `service/operator_view.py`.
4. **OC1.4.** `service/operator_cli.py` with the commands of §3.1, and the
   two moves of code of §4.
5. **OC1.5.** The player commands of §3.2.
6. **OC1.6.** The day and schedule commands, with the server change of
   §11 D1.
7. **OC1.7.** The target, the rank, the quarantine, and the commands of
   §3.4.
8. **OC1.8.** The parity test, `deploy/sv`, and the deployment documents.
   A dated note goes in spec BR1 §7, spec M1 §4, spec MD1 §3, and
   spec S1.
9. **OC1.9.** The changes at build time, in §12.

Each item is one commit, green and Vale-clean on the touched prose.

## 11. Decisions, ruled 2026-11-19

The owner accepted each proposal as it was written.

- **D1 — a named day on the public server.** Ruling:
  `POST /api/day/close` and `POST /api/day/reveal` accept a body
  `{"day": D}`, and an empty body moves the latest day as today. The
  paths do not change, thus the edge refuses them as before. This changes
  spec M1 §4, spec S2 §5, and spec BR1 §7.6.
- **D2 — the rank and the target of an open day.** Ruling: the terminal
  refuses the two, with no flag that changes it, because spec S1 R3 names
  the terminal. The console keeps its procedure.
- **D3 — the shape of the journal.** Ruling: one JSON record for each entry,
  written with `write_once_json`, as the rollover moves have. A record of that type cannot be
  cut by a power failure, and it adds no new lock. `sv log` prints one
  line for each command.
- **D4 — the console and the journal.** Ruling: the console paths write the
  same journal, as a build item after this spec. Then each operator change
  has a record, from each tool.
- **D5 — the name and the callers.** Ruling: the name `sv`, in
  `/usr/local/sbin`, and each user with `sudo` can use it. The package
  runit has a command with the same name, which is not on the server
  computer.
- **D6 — `sv schedule run` and the pause.** Ruling: it does not read
  the pause and it does not try again, as the console button of spec
  BR1 §7.2. Its question says so when the automatic days are paused.
  `service.rollover` stays the command of the timer, with the pause and
  the retries.
- **D7 — scoring in the command.** `sv day rank` and `sv day quarantine`
  make a scoring context in the process of the command, with the
  provider key. The server holds a second copy at the same time.
  Ruling: accept this for the two commands.
- **D8 — the module commands.** Ruling: they stay as they are, because
  the timer unit starts `service.rollover`. The documents send the
  operator to `sv`. A module command writes no journal entry.
- **D9 — a recovery code to a pipe.** Ruling: the command refuses,
  unless the flag `--code-to-pipe` is there.

## 12. Changes at build time

- **The facts of a journal entry.** §7 gives a small set of machine
  facts. In the store, each fact key has one shape: a count, a flag, a
  step name, a field name, or the hexadecimal digits of a session
  identifier. No fact is text, thus a recovery code in its groups of
  four fits in no fact.
- **A close and a reveal name their day each time.** The body holds the
  day of the question, also for the latest day. The server thus moves
  the day that the operator accepted, and not a newer day that a
  rollover opened in the time between.
- **The lock and the question.** A day move and `sv schedule run` look
  at the lock before the question, and stop with the exit code 2 when a
  rollover holds it. They get the lock after the answer, thus a person
  who reads the question does not stop the timer.
- **A change that stops before its question** writes no journal record:
  a player or a day that is not stored, a confirmation of a deletion
  that does not agree, a code to a pipe, a path of a new file that is
  in use. A change that the store or the server refuses after the
  `start` record has the outcome `refused`.
- **`sv schedule run` with no step due** refuses before the journal. The
  console writes a record for the same condition. A rollover that did
  not complete has the error type `rollover-failed`.
- **A `vp1` day before its pick.** `sv day target` prints
  `no target until the close` with the exit code 0, and `sv day rank`
  refuses with the same words.
- **`sv db verify`** has the exit code 1 when the index does not agree
  with the store, as `service.index verify` has.
- **More flags.** `sv day rank` takes `--show-target` and `--limit`.
  `sv db trials` takes `--from`, `--to`, and `--player`.
- **The store owner.** Each command checks the owner of the store
  folder, the commands that read and the commands of §3.4 also.
- **The start script.** It reads the two named lines of the env file as
  text and does not use the file as a script. It refuses an env file
  that `root` does not own or that a different user can read. It starts
  Python with `-E -s`, thus the caller's environment does not change
  how Python starts.
- **The output of a completed change** prints when the `end` record
  does not write (exit code 3). Thus the operator does not miss a new recovery code.
- **`--text-file`** drops one line end at the end of the file, because
  the store refuses a description that ends in a space character.
- **A player path below the day paths.** `POST /api/day/start` is the
  start report of a player (spec R1 §4). The parity test of §9 names it
  with the paths that have no command.
- **D4 is not built.** The console paths write no journal record. That
  is a build item after this spec.
