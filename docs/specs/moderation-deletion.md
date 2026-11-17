# Spec MD1 — moderation and account deletion

**Status:** ruled 2026-11-16 (§8), and built on branch
`feat/moderation-deletion` with the changes of §9.
**Phase:** before the first public day. The boards show usernames,
descriptions, and avatars to each player, and today the operator's one
tool is to revoke the full account.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I4, I7), §10, §11.
**Input:** spec A1 (the account page), spec A2 (sign-up and the name
claims), spec R1 (the public database and the anonymous identifiers).

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §8 says so and records
the ruling. Do not implement an open decision without agreement.

---

## 1. Purpose

1. **Moderation.** The operator changes or clears a player's description,
   and replaces or removes a player's avatar, with no revoke.
2. **Account deletion.** A player, or the operator, deletes an account.
   The account and its credentials go, the username can not be used
   again, and the earlier responses stay with an anonymous identifier.

## 2. What stands today, with evidence

- **The account.** `store/accounts/<player>.json` holds the description
  and the avatar digest, and the avatar bytes sit adjacent to it
  (spec A1). The player edits the two on the account page. The operator
  has no edit path.
- **The operator.** The console's player panel
  (`web/src/dev/player-account.tsx`) and `service.players` give sessions,
  a recovery code, sign-out, revoke, and `restore`, through
  `/api/dev/players/<name>/...`.
- **Revoke.** It sets the player status to `revoked`, removes the
  sessions, and makes the anonymous identifier (`revoke_player` in
  `service/players.py`). The account, the credentials, and the record
  stay, thus `restore` is possible.
- **Name claims are permanent.** `store/names/<folded>.json` holds one
  claim for each folded username, and spec A2 §4.3 says that a claim is
  not removed. A sign-up for a claimed shape refuses.
- **Raw records do not change.** Each stored send and trial row holds the
  player's store key, the username, and I4 forbids an edit of them.
- **The public database** shows each player with no active record by an
  anonymous identifier (spec R1 §8). A snapshot that is published stays
  as it is.

## 3. Moderation

- **Commands.** `service.players set-description --player P --text T`,
  `clear-description --player P`, `set-avatar --player P --file F`, and
  `clear-avatar --player P`.
- **The console.** The player panel gets an edit field for the
  description with `Save` and `Clear`, and an avatar control with
  `Replace` and `Remove`. They send:
  - `PUT /api/dev/players/<name>/description` with `{"description": T}`,
  - `PUT /api/dev/players/<name>/avatar` with the image bytes,
  - `DELETE /api/dev/players/<name>/avatar`.
- **The rules.** The text and the image get the same checks as the
  player's own edits: the 500-character cap, the 1 MiB cap, and the four
  image kinds of spec A1. The player's sessions and status do not
  change. Each edit writes one line to the operator journal with the
  player and the field, and with no text.
- The boards read the account at read time, thus an edit shows on the
  next read with no new board.

## 4. Account deletion

### 4.1 What goes and what stays

| Goes | Stays |
|---|---|
| the player record | each stored send and trial row (I4) |
| the account record and the avatar | each quarantine, start, and withhold record |
| the password digest and each recovery code | each consent record, which is the basis of the publication of earlier responses |
| each session and each device code | the name claim, which keeps the username from each new sign-up |
| | the anonymous identifier, made at the deletion if there is none |

- A deletion record goes in `store/deleted/<player>.json`: the player, the
  anonymous identifier, the time, and who deleted (`player` or
  `operator`). It is permanent. It holds no text that says why.
- A player from before spec A2 can have no name claim. The deletion
  writes one, thus the username is closed in each condition.
- The earlier password and each recovery code open nothing, because their
  digests are gone. A different player can select the same password for
  a different account (§8, D2).

### 4.2 What each reader shows

- **Boards and reveal pages.** A deleted player's rows stay, with the
  anonymous identifier as the name and no avatar (§8, D3). The scores and
  the statistics stay full.
- **The public database.** The anonymous identifier, as for a revoked
  player. A snapshot that is published before the deletion stays as it
  is, with the username in it. The deletion screens say so.
- **The private store and the results index** keep the raw records with
  the username, because I4 forbids an edit of them. No player surface
  reads the username of a deleted player.

### 4.3 The player's deletion

