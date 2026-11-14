# Spec H1 — the home page: send count, streak marks, and the greeting

**Status:** values ruled 2026-11-13 (§9, D1 to D5), in build.
**Phase:** surface growth after spec A2 and spec R1. Three small pieces land
in the web app, and one field joins the day view. No scoring code moves and
no frozen tier moves.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I7), §3, §4, §7, §10.
**Input:** the owner asked for four additions. The fourth, a beacon that
verifies the daily pick, changes the day lifecycle and has its own spec.
It is not in this one.

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §9 says so and records the
ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

1. **The send count.** The home page shows how many players have sent
   today.
2. **Streak marks.** A long streak changes the ring of the avatar and the
   look of the username, where the public can see them.
3. **The greeting.** The home heading resolves out of noise, as the first
   sense of a target does for a viewer. An epigraph from a named source
   is below it.

## 2. What stands today, with evidence

- `GET /api/day` answers one stat for `submitted` and no count
  (`service/server.py`, `day_view`). Spec PL1 §4 made it a single stat
  because an open tab polls it.
- The streak is `_streak` in `service/server.py`. It counts the days in an
  unbroken run that ends on the newest revealed day, so the open day cannot
  enter it. `GET /api/me` and the rows of `GET /api/leaderboard` hold it.
  The rows of `GET /api/leaderboard/skill` and the reveal report do not.
- `AvatarCircle` (`web/src/ui/avatar.tsx`) draws each avatar. The nav, the
  account screen, the reveal report, and the board rows use it.
- The home heading is `greeting()` and the username, in
  `web/src/screens/home.tsx`. The browser clock picks the greeting.

## 3. The send count

- `GET /api/day` gains `sends`: the number of stored submissions for the
  latest day, in each status. It is an integer from zero.
- `store.count_submissions(store, day)` counts the files of the day's
  `submissions` folder that end in `.json` and not in `.tmp`. It does not
  sort and it builds no sequence of names. Practice trials are not in that
  folder, so they are not in the count.
- The count is a function of the stored sends alone. It holds no score and
  no target value. The number of sends does not change with the target.
  The integrity test of spec M1 B10 forbade each open-day byte that follows
  the sends of other players, so ruling D5 changes it in §9.
- **Cost.** One scan of a folder of about 1,000 files for each read. An
  open tab polls at an interval of 5 minutes, or 20 seconds near the close.
  The load test of spec PL1 §9 holds about 880 active players. §7 gives the
  measure of the scan at that dimension, and §8 records the result.
- The home hero card shows the count in each status:

  | Count | Text |
  |---|---|
  | 0 | `Be the first to send today` |
  | 1 | `1 player has sent today` |
  | 2 or more | `N players have sent today` |

  After the reveal, the same count reads as the total of the day. The text
  does not change, because the day label in the card names the day.
- The mock API of the web app gives a fixed `sends`, so the screens operate
  with no server.

## 4. Streak marks

### The tiers

The tier is a pure function of the streak in days. The cut points are in
`web/src/ui/streak.ts` and nowhere else.

| Streak | Tier | Avatar ring | Username |
|---|---|---|---|
| 0 to 2 | 0 | none | plain |
| 3 to 6 | 1 | solid ring in the accent color | plain |
| 7 to 29 | 2 | gradient ring with a slow pulse | accent color |
| 30 or more | 3 | gradient ring that turns slowly | gradient text with a slow shimmer |

### Where a mark shows

A mark shows where the wire holds the streak: the nav, the account
screen, and the rows of the daily board. The skill board and the reveal
report show no mark in this phase, because their rows hold no streak. §10
records the cause.

### Rules

- The avatar stays a circle of the same outer dimension. A wrapper draws the
  ring around it, so the layout of a row does not change between tiers.
- Each animation stops when `prefers-reduced-motion: reduce` is set. The tier continues to read: the ring and the color stay, and
  only the movement goes.
- The mark is not the only sign of the streak. The streak number stays
  in the nav badge and in the board column. A screen reader gets the text
  `N-day streak` adjacent to the username, in a visually hidden element.
- The streak is the value of `_streak`, so a mark changes at the reveal of a
  day and not at the send. This holds I7: the open day cannot enter the
  streak, so a mark says nothing of the trial of today.
- CSS draws the effect. No script operates for it, and a long board has no
  timer for each row.

## 5. The greeting

### The heading

- The `<h1>` keeps its text for assistive technology and for the
  document outline. The visual layer is a second element that is hidden
  from assistive technology.
- The screen picks one greeting from a small set when it opens and keeps it
  until the screen closes. The set is the time-of-day greeting of
  `greeting()`, `Welcome back`, and `Ready to view`. The username follows
  after a comma.
