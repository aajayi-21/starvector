# Spec CR1 — close resilience: whitespace text, the blind run, and the automatic skip

**Status:** ruled 2026-11-16 (§10), built on branch
`feat/close-resilience`. §14 records the changes made at build time.
**Phase:** before sign-up opens and before the first public day. With
sign-up open, each account can send a crafted record, and one record that
does not score holds the close of the day for each player.
**Architecture sections:** §8 (Layer 0), §16 (Layer 8), §22 (protocol
integrity).
**Working agreement:** `CLAUDE.md` §2 (I1, I3, I4, I6, I7), §3 (errors),
§5 (the tiers), §6 (providers), §10, §11.
**Input:** spec PL1 §3.1, which proposed a quarantine and did not build
it, and spec VP1, which picks the target in the close.

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §10 says so and records
the ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

1. **Refuse whitespace text at the send.** A row of impressions or a group
   label that holds ASCII whitespace alone becomes a text atom today, and the
   encoder of the close receives it.
2. **Score each send with no target first.** The close runs Layers 0 to 6
   for each send before it picks or reads the target. A send that fails
   that run is known while no target exists.
3. **Skip a refused send by itself.** A send that the provider refuses on
   each fast retry gets a permanent quarantine record, and the close
   finishes the day without it. A guard keeps an outage from removing
   trials.

## 2. What stands today, with evidence

- **Whitespace text gets through.** `core/atoms.py` makes one DESCRIPTION atom
  from each `impressions` row with its text unchanged, and a group label
  of whitespace alone gives an atom with that text. Layer 0 refuses an
  empty string and nothing more. The send check of the server
  (`_checked_or_refusal` in `service/server.py`) asks only that one atom
  reads into a weighted channel. The web app trims the impressions and
  each label before the send, thus a player of the app cannot send one,
  and a crafted `POST` can.
- **One failure stops the close.** `close_day` in `service/day.py` scores
  each send in one loop. An error of one send stops the loop, the day
  stays in `closing`, and the day after it cannot open. The hourly timer
  tries again (spec PL1 §3), which repairs a fault that goes away and does
  not repair one that stays.
- **A batch hides the send.** `harness.prewarm_records` encodes the cold
  atoms of each send of the day in shared batches. A refusal of one batch
  does not say which send holds the input.
- **The provider refuses some inputs with no wait.** The OpenRouter client
  retries 408, 429, 500 and higher, and timeouts, and raises
  `OpenRouterRequestError` with no retry for each other 4xx status.
- **The target comes before the score.** With spec VP1 the close gets the
  pulse and records the pick before it scores. An operator who decides a
  skip after a failure can read the target and the trial rows that the
  close wrote before it stopped.

## 3. Whitespace text at the send

- The send check refuses a record with a row of impressions, or a group
  label,
  that holds ASCII whitespace alone. The set is the one that
  `core/atoms.py` pins for pasted text: space, tab, and the four line and
  page marks. The cause is `blank-text`, with status 400, and the message
  names the field.
- The check sits in `service/limits.py` with the record caps, before
  Layer 0. Layer 0 is in the tier that does not change (`CLAUDE.md` §5),
  and a stored record does not change.
- Practice reads the same check.

## 4. The close, step by step

1. **Wire and check**, as today. A vp1 day checks the time of its pulse
   before the move, as today.
2. **Move to `closing`**, as today.
3. **Read the sends.** A send with a quarantine record is not read again.
4. **The blind run.** For each send, `pipeline.score.fused_pool_scores`
   gives its fused pool scores, Layers 0 to 6, with no target. The batch
   step of `prewarm_records` runs first to fill the caches. When the batch
   raises, the close continues, because the run encodes each send alone
   and finds the send that holds the input.
5. **Fast retries.** A send that the provider refuses (§5) gets three more
   tries, after pauses of 30, 60, and 120 seconds. The provider client
   retries the passing faults by itself, thus these tries are for a
   refusal alone.
