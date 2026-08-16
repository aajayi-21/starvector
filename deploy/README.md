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
`data_root`, `store_root`, `port`, and (optional) `closes_at_utc`
for the countdown. Paths are relative to the unit's working
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
The proxy also answers 404 on `/dev.html`, `/dev`, `/ui/dev.js`,
`/api/dev`, `/api/dev/*`, and the three day lifecycle paths.

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
shows the roster with no secret in it, `revoke` stops a player,
and `restore` puts one back with a new invite.

## 8. The smoke checklist

- The site answers on HTTPS with the app. `/history` and the other
  app paths load when typed into the address bar. `/assets/*` for
  an incorrect hash answers 404, not HTML.
- `curl -s -o /dev/null -w "%{http_code}" https://<domain>/dev.html`
  → 404. The same for `/api/dev`, `/api/dev/days`, and
  `/api/day/close`.
- `curl https://<domain>/image/<an unrevealed image id>` → 404.
- **`curl -sI https://<domain>/join/bogus` → the server's 401, and
  the content type is JSON and not `text/html`.** HTML here means
  the invite path fell to the app fallback. The server then sees no
  invite, and no invite URL can sign anybody in. No test in the
  repository sees this one, because it lives in the edge
  configuration alone.
- With the dev unit started and the tunnel up, the console lists
  the days.
- `systemctl reboot` → the site is back with no hand work.
- `restic snapshots` shows the daily entries, and the `restore`
  drill passes.
