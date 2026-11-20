# Spec PW1 — a proof of work at sign-up

**Status:** built on branch `feat/altcha-signup`, 2026-11-19. The owner
ruled each decision on 2026-11-19 (§6).
**Phase:** before the first public day. Sign-up opens to each visitor at the
production cutover (`docs/production-cutover.md`).
**Architecture sections:** §22 (protocol integrity).
**Working agreement:** `CLAUDE.md` §2 (I7), §10.
**Input:** spec A2 §3.1 (make an account), §8 (the paths), and §9 (limits
and refusals).

This spec is written for implementation by an AI agent. Where a value is
not given by an earlier spec, §6 records the decision.

---

## 1. Purpose

Spec A2 lets each visitor make an account with a username and a password. Its
defense against accounts in bulk is two caps: 10 accounts for each client
address and 1,000 for the process in 24 hours (spec A2 §9.2). A script that
uses many addresses goes around the first cap.

This spec adds a proof of work to each sign-up. The browser does a small
quantity of work before it sends the sign-up. For one person this costs some
seconds of processor time, one time. For a script that makes thousands of
accounts it costs thousands of those seconds.

The tool is ALTCHA (D1). It is self-hosted: the server signs each
challenge and checks each answer. No other site sees a visitor.

## 2. What it is not

- **It is not a test of a person.** A script can do the work. The
  proof makes each account cost more, and nothing more.
- **It does not replace a cap.** The caps of spec A2 §9.2 stay as they are,
  and the sign-up checks the cap before the proof.
- **It does not change sign-in or recovery.** Those paths have their own
  caps (spec A2 §9.2), and a returning player does no work.
- **It keeps no new record.** The store does not change (spec SC1). The
  server keeps the spent proofs in memory (§3.3).

## 3. The server

`service/proofs.py` holds the work of the server. `service/server.py` adds one
path and changes one.

### 3.1 `GET /api/signup/challenge`

The answer is one new challenge, as JSON, with `Cache-Control: no-store`.
With sign-up closed the answer is the constant 404 of `GET /api/signup`.

The server picks a random counter in the range of D3 and derives its key
with PBKDF2-SHA-256 (D2). The challenge holds the first half of that key,
an HMAC of the full key, its end (D4), and an HMAC of all its parameters.
The browser must find the counter. The server derives one key for each
challenge, at a measured 1.2 ms (D8).

### 3.2 `POST /api/signup`

The body gets one more field, `proof`: the text that the widget gives when
it finds the counter. The server does these steps in sequence:

1. The `Origin` and media-type checks of spec A2 §8.
2. The sign-up caps of spec A2 §9.2 (429).
3. The proof. The body `{"cause":"proof"}` with status 400 answers each of
   these: no `proof` field, a text that is not the ALTCHA shape or is
   longer than D10, a challenge that this server did not sign, a key that
   does not agree with the challenge, a challenge after its end, and a
   proof that made an account before (§3.3).
4. The sign-up of spec A2 §3.1.

The server clock decides the end of a challenge. The ALTCHA library also
checks it against the system clock.

### 3.3 One proof makes one account (D5)

A sign-up holds its proof before the store work. When the store makes the
account, the proof stays spent until its end. When the store refuses the
account, for example because the name is taken, the server gives the proof
back. The person then tries a different name with the same proof.

The ledger of spent proofs is in memory. A start of the server empties it,
and a proof that made an account before the start can then make one more
before its end. The caps of spec A2 §9.2 count that account too.

### 3.4 The key and the start-up guard

One secret, `STARVECTOR_ALTCHA_KEY` in `/etc/starvector/env` (D6), gives
two HMAC keys: one signs the challenges, and one signs the derived keys.
The server refuses to start when sign-up is open and the secret has no
value (D7). The refusal names the environment name, as the refusal of the
pepper does (spec A2 §10.2).

The secret needs no backup. With a new secret, each open challenge does not
agree one time, and the person gets a new challenge.

## 4. The web app

### 4.1 The sign-up card

The sign-up card of the gate screen (spec A2 §3.1) shows the ALTCHA widget
after the notice that results are public, and before `Create account`.

- The widget starts when the card opens (`auto="onload"`, D11), thus the
  work goes on while the person types a name and a password.
- `Create account` stays disabled until the widget shows `Verified`.
- When the server answers `{"cause":"proof"}`, the card shows the message
  of `web/src/api/types.ts` and puts a new widget in the same position. The
  new widget reads a new challenge and starts again.
