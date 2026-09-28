# Deployment runbook (spec S2 §4)

Provider-neutral: an Ubuntu 24.04 VPS with 2 GB or more. Named
examples and prices sit in spec S2 ruling 1. The owner runs each
command here — the API key stays out of transcripts.

## 1. The box

```
adduser --system --group --home /srv/starvector starvector
apt update && apt install -y caddy restic ufw unattended-upgrades
```

Install `uv` (the Python runner) as root:
`curl -LsSf https://astral.sh/uv/install.sh | sh` and put the
binary at `/usr/local/bin/uv`. It builds the environment in step 2.
The units then start the environment's own interpreter.

## 2. The app

```
sudo -u starvector git clone <repo> /srv/starvector/app
cd /srv/starvector/app
sudo -u starvector uv sync                 # writes .venv
sudo -u starvector mkdir -p store data     # the writable roots
cd web && sudo -u starvector pnpm install && sudo -u starvector pnpm build
```

The store and the pool data live in the app directory
(`store/`, `data/`) — the paths the units mark writable. The two
directories must be there before the unit starts: systemd refuses
a `ReadWritePaths` entry that is missing. Copy the pool artifacts for the release the
server config names into `data/`.

## 3. Configuration

Two files with two different readers:

```
mkdir -p /etc/starvector
chown root:starvector /etc/starvector && chmod 750 /etc/starvector

cp deploy/env.example /etc/starvector/env          # add the key
chmod 600 /etc/starvector/env                      # root reads it

# the server process reads this one as the starvector user
$EDITOR /etc/starvector/service.json
chown root:starvector /etc/starvector/service.json
chmod 640 /etc/starvector/service.json
```

systemd reads `EnvironmentFile` as root before it drops
privileges, thus the key file stays root-only. The server process
opens the other file as the `starvector` user, thus the group
needs read permission on it.

`service.json` holds `config_version`, `player`, `scoring_config`,
`data_root`, `store_root`, `port`, and (optional) `closes_at_utc`,
the daily rollover hour in UTC: the countdown shows it, and the
rollover timer closes each day at it (spec BR1 §3). Paths are relative to the unit's working
directory (`/srv/starvector/app`).

## 4. The units and the edge

```
cp deploy/starvector.service deploy/starvector-dev.service \
   /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now starvector
cp deploy/Caddyfile /etc/caddy/Caddyfile   # set the real domain
systemctl reload caddy
```

Point the domain's A and AAAA records at the box first — Caddy
fetches the certificate when the first browser arrives.

`starvector-dev.service` stays stopped. §7 starts it when the
operator needs the console.

Mint the first player (§7) before the first start: a server with no
player record refuses to start without `--dev` or `--single-player`
(spec BR1 §4).

The daily rollover, after a week of days moved by hand:

```
cp deploy/starvector-day.service deploy/starvector-day.timer \
   /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now starvector-day.timer
```

Keep the timer's `OnCalendar` hour equal to `closes_at_utc`. The
deployment guides (section 14) have the full procedure. The console's
Automatic days tab pauses and resumes the timer and shows its runs,
and its `Do what is due now` button does the due steps at the moment
you press it. The unit keeps its lock and its run
records in `store/rollover/` (spec BR1 §7.2), thus it has write
access to the store.

## 5. Firewall and updates

```
ufw default deny incoming
ufw default allow outgoing
ufw limit OpenSSH
ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw enable
dpkg-reconfigure -plow unattended-upgrades
```

Set `Automatic-Reboot "true"` and `Automatic-Reboot-Time "04:30"`
in `/etc/apt/apt.conf.d/50unattended-upgrades` — out of the game
window. The server rebuilds its resident context on start.

## 6. Backup

```
cp deploy/restic-env.example /etc/starvector/restic-env  # fill in
chmod 600 /etc/starvector/restic-env
cp deploy/restic-backup.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now restic-backup.timer
```

The units load `/etc/starvector/restic-env` on their own. A
command typed by hand needs it too — restic reads the repository
and the password from the environment:

```
sudo bash -c 'set -a; . /etc/starvector/restic-env; set +a; restic init'
sudo bash -c 'set -a; . /etc/starvector/restic-env; set +a; \
    restic snapshots'
```

Use a remote credential that cannot delete (spec S2 §4). Do the
`restic restore` drill after the first snapshot and compare
`store/` byte for byte:

```
sudo bash -c 'set -a; . /etc/starvector/restic-env; set +a; \
    restic restore latest --target /tmp/restore-drill'
diff -r /srv/starvector/app/store /tmp/restore-drill/srv/starvector/app/store
```

