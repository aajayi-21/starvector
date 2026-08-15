# Spec S2 — the backend contract phase

**Status:** ruled, prepared to build.
**Phase:** the backend phase spec W1 §7 promised. The server grows
the contract surfaces the frontend scaffolded, the deployment story
is settled, and the operator console is rebuilt in the new stack.
**Architecture sections:** §22 (integrity), §18 (latency), §15.
**Working agreement:** `CLAUDE.md` §2 (I4, I7), §5, §9, §10.
**Input:** spec W1's frontend is merged (`web/` on `main`). The
server runs FastAPI 0.141.1 with uvicorn 0.52.1 — no new Python
dependency is needed for this phase.

---

## 1. Purpose

The frontend consumes six surfaces through a typed seam that a
deterministic mock serves today. This phase makes them live,
resolves the serving story for a public host, and gives the
operator a console in the production stack. The frozen tiers do
not move: no stored artifact changes, each new surface is fully
read-only against the store, and the rescore byte equality
(spec S1 R8) holds untouched.

## 2. The rulings of 2026-08-14

1. **The host is a VPS. The deploy files stay provider-neutral.**
   The research passes (three, August 2026) hold the VPS above
   platform services and above a home server: the app
   runs ONE process with a resident scoring context, thus
   scale-to-zero economics buy nothing, and the permanent store
   wants a plain disk with an offsite backup. Named examples: a
   Hetzner CX23 (EU, 4 GB, about EUR 5.49) or a DigitalOcean
   basic droplet (US, 2 GiB, about USD 12). The deploy files are
   written for Ubuntu 24.04 with 2 GB or more and use no function
   that one provider alone has.
2. **No access control this phase — a recorded standing risk.**
   The server has none today: the player identity is the
   configured name, and the day lifecycle endpoints answer each
   caller. The owner ruled to ship without it for a short,
   unlisted window. Two facts are recorded: (a) a person who
   finds the address can send the day's submission and move the
   day lifecycle — the deployment's `Caddyfile` thus answers 404
   on the operator and dev paths at the proxy, and the operator
   reaches them through an SSH tunnel. (b) The sketched setup for
   a subsequent phase, from the research: an invite URL
   `/join/{token}` sets an `HttpOnly` cookie for the player
   plane, the operator plane takes a bearer token, and a
   configuration with no tokens behaves as today.
3. **`closes_at` comes from configuration, display only.** The
   day record's field set is frozen (the store refuses unknown
   fields), thus the countdown field can not enter it. The server
   config gains an optional `closes_at_utc` (`"HH:MM"`). The day
   view serves the computed timestamp for an open day and null
   when the day is not open or the time is not set. Closing stays
   the operator's manual action.
4. **The operator console is a second build entry, reached
   locally or through the tunnel.** `web/dev.html` builds with
   the player app, is not precached by the worker, and is
   answered 404 publicly by the proxy. The earlier page in
   `service/ui/` stays byte-untouched — its tests pin the page —
   and keeps serving with `--dev`.

   Amended 2026-08-14 (review): the console's read surfaces want
   `--dev`, and that flag also ungates `/image`, which the proxy
   serves publicly. The public process thus keeps the flag off,
   and a second unit (`deploy/starvector-dev.service`) carries it
   on `127.0.0.1:8001` when the operator wants the console. The
   proxy holds no path to that port. The two processes share the
   store, which the `write_once_json` records and the guarded
   status moves make safe.

## 3. The wire additions

The shapes are typed in `web/src/api/types.ts` and this section
does not restate them. The system of record for each handler is
`service/server.py`.

- **`closes_at` on `GET /api/day`** — always in the answer:
  `"{day}T{closes_at_utc}:00+00:00"` while the day is open and
  the config sets the time, else null. A pure function of the day
  string and the config — no target dependence.
- **`GET /api/reveal?day=`** — the same document as the latest-day
  shape, built by one shared builder. One constant `not revealed`
  refusal for an unknown, open, or closed-unrevealed day.
- **`GET /api/history`** — revealed days that hold the player's
  trial row, newest first, each projected to
  `{day, trial_code, p, target_rank, decoy_count}`, plus `skill`.
  The skill values are the `/history` page's numbers, computed
  with the same functions: `skill_summary` with `unbiased` at two
  or more trials, and `shrunk` as the exponent of
  `shrunk_log_theta` with the display constants
  `POPULATION_MEAN` and `POPULATION_SPREAD`. **`skill` is null in
  two defined conditions:** no revealed trial with a stored row,
  or each stored `p` equal to 1.0 (the aggregation's S statistic
  is zero there and the summary refuses) — a defined wire value,
  not a fallback.
