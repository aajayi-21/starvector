# Spec A1 — the account page, the open door, the console roster, and the practice intake

**Status:** ruled 2026-08-21 (§10), in build.
**Phase:** surface growth after spec M1. Four pieces land across
the server and the two web apps. No scoring code moves and no
frozen tier moves.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I7), §5, §7, §10, §11.
**Input:** spec M1 is merged. The store holds player records, the
console mints invites, and the S2 surfaces are live.

This spec is written for implementation by an AI agent. Where a
value is not given by the architecture or an earlier spec, §10
says so and proposes a default. Do not implement an open decision
without agreement.

---

## 1. Purpose

Four asks land in one phase:

1. **The account page.** A player opens their own page from the
   avatar at the top right, puts a picture there, and writes a
   description of themselves.
2. **The open door.** On a development box a person opens an
   account or signs in with a name alone — no password, a test
   surface, off in production.
3. **The console roster.** From the dev console the operator
   clicks a player and reads that player's full history. The
   owner asked for a check first — §5 records the verdict: this
   is not built today.
4. **The practice intake.** The practice screen gains the typed
   inputs the daily screen has: impressions and labeled groups.

The four are surface work. The scoring path, the store's play
records, and the frozen tiers of `CLAUDE.md` §5 do not move.

## 2. What stands today, with evidence

- `GET /api/me` answers `player`, `display_name`, `streak`, and
  `reminder` (`service/server.py`). No picture and no description
  anywhere. The nav draws an initials circle from `display_name`
  (`web/src/ui/nav.tsx`), and the circle is not a control.
- Identity is the invite of spec M1 §4. The gate screen
  (`web/src/ui/invite-gate.tsx`) says an invite URL is the one
  procedure in, and there is no path a player can open alone.
- The dev endpoints read one player. `dev_submission` and
  `dev_rankings` read the configured `service_config.player`
  closure, and no roster endpoint exists. The console
  (`web/src/dev/app.tsx`) browses days, not players.
- The practice screen sends `serialize(doc, [], "")`
  (`web/src/screens/practice.tsx`): strokes alone, with no
  `impressions` input and no group card. The server validates the
  full record on `POST /api/practice/score` today, thus item 4 is
  frontend work alone.

## 3. The account page

### The account record

A new record class: `store/accounts/<player>.json`, with a strict
field set in the manner of the day record.

```
player          the store key, agrees with the file name
description     0 to 500 code points (see D1)
avatar_hash     sha256 hex of the stored avatar bytes, or null
updated_at      the time of the last write
```

**Why not `store/players/`.** `list_players` and `any_player` walk
that directory and read each `.json` name as a player. A second
file class there becomes a phantom player name that the strict
read then refuses. Account records get their own directory.

**The edit path.** Submissions and trial rows are one-write
files, and the day record has one guarded move. The account
record is a third class: player-owned and replaceable. The writer
lands a temporary sibling and claims the destination with
`os.replace`. That is atomic, thus a torn document cannot occur.
A missing account file is an ordinary answer that reads as the
empty account, not an error.

**I4.** The account record is a raw fact of play, not a cache
derivable from elsewhere. It lives in the store and rides each
backup.

**The description check.** The display-name discipline
(`check_display_name`) grows a sibling for long text: 0 to 500
code points (see D1), printable characters with the newline as
the one control character permitted, and no space or newline at
the start or the end.

### The avatar bytes

`store/accounts/<player>.avatar` holds the picture as received —
one file, no derivation. The media type comes from magic bytes
when the bytes are served, with the four kinds the server reads
today (`_mime_of`: PNG, JPEG, WebP, GIF). The byte cap is 1 MiB
(see D2). A new picture replaces the earlier file atomically. The
bytes land first and the record follows. A stop between the two
gives a stale `avatar_hash` — a cache key and not a claim — and
the next write heals it.

### The wire additions

The system of record is `service/server.py`. Types land in
`web/src/api/types.ts`.

- `GET /api/me` grows `description` (string, empty when unset)
  and `avatar_hash` (string or null). The caller's own account
  record joins the answer with one file read.
- `PUT /api/account` — body `{description}`. The description
  check guards the boundary, each refusal names `{cause,
  detail}`, and the answer echoes the stored value.