6. **The guard.** Count the sends that the provider refused after the
   fast retries. With that count at or below 10% of the day's sends, the
   close writes a quarantine record for each of them (§6) and continues.
   Above 10%, the close writes no record and stops with an error that
   names each refused player. The day stays in `closing`, the failure
   ping goes out, and the next firing tries again. Each error that is not
   a refusal stops the close with no wait, as today.
7. **The pick.** A vp1 day gets its pulse and records the pick after the
   guard, thus each quarantine decision is made while no target exists.
8. **Rank and write.** Layer 8 ranks the fused row of each send that the
   run kept, and the close writes the trial rows and the day-score file
   of spec AG1 from those rows alone.
9. **Move to `closed`.** The close answers the row count and the
   quarantine count.

A close that runs again on a day in `closing` honors each record and gives
equal rows for the other sends, as today.

## 5. What a refusal is

- **The protocol.** `providers/protocols.py` gets `InputRefused`, an
  error that a provider raises when the model server refuses one input
  and a wait does not change the answer. A refusal names
  the provider and the status, and holds no secret.
- **OpenRouter.** An encode `POST` that gets a 4xx status other than 408
  and 429 raises `InputRefused`. A batch `POST` with such a status raises
  it too, and the blind run then isolates the send.
- **The fake providers.** The fake text encoder refuses a text that
  starts with a fixed marker, for the tests.
- **The scoring path.** An `IntakeError` or a `NoActiveChannels` of a
  stored send counts as a refusal of that send too. The send check
  refuses each of them at the send, thus at the close they mean that the
  configuration moved, and the send cannot score with the day's config.
- **Each other error is not a refusal.** A timeout after the retries of the
  client, a status of 500 or higher, an answer of an incorrect shape, or an
  error in the code stops the close, because a skip of such a send is a
  skip that an outage or a defect decided.

## 6. The quarantine record

- **Where.** `store/days/<day>/quarantine/<player>.json`, written one
  time with the atomic primitive of the store. It is a record of play and
  permanent (I4). The send stays in the store unchanged.
- **What.** The day, the player, the trial id, the SHA-256 digest of the
  stored send, the cause (`input-refused`), the error text of the last
  try, the try count, who decided (`close` or `operator`), an operator
  note or null, and the time.
- **No connection to a score.** The record is written before the pick of
  a vp1 day and reads no target on a `commit-v1` day, thus no skip can
  follow the outcome (I3, I6).
- **The operator path.** `service.day quarantine --date D --player P
  --note TEXT` writes a record with `decided_by: operator` for a day in
  `closing` that the guard held. The command runs the blind run on that
  one send first and refuses unless the provider refuses it, thus the
  operator cannot skip a send that scores. It is the path for a day where
  the guard holds the skip, for example a day of 5 sends where 1 is
  refused.
- **A repair.** `service.day rescore` gives a quarantined send a score
  when the fault is gone, in an adjacent row. The record stays, because
  it is history.

## 7. What the player sees

- **The reveal.** A quarantined send gets `trial: null` and
  `quarantined: true`, and the screen says `We couldn't score your send
  this day.` The operator note is not on the wire.
- **The history.** The day shows with no result and the words `Not
  scored`. It is not in the skill number, the hit number, or the evidence.
- **The streak.** It does not break: the streak counts the days with a
  stored send, and the send is stored.
- **The daily board.** No row for the player.

## 8. The operator and the data

- **The close answer.** `POST /api/day/close` answers `trial_rows` and
  `quarantined`.
- **The status.** `service.day status` and the console's Days tab show
  the quarantine count of each day.
- **The results index.** A `quarantined` table with one row for each
  record.
- **The public database.** `submissions` gets a `quarantined` column. A
  quarantined send is in the file as a response, with no trial row, in
  the manner of a withheld response's scores. The schema version moves
  by one.

## 9. Integrity

- **I1.** The blind run reads no target. The pick of a vp1 day comes
  after each quarantine decision.
