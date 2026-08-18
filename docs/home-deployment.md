# Home deployment runbook

One always-on PC on your home network serves a live, invite-only
test of Starvector to the internet. This page is the full path from
an empty PC to a played day. It follows `deploy/README.md`, the
provider-neutral runbook. It adds what a home network wants: router
work, dynamic DNS, and a build step that runs on your development
machine, not on the box.

## 1. What this run is

Three facts frame the setup.

- **The app is invite-only by construction (spec M1).** There is no
  open registration. A browser with no invite cookie gets the invite
  gate, and each player surface answers 401. "Public" means the site
  answers — play is for the testers you invite.
- **This run serves the development pool.** The release is
  `dev-wit-002`: 204 images, marked `dev_only`. The scores are
  development numbers, and `CLAUDE.md` section 7 says they do not go
  public. This run is for invited testers, not for the public.
- **The production pool is a subsequent phase, and nothing here
  waits for it.** It is not built at this time, thus the development
  release is the correct pool for this run. When the production pool
  lands, this same box serves it after one data copy, one config
  edit, and one `systemctl restart` (section 16).

## 2. The pool and the storage budget

The 10 GB budget is more than this run wants. Measured 2026-08-17:

| item | on disk |
|---|---|
| repo checkout | < 0.1 GB |
| Python environment (`uv sync`, base set) | ~0.3 GB |
| release tree `data/preparation/9644fac1` | 32 MB |
| commonness tables `data/commonness` | < 1 MB |
| pool photographs `data/images` | 0.42 GB |
| built app `web/dist` | < 5 MB |
| play store `store/` | grows by kilobytes for each submission |
| **total at the start** | **~0.9 GB** |

The torch stack does not install here. It belongs to the optional
`local-cuda` and `local-xpu` dependency groups, and the base
`uv sync` stays near 0.3 GB.

Room for what follows: a 20,000-image production pool, fetched at 768 px
with rejected candidates pruned, is about 2.3 GB (measured estimate,
2026-08-17). It fits this budget with room. Its resident arrays want
4 GB of memory or more at start. The development pool's arrays are
40 MB, thus the PC you have serves the current run.

## 3. What you must have

- The PC: x86-64, 2 GB memory or more, 25 GB free disk. 4 GB memory
  or more when a production pool lands.
- An Ubuntu Server 24.04 LTS installer, written to USB. The deploy
  stack (the systemd units, Caddy, `ufw`) is built for this system.
- A domain name you control. Caddy gets the certificate for that
  name on its own.
- Admin access to your router.
- An OpenRouter account.
- Your development machine, with this repo, `uv`, and `pnpm`.

## 4. Keys and secrets

There are four secrets. No other credential is in the system.

| secret | where it lives | who reads it | how you get it |
|---|---|---|---|
| `OPENROUTER_API_KEY` | `/etc/starvector/env` (root, 0600) | systemd, as root, before privileges drop | make a key at openrouter.ai and set a spend cap of $5–10 |
| `STARVECTOR_OPERATOR_TOKEN` | `/etc/starvector/env` | same | make one on the box (section 10) |
| restic repository password | `/etc/starvector/restic-env` (0600) | the backup units | make one on the box |
| backup storage credential | `/etc/starvector/restic-env` | same | from your storage provider — use an append-only credential |

Player invites are not stored. The store keeps a digest alone, and
each invite prints one time.

Three rules:

- Type secrets on the box. Do not paste them into a chat, a
  transcript, or a commit.
- The spend cap limits a leaked OpenRouter key. Set it before the
  key goes on the box.
- The server refuses to start when player records are stored and the
  operator token is not set. That refusal is deliberate — set the
  token from the start.

## 5. Install the operating system

1. Install Ubuntu Server 24.04 (the minimal install). Make your
   admin user during the install and select the OpenSSH server.
2. Give the PC a fixed address: add a DHCP reservation for it in the
   router.
3. From your development machine, copy your SSH key:
   `ssh-copy-id you@<lan-ip>`.
4. Set `PasswordAuthentication no` and `PermitRootLogin no` in
   `/etc/ssh/sshd_config`, then run `sudo systemctl restart ssh`.
   Password login and root login then stop.

## 6. The box baseline

```
sudo apt update
sudo apt install -y caddy restic ufw unattended-upgrades rsync
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo mv ~/.local/bin/uv /usr/local/bin/uv
sudo adduser --system --group --home /srv/starvector starvector
```

The firewall on the box — the router is the second layer
(section 7):

```
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <your-lan-subnet> to any port 22 proto tcp
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw enable
```

Port 22 stays open to the LAN alone. It is not forwarded at the
router, thus the internet has no SSH path to this box.

Automatic updates, with the reboot out of the game window:

```
sudo dpkg-reconfigure -plow unattended-upgrades
```

Set `Automatic-Reboot "true"` and `Automatic-Reboot-Time "04:30"` in
`/etc/apt/apt.conf.d/50unattended-upgrades`.

If the router offers an isolated network segment for servers, put
this PC on it. A compromised box then sees no other home device.

## 7. Open the path from the internet