- **`GET /api/submission?day=`** — the player's own stored record,
  projected to `{trial_id, record}`. The player name comes from
  the config alone. The endpoint takes no player parameter. One
  constant `no submission` refusal when nothing is stored. Served
  in each day status: the body is an echo of the player's own
  input and holds no target information and no score.
- **`GET /api/leaderboard?day=`** — revealed days alone, the
  constant `not revealed` refusal for the remainder. `rows` holds
  the one configured player's row from the stored trial row —
  with `streak` — or stays empty when the player has no row. The
  mock's invented cast stays a full-mock display. The live
  endpoint reports the truth.
- **`GET /api/me`** — `{player, streak, reminder, public}` with
  the two flags `false` (no storage behind them at this time).
- **Streak, defined:** the count of calendar days in an unbroken
  run that ends on the newest revealed day, with the player's
  stored submission on each day of the run. Zero when no day is revealed or
  when the newest revealed day holds no submission. The open day
  can not enter the count — it lies after the run's last day. The
  mock at `web/src/api/mock.ts` computes the same definition and
  is the reference.
- **The `/history` page moves behind `--dev`.** The app owns the
  `/history` path (spec W1 §7 recorded the collision). Without
  the flag the page answers the constant dev refusal.

The refusal discipline holds for each new surface: one
module-level byte constant for each refusal, returned before store
reads that touch a target (R3), bytes a function of revealed days
alone (the R4 property), and no store write anywhere (the R8
snapshot guard).

## 4. Serving and deployment

The research verdict, recorded as the resolution of spec W1 §7's
"Serving" item: **the proxy serves the app. The Python process
serves the API and the images.**

- **Caddy** (2.11) terminates TLS with automatic certificates,
  serves `web/dist` as static files with the SPA fallback
  (`try_files {path} /index.html`), keeps `/assets/*` out of the
  fallback so a stale hashed asset answers 404 rather than HTML,
  and proxies `/api/*` and `/image/*` to uvicorn on
  `127.0.0.1:8000`. The refused set answers 404 at the proxy:
  `/dev.html`, `/api/dev/*`, and the three day lifecycle paths.
  `app.frontend()` and `StaticFiles` stay out of the build — the
  Python process serves no static app bytes in production.
- **One uvicorn process** as a systemd unit: the resident context
  must live in one process, thus no worker pool. The unit runs a
  dedicated user, `Restart=on-failure`, an `EnvironmentFile` with
  mode 0600 for `OPENROUTER_API_KEY`, and hardening
  (`ProtectSystem=strict` with the store and data roots as the
  only writable paths, `NoNewPrivileges`, `PrivateTmp`).
- **Firewall and updates:** UFW with 80/tcp, 443/tcp, 443/udp
  (HTTP/3), and SSH behind a connection limit. Automatic upgrades
  from the `security` source with the automatic reboot at 04:30 —
  out of the game window. The server rebuilds its resident
  context from the store on start, so a reboot costs seconds.
- **Backup:** a restic timer ships the store, the pool artifacts,
  and `/etc/starvector` to an offsite repository daily. The
  remote credential can not delete (an append-only shape), so a
  compromised box can not remove the game history. The store is
  the one irreplaceable artifact (I4). The remainder is
  rebuildable cache.
- **Spend cap:** the OpenRouter account carries a spend cap, so a
  leaked server key is bounded.

The files land in `deploy/`: `Caddyfile`, `starvector.service`,
`starvector-dev.service`, `restic-backup.service`,
`restic-backup.timer`, `env.example`, `restic-env.example`, and a
provider-neutral `README.md` runbook.

The proxy's refused set names each dev path in the two shapes a
Caddy matcher needs — `/api/dev` and `/api/dev/*` are two
patterns, and the bare one answers the day's target id. `/history`
is not refused: the app owns that path, and the server's page
answers 404 without the flag.

## 5. The operator console

A second build entry, `web/dev.html` with `web/src/dev/`, with the
earlier console's full function set on the existing dev wire
shapes verbatim:

- The day browser (newest first: day, code, status, sent flag)
  with the latest-day-only control rule: open when not open,
  close (with a confirmation — scoring runs) when open, reveal
  when closed.
- The status panel: trial code, day, status line, commitment.
- The blind-run target toggle: hidden by default, the image
  source set lazily on first show, the toggle condition and the
  source cleared on each day switch.
- The stored-submission viewer: received time, trial id, the SVG
  stroke replay (stroke color, else the group hue, else ink),
  impressions, groups and relations, pasted text.