- `PUT /api/account/avatar` — the raw image bytes as the body.
  The server checks the cap and the magic bytes before a write,
  refuses everything else, and answers `{avatar_hash}`. `DELETE`
  on the same path removes the picture.
- `GET /api/avatar/{player}` — the stored bytes for each
  signed-in caller, media type from magic bytes. One constant 404
  covers a player with no picture and a name with no record — the
  answer says nothing about who is stored. Display names face
  each player on the boards today, and the avatar is the same
  class of fact. The pool path `/image/{image_id}` does not
  move — pool images keep their reveal gate. An `<img>` fetch
  works here because the session cookie rides the app's own
  fetches to the same site — no header wanted.
- The two board reads get `avatar_hash` on each row (D5 as
  ruled): joined at read time in the manner of the display name,
  one account read for each row, null with no picture.

Each new surface sits behind `_caller`, and the two writers write
for the resolved caller alone — no `player` parameter on the
player plane. The `Api` interface grows the grown `getMe`,
`putAccount`, `putAvatar`, `deleteAvatar`, and
`avatarUrl(player, hash)` — no screen holds a URL.

### The screen

- The nav's initials circle becomes a control that opens a new
  `/account` path, with an `aria-label` ("your account"). When
  the account holds a picture the circle shows it rather than the
  initials. The nav reads `avatar_hash` from the same `/api/me`
  query it holds today, and the image URL holds the hash as a
  cache-busting query value.
- The account screen: the picture with a file input and a remove
  control, the display name and the store key, the streak, and a
  description editor with one save control. The client downscales
  the picked image to 256 px on its longest side (see D2) on a
  canvas before the `PUT`, thus a phone photograph shrinks below
  the cap.
- The mock adapter (`web/src/api/mock.ts`) grows the same shapes
  with deterministic values, and the full-mock mode keeps working
  offline.

## 4. The open door

**What it is.** A development-only path that turns a typed name
into a signed-in session, for testing the multiplayer surfaces
without minting invites by hand. It is not an account system. No
password guards it, deliberately, and it is for test boxes alone.

**The gate.** The door serves only when the server has `--dev`
(the `dev_mode` flag). Without the flag the two paths answer the
constant 404 (`_DEV_OFF`), byte-equal with today's production
answers. Note the divergence from the `/api/dev/*` namespace:
those endpoints pair `dev_mode` with the operator bearer, and the
door is `dev_mode` alone — a player surface, not an operator
surface. The door thus lives at its own path, `/api/door`.

**The two endpoints.**

- `GET /api/door` → `{open: true}` when the door serves, the
  constant 404 when it does not. The gate screen probes this one
  time.
- `POST /api/door` — body `{player, display_name?}`.
  - No record stored with that name: the mint path of
    `service/players.py` writes the record, and the answer sets
    the session cookie with the new token.
  - An active record stored: the token turns (the `rotate` path)
    and the answer sets the cookie with the new token. Each other
    session of that player stops at its next read — the door
    trades sessions for passwordlessness, which is right for a
    test surface.
  - A revoked record: 409 `{cause: "revoked"}`. The door cannot
    put a revoked player back.

The name goes through `check_player_name` and the label through
`check_display_name` — the same boundary checks as the mint
endpoint.

**Consequences to hold in mind, written down.**

- Each person who reaches a `--dev` server can claim a name,
  also a name that has played. That is the point on a test box,
  and it is why the flag must not ride a deployment. The S2
  deploy files do not hold `--dev`, and nothing here changes
  them.
- The first door mint flips access control on (spec M1 ruling 7):
  `any_player` becomes `true`, and the next server start refuses
  without `STARVECTOR_OPERATOR_TOKEN` in the environment. The
  runbook (§12) records this.
- A door mint for the configured player name adopts that name's
  played history — the spec M1 §4 property, not a special path.

### The gate screen grows

`invite-gate.tsx` probes `GET /api/door` through the typed
client, mock included. With `{open: true}` the card grows a name
field, an optional display-name field, and one control:
`create or sign in`. A 200 sets the cookie, the client
invalidates the `me` query, and the shell renders signed in. With
the constant 404 the card keeps today's copy — invite only,
nothing to type.

## 5. The console roster and history

### The verdict