- The effect resolves each letter out of blur, a small offset, and low
  opacity, each at its own random delay. The total time is 1.4 seconds.
  When `prefers-reduced-motion: reduce` is set, the text shows with no
  delay.
- A random value for the effect comes from a generator that the component
  receives. The tests give a fixed one.

### The epigraph

- A `<figure>` below the heading holds one epigraph and its attribution. It
  picks a first epigraph when the screen opens, and it then changes to a
  different one at an interval of 12 seconds. It does not change while the
  tab is hidden, and it does not change when `prefers-reduced-motion: reduce`
  is set.
- The figure keeps a fixed minimum height of two lines, so a change does not
  move the page.
- A change fades in the epigraph with the same resolve effect as the
  heading.
- The epigraphs are in `web/src/screens/epigraphs.ts`: text, author or
  agency, work, and the source address. Each epigraph has a maximum of 25
  words.
- **Sources.** Each epigraph comes from a source in the public domain or
  from a work of the US government, with the wording checked against the
  source page. Section 9, ruling D3, records this, and it excludes
  Warhammer text. Games Workshop holds the copyright of that text.

## 6. Integrity

- **I7.** The send count says nothing of a score or the target. The streak
  mark is a function of revealed days and the records of the player, as
  `_streak` is today. The effect code reads no result of the open day.
- No code upstream of `core/ranking.py` changes. No target identifier enters
  a component.
- The epigraph data is in the repository, so no network connection loads it.

## 7. Testing

- **Server.** `count_submissions` on an empty day, on a day with a `.tmp`
  file, and on a day with three sends. `GET /api/day` holds `sends` for the
  open, closing, closed, and revealed status. A send adds one to the next
  read.
- **Scan cost.** A one-time measure of `count_submissions` on a folder of
  3,000 files. The number goes in §8 when the build ends.
- **Web unit.** `streakTier` at 0, 2, 3, 6, 7, 29, 30, and 365.
- **Web component.** The home card text for the counts 0, 1, and 2. The ring
  and the hidden text on the avatar for each tier. The heading holds the
  full greeting and username as text. The epigraph changes after 12 seconds
  with fake timers, does not change on a hidden tab, and does not change
  when the player sets reduced movement.
- **Prose.** Vale on this spec, and on each comment and docstring that the
  build writes.

## 8. Build items

1. **H1.1.** The spec, with a clean Vale result.
2. **H1.2.** `count_submissions`, the `sends` field, the type, the mock, the
   home text, and their tests.
3. **H1.3.** `streak.ts`, the ring and name components, the four use sites,
   and their tests.
4. **H1.4.** The greeting and epigraph components, the epigraph data, and
   their tests.

Each item is one commit, green and Vale-clean on the touched prose.

## 9. Decisions, ruled 2026-11-13

- **D1 — the tier cut points.** The owner ruled 3, 7, and 30 days. The
  three tiers of §4 follow.
- **D2 — low counts.** The owner ruled that the count always shows, with
  the text for zero in §3.
- **D3 — the epigraph sources.** The owner asked for epigraphs from named
  sources: declassified remote-viewing documents, and religion, philosophy,
  and mythology, with Warhammer as one example. This spec accepts the first
  two groups from works in the public domain or from the US government. It
  excludes Warhammer text, because a short epigraph copies a work that has a
  copyright, and the public site shows it. **The owner can overrule this.**
  The record then holds the correct words and a statement of the right to
  use them.
- **D5 — the live count and the M1 gate.** Spec M1 treated a count of sends
  as score-adjacent, and `test_no_open_day_answer_follows_the_other_players_sends`
  pinned each open-day byte. The owner ruled on 2026-11-13 that the day view
  can hold one anonymous total, `sends`. The change is narrow. The test
  removes that field from the two day views and compares the remaining
  bytes. It also checks that the total is one more in the first world.
  The paragraph of spec A1 §7 has the same change. No name, no sequence of
  names, and no other field follows the sends.
- **D4 — the timing numbers.** The 1.4 second effect and the 12 second
  change of epigraph are cosmetic values that this spec proposes. They are
  in one file of constants, so a change is one edit.

## 10. Out of scope, with causes

- **Marks on the skill board and the reveal report.** Their rows hold no
  streak. To add it, the server makes one `_streak` walk for each row of the
  skill board, which has all players. That cost needs its own measure, and
  the daily board, which is the public one, has the value.
- **A beacon for the daily pick.** It changes `pick_target`, the day record,
  and the public `days` table. It has its own spec, and it must land before
  the first public day.
- **A live count.** The count refreshes with the day query, so it can lag
  by 5 minutes. A live stream adds one connection for each open tab.