- The rankings view: the trial line with `target_position` and
  the rank after the near-duplicate group exits. The atom report
  (five columns, 3/3/2 decimals). The full-pool table with
  position, thumbnail (lazy, hover zoom), the shortened image id,
  one column for each entry of `channel_names`, and `fused`. The
  target row is highlighted and always included in the top-25
  slice. A show-all control. The view loads itself for a closed
  or revealed day and offers the manual preview button while
  open.
- The help text and the `/history` URL.

Access: the entry is out of the worker's precache and out of the
SPA navigation fallback, the proxy answers 404 for it, and the
operator opens it through `pnpm dev` locally or through the SSH
tunnel against the VPS.

## 6. Build items

- **B1 — `closes_at`.** The optional config field with strict
  validation, the day-view field, the parse and serving tests.
- **B2 — the reveal builder.** `_reveal_value` extracted. The
  `?day=` shape. Refusal and byte-equality tests.
- **B3 — the four surfaces.** `_skill_value` and `_streak` pure
  helpers. `/api/history`, `/api/submission`, `/api/leaderboard`,
  `/api/me`. The `no submission` constant. Unit tests pinned
  against `core/aggregate` with no HTTP in between.
- **B4 — the page move.** `/history` behind the dev flag. The R3
  walk grows the new paths. The dev-404 set grows `/history`.
- **B5 — the frontend changeover.** The live adapter gains the
  five §7 methods, the composite serves the live side outright,
  the mock stays as the full-mock mode, the countdown lights up.
- **B6 — the operator console.** The `web/src/dev/` entry with
  component tests and the worker-precache assertion.
- **B7 — the deploy files.** §4's set, prose Vale-clean.
- **B8 — the e2e refresh.** The fixture server stores a played
  submission before the practice day closes and sets a close
  time. The history and reveal specs re-pin against live numbers.
  A countdown assertion.
- **B9 — the adversarial review.** The find-and-refute pattern on
  the branch. Confirmed findings close in one commit.

## 7. Testing

- Each new endpoint carries: the R3 walk membership (no target
  id, no secret, no score bytes while open or closed, and refusal
  constants byte-equal across statuses), the R4 two-world test
  (equal revealed history, different open targets, byte-equal
  answers — the open trial code is fixed through
  `open_day(trial_code=...)` so bodies compare raw), and the R8
  snapshot guard (the store is byte-equal around each GET).
- `_skill_value`: unit tests for the two null conditions and the
  single-trial biased variant.
- `_streak`: three days one after the other, a calendar hole, the
  empty store, and a newest revealed day with no submission.
- The frontend: the composite-dispatch rewrite, the countdown
  component test, the console component tests (control visibility
  by status, the close confirmation, the toggle clearing, the
  report decimals, the top-25-plus-target slice, self-load
  against preview).
- The suites stay green during the build: the Python suite, the
  web unit and component tests, and the Playwright flows offline.

## 8. Out of scope

- Access control (ruling 2 — the sketched setup waits for the
  owner's word), accounts, and correct multi-player leaderboard
  rows.
- Web Push sending (spec W1 §7 keeps it deferred).
- The production pool — the phase after this one.

## 9. The owner's full test runbook

Four layers, from fast to slow. The first two run with no network
and no key.

1. **The suites.**
   `uv run pytest -q` (the scoring engine and the server),
   `cd web && pnpm typecheck && pnpm lint && pnpm test` (the
   client), `pnpm exec playwright test` (the built app against a
   throwaway fixture server — it boots itself and needs no
   process started by hand).
2. **A full day by hand, offline.** Terminal one:
   `uv run python web/e2e/serve_fixture.py` (a fake-provider
   world on `127.0.0.1:8199` with one revealed practice day and
   one open day). Terminal two:
   `cd web && VITE_PROXY_TARGET=http://127.0.0.1:8199 pnpm dev`.
   Play the open day at `http://localhost:5173/`. Move the day
   with the operator console at `/dev.html` (close scores with
   fake providers, then reveal). Check the reveal report, the
   history screen, and practice.
3. **The live smoke, with the key.** Against the dev store on
   `:8000` (the owner runs commands that use the key): open a
   day from the console, play it from the app through
   `pnpm dev`'s proxy, close and reveal from the console. One
   day costs a handful of embedding posts.
4. **The deployment smoke, on the box.** After `deploy/README.md`:
   the site answers on HTTPS with the app. `curl` probes on
   `/dev.html`, `/api/dev/days`, and `/api/day/close` answer 404
   at the proxy. The tunnel reaches them. A restic
   `restore --target` drill brings the store back to a scratch
   directory. A reboot brings the server back with no hand work.

## 10. Runbook

Build sequence (§6) on branch `feat/backend-support`, each commit
green (`uv run pytest -q`, the web gates from B5 on) and
Vale-clean on touched prose. The review closes the phase. The
production pool phase follows.