Checked against `service/server.py` and `web/src/dev/`: clicking
a player is not built today. `GET /api/dev/submission` and
`GET /api/dev/rankings` read the configured player closure with
no `player` parameter, no endpoint answers the roster, and the
console has no player element to click. The invite panel writes
players and cannot show them. This section adds the piece.

### The wire additions

Each endpoint below sits behind the standing dev gate —
`dev_mode` plus the operator bearer — and answers the constant
404 in the other conditions, byte-equal with today.

- `GET /api/dev/players` → `{players: [{player, display_name,
  status, created_at}]}`, ascending by name. With no record
  stored the roster holds one row for the configured player,
  which is the world of ruling 7.
- `GET /api/dev/history?player=` → `{player, days: [...]}`,
  newest first, one row for each stored day: `day`, `status`,
  `trial_code`, `target_id`, `submitted`, and `trial` (the stored
  row's `p`, `target_rank`, `decoy_count`, `beaten`, `tied`, or
  null before close). The dev plane reads open days too — that is
  what the plane is for, and the production answer stays 404.
- `GET /api/dev/submission?day=&player=` — the optional `player`
  falls back to the configured player, thus today's caller sees
  today's behavior. The same growth lands on
  `GET /api/dev/rankings`.

The `player` value goes through `check_player_name` before the
path arithmetic — the same rule that keeps the day query string
out of the path.

### The console growth

- A roster card joins the console, adjacent to the invite panel:
  one row for each player with name, label, status, and created
  time.
- Clicking a row opens the history view for that player: a table
  of each stored day with status, sent flag, `p`, and rank, from
  `GET /api/dev/history`.
- Clicking a day row in the history shows that player's stored
  submission through the standing `SubmissionView`, and the
  rankings action serves that player's record through the grown
  `GET /api/dev/rankings`.
- The day browser keeps its shape. The roster is a second axis,
  not a replacement.

## 6. The practice intake

The asked-for growth: typed `impressions` and labeled groups in
practice. The server accepts them today, thus each piece is in
`web/`.

- **Extract the intake cards.** The impressions card and the
  group card live inline in `screens/today.tsx`. They move to
  shared components (`web/src/intake/`), and the daily screen
  keeps its behavior byte-for-byte on the wire.
- **Add them to practice.** The practice screen gains the
  impressions card, the group card, the select mode, and the
  selection set — `SketchCanvas` holds the mode and selection
  props today. `serialize(doc, impressions, "")` picks up the
  typed rows, and groups ride the document as they do on the
  daily screen.
- **The score control.** Today it wants one stroke. It grows to
  the daily screen's rule: strokes or impressions — the mirror of
  the server's `no-scoreable-atom` refusal.
- **Nothing is stored.** Practice stays ephemeral: no draft
  autosave, no `localStorage`, and the session counter stays as
  it is. The screen's own copy says so today and keeps saying so.
- **Relations and notes stay out** this phase (see D4). The
  relation card wants the vocabulary from `GET /api/day`, which
  practice does not read today, and item 4 names impressions and
  groups.

## 7. Integrity

- **I7 and R3.** The new player surfaces are functions of the
  caller's own records alone. No answer holds a target, a score,
  or a count of other players' sends. Each new path joins the R3
  walk with constant refusals.
- **R4.** Account reads and writes cannot change with the open
  day's target. The two-world compare grows the new surfaces.
- **The store snapshot.** Read paths keep the store byte-equal.
  The two account writers are player-plane writes with the same
  atomic discipline as the other store writers.
- **Uploads at the boundary.** The avatar writer checks the cap
  and the magic bytes before a write, refuses everything else
  loudly, and stores the bytes as received — no image library
  joins the dependencies (D2 records the client-side downscale).
