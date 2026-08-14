# Spec W1 — the production web app (frontend phase)

**Status:** ruled, prepared to build.
**Phase:** the frontend phase. The production player app is built
against the dev server as it stands. The backend phase follows with
its own spec. §7 of this document holds that phase's work items.
**Mockup source:** the `claude.ai/design` project "Starvector Logo"
(`3bee2c8f-9607-4d0a-8a9b-423c1418365b`, superseding
`3b93c3db-289b-44cb-a38a-da72fa45407e`): screens `1a`–`1f` of
`StarVector Production UI.dc.html` with `nocturne.css` (the
2026-08-14 retune), the logo docs `Starvector Logo v2.dc.html`
(adopted) and `Starvector Logo.dc.html`, and seven SVG assets (§3).
**Architecture sections:** §22 (integrity), §18 (latency), §15 (what
stays out of the interactive path).
**Working agreement:** `CLAUDE.md` §2 (I4, I7), §7, §10.
**Input:** Phase 5 closed. The server has the surfaces of specs S1
and P5 on the dev pool `dev-wit-002`. The C1 color palette is live.

---

## 1. Purpose

The player surface today is the dev build's one page: correct,
plain, and built for one tester. The mockup project holds the
production direction: a dark `Nocturne` app with a live sketch
canvas, practice, a reveal report, history with the skill number,
and multiplayer surfaces (leaderboard, streak, account).

This phase builds that app as a self-contained `web/` workspace
against the endpoints that are live today, with a typed mock behind
the same interface for the surfaces the backend does not have. The
backend phase then implements §7 and swaps the served page. No
backend file changes in this phase.

## 2. The rulings of 2026-08-14

1. **Canvas-first is the direction.** Screen `1a` (one-screen
   workspace: canvas left, card column right) is the
   daily-trial layout, with `1f` as its 390 px shape. The
   guided-steps layout `1b` is not built. A first-run hint layer
   can come as a follow-on.
2. **The stack is `React` 19 + `TypeScript` + `Vite`.** Pinned in
   §4. The mock's logic component is written in `React`-style
   semantics and ports almost one-to-one.
3. **`Cross-platform` means responsive web plus a PWA layer.**
   Desktop and mobile browsers, plus manifest, icons, and an
   app-shell worker for installability. No native wrappers.
4. **Multiplayer surfaces build in this phase, on a mock
   adapter.** Each screen ships complete. A typed client serves
   live endpoints where the server has them and a deterministic
   mock elsewhere. §7 is the written contract the backend phase
   implements.

A second set of rulings, same day — theming and the logo:

5. **The `Nocturne` retune is the look.** The tokens moved to the
   Nord family: ground `#2e3440`, surface `#3b4252`, text
   `#eceff4`, frost accent `#88c0d0`, second accent `#81a1c1`,
   with regenerated ramps, section colors, and shadows. Token
   values alone — the component classes are byte-equal, thus
   the vendored-copy refresh is a token diff.
6. **The Nord sketch palette is the C1 palette.** Wire and display
   use the new values, and the eighth slot changes brown → teal.
   C1 §5 carries the dated change (its own rule: a palette
   change is an interface change), and the v2c gate re-runs on the
   new values. §3 holds the details.
7. **Logo v2 is the mark, v1 stays on hand.** The nav takes
   `starvector-logo-v2-nav.svg` — the v2 doc's offer ("put v2 in
   the production navs") is taken. v1 is vendored, on hand.
   The favicon keeps the rayless reduction.

## 3. The mockup source of truth

The mockup project is canonical for the look: `nocturne.css` (the
tokens and component classes), the six screens of
`StarVector Production UI.dc.html`, and the logo docs with their
SVG assets. This spec does not restate pixel values — read them
there. What the repo holds are vendored copies (see §5). When the
mockup project changes, the copies are refreshed by hand and the
change is reviewed like code.

**The 2026-08-14 retune (ruling 5).** The tokens moved from the
blurple family to Nord, the component layer stayed byte-equal,
and the sample chrome across the screens follows (canvas ground
`#272c37`, group chips from the sketch palette). One note for the
vendored copy: the accent's explanatory comment in `nocturne.css`
describes the earlier blurple move — stale prose in the mockup
source, not a value error.