- When a challenge ends before the person sends, the widget shows that it
  ended, and `Create account` is disabled again. A click on the widget
  starts the work again.

### 4.2 How the widget loads

The widget loads when the sign-up card opens, as a different file of the
build. A signed-in player does not download it. The build is
`altcha/external`: it has no inline style element and makes no worker from
a `blob:` URL. Its stylesheet and its PBKDF2 worker are files of the site.
The `Content-Security-Policy` of `deploy/Caddyfile` thus stays as it is.

The widget records no pointer, scroll, or key timing, and it shows its
small attribution to `altcha.org` (D9). The widget sends that data only
when a server asks for it, and this server does not, thus the data has
no use here. Its colors come from the theme tokens of
the app, in light and dark.

### 4.3 The mock world

The mock world of spec W1 has no server to sign a challenge. Its API gives
no challenge address, the card shows no widget, and the card sends the
fixed text `mock-proof`. The mock `signUp` accepts it.

## 5. Deployment

- Add `STARVECTOR_ALTCHA_KEY` to `/etc/starvector/env` before the server
  starts with this build and with sign-up open. Make it with
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
- The edge needs no change: `/api/*` goes to the server.
- `deploy/env.example`, `deploy/README.md`, `docs/droplet-deployment.md`,
  and `docs/production-cutover.md` name it.

## 6. Decisions

| # | Decision | Value | Status |
|---|---|---|---|
| D1 | The tool | ALTCHA: the widget `altcha` 3.6.0 (npm, MIT) and the library `altcha` 2.4.0 (PyPI, MIT), with no new indirect Python package | the owner's, 2026-11-19 |
| D2 | The algorithm | `PBKDF2/SHA-256`, the default of the widget, which the browser computes with its own cryptography | ruled |
| D3 | The cost of one challenge | 5,000 PBKDF2 iterations for each try, as in the example of the ALTCHA library, and a counter from 1,000 to 4,999: the owner chose a lighter range than that example | ruled |
| D4 | The life of a challenge | 10 minutes, the value of the example of the library | ruled |
| D5 | Spent proofs | One proof makes one account. A refused sign-up gives its proof back. | ruled |
| D6 | The environment name | `STARVECTOR_ALTCHA_KEY`, with two keys made from it by HMAC | ruled |
| D7 | No key | The server refuses to start with sign-up open | ruled |
| D8 | A cap on the challenge path | None. One challenge costs the server 1.2 ms. | ruled |
| D9 | Data of the widget | No pointer, scroll, or key timing (`humanInteractionSignature` off), and the attribution of the widget shows | ruled |
| D10 | The length of a payload | 4,096 characters at most. A payload of this server is less than 1,000. | ruled |
| D11 | When the widget starts | When the sign-up card opens | ruled |
| D12 | Where the widget goes | Adjacent to `Create account`, after the notice that results are public | ruled |

**The time on a phone is not measured (D3).** On the development machine,
the Python library solves one challenge at counter 3,000, the mean of the
range, in 1.4 s on one processor. The widget uses the cryptography of the browser and more than
one worker, thus it is faster. Measure the time on a phone after the
deployment, with the card open and nothing typed. If it is more than the
time to type a name and a password, make the counter range smaller.

## 7. Testing

- `tests/service/test_signup_proof.py`: the challenge path and the switch,
  a new challenge at each read, the end of a challenge, a proof that makes
  an account, each refusal of §3.2, a payload of a different key, a changed
  payload, a proof after its end, one proof for one account, a refused
  sign-up that gives its proof back, the cap before the proof, the ledger,
  the keys of a secret, and the values of §6.
- `svc_fixture.QUICK_PROOF` makes a challenge that solves in 8 tries at most,
  and `svc_fixture.solved_proof` solves one as the widget does. Each test of
  sign-up sends one, and so do `tools/freeze_store.py` and the Playwright
  server `web/e2e/serve_fixture.py`.
- `web/tests/component/gate.test.tsx`: the card sends the proof, and a
  refused proof starts a new check. `web/tests/unit/credential-api.test.ts`:
  the client sends `proof` in the body.
- `web/e2e/07-sign-up.spec.ts`: the widget in Chromium shows `Verified`, and
  the account is made with its proof. `web/e2e/11-delete-account.spec.ts`
  sends a proof that `e2e/helpers.ts` solves.