- **The door in production.** Without `--dev` the door's two
  paths answer the dev surfaces' constant 404, byte-equal with
  the body `/api/dev/days` gives in that world. A Python test
  pins the bytes and the on-world flow rides Playwright.
  (Amended at build time: the draft said "an unknown path",
  and the framework's own 404 body is a different constant.)

## 8. Build items

Each item lands green (`uv run pytest -q`, `tsc --noEmit`,
`biome ci`, `vitest`, Playwright where named) and Vale-clean
before the next starts.

- **A1 — the account store.** The record, the strict read, the
  atomic replace, the description check, the avatar bytes, and
  the two hazards above (the phantom player, the stale hash) as
  tests.
- **A2 — the account endpoints.** The grown `/api/me`,
  `PUT /api/account`, `PUT` and `DELETE /api/account/avatar`, and
  `GET /api/avatar/{player}`, with R3, R4, and snapshot tests.
- **A3 — the account screen.** The `/account` path, the nav
  circle as its control, the screen, the mock growth, and
  component tests.
- **A4 — the door.** The two endpoints, the gating, the mint and
  `rotate` paths, the revoked refusal, and the byte-equality test
  without `--dev`.
- **A5 — the gate growth.** The door check, the card, the
  sign-in flow, and a Playwright flow: door on, make a player,
  play.
- **A6 — the roster endpoints.** `/api/dev/players`,
  `/api/dev/history`, the `player` growth on submission and
  rankings, with gate tests.
- **A7 — the console growth.** The roster card, the history
  view, the drill-down, and the dev API client growth.
- **A8 — the practice intake.** The extraction, the two cards in
  practice, the score-control rule, and the grown Playwright
  practice flow: type impressions, group strokes, score, and
  read the report row for the typed text.

## 9. Testing

The standing disciplines hold: the R3 walk, the R4 two-world
property, the store snapshot, and the rescore byte equality
(spec S1 R8) — the last is untouched because nothing here
scores.

New pins:

- The account record writes and reads back equal, and a record
  with an unknown field refuses loudly.
- The avatar writer refuses bytes above the cap and bytes with
  unknown magic, in that sequence, before a write.
- The door without `--dev` answers bytes equal to the dev
  surfaces' constant 404.
- The door mint and the console mint write the same record
  shape.
- The extracted intake cards serialize byte-identically to the
  inline cards they replace (a fixture from the daily screen).
- Two players hold two account records, and each reads their own
  on `/api/me`.

## 10. Open decisions, ruled 2026-08-21

In the manner of spec S1 §14: each value below is not given by
the architecture, thus it waited for agreement before it landed
in code. **The owner ruled on 2026-08-21:** D1, D2, D3, and D4
land as proposed. D5 turned around — the boards hold avatars.

- **D1 — the description cap.** Proposed: 500 code points,
  printable plus the newline, no edge whitespace. The
  display-name rule at 32 is the precedent.
- **D2 — the avatar caps.** Proposed: 1 MiB on the wire, client
  downscale to 256 px on the longest side before the `PUT`. The
  four magic-byte kinds the server reads today are the accepted
  set.
- **D3 — display-name edits.** The account page shows the label
  and does not edit it this phase. The mint and the door set it.
  Moving it into `PUT /api/account` is one field and one guarded
  edit if the owner wants it.
- **D4 — relations and notes in practice.** Proposed: out this
  phase, for the §6 reasons. Saying yes pulls the relation
  vocabulary into the practice screen's reads.
- **D5 — avatars on the boards.** Proposed: the boards keep
  initials this phase. **The ruling turned it around:** the
  daily board rows and the skill board rows get `avatar_hash`,
  and the two board
  tables render the circle adjacent to the label, with the
  initials as the fallback when no picture is stored.

## 11. Out of scope, with reasons

- **A credential system.** Passwords, recovery, mail, and rate
  limits — the owner asked for a test surface alone, and spec M1
  ruling 1 keeps the record layout prepared for an open
  registration phase.
- **More avatar treatment.** No crop tool, no server-side
  resize, no content check — the client downscale and the
  magic-byte check are the full treatment this phase.
- **Account pages of other players.** The account page is the
  caller's own. A public page for other players is a decision
  for the owner, and it waits.
- **The reminder toggle.** It stays inert, as spec W1 §7
  recorded.

## 12. Runbook

Build sequence §8 on branch `feat/account-surfaces`, each commit
green and Vale-clean on touched prose.

On the dev box:

```
uv run python -m service.server --service-config configs/service/dev-wit.json --dev
```

The first door mint writes a player record, and from then on the
server start wants `STARVECTOR_OPERATOR_TOKEN` in the
environment (spec M1 §4). Set it before the first door use, and
paste it into the console for the roster and the day controls.

The owner's ruling on §10 closes the spec for build.
