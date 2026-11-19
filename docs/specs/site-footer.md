# Spec F1 — the site footer and the two public pages

**Status:** ruled 2026-11-19 (§6), built on branch
`feat/footer-and-store-guard`.
**Phase:** before the first public day. A visitor has no path from the app
to its source, and a signed-out visitor can read nothing but the gate
screen.
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I7), §10.
**Input:** spec W1 (the app), spec BR1 §6 (the theme and the screens), spec
A2 §3 (the gate screen), spec R1 §3.3 (the notice screen).

This spec is written for implementation by an AI agent. Where a value is
not given by an earlier spec, §6 records the ruling.

---

## 1. Purpose

1. **A footer on the screens of the app.** It holds the brand and three
   controls: `About`, `Releases`, and `GitHub`.
2. **Two public pages.** `/about` and `/releases` open in a browser with no
   session. The owner writes the text of the first and sets up the second.
3. **A position for an email-updates box.** The box is not built (§4).

The change is in the web app alone. It adds no server path, no stored
record, and no text that comes from a day.

## 2. The footer

- **What it holds.** At the start: the logo mark, the name, and the line
  `a new photo every day`. At the end: `About` (to `/about`), `Releases`
  (to `/releases`), and `GitHub` (to
  `https://github.com/aajayi-21/starvector`, in a new tab, with
  `rel="noreferrer"`). `web/src/ui/site-links.ts` holds the address.
- **Where it is.** After the page of each screen, signed in or not: the
  home screen, the results, the leaderboard, the reveal, the account screen,
  `How it works`, the gate screen, the notice screen, and the two public
  pages.
- **Where it is not.** The two drawing screens, `/today` and `/practice`.
  The canvas uses the height of the window there, and a phone holds the send
  bar above the tab bar.
- **The look.** One 1px line of `--border` above it, the ground of the page
  behind it, and the width of the page. The text uses `--text-2` and
  `--text-3`. It adds no token to `theme.css`. On a short page the footer is
  at the end of the window.
- **A phone.** The controls come first and the brand line second. The
  footer is in the flow of the page and ends above the tab bar. The page
  gives its tab-bar clearance to the footer.
- **It is not a navigation.** The element is a `footer`. The app has one
  navigation, the five places, in the top bar and the tab bar.

## 3. The public pages

The app gives a signed-out browser the gate screen on each path (spec A2
§3). It gives a player with no agreement the notice screen on each path
(spec R1 §3.2 and §3.3). This spec changes the two rules for two paths:

- `/about` and `/releases` render their page for each browser. A browser
  with no session, and a player who has not agreed to the notice, get a top
  bar with the brand alone, the page, and the footer. The brand goes to `/`,
  where the gate screen or the notice screen is. A signed-out browser also
  gets a `Sign in` control to `/`.
- A signed-in player who has agreed gets the same page in the app, with the
  top bar and the tab bar.
- Each other path keeps the two rules.

The two pages hold fixed text. They read no day, no result, and no player,
thus the notice of spec R1 has nothing to wait for there.

- **`/about`.** The heading `About Starvector`, the text of the owner, and
  one line with the GitHub address. The text is the constant
  `ABOUT_PARAGRAPHS` in `web/src/screens/about.tsx`, one string for each
  paragraph. It is a short placeholder until the owner writes it.
- **`/releases`.** The heading `Releases` and the line `No releases to
  download yet.` The owner sets up the page.

No change of the edge is necessary: the Caddyfile answers each path that is
not a file with the app.

## 4. The email-updates box is not built

The owner asked for a box that takes an email address for updates. Spec A2
§1 and §7.4 record an earlier ruling: the server asks for no email address,
and it holds no datum that names a person. The content policy of the edge
(`form-action 'self'`, `connect-src 'self'`) stops a box that sends the
address to a different company.

The owner ruled on 2026-11-19 to build the footer with no box (§6 D1). The
footer keeps a position for it between the brand and the controls. A box
needs a new ruling first: where the addresses go, and that no address is
connected to a player.

## 5. Integrity

- **I7.** The footer and the two pages are fixed text in the app bundle,
  the same for each browser and each day. They send nothing to the server
  and read nothing from it. No answer changes its length or its time.
- **The gate.** The two public paths show no player data. The test
  `stay behind the gate for each other path` proves that the gate stands
  for the other paths.
- **A different company.** The GitHub control is a plain address. The app
  loads nothing from GitHub, and `rel="noreferrer"` sends no address of the
  app with the click.

## 6. Decisions, ruled 2026-11-19

| # | Decision | Ruling |
|---|---|---|
| D1 | Where the addresses of the email box go | The box is not built in this branch. |
| D2 | Can a signed-out browser open the footer and the two pages? | Yes. |
| D3 | Which screens have the footer | All but `/today` and `/practice`. |
| D4 | The GitHub address | `https://github.com/aajayi-21/starvector`. |

## 7. Testing

- `web/tests/component/footer.test.tsx`: the three controls and their
  addresses, no navigation and no text box in the footer, the footer on each
  screen but the two drawing screens, the two pages with no session and with
  no agreement, and the gate on each other path.
- `web/tests/component/shell.test.tsx` stays as it was: the gate screen has
  no navigation and two text boxes.
- `web/e2e/12-footer.spec.ts`: the same paths against the server.

## 8. Out of scope, with causes

- **The email-updates box.** §4.
- **The text of the About page and the contents of the Releases page.** The
  owner writes them.
- **A footer in the operator console.** The console is not a player screen.