- **I3 and I6.** A skip removes a full trial before Layer 8, by a rule
  that reads no outcome. It filters no image, thus the target and the
  decoys keep one path.
- **I4.** The send and the record are permanent, and a rescore can score
  the send again.
- **I7.** The player reads the result of a quarantine at the reveal, as
  each result.
- **Spec VP1.** The skip is decided before the pulse is fetched, thus a
  vp1 day decides it with no target in existence.

## 10. Decisions, ruled 2026-11-16

- **D1 — what starts a skip.** The owner ruled an automatic skip (§4 steps
  5 and 6), and not an operator command alone. The operator command of §6 stays
  for a day where the guard holds the skip.
- **D2 — the streak.** A quarantined day does not break the streak.
- **D3 — the blind run.** The close scores each send with no target
  first, and a skip is allowed only for a send that fails that run.
- **D4 — the player's words.** The fixed message of §7 alone. The
  operator note stays in the record.
- **D5 — the tries.** One close, with fast retries. The owner asked for
  some retries in a time of minutes. Three more tries after 30, 60, and 120
  seconds read that ruling, about three and a half minutes in all, and
  the values are in one module.
- **D6 — the guard.** Refusals of one send alone, and at most 10% of the
  day's sends. Above that, the close holds the day and alerts.

## 11. Testing

- **The send check.** An impressions row of spaces, a label of a tab, and a
  label of an empty string: the first two refuse with `blank-text`, and
  the third keeps the behavior of today.
- **The blind run.** A send with the refusal marker and 20 good sends:
  the close retries it three times with the pauses as a seam, writes one
  record, and closes the day with 20 rows. A vp1 day gets its pulse after
  the record.
- **The guard.** 3 refused sends of 20: the close writes no record and
  stops, the day stays in `closing`, and the error names the three. A
  timeout or a status of 500 stops the close with no wait with no record.
- **A batch refusal.** The batch step raises and the run finds the one
  send.
- **The operator path.** The command refuses a send that scores, and
  writes a record for a send that the provider refuses.
- **The wire.** The reveal, the history, the streak, the close answer,
  the index, and the public database of §7 and §8.
- **Integrity.** The record of a vp1 day exists before the pick. The I1
  test stays green.
- **Prose.** Vale on this spec and each docstring that the build writes.

## 12. Build items

1. **CR1.1.** This spec, Vale-clean.
2. **CR1.2.** The check of whitespace text and its tests.
3. **CR1.3.** `InputRefused` in the protocols, the OpenRouter and fake
   providers.
4. **CR1.4.** The blind run, the fast retries, the guard, the record,
   and the operator command.
5. **CR1.5.** The reveal, the history, the close answer, the status, the
   index, and the public column.
6. **CR1.6.** The screens of §7.

Each item is one commit, green and Vale-clean on the touched prose.

## 13. Out of scope, with causes

- **Other content that a provider can refuse.** No other refusal is known
  today. §5 handles each refusal of one send, whatever its cause.
- **A shorter hold on an outage.** The next day waits while the close
  holds an outage day. The hourly firing and the failure ping of spec PL1
  stay the repair.

## 14. Changes at build time

- **Which statuses are a refusal.** §5 said each 4xx status other than
  408 and 429. A 401, 402, 403, or 404 names a key, a balance, or a model
  that is missing, which is the setup and not the input, thus OpenRouter
  raises `InputRefused` for 400, 413, and 422 alone, in the answer and in
  an error body. The other statuses stop the close as before.
- **The batch step.** The close continues when the batch step raises
  `InputRefused` or an `IntakeError`, and the run of each send finds the
  send. Each other error of the batch stops the close with no wait,
  before a retry.
- **The words of the screens.** The reveal adds one sentence to the fixed
  message of §7: the day is not part of the results, and the streak
  stands. An empty history notes the day in one line. The console
  shows the count in the message of a close and in the day picker.
- **The wire.** The history answer holds the days with no score in the
  `not_scored` field, and the reveal answer holds `quarantined` for each
  caller. The results index and the public database move to schema 4.