- The account page gets a `Delete my account` section. It says what goes,
  what stays, and that a published snapshot keeps the username.
- The player types their username and their password, and presses a red
  `Delete my account` button.
- `POST /api/account/delete` with `{"username": U, "password": P}`. The
  username must equal the caller's, and the password must agree, with the
  limit on incorrect sign-ins of spec A2. The server deletes the account,
  removes the cookie, and answers 200.
- An account with no password (from before spec A2) cannot delete by
  itself. The page says to set a password first, or to send the operator
  a message.

### 4.4 The operator's deletion

- **Step 1, the preview.** `service.players delete --player P` prints what
  goes and what stays: the days played, the send count, the sessions, and
  the anonymous identifier that the rows will show. It changes nothing.
  In the console, `Delete account` opens the same preview from
  `GET /api/dev/players/<name>/deletion`.
- **Step 2, the confirmation.** The operator types the full username. On
  the command line, `service.players delete --player P --confirm P`. In
  the console, a text field that must equal the username enables a red
  `Delete permanently` button, which sends
  `POST /api/dev/players/<name>/delete` with `{"confirm": P}`. A
  confirmation that does not equal the username refuses.
- A deleted player cannot be put back. `restore` refuses.

## 5. Integrity

- **I4.** No raw record changes. The deletion removes the account side
  alone.
- **I7.** Nothing here reads a score.
- **Sign-up.** The name claim stays, thus the username refuses at each
  new sign-up, with the cause of a taken name.

## 6. Testing

- **Moderation.** Each command and each console path changes the field,
  keeps the sessions and the status, refuses an image above the cap, and
  shows on the next board read.
- **Deletion.** After a deletion:
  - the player, account, avatar, credential, session, and device-code
    files are gone.
  - the sends, trial rows, consents, and the claim stay.
  - the deletion record and the identifier are there.
  - a sign-in with the earlier password refuses, and a sign-up with the
    username refuses.
  - the boards and the reveal show the identifier and no avatar, and the
    public build shows the identifier.
- **The player path.** An incorrect password and an incorrect username
  refuse and delete nothing. A good `POST` deletes and removes the
  cookie.
- **The operator path.** The preview changes nothing. A confirmation that
  does not equal the username refuses. `restore` of a deleted player
  refuses.
- **Prose.** Vale on this spec and each docstring that the build writes.

## 7. Build items

1. **MD1.1.** This spec, Vale-clean.
2. **MD1.2.** The moderation commands, routes, and console controls.
3. **MD1.3.** The deletion in the store, the commands, the routes, and the
   anonymous name on each player surface.
4. **MD1.4.** The account page section and the console flow.

Each item is one commit, green and Vale-clean on the touched prose.

## 8. Decisions, ruled 2026-11-16

- **D1 — who deletes.** The player from the account page, and the
  operator.
- **D2 — the password.** The earlier password does not sign in again,
  because its digest is gone. Nobody keeps a record of passwords to
  refuse.
- **D3 — earlier responses.** They stay, with the anonymous identifier and
  no avatar, on each board, reveal page, and public snapshot.
- **D4 — the operator's confirmation.** A preview, then the full
  username typed, then a red button. No hold.
- **D5 — moderation.** The operator changes or clears the description and
  replaces or removes the avatar, with no revoke.

## 9. Changes at build time

- **An incorrect password of the player.** §4.3 gives the limit on
  incorrect sign-ins. The server counts each failure with the counter of
  the other account moves, keyed by the account. An incorrect password
  answers 403 with the cause `password`, as the password change does. A
  401 tells the web app that the session ended, and the session stays
  live.
- **The identifier in the preview.** A player with no anonymous
  identifier gets one at the deletion, and the preview changes nothing,
  thus it says `a new anonymous identifier` for such a player.
- **What stays, in the preview,** includes each public snapshot that is
  published before the deletion, with the username in it.
- **`restore` of a deleted account** refuses with its own message, and
  not with the error of a missing record.
- **The journal.** Each operator edit and each deletion writes one line
  with the player and the field, and with no text. The lines go to the
  journal with the name `starvector.moderation`. The player's own
  deletion writes one line too.
- **The console.** After a deletion the roster drops the player and
  shows the identifier that the earlier results show. The red button
  style moves to the shared theme, because the account page uses it too.