1. **DNS.** Point an A record for your domain at your public
   address. On Cloudflare, keep the record DNS-only (grey cloud),
   thus the box gets its own certificate.
2. **A changing address.** Home addresses change. Run a dynamic DNS
   updater on the box — your registrar's client, or `ddclient` —
   thus the record follows the address.
3. **Port forwarding.** On the router, forward TCP 80, TCP 443, and
   UDP 443 to the PC's fixed address. Do not forward 22.
4. **CGNAT.** Some providers give no inbound path at all. The test:
   the router's WAN address and the address at `https://ifconfig.me`
   must agree. When they do not, port forwarding cannot work. An
   outbound tunnel (for example, Cloudflare Tunnel) is the
   replacement, and its TLS shape is different from this page.
5. **NAT loopback.** From your own network, the domain answers
   only when the router supports NAT loopback (hairpin).
   Turn it on, or add a local DNS entry for the domain.

Caddy fetches the certificate at the first HTTPS visit. Wait for
DNS to resolve before that first visit.

## 8. Get the code onto the box

A read-only deploy key, not a GitHub login. The private half stays
on the box, opens one repository, and cannot write.

```
sudo -u starvector mkdir -p /srv/starvector/.ssh
sudo -u starvector chmod 700 /srv/starvector/.ssh
sudo -u starvector ssh-keygen -t ed25519 \
    -f /srv/starvector/.ssh/id_ed25519 -N ""
sudo cat /srv/starvector/.ssh/id_ed25519.pub
```

Paste the public key into the repository settings, in Deploy keys,
with write access off. Then:

```
sudo -u starvector tee /srv/starvector/.ssh/config >/dev/null <<'CFG'
Host github.com
  IdentityFile /srv/starvector/.ssh/id_ed25519
  IdentitiesOnly yes
CFG
sudo -u starvector chmod 600 /srv/starvector/.ssh/config
sudo -u starvector git clone \
    git@github.com:<owner>/<repo>.git /srv/starvector/app
cd /srv/starvector/app
sudo -u starvector /usr/local/bin/uv sync
sudo -u starvector mkdir -p store data
```

`uv sync` installs the base set — about 0.3 GB. The units refuse to
start while `store/` or `data/` is missing, thus the `mkdir` is part
of the setup.

## 9. Ship the app build and the pool

The box builds nothing. The web app builds on your development
machine, and the pool artifacts come from there too — the same
pattern serves a subsequent production pool.

On the development machine:

```
cd web && pnpm install && pnpm build
rsync -a web/dist/ you@<lan-ip>:staging/dist/
cd .. && rsync -a data/preparation/9644fac1 data/commonness \
    data/images you@<lan-ip>:staging/data/
```

On the box:

```
sudo rsync -a --chown=starvector:starvector \
    ~/staging/dist/ /srv/starvector/app/web/dist/
sudo rsync -a --chown=starvector:starvector \
    ~/staging/data/ /srv/starvector/app/data/
rm -r ~/staging
```

Do not copy your development `store/`. Those days were experiments.
The box starts its own history, and no other machine holds a copy
of its store.

## 10. Configure

Two files with two different readers — the split is
`deploy/README.md` section 3:

```
sudo mkdir -p /etc/starvector
sudo chown root:starvector /etc/starvector
sudo chmod 750 /etc/starvector
```

The secret file. Root reads it, and the `starvector` user cannot:

```
sudo cp /srv/starvector/app/deploy/env.example /etc/starvector/env
sudo chmod 600 /etc/starvector/env
sudo nano /etc/starvector/env
```

Put two values in it. The OpenRouter key comes from openrouter.ai —
set the spend cap first. The operator token comes from:

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The server config. The `starvector` user reads this one:

```
sudo tee /etc/starvector/service.json >/dev/null <<'JSON'
{
  "config_version": 1,
  "player": "<your-handle>",
  "scoring_config": "configs/scoring/dev-wit-mixed-3.json",
  "data_root": "data",
  "store_root": "store",
  "port": 8000,
  "closes_at_utc": "20:00"
}
JSON
sudo chown root:starvector /etc/starvector/service.json
sudo chmod 640 /etc/starvector/service.json
```

`player` is the ruling-7 fallback identity and a legal store key:
lowercase letters, digits, hyphens. After the first mint, sessions
name the caller and this field is only the fallback. `closes_at_utc`
drives the countdown on the Today screen — set your close time, or
drop the line.

## 11. Units and the edge

```
cd /srv/starvector/app
sudo cp deploy/starvector.service deploy/starvector-dev.service \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now starvector
sudo journalctl -u starvector -n 20
```

The journal must show
`Uvicorn running on http://127.0.0.1:8000`. The dev unit
(`starvector-dev.service`) stays stopped — section 14 starts it for
console work.

The edge:

```
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile        # set your real domain
sudo systemctl reload caddy
```

The uvicorn process binds `127.0.0.1` alone. On your own network,
the only doors are Caddy's 80 and 443 — and SSH from the LAN.

## 12. Smoke checks

Run these away from your own network when you can. A phone on its
mobile connection works.

