# Deployment runbook (spec S2 §4)

Provider-neutral: an Ubuntu 24.04 VPS with 2 GB or more. Named
examples and prices sit in spec S2 ruling 1. The owner runs each
command here — the API key stays out of transcripts.

## 1. The box

```
adduser --system --group --home /srv/starvector starvector
apt update && apt install -y caddy restic ufw unattended-upgrades
```

Install `uv` (the Python runner) as root or the deploy user:
`curl -LsSf https://astral.sh/uv/install.sh | sh` and put the
binary at `/usr/local/bin/uv`.

## 2. The app

```
sudo -u starvector git clone <repo> /srv/starvector/app
cd /srv/starvector/app && sudo -u starvector uv sync
cd web && pnpm install && pnpm build       # or copy web/dist in
```

The store and the pool data live in the app directory
(`store/`, `data/`) — the paths the systemd unit marks writable.
Copy the pool artifacts for the release the server config names.

## 3. Configuration

```
mkdir -p /etc/starvector && chmod 700 /etc/starvector
cp deploy/env.example /etc/starvector/env          # add the key
chmod 600 /etc/starvector/env
```

Write `/etc/starvector/service.json` — the server config with
`config_version`, `player`, `scoring_config`, `data_root`,
`store_root`, `port`, and (optional) `closes_at_utc` for the
countdown. Paths are relative to the unit's working directory.

## 4. The unit and the edge

```
cp deploy/starvector.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now starvector
cp deploy/Caddyfile /etc/caddy/Caddyfile   # set the real domain
systemctl reload caddy
```

Point the domain's A and AAAA records at the box first — Caddy
fetches the certificate when the first browser arrives.

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
restic init                                # one time
cp deploy/restic-backup.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now restic-backup.timer
```

Use a remote credential that cannot delete (spec S2 §4). Do the
`restic restore` drill after the first snapshot:
`restic restore latest --target /tmp/restore-drill`, then compare
`store/` byte for byte.

## 7. The operator plane

The proxy answers 404 on `/dev.html`, `/api/dev/*`, `/history`,
and the day lifecycle paths. The operator reaches them through a
tunnel:

```
ssh -L 8000:127.0.0.1:8000 <box>
# then, on the laptop:
cd web && VITE_PROXY_TARGET=http://127.0.0.1:8000 pnpm dev
# open http://localhost:5173/dev.html
```

The earlier console page also serves at `/dev` when the unit runs
with `--dev` — keep the flag off in production and move days from
the tunnel.

## 8. The smoke checklist

- The site answers on HTTPS with the app. `/assets/*` for an
  incorrect hash answers 404, not HTML.
- `curl -s -o /dev/null -w "%{http_code}" https://<domain>/dev.html`
  → 404. The same for `/api/dev/days` and `/api/day/close`.
- Through the tunnel, the console lists the days.
- `systemctl reboot` → the site is back with no hand work.
- `restic snapshots` shows the daily entries, and the `restore`
  drill passes.