The `.dc.html` scaffolding (`x-dc`, `sc-for`, `{{ }}` bindings,
`DCLogic`, `support.js`) is the mock player's runtime, not part of
the build. The logic in the mock's script — stroke capture, the
palette, how impressions add and remove — is the reference for
behavior.

**Canonical against illustrative.** Layout, tokens, classes, copy
tone, and interaction shapes are canonical. All numbers in the mock
are illustrative props. The reveal screen's set cannot all be
correct at the same time (score 0.8712 with "beat 207 of 237" does not sit
at "rank 3 of 238"): display values derive only from the trial row
fields `p`, `beaten`, `tied`, `target_rank`, `decoy_count` — the
client does not invent a number the row does not hold.

**Mock-fidelity rulings** (deltas between the mock and the system
of record, resolved here):

- **The sketch palette (ruling 6).** The mock recolors the eight
  swatches to the Nord family and renames the eighth slot brown →
  teal — despite its own stale caption ("keeps the fixed spec
  colors"). Ruling: adopted. Wire and display use the amended C1
  §5 values. Ink displays `#eceff4` and sends no `color` key, so
  the promotion rule is untouched: an all-ink sketch stays on the
  mono path. Stored records keep their stored hexes and rescore
  byte-identically. The v2c gate re-runs on the new values before
  the first day played in color here — the encoder reads color
  (mean absolute delta-p near 0.12–0.14 on the earlier set) and
  the new set is lower-chroma, thus that measurement does not
  hold for it.
- **The brand (ruling 7).** Logo v2 — the halo of seven vector
  rays with the serpent leaving through the open segment at the
  bottom — is the adopted mark. v1 (fifteen plain rays) is
  vendored, on hand. The nav takes `starvector-logo-v2-nav.svg`
  at 18 px (16 px mobile). The screens continue to inline v1's
  plain-ray nav mark, which ruling 7 supersedes. Below nav scale the icon set keeps v1's reduction
  ("rays drop first, then the head"): `starvector-favicon.svg` is
  the rayless halo and serpent, `starvector-appicon.svg` the
  five-ray mini on the night gradient. Snow and night monochrome
  variants ship for light and print grounds. If the arrowheads
  close up at nav scale on device, the fallback is v1's nav mark
  (the v2 doc's own caption).
- **Countdown.** "closes in 6h 24m" requires `closes_at`, which
  `GET /api/day` does not hold. Contract item (§7). Until it
  lands, the status row shows the `Open` tag alone.
- **"+0.041 vs your median".** Defined as today's `p` minus the
  median of all prior revealed `p` values for this player. Hidden
  when there are fewer than two prior revealed trials.
- **"Your sketch" on the reveal screen.** Replayed from the
  player's own stored record — `GET /api/submission` (§7), with the
  locally kept sent copy as the display fallback.
- **Streak, account card, leaderboard.** `/api/me` and
  `/api/leaderboard` shapes (§7). The mock adapter serves them
  until the backend phase.
- **Navigation.** The nav's four items are Today, Practice,
  History, Leaderboard. Leaderboard goes to the reveal screen
  (`1c` holds the leaderboard card).
- **"autosaved".** That label belongs to the unbuilt `1b`, but the
  behavior is kept: drafts stay on the device (§8) with a quiet
  "draft saved" note.

**Adaptations.** The vendored `nocturne.css` drops its Google Fonts
`@import`. `Inter` (400/500/600/700, `woff2`) is self-hosted so dev
and tests run offline. Icons come from `@phosphor-icons/react`,
tree-shaken, as the `Nocturne` readme says.

## 4. The stack

Surveyed 2026-08-14 (four parallel web surveys: framework, canvas,
platform tier, toolchain — versions checked against release notes).

| Tool | Pin | Role |
| --- | --- | --- |
| `Node.js` | 24 (LTS line, floor 20.19) | runtime for the toolchain |
| `pnpm` | 11.x, `packageManager` field, `save-exact` | installs, made deterministic by `pnpm-lock.yaml` |
| `Vite` | 8.2.x | build and dev server (`Rolldown` bundler is built in) |
| `React` / `react-dom` | 19.2.x | screens, shell |
| `TypeScript` | 6.0 | types — `tsc --noEmit` is the authoritative type gate |
| `@tanstack/react-router` | 1.x | the four screens, code-based routing tree |
| `@tanstack/react-query` | 5.x | server data: caching, invalidation on reveal |
| `vite-plugin-pwa` | 1.3.0, pinned to the version | manifest + app-shell worker generation |
| `Vitest` | 4.1.x | unit tests (`node`/`jsdom` — browser mode held in reserve) |
| `Playwright` | 1.62.x | end-to-end tests |
| `Biome` | 2.4.x | the one lint + format gate |
| `@phosphor-icons/react` | current | icons |

Decisions behind the table:

- **No meta-framework.** SSR, file routing, and server functions
  buy nothing here: no SEO, and the server owns the day lifecycle
  and all score gating (I7). `Vite` builds static assets, and the
  server serves them (backend phase).
- **`TypeScript` 6.0, not 7.** TS 7 (the native compiler) shipped
  2026-07 without the stable programmatic API. Tools that read
  that API break until 7.1. Pin 6.0. Upgrade when 7.1 lands and
  `Vitest` and `Biome` are compatible.
- **`Biome`, not `ESLint` + `Prettier`.** One fast tool, no plugin
  chain, no dependency on the TS programmatic API, with
  `tsc --noEmit` as the type authority. (`ESLint` 9 reached end of
  life 2026-08-06. The v10 path can work but is two tools.)
- **No canvas library.** `konva`, `fabric`, `paper`, the `tldraw`
  SDK: each imposes its own retained document model between
  pointer input and the frozen wire format — a lossy export step
  for zero gained capability. The needed behavior is a small pure
  core (§9). `perfect-freehand` is pressure-stylized rendering
  the stored format cannot hold — not adopted.
- **No `MSW`.** The typed client seam (§6) is the mock boundary.
  Unit tests inject the mock adapter, and end-to-end tests run
  against the live server on fake providers. A
  network-interception layer can only duplicate that seam.
- **Rejected frameworks, for the record.** `Svelte` 5 is a strong
  second with a weak standalone-router story. `SvelteKit` 3 is in
  `@next`. `SolidJS` 2.0 is in beta. `Preact` 11 is at RC.
  `React Router` v7 concentrates its typed APIs in framework
  mode.
- **Upgrade discipline.** Pin `Vite` at 8.2.x and review bundler
  bumps like code (`Rolldown` became the default 2026-03).
  `vite-plugin-pwa` is pinned to the version — its `workbox` base
  is in maintenance with a fork landing. The recorded fallback is
  a hand-written ~50-line worker.

## 5. Repository layout

```
web/
  package.json            # pnpm, ESM only ("type": "module")
  vite.config.ts          # dev proxy: /api, /image -> 127.0.0.1:8000
  index.html
  public/                 # manifest icons
  src/
    main.tsx
    app.tsx               # shell: nav, router, query provider
    nocturne.css          # vendored tokens + classes (see 3, adaptations)
    brand/                # the seven vendored SVG assets (logo v2 + variants, v1, icons)
    fonts/                # Inter woff2
    api/
      types.ts            # wire types mirroring 6 and 7
      client.ts           # the Api interface
      real.ts             # fetch adapter, fails loudly
      mock.ts             # deterministic adapter, seeded by day
    sketch/
      core.ts             # pure: document, reducers, hit-test, serialize
      canvas.tsx          # DOM adapter: pointer wiring, two layers, DPR
      palette.ts          # the C1 palette, wire and display values
    screens/
      today.tsx           # 1a / 1f
      practice.tsx        # 1e
      reveal.tsx          # 1c
      history.tsx         # 1d
    ui/                   # shared: nav, target code row, tables, tags
  tests/                  # Vitest
  e2e/                    # Playwright
```

`web/` owns its own toolchain. The repo root stays Python-only. The
current `service/ui/` page and the dev console are untouched — the
dev console stays the operator surface, and the served player page
swaps in the backend phase.

## 6. The wire today

The client is typed against the shapes the server serves today. The
system of record for each is the handler in `service/server.py` and
the intake contract in `core/intake.py`. This section is the index,
not a restatement.

- `GET /api/day` → `day`, `trial_code` (6 chars A–Z0-9), `status`,
  `commitment`, `player`, `submitted`, `relation_vocabulary`,
  `canvas_px`, plus `target_id` and `secret` when revealed.
- `POST /api/submission` — the wire record
  `{impressions, canvas_strokes, groups, relations, pasted_text}`.
  Strokes hold `points` (normalized pairs), `group_id`
  (nullable), optional `color` (lowercase `#rrggbb`). Answer:
  `{trial_id, atom_count}`. Refusals hold `{cause, detail}`.
- `GET /api/reveal` → `day`, `target_id`, `secret`, `commitment`,
  `check`, `trial` (`p`, `decoy_count`, `beaten`, `tied`,
  `target_rank`) or null, `report` rows.
- `GET /api/practice` → revealed days
  (`{day, target_id, trial_code}`), newest first. Constant 404
  when there are none.
- `POST /api/practice/score` → `{day, record}` in, then `{day,
  target_id, trial, target_position, ranking_head, report}` out.
  The `ranking_head` rows are anonymous
  (`position`, `fused`, `is_target`) — §22's rule.
- `GET /image/{image_id}` — revealed targets alone. Constant 404
  elsewhere.

The composite client wires these through the live adapter. The
screens consume the `Api` interface alone — no screen holds a URL.

## 7. The contract for the backend phase

The mock adapter implements these shapes in this phase. The backend
phase makes them live and swaps the wiring. Nothing in this section
changes a stored artifact or a frozen tier.

- **`closes_at` on `GET /api/day`.** ISO 8601 UTC timestamp or
  null (the day lifecycle is operator-run today, thus null is
  legitimate). The client shows the countdown when the field is
  set.
- **`GET /api/history`** →
  `{days: [{day, trial_code, p, target_rank, decoy_count}],
  skill: {theta, shrunk, evidence_p, n} | null}`, newest first —
  the JSON twin of the `/history` page, same aggregation source.
- **`GET /api/leaderboard?day=`** → revealed days alone.
  `{day, rows: [{player, p, target_rank, decoy_count, streak}]}`
  sorted by `p`, descending. Constant 404 for a day that is not
  revealed — the same refusal discipline as practice, and the I7
  result: no leaderboard shape for an open day.
- **`GET /api/submission?day=`** → the player's own stored wire
  record with `trial_id`, or 404. Own data, no target
  information. Serves the reveal screen's sketch replay.
- **`GET /api/me`** → `{player, streak, reminder, public}`.
- **Streak, defined.** The count of days in an unbroken run that
  ends at the newest revealed day, each with a stored submission
  from this player. The mock adapter computes the same
  definition.
- **Serving.** Build output `web/dist` served by the server:
  `FastAPI` ≥ 0.138 `app.frontend()`, or the classic
  `StaticFiles` setup with a guarded catch-all (404 for missing
  asset-like paths, `index.html` for screen paths). `/api`
  registers first. The dev console keeps its path.
- **Daily reminder (deferred).** Web Push with VAPID keys and
  `pywebpush`, declarative payloads with a worker fallback,
  subscription rows keyed to the player. iOS receives push only
  as an installed app, thus a calendar (ICS) fallback is part of
  the item. The frontend phase ships only an inert toggle.
- **Accounts.** Out of contract. Identity stays the configured
  single player until an accounts phase. The leaderboard's other
  rows stay mock until then.

## 8. Integrity in the client

The invariants are server-enforced. The client must not blur them.

- **I7 — no score-shaped signal before close.** No optimistic
  score display, no client-side estimate, no polling with a
  cadence that depends on content. The send acknowledgment shows
  `trial_id` and `atom_count` and nothing else.
- **One send for each day.** The send button locks after a 200 or
  an `already-submitted` 409. The submitted view replaces intake.
- **§22 — practice names no other image.** The head table
  renders the anonymous rows as-is. The client fetches `/image`
  only for a revealed target it was handed.
- **Drafts are disposable caches (I4).** The draft (strokes,
  impressions, groups, relations, notes) is kept in
  `localStorage`, keyed by day, cleared on send. Raw permanence
  lives server-side — a browser can evict the draft and the
  record on the server stays safe. Safari evicts after seven days
  for non-installed players, thus the note says "draft", not
  "saved".
- **The wire format is frozen (L0).** The client serializes to
  the record shape accurately and adds nothing. Pen pressure,
  tilt, and timestamps have no slot in the format. Wanting them
  is a format change with server-side effects — flagged here so
  it is a decision, not drift.
- **The worker does not answer for the API.** The app-shell
  worker precaches hashed static assets alone. `/api/*` and
  `/image/*` are network-only with no fallback — a synthesized
  answer breaks I7 and the no-silent-fallbacks rule at the same
  time. The worker is off in dev and in test runs.
- **Offline is explicit.** The shell loads offline with a banner.
  Scoring and reveal do not work offline — they refuse loudly.

## 9. The sketch canvas

A pure core plus a thin DOM adapter, no library (§4).

**The core (`sketch/core.ts`)** imports nothing from the DOM and
holds no clock and no RNG — stroke identifiers come from a passed
counter. The drawing document is an immutable value: stroke records
(`points`, `colorIndex`, `id`) plus group assignments. Each
mutation (add-stroke, clear, group, ungroup) is a pure reducer
returning a new document. `undo`/`redo` is a history array with an
index pointer. Clear is a recorded operation. A new operation after
`undo` truncates the `redo` tail. Serialization emits the §6
record.

**Constants** (spec-fixed, not invented in code):

| Constant | Value |
| --- | --- |
| coordinates, rounded | to 4 decimal places at serialization |
| minimum point distance | 0.5 CSS px between kept points |
| select tolerance, mouse/pen | `max(strokeWidth / 2 + 4 px, 8 px)` |
| select tolerance, touch | 12 px |
| palette (wire) | C1 §5 as amended 2026-08-14 — ink sends no key. Colors `#bf616a`, `#d08770`, `#ebcb8b`, `#a3be8c`, `#81a1c1`, `#b48ead`, `#8fbcbb` |
| palette (display) | the wire values — ink displays `#eceff4` |

**The adapter (`sketch/canvas.tsx`)** attaches the core one time in
a ref effect. Committed documents alone touch `React` — points in
flight do not.

- Pointer Events alone, no mouse/touch fallbacks. On
  `pointerdown`: check `isPrimary`, capture the pointer, key the
  active stroke to its `pointerId`, ignore a second `pointerdown`
  while a stroke is active (cheap palm defense).
- A stroke ends on `pointerup` and on `pointercancel`. On cancel,
  commit at two or more points, else discard. No stroke stays
  open.
- `touch-action: none` and `user-select: none` on the canvas
  element alone. The context menu is suppressed on it. Page
  scroll elsewhere keeps working.
- Stroke fidelity: in `pointermove`, walk
  `getCoalescedEvents?.() ?? [event]` and append each point. Read
  positions as `clientX`/`clientY` minus the canvas bounding rect
  — Safari's first coalesced-events implementation omits other
  fields on coalesced entries. Predicted entries are not used.
- Coordinates normalize to `[0,1]` against the CSS-pixel box,
  clamped. The canvas keeps a fixed aspect ratio so a shape means
  the same thing at each display dimension.
- Backing store from a `ResizeObserver` using
  `devicePixelContentBoxSize` when the browser has it (fallback:
  content rect × `devicePixelRatio`), integer device pixels,
  `setTransform(dpr, 0, 0, dpr, 0, 0)`, drawing in CSS units.
- Two stacked canvases. The committed layer replays the full
  stroke array, redrawn only on commit, `undo`, `redo`, clear,
  selection change, or resize. The live layer draws the active
  stroke, flushed one time for each animation frame, optionally
  with `{desynchronized: true}`.
- Hit-testing is a core function: minimum point-to-segment
  distance in CSS-pixel space (tolerance is perceptual, thus not
  in normalized space). The nearest stroke wins, the newest
  breaks ties. Selection is an explicit mode, entered from the
  group card.

**Device risks, recorded.** iOS system gestures can fire
`pointercancel` despite `touch-action: none` (the commit-on-cancel
rule limits the damage). Coalesced-point density differs between
60 Hz touch and 240 Hz pens (the distance constant limits payload
drift). A small device matrix belongs to B11: desktop Chrome,
Android touch, iPad pencil.

## 10. Build items

Each item lands green (`tsc --noEmit`, `biome ci`, `vitest`) and
Vale-clean before the next starts.

- **B1 — scaffold.** `web/` with the §4 toolchain, vendored
  `nocturne.css` (the retuned tokens) with self-hosted `Inter`,
  the seven brand SVG files, a token smoke page. Acceptance:
  `pnpm build` emits `web/dist`, and the toolchain gates run
  green offline.
- **B2 — the API layer.** `types.ts`, the `Api` interface, the
  live adapter (fails loudly, no retries that hide errors), the
  mock adapter (deterministic, seeded from the day string), the
  composite wiring (§6 live, §7 mock) plus a full-mock mode for
  offline UI work. Acceptance: unit tests pin the mock's
  determinism and the composite's dispatch.
- **B3 — the stroke core.** `sketch/core.ts` (§9) with recorded
  pointer-sequence fixtures asserting byte-stable serialization.
- **B4 — the canvas adapter.** Two layers, pointer wiring, DPR
  handling, palette, and a `jsdom` smoke test (the check that
  counts is B11's device matrix).
- **B5 — the shell.** Nav, router (`/`, `/practice`, `/history`,
  `/reveal`), query provider, streak tag and avatar from
  `/api/me`. Acceptance: each screen renders against the
  full-mock client.
- **B6 — Today (`1a`).** Target code row, status row (plus
  countdown when `closes_at` arrives), sketch card, impressions,
  groups and relations (vocabulary from `/api/day`), notes, the
  send card with its lock behavior, draft autosave. Views: no
  day, open, submitted, closed, revealed (hand-off to the reveal
  screen).
- **B7 — Practice (`1e`).** Day picker and random day, the same
  canvas, score card, revealed target image, report table,
  session counter (client-side, ephemeral).
- **B8 — Reveal (`1c`).** Score hero from the trial row, the
  commitment/secret check line, target image, sketch replay,
  what-matched table, leaderboard card (mock adapter).
- **B9 — History (`1d`).** Skill hero (`theta`, shrunk, evidence,
  n), stat cards, last-14 bars, revealed-days table — from the
  `/api/history` shape (mock until the backend phase).
- **B10 — mobile and PWA.** The `1f` layout at 390 px, the
  manifest (standalone, dark theme color from the tokens,
  maskable icons rasterized from `starvector-appicon.svg`, the
  page icon from `starvector-favicon.svg`), the app-shell worker
  (§8), the install hint (manual on iOS, `beforeinstallprompt`
  elsewhere), the offline banner.
- **B11 — end-to-end and polish.** `Playwright` runs the built
  app (preview server proxying to a live server instance on fake
  providers, tmp store): open day → sketch and impressions →
  send → lock, a practice cycle, reveal after operator close,
  history. Offline-deterministic. Plus the §9 device matrix and
  a keyboard and focus check (`:focus-visible` is in the tokens
  — the canvas has text alternatives by construction:
  impressions and groups).

## 11. Testing

- **Unit (`Vitest`, node).** The stroke core: reducers,
  hit-tests, serialization fixtures. The mock adapter:
  determinism, streak and median definitions. No DOM, no
  network.
- **Component (`jsdom`).** Screen-level rendering against the
  full-mock client: views, locks, refusal rendering.
- **End-to-end (`Playwright`).** The B11 flows against the live
  server on fake providers — the same offline posture as the
  Python suite. Browser binaries are cached, not fetched in
  runs.
- **What is not tested here.** Scoring numbers (the Python suite
  owns them) and the wire format (pinned by `core/intake.py`
  tests — the client's fixtures assert shape agreement, not
  scoring).

## 12. Out of scope

- Backend changes of all kinds — §7 is a contract, not work done
  here. The current player page keeps serving until the backend
  phase swaps it.
- Accounts, live leaderboard rows, Web Push sending, HTTPS and
  `reverse-proxy` work on the home server (recorded as
  backend-phase concerns).
- Native wrappers (`Capacitor`, `Tauri`) — on the table again
  only if the app stores become a goal.
- The guided-steps layout `1b` and an onboarding tour.
- Publishing dev-pool numbers anywhere public. The leaderboard
  gate of `CLAUDE.md` §7 (V2 and V3 green) is met, but dev
  results stay dev-only. The production pool phase supplies the
  numbers that can face players.

## 13. Runbook

```
cd web
pnpm install                # deterministic via the lockfile
pnpm dev                    # Vite on :5173, proxy to uvicorn :8000
pnpm test                   # Vitest
pnpm build && pnpm preview  # the built app
pnpm exec playwright test   # e2e (starts its own service instance)
```

The server side stays as today: `uvicorn` on `:8000` with the dev
store. Nothing in this phase changes what the operator runs.

One scoring-side gate rides on ruling 6: before the first day
played in color on this app, the owner re-runs v2c on the amended
palette (`validation/colorize.py` updates with C1 §5 — about 9–16
posts cold, fewer warm) and records the verdict.