- `https://<domain>/` loads the app and shows the invite gate. The
  gate is success: no cookie, no play.
- `curl -sI https://<domain>/join/bogus` answers 401 with a JSON
  content type. HTML here means the invite path fell to the app
  shell, and no invite URL can sign anybody in.
- `curl -s -o /dev/null -w "%{http_code}" https://<domain>/dev.html`
  answers 404. The same for `/api/dev`, `/api/day/close`, and
  `/api/players`.
- `https://<domain>/leaderboard` and `https://<domain>/history` load
  when typed into the address bar.
- `sudo systemctl reboot` — the site is back with no hand work.

One warning for each test that follows: use the HTTPS domain, not
`http://<lan-ip>`. The session cookie holds the `Secure` transport
flag, thus a plain-HTTP visit cannot keep a session, and the failure
names nothing.

## 13. Invite players

The console (section 14) has an invite panel with an `origin` field.
The command line, on the box:

```
cd /srv/starvector/app
sudo -u starvector .venv/bin/python -m service.players \
    --service-config /etc/starvector/service.json \
    --origin https://<domain> \
    mint <name> --display-name "<Label>"
```

The invite prints one time — send it, then forget it. `list` shows
the roster with no secret in it. `rotate` replaces an invite nobody
can find,
`revoke` stops a player, and `restore` brings one back.

Mint your own player first, and open your own invite. The first
mint switches access control on for the world. From then on, each
player surface wants a session, and the operator surfaces want the
bearer token.

## 14. Run a day

The loop: open, players play, close (this step spends through
OpenRouter), reveal. Each step is an operator action.

**The console** — the full view: day browser, rankings, the invite
panel. On the box: `sudo systemctl start starvector-dev`. On your
development machine:

```
ssh -L 8001:127.0.0.1:8001 you@<lan-ip>
# in a second terminal
cd web && VITE_PROXY_TARGET=http://127.0.0.1:8001 pnpm dev
```

Open `http://localhost:5173/dev.html` and paste the operator token
into its field. Move the day with the control row. Stop the dev
unit at the end: `sudo systemctl stop starvector-dev`.

**The command line** — fast, on the box. The public process holds
the key and the token from its environment file, thus a localhost
`curl` with the bearer is sufficient:

```
sudo bash -c '. /etc/starvector/env; curl -s -X POST \
  -H "Authorization: Bearer $STARVECTOR_OPERATOR_TOKEN" \
  http://127.0.0.1:8000/api/day/open'
```

The same `curl` with `/api/day/close` and `/api/day/reveal`. The close
encodes the stored submissions and can run for a minute. Its answer
names the row count and no score. To read the day with no console:

```
sudo -u starvector .venv/bin/python -m service.day \
    --service-config /etc/starvector/service.json status
```

A close at the development pool costs cents: some embedding posts
for each submission, cached for repeats. The lifecycle is
deliberately hand-driven. After the first week runs cleanly by hand,
a systemd timer around the two `curl` requests can automate it.
Read the close output for that first week.

## 15. Backups

The store is permanent play records. Back it up off the box from the
first day.

```
sudo cp /srv/starvector/app/deploy/restic-env.example \
    /etc/starvector/restic-env          # fill in
sudo chmod 600 /etc/starvector/restic-env
cd /srv/starvector/app
sudo cp deploy/restic-backup.service deploy/restic-backup.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now restic-backup.timer
```

Use a storage credential that cannot delete (append-only), thus a
compromised box cannot delete its own history. Run the
`restic restore` drill after the first snapshot — the commands are
in `deploy/README.md` section 6.

## 16. Update the deployment

Code and pool artifacts move in one direction: development machine
to box.

```
# on the box
cd /srv/starvector/app
sudo -u starvector git pull
sudo -u starvector /usr/local/bin/uv sync
sudo systemctl restart starvector

# on the development machine, when the web app changed
cd web && pnpm build
rsync -a dist/ you@<lan-ip>:staging/dist/

# then on the box
sudo rsync -a --chown=starvector:starvector \
    ~/staging/dist/ /srv/starvector/app/web/dist/
```

Two standing rules from the working agreement. Do not edit stored
days, earlier configs, or earlier releases — stored days rescore
against them forever. When the production pool lands, its release
is a new preparation adjacent to the earlier one. The move is one
`rsync` of new artifacts, one `service.json` edit, and one
`systemctl restart`.

## 17. What is open and what is closed

| surface | exposure |
|---|---|
| 80 and 443 (Caddy) | the internet — app shell, `/api`, `/image`, `/join` |
| lifecycle, console, and mint paths | blocked at the edge (404) and bearer-gated in the process |
| 8000 and 8001 (uvicorn) | `127.0.0.1` alone |
| SSH | LAN alone, keys alone — not forwarded at the router |
| player surfaces | 401 without an invited session |
| secrets | root-read file, spend-capped key, one-time invites |
| backups | off-box, append-only credential |

Each layer holds alone, on purpose. The edge blocks the operator
paths. The process gates them again on the bearer, and the dev unit
is not started at all in the usual condition.