## 7. The operator plane

The public process runs without `--dev`, thus its console
surfaces answer 404 and `/image` serves revealed targets alone.
The proxy also answers 404 on `/dev.html`, `/api/dev`,
`/api/dev/*`, the three day lifecycle paths, the player mint, and
the results reader `/api/ops/*`.
It keeps refusing `/dev` and `/ui/dev.js`, which name nothing in
the server since the hand-written pages retired. A caller that
tries a console-shaped path meets a 404 and not the app shell.

The mint wants the proxy refusal because of something the others
do not have. It is the one operator path that needs no `--dev`,
thus it is live in the public process, and that process must hold
the operator token. The bearer alone then stands in front of it.
The console reaches the mint through the tunnel and the
command-line path runs on the box, thus the public edge wants no
path to it.

The console runs against the dev unit, which binds
`127.0.0.1:8001`. The proxy holds no path to that port:

```
# on the box
systemctl start starvector-dev

# on the laptop
ssh -L 8001:127.0.0.1:8001 <box>
cd web && VITE_PROXY_TARGET=http://127.0.0.1:8001 pnpm dev
# open http://localhost:5173/dev.html

# on the box, at the end of the work
systemctl stop starvector-dev
```

The two processes share the store. The store's `write_once_json`
records and its guarded status moves keep that safe, and the
operator moves days from the dev unit.

### The operator token

The tunnel and the proxy refusal are two layers. The bearer token
is the third. It holds when the other two are misconfigured. Put
`STARVECTOR_OPERATOR_TOKEN` in `/etc/starvector/env` before the
first invite goes out. **The server refuses to start when the
store holds player records and this token is not set.**

The token stands in front of the three day lifecycle paths, the
console surfaces, and the player mint. The console asks for it in
a field and keeps it in the browser's local storage.

A check that does not agree on a console surface answers the same
404 that the surface gives with no `--dev` flag. That is
deliberate: a 401 there tells an outsider that this deployment
runs the flag. The lifecycle paths answer 401, because they are in
each process and there is nothing to hide.

### Inviting a player

```
# on the box, as the starvector user
cd /srv/starvector/app
.venv/bin/python -m service.players \
    --service-config /etc/starvector/service.json \
    --origin https://<domain> \
    mint <name> --display-name "<label>"
```

The invite prints one time. The store keeps its digest alone, thus
an invite nobody can find wants `rotate` and not a lookup. `list`
shows the roster with no secret in it, `revoke` stops a player and
ends their sessions, and `restore` puts one back with a new invite.
`sessions <name>`, `signout <name>`, and `prune` read and end
sessions (spec BR1 §4). A `rotate` leaves each signed-in device
signed in.

### The results index

The results index is a SQLite copy of the store for programs to
read (spec BR1 §5). It lives in `data/index/` and a command makes it
again from the store at each moment, thus it needs no backup:

```
.venv/bin/python -m service.index \
    --service-config /etc/starvector/service.json build
.venv/bin/python -m service.index \
    --service-config /etc/starvector/service.json verify
STARVECTOR_EXPORT_SALT=<a secret> .venv/bin/python -m service.index \
    --service-config /etc/starvector/service.json \
    export --out /tmp/research --format csv
```

`sqlite3 -readonly` reads the file directly. Through the tunnel, a
script reads the revealed trial rows with the bearer:
`GET /api/ops/trials?from=2026-09-01&to=2026-09-30&player=<name>`.

## 8. The smoke checklist

- The site answers on HTTPS with the app. `/history`,
  `/leaderboard`, and the other app paths load when typed into the
  address bar. `/assets/*` for an incorrect hash answers 404, not
  HTML.
- `curl -s -o /dev/null -w "%{http_code}" https://<domain>/dev.html`
  → 404. The same for `/api/dev`, `/api/dev/days`,
  `/api/day/close`, `/api/players`, and `/api/ops/trials`.
- `curl https://<domain>/image/<an unrevealed image id>` → 404.
- **`curl -sI https://<domain>/join/bogus` → the server's 401, and
  the content type is JSON and not `text/html`.** HTML here means
  the invite path fell to the app fallback. The server then sees no
  invite, and no invite URL can sign anybody in. No test in the
  repository sees this one, because it lives in the edge
  configuration alone.
- With the dev unit started and the tunnel up, the console shows
  the days, the automatic days, the players with their devices, and
  the results database (spec BR1 §7).
- `systemctl reboot` → the site is back with no hand work.
- `restic snapshots` shows the daily entries, and the `restore`
  drill passes.
