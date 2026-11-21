# Spec SS1 — send, then see

**Status:** ruled 2026-11-20 (§2 and §15). Build items SS1.1 to SS1.6
are on branch `feat/send-then-see`. The player page of §8 is a contract
here, and its build waits for the owner's decision on the gallery.
**Phase:** the days after the first production day.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I5, I7), §9, §10, §11.
**Input:** spec M1 §5, spec H1 §3 and §9, spec A1 §7 and §11, spec R1
§3, §7 and §9, spec BR1 §6.2, spec MD1 §4.2, spec A2 §9.5, spec S1 R2,
and spec VP1.

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §15 says so and records
the ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

The owner gave three instructions after the first production day. Each
one puts the sketch of a player in view of a second person before the
reveal of its day.

1. **The share of a sketch.** After the send, a player gets a JPEG of
   their own sketch and gives it to friends.
2. **The sends of the day.** The count of the sends of a day opens the
   sketches of that day.
3. **The player page.** Each player has a public page, at an address
   that the player can give to friends. It holds the sketches of that
   player.

## 2. The rulings of 2026-11-20

| # | Question | Ruling |
|---|---|---|
| 1 | Who can see the sketch of a different player while its day is not revealed? | A player with a session and with their own send of that day in the store. Each other reader gets revealed days alone. |
| 2 | What does a second person get of a send? | The sketch alone: the points and the colors of the strokes. No words, no part labels, no relations, and no notes. A send with no stroke gets a `words only` mark. |
| 3 | Is the share of a sketch before the reveal permitted? | Yes. The player gets a JPEG of their own sketch after the send. |
| 4 | Does the count of the sends open the sends of the day? | Yes, with ruling 1. After the reveal, each player with a session can open them. |
| 5 | Is the player page public? | Yes, with no session. It holds revealed days alone for a reader with no session. Its screen waits for the owner's decision on the gallery. |

## 3. What stands today, with evidence

- **The rule of spec M1 §5.** `No answer says how many players have
  sent, or which.` Spec H1 §9 D5 permitted one anonymous total,
  `sends`, with the words `No name, no sequence of names, and no other
  field follows the sends.`
- **The test.** `test_no_open_day_answer_follows_the_other_players_sends`
  in `tests/service/test_protocol_integrity.py` compares two worlds. The
  bytes that a player gets must not follow the send of a second player.
- **The architecture.** §22 has a sentence on score information that
  ends with `nothing returned until the window closes`.
- **The notice.** Spec R1 §3.1 tells a player that the sketches are
  published `after each day closes`.
- **No path gives a second person a sketch.** `GET /api/submission`
  gives the caller's own record. The reveal screen shows the caller's
  own sketch. The public database holds the strokes of revealed days
  (spec R1 §6), and the operator publishes it by hand.
- **One send.** A second send for one day and one player is refused,
  and no code path edits a stored send (spec S1 R2).
- **No target during play.** With spec VP1 a public random number picks
  the target after the close. A sketch of an open day holds nothing of
  the target.

## 4. The rule: send, then see

A player sees the sketches of a day in play after their own send is in
the store. One send for each day is the rule, thus a player who sees a
sketch has no send to change.

| The reader | The day is not revealed | The day is revealed |
|---|---|---|
| no session | nothing | the player page alone (§8) |
| a session, and no send of that day in the store | nothing | the sends of the day |
| a session, and a send of that day in the store | the sends of the day | the sends of the day |

**I7 holds.** I7 forbids score feedback before the window closes, and
an answer that follows the target. A sketch is not a score. No answer
of this spec reads a target, a trial row, or a pick. A reader with no
send in the store gets the same bytes of an open day for each set of
sends. The `sends` total is the one difference.

**What changes.** A player with a send in the store learns which
players sent, and sees their sketches. Spec M1 §5 called that
`score-adjacent` because it says who is in contention. The owner
accepts it for a player with a send in the store. §12 gives the
remaining risk.

## 5. The sketch alone

- `service/sketches.py` holds one pure function, `sketch_of`. It gets a
  stored wire record and gives the strokes, each with its `points` and
  its `color` when the stroke has one. It gives no other key.
- The function drops `group_id`. A group identifier is text of the
  client.
- Each answer of §7 and §8 builds its sketches with this function. A
  test fails when a text field of a record is in an answer (§13).
- A send with no stroke has the `state` value `words-only` and no
  strokes. The value is a fact for a screen. It is not a branch of
  scoring code, thus I5 does not change.

## 6. The share of a sketch

- The sent view of the Play screen has a control, `Share your sketch`.
  The home screen of a player with a send of the day has it too.
- It makes one JPEG, 1080 by 1350 pixels, on the device of the player.
  The image holds the sketch, the name `Starvector`, the name of the
  day, the username, the host of the site, and one sentence that says
  when the photo is picked.
- The image holds no score, no code, no word of the send, and no
  target. No target is there to show.
- The strokes come from the record that the device kept at the send. A
  different device reads `GET /api/submission`. No `POST` and no new
  server path is in it.
- A send with no stroke gets no control.
- The share sheet of the browser gets the file where the browser can
  share a file, and each other browser saves it. This is the procedure
  of the result image of spec BR1 §6.2.
- The code is in `web/src/share/` and `web/src/ui/share-button.tsx`.

## 7. The sends of the day

### 7.1 The path

`GET /api/sends?day=<day>&before=<position>`. The two parameters are
optional. With no `day`, the path reads the latest day.

The handler does these steps in this sequence:

1. It reads the session. With no session the answer is the constant 401
   of each player path.
2. It reads the day. A day that is not in the store gets the constant
   404 `{"detail":"sends not shown"}`.
3. A day that is not revealed needs the send of the caller: one check
   that the caller's own file is there. With no such file the answer is
   the same constant 404.
4. It reads `before`. Text that is not a position gets 400
   `{"cause":"bad-cursor"}`.
5. It makes the page.

Steps 1 to 3 read the session, the day record, and the caller's own
file. They read no file of a second player. The refusal is one constant
and the work is the same, thus the refusal says nothing of the sends.

### 7.2 The answer

```
day            the day
total          the number of sends of the day
next_before    the position for the subsequent page, or null
entries        the sends of this page
```

Each entry:

```
player         the board label of the player (spec MD1 §4.2)
named          false for an anonymous identifier
avatar_hash    the avatar digest, or null
state          sketch, words-only, withheld, or after-reveal
strokes        the sketch of §5, empty when the state is not sketch
```

- **The sequence.** The newest send comes first, by the stored
  `received_at`, then by `trial_id`. A position is the number of a send
  in the opposite sequence, from 0. The sequence does not follow the
  names, thus the position of an anonymous identifier says nothing of
  the username that it replaced.
- **The page.** A page has no more than `PAGE_ENTRY_CAP` entries (§15)
  and no more than `POINT_CAP` points (the cap of one send in
  `service/limits.py`). The first entry of a page is always in it.
- **Each send is there.** The floor of the ranked boards (spec A2 §9.5)
  does not apply. The owner asked for each send, and this answer has no
  rank.
- **No cache.** The answer has `Cache-Control: private, no-store`.
- **The cost.** The server keeps the sequence of each day in memory and
  reads the new files alone. A page reads the records of its own
  entries.

### 7.3 The screen

- The text of the count on the home screen and on the Play screen is a
  control. It opens `/sends?day=<day>`. With zero sends it stays text.
- A player who has not sent sees the count and one sentence: `The
  sketches open after you send yours.` The screen sends no `GET` to the
  server in that condition.
- The screen is a plain grid of sketches, each with the avatar and the
  label of the player, and a `Show more` control. The gallery that the
  owner picks for the player page can replace the grid.

## 8. The player page

This section is a contract. The screen and the three paths are not
built in this phase.

- **The address.** `/u/<username>`, with no session.
- **The paths.** `GET /api/profile/<player>` gives the label, the
  avatar digest, the description, and the statistics.
  `GET /api/profile/<player>/sketches` gives the sketches of revealed
  days, the newest first, in pages. `GET /api/profile/<player>/avatar`
  gives the picture.
- **Revealed days alone.** The three paths read no day that is not
  revealed, thus they have the same bytes for each reader.
- **The day in play.** The page of a player shows the sketch of the day
  in play through the path of §7 and its rule.
- **One refusal.** One constant 404 answers a name with no account, a
  deleted player, a revoked player, and each pool with the `dev_only`
  flag (spec P1a R13).
- **Open decisions** for the phase that builds it: the statistics on
  the page, a floor for a reader with no session, and a limiter on the
  paths that are open with no session.

## 9. Moderation

- **A withheld send.** The operator withholds a send with the command
  of spec R1 §9, also on a day that is open. Each answer of this spec
  reads the withhold record at the time of the answer. The entry stays
  with the `state` value `withheld` and no strokes. A release shows the sketch
  again.
- **A deleted player.** The send stays, with the anonymous identifier
  and no avatar (spec MD1 D3). No answer holds the username.
- **A revoked player.** The entry has the label and the avatar that the
  boards show.
- **No journal line.** The withhold command writes no line to the
  operator journal today. It is a moderation step from this phase on.
  A journal line for it is an open item.

## 10. The notice, version 2

Version 1 said that the sketches are published after each day closes.
With rulings 1 and 5 that is not the full fact. The text of version 2:

> **Your sketches and results are public.** After you send, each
> player who sent that day can see your sketch. After each day closes,
> each person can see your username, score and sketches on your public
> page, and your words in an open database. Do not sketch or type
> anything private.

- The version number is 2 in `service/notice.py` and in
  `web/src/signin/notice.ts`. Version 2 also holds the player page,
  thus the build of §8 brings no third version.
- A player who agreed to version 1 gets the new text one time, and a
  send needs the agreement (spec R1 §3.2 and §3.3).
- **A send of version 1.** Version 1 told a player `after each day
  closes`. On a server that publishes, the send of a player who agreed
  to version 1 alone has the `state` value `after-reveal` and no
  strokes until the reveal of its day.
- The `Public data` section of the account screen says the two new
  facts.

## 11. Integrity

- **I7.** §4 gives the argument, and §13 has its tests.
- **R3.** Each new path joins the length walk and the pick-seed walk of
  `tests/service/test_protocol_integrity.py`.
- **I4 and spec SC1.** This spec adds no record class, no directory,
  and no field. The agreement to version 2 is a second file of the
  consent class. The sequence of a day in memory is a cache of stored
  sends.
- **Architecture §22.** The sentence on score information stands. A
  note there says that a sketch of a different player is not score
  information.

## 12. The remaining risk

What limits a copy of a sketch:

- One send for each account and each day.
- A sketch of a day in play holds nothing of the target, thus a copy has
  the same chance result as each other sketch: 0.5.
- The day-level test of spec AG1 §5 holds for each correlation of the
  players.

What does not limit it:

- A second account. It sends a sketch of no worth, sees the sends of
  the day, and the first account then sends a copy. The proof of work
  of spec PW1 is the one cost of a second account.
- The shared image of §6. It goes to persons who have not sent.
- If the ability that the game measures is there, a player who copies
  gets the result of a different player. The skill number of that
  player then does not measure that player.

No mitigation is built. Possible ones are a floor of played days before
a player sees the sends, the sends after the close alone, and an
offline check for sketches that are almost the same.

## 13. Testing

- **A reader with no send.** The two-world test keeps its body. Its
  paths get the new path, with and without the two parameters.
- **A reader with a send.** The sends of the day are in the answer, and
  each other path of the walk has the same bytes in the two worlds.
- **The refusal.** A caller with no session, a day that is not in the
  store, and a caller with no send get constant bytes. A send changes
  the answer from 404 to 200 with no cache between.
- **The sketch alone.** Sentinel text in each text field of a record
  (words, labels, group identifiers, relation names, notes) is in no
  answer.
- **Moderation.** A withheld send, a release, a deleted player, and a
  revoked player.
- **The notice.** A send of version 1 alone is `after-reveal` before the
  reveal and `sketch` after it.
- **The target.** The answer has the same length and the same bytes for
  each pick seed.
- **The store.** Each read of the new path writes no file, and the
  frozen store walk covers the path.
- **The page.** The caps, the cursor, and a bad cursor.
- **The web app.** The gate function, the grid, `Show more`, the states
  of an entry, and the share image.

## 14. Build items

- **SS1.1** This spec, and the dated notes in the specs of the input.
- **SS1.2** Notice version 2.
- **SS1.3** `service/sketches.py` and its tests.
- **SS1.4** `GET /api/sends`, the page constants, and the tests of §13.
- **SS1.5** The web API, the mock, the control, and the screen of §7.3.
- **SS1.6** The share of a sketch (§6).
- **SS1.7** The paths of §8. Not in this phase.
- **SS1.8** The player page screen. Not in this phase.

## 15. Decisions, ruled 2026-11-20

The owner accepted each proposal with the plan of this phase.

- **D1 — the sequence.** The newest send first.
- **D2 — `PAGE_ENTRY_CAP`.** 24 entries. The point bound comes from
  `POINT_CAP`, and no earlier spec gives a count of entries.
- **D3 — no floor on the sends of the day.** §7.2.
- **D4 — a send of version 1.** The `state` value `after-reveal`, §10.
- **D5 — a withheld send.** A mark and no strokes, as spec R1 §9 does.
- **D6 — a revoked player.** The board label.
- **D7 — the image.** 1080 by 1350 pixels, as the result image, and a
  JPEG quality of 0.92 in `web/src/share/share.ts`.
- **D8 — the word `profile`.** The prose says `player page`. The code
  paths of §8 keep the word.
- **D9 — architecture §22.** One dated note, §11.

## 16. Out of scope, with causes

- **Rivals.** The owner asked for ideas alone. The statistics function
  of §8 stays one function, thus a rivals path can use it.
- **The gallery.** The owner picks it from mock screens.
- **A report control for a sketch.** The operator withholds. No player
  control is asked for.
- **Words on the new surfaces.** Ruling 2.
