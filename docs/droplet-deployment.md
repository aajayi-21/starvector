# DigitalOcean droplet deployment runbook

One DigitalOcean droplet serves a live, invite-only test of Starvector
to the internet. This page is the full path from an empty account to a
played day. It follows `deploy/README.md`, the provider-neutral
runbook. It adds what a droplet wants: the plan, the first-login user
work, a firewall that faces the internet, and the recovery console.

**Angle brackets mark a placeholder.** `<droplet-ip>`, `<domain>`,
`<owner>`, `<repo>`, and `<your-handle>` each want your own value.
The brackets come out with the text. Two steps stop hard when a
placeholder stays. Bash reads `<` and `>` as redirections in
section 8. Section 10 then gives the server a `player` field that it
refuses.

`docs/home-deployment.md` is this same runbook for a PC on a home
network. Sections 8 to 17 of the two pages agree almost word for word.
The network work is where they part, and section 6 of the home page
will lock you out of a droplet. Read section 5 and section 6 here
before you type anything.

## 1. What this run is

Four facts frame the setup.

- **The app is invite-only by construction (spec M1).** There is no
  open registration. A browser with no invite cookie gets the invite
  gate, and each player surface answers 401. "Public" means the site
  answers — play is for the testers you invite.
- **This run serves the development pool.** The release is
  `dev-wit-002`: 204 images, marked `dev_only`. The scores are
  development numbers, and `CLAUDE.md` section 7 says they do not go
  public. This run is for invited testers, not for the public.
- **The production pool is a subsequent phase, and nothing here waits
  for it.** When it lands, this same droplet serves it after one data
  copy, one config edit, and one `systemctl restart` (section 16).
- **The droplet faces the internet with no router in front of it.** A
  home box sits behind a router that forwards three ports and hides
  port 22. A droplet answers on each port its firewall opens. The
  firewall on the box is thus the first layer here and not the second,
  and port 22 is reachable from anywhere.

## 2. The droplet plan

Spec S2 ruling 1 names the target: a DigitalOcean basic droplet, US,
2 GiB, about USD 12 each month. Set these at creation.

| item | value | why |
|---|---|---|
| image | Ubuntu 24.04 (LTS) x64 | the deploy stack — the systemd units, Caddy, `ufw` — targets this system |
| plan | Basic, 2 GB memory, 1 vCPU, 50 GB disk | spec S2 ruling 1 |
| region | closest to your testers | Caddy answers the players, and the daily close posts to OpenRouter |
| authentication | SSH key | a password on a public address meets scanners in minutes |
| hostname | a name you can read on a bill | |

The 1 GB plan, about USD 6, is below the spec. The scoring context of
the development pool is 40 MB, thus the served app fits it. `uv sync`
is the step that fails first, because it unpacks wheels in memory. Add
virtual memory (section 6) with that plan.

Two creation options are worth a word. IPv6 is free and wants one more
DNS record (section 7). The droplet backup add-on makes machine
snapshots. It is a convenience and it is not the store backup.
Section 15 sets up the store backup, which is the one that matters.

## 3. The storage budget

Measured 2026-08-17 and checked against the repository 2026-08-19:

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

A 50 GB droplet disk holds this with much room. The torch stack does
not install here: it belongs to the optional `local-cuda` and
`local-xpu` dependency groups, and the base `uv sync` stays near
0.3 GB.

Room for what follows: a 20,000-image production pool, fetched at
768 px with rejected candidates pruned, is about 2.3 GB (measured
estimate, 2026-08-17). Its resident arrays want 4 GB of memory or more
at start, thus a production pool wants a larger plan and not a larger
disk.

## 4. Keys and secrets

There are four secrets in the app. No other credential is in the
system. Your SSH key is a fifth, and it is yours and not the
deployment's.

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
- The spend cap limits a leaked OpenRouter key. Set it before the key
  goes on the box.
- The server refuses to start when player records are stored and the
  operator token is not set. That refusal is deliberate — set the
  token from the start.

## 5. First login and your admin user

**This section holds the first step that can lock you out. Read it
before you type.**

DigitalOcean put your public key on the `root` account and on no
other. Each command in the sections that follow runs with `sudo` from
an admin user, and section 5.4 stops root login. Make the admin user
first, check it, and change `sshd` last.

**5.1 — Sign in as root.**

```
ssh root@<droplet-ip>
```

**5.2 — Make your admin user and give it your key.**

```
adduser you
usermod -aG sudo you
rsync -a --chown=you:you /root/.ssh /home/you/
```

**5.3 — Keep the root session open.** In a second terminal on your
development machine:

```
ssh you@<droplet-ip>
sudo -v
```

The two commands must work. A failure at this point, with the root
session closed, makes the recovery console (section 18) the only door
back in.

**5.4 — Stop password login and root login.**

```
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sshd -t
sudo systemctl restart ssh
```

`sshd -t` reads the file and raises on a syntax error. With no check,
a typo stops the daemon and shuts the door.

**5.5 — Close the root session.** Open one more session as `you` to
make sure the new config lets you in.

## 6. The box baseline

```
sudo apt update
sudo apt install -y caddy restic ufw unattended-upgrades rsync
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo mv ~/.local/bin/uv /usr/local/bin/uv
sudo adduser --system --group --home /srv/starvector starvector
sudo chmod 755 /srv/starvector
```

`adduser --system` makes the home directory group-restricted, and the
`chmod` opens it for traverse. Two other users must walk through it:
your admin user, for each `cd` in this page, and `caddy`, which serves
`/srv/starvector/app/web/dist` from disk. The deploy key stays shut,
because `/srv/starvector/.ssh` is 700 in its own right.

With the tighter mode, section 8 answers `cd: Permission denied` and
Caddy answers 403 on each asset. The second one is quiet: `/api` keeps
working, because that path goes through uvicorn and not the disk.

Caddy ships from its own apt repository and not from Ubuntu's
archive. Check with `apt-cache policy caddy` before the install. When
the candidate is `(none)`, add the repository from the instructions at
`caddyserver.com/docs/install` and then `apt update` again.

### The firewall

```
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw limit OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```

**Do not copy the firewall of the home page.** It opens port 22 to a
home subnet alone, with
`ufw allow from <your-lan-subnet> to any port 22 proto tcp`. A droplet
has no such subnet, because your SSH arrives from the public internet.
That rule, with `ufw enable` behind it, ends your session, and it
makes the recovery console the only door back in.

`ufw limit OpenSSH` is the droplet rule. It opens port 22 and it caps
an address that opens six connections in 30 seconds. The key-only
config from section 5.4 is what shuts the door. The cap keeps the
attempts down.

### More virtual memory, for the 1 GB plan alone

The 1 GB plan runs `uv sync` near its memory limit. A 2 GB `/swapfile`
gives it room, and the `/etc/fstab` line keeps it after a reboot. Skip
this on the 2 GB plan.

```
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Automatic updates, with the reboot out of the game window

```
sudo dpkg-reconfigure -plow unattended-upgrades
```

Set `Automatic-Reboot "true"` and `Automatic-Reboot-Time "04:30"` in
`/etc/apt/apt.conf.d/50unattended-upgrades`. The server builds its
resident context again at each start.

### A second layer

DigitalOcean's cloud firewall stands in front of the droplet and
answers first. It is this page's answer to the home page's router. A
good rule set: inbound TCP 22 from your own address alone, and TCP 80,
TCP 443, and UDP 443 from anywhere. Your home address changes, thus
keep `ufw limit OpenSSH` on the box too.

## 7. Point the domain at the droplet

1. **DNS.** An A record for your domain at the droplet's IPv4 address.
   Add an AAAA record at its IPv6 address when you turned IPv6 on. On
   Cloudflare, keep the records DNS-only (grey cloud), thus the box
   gets its own certificate.
2. **Nothing else.** Section 7 of the home page has four more items:
   dynamic DNS, port forwarding, the CGNAT test, and NAT loopback. A
   droplet has a static public address and no router in front of it,
   thus each of the four drops.
3. **Wait for the record.** `dig +short <domain>` must answer the
   droplet's address before the first HTTPS visit. Caddy fetches the
   certificate at that visit, and a visit before DNS resolves counts
   against the certificate authority's failure limit.

## 8. Get the code onto the box

A read-only deploy key, not a GitHub login. The private half stays on
the box, opens one repository, and cannot write.

The four steps below run in sequence. Step 8.2 is a stop: it happens
in a browser, and the clone in 8.4 fails when you skip it.

**8.1 — Make the key on the box.**

```
sudo -u starvector mkdir -p /srv/starvector/.ssh
sudo -u starvector chmod 700 /srv/starvector/.ssh
sudo -u starvector ssh-keygen -t ed25519 \
    -f /srv/starvector/.ssh/id_ed25519 -N ""
sudo cat /srv/starvector/.ssh/id_ed25519.pub
```

**8.2 — Add the key to GitHub. Stop here and do this first.** In the
repository, open Settings, then Deploy keys, then Add deploy key.
Paste the one line that 8.1 printed, and keep write access off. A
clone before this step answers `Permission denied (publickey)`.

**8.3 — Point ssh at the key, and check it.**

```
sudo -u starvector tee /srv/starvector/.ssh/config >/dev/null <<'CFG'
Host github.com
  IdentityFile /srv/starvector/.ssh/id_ed25519
  IdentitiesOnly yes
CFG
sudo -u starvector chmod 600 /srv/starvector/.ssh/config
sudo -u starvector ssh -o StrictHostKeyChecking=accept-new -T git@github.com
```

The `ssh` command proves the key and records the host fingerprint, and
the clone then wants no answer at a prompt. Success is
`Hi <owner>/<repo>! You've successfully authenticated, but GitHub does
not provide shell access.` GitHub gives no shell to a deploy key, thus
the second half of that message is correct and not a failure.

**8.4 — Clone and build the environment.** `<owner>` and `<repo>` are
placeholders. Replace them with your own names, angle brackets and
all: bash reads `<` and `>` as redirections, and the command fails
before git starts.

```
sudo -u starvector git clone \
    git@github.com:<owner>/<repo>.git /srv/starvector/app
cd /srv/starvector/app
sudo -u starvector /usr/local/bin/uv sync
sudo -u starvector mkdir -p store data
```

`uv sync` installs the base set — about 0.3 GB. The units refuse to
start while `store/` or `data/` is missing, thus the `mkdir` is part
of the setup.

The `cd` wants the `chmod` from section 6. With no traverse
permission it answers `Permission denied`, and the two commands after
it then run in your own home directory. `uv` reports a `uv.toml` it
cannot read, and `mkdir` cannot write. The `chmod`, and then these
commands again, clears each of the three.

The clone brings the release records, the preparation records, and the
scoring configs, which are all tracked in git. The `data/` tree is
git-ignored, and section 9 copies it.

## 9. Ship the app build and the pool

The box builds nothing. The web app builds on your development
machine, and the pool artifacts come from there too — the same pattern
serves a subsequent production pool.

Three artifact trees move, and the scoring config
`configs/scoring/dev-wit-mixed-3.json` chains through each of them:

| tree | on disk | what it holds |
|---|---|---|
| `data/preparation/9644fac1` | 32 MB | the prepared release `dev-wit-002-9644fac1` |
| `data/commonness` | 420 KB | the commonness tables |
| `data/images` | 419 MB | `raw` photographs and `linedraw` renders |

`data/preparation/b89d8614` is the earlier `dev-wit-001` release,
207 MB, and it does not move.

Build the app, from the repository root:

```
cd web && pnpm install && pnpm build && cd ..
```

The `cd ..` at the end matters. Each `rsync` below names a path from
the repository root. A shell that stays in `web/` reads `web/dist/` as
`web/web/dist/`, and it stops with `No such file or directory`.

Make the staging directories on the box. `rsync` makes the last part
of a destination path and no parent above it, thus a missing
`staging/` stops it with `mkdir ... failed`:

```
ssh you@<droplet-ip> 'mkdir -p staging/dist staging/data/preparation'
```

The `preparation/` level in that command is load-bearing. The server
reads a stage at
`<data_root>/preparation/<pool>/<prep>/<stage>`
(`pool/preparation/manifest.py`), and a source path with no trailing
slash copies the directory itself and not its parents. The release
tree thus wants a destination that names `preparation/`, and the other
two trees do not.

```
rsync -a web/dist/ you@<droplet-ip>:staging/dist/
rsync -a --info=progress2 \
    data/preparation/9644fac1 you@<droplet-ip>:staging/data/preparation/
rsync -a --info=progress2 \
    data/commonness data/images you@<droplet-ip>:staging/data/
```

This is 0.42 GB across the internet and not across a LAN, thus it
takes minutes and not seconds. A dropped connection is safe: `rsync`
resumes when you type the same command again.

On the box:

```
sudo rsync -a --chown=starvector:starvector \
    ~/staging/dist/ /srv/starvector/app/web/dist/
sudo rsync -a --chown=starvector:starvector \
    ~/staging/data/ /srv/starvector/app/data/
```

Check the layout before you remove the staging copy. This file is the
first artifact the server opens, and a day stops at the open when it
is missing:

```
cd /srv/starvector/app/data/preparation/9644fac1/c2000c97
ls -l p00-intake/records.jsonl
cd - && rm -r ~/staging
```

A tree at `data/9644fac1` and not at `data/preparation/9644fac1` is
the destination error above. Remove the misplaced copy and send it
again.

Do not copy your development `store/`. Those days were experiments.
The box starts its own history, and no other machine holds a copy of
its store.

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

Replace `<your-handle>` below before you send the file. The server
reads `player` at each start, and a bracket in it stops the unit
(`service/config.py`).

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
lowercase letters, digits, and hyphens, 1 to 64 of them. The value
becomes a file name in the store. The server thus checks it against
`^[a-z0-9-]{1,64}$` and refuses anything else: no capitals, no
underscores, no spaces. After the first mint, sessions name the caller
and this field is the fallback alone. `closes_at_utc`
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

The journal must show `Uvicorn running on http://127.0.0.1:8000`. A
`refused:` line names the field of `service.json` that the server does
not accept, and the unit then starts again each two seconds. Stop it with
`sudo systemctl stop starvector`, correct the file, and start it
again. The dev unit (`starvector-dev.service`) stays stopped —
section 14 starts it for console work.

The edge:

```
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile        # set your real domain
sudo systemctl reload caddy
sudo -u caddy test -r /srv/starvector/app/web/dist/index.html \
    && echo "caddy reads the app"
```

The last command is the traverse check from section 6. No answer there
means Caddy answers 403 on each asset while `/api` keeps working, and
no journal names the cause.

The uvicorn process binds `127.0.0.1` alone. The doors from the
internet are Caddy's 80 and 443, and SSH on 22.

## 12. Smoke checks

The home page asks you to test away from your own network. A home
router can answer its own public address differently. A droplet has no
such behaviour, thus each check here runs from anywhere.

- `https://<domain>/` loads the app and shows the invite gate. The
  gate is success: no cookie, no play.
- `curl -sI https://<domain>/join/bogus` answers 401 with a JSON
  content type. HTML here means the invite path fell to the app shell,
  and no invite URL can sign anybody in.
- `curl -s -o /dev/null -w "%{http_code}" https://<domain>/dev.html`
  answers 404. The same for `/api/dev`, `/api/day/close`, and
  `/api/players`.
- `https://<domain>/leaderboard` and `https://<domain>/history` load
  when typed into the address bar.
- `sudo systemctl reboot` — the site is back with no hand work.

One warning for each test that follows: use the HTTPS domain, not
`http://<droplet-ip>`. The session cookie holds the `Secure` transport
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

The invite prints one time — send it, then forget it. `list` shows the
roster with no secret in it. `rotate` replaces an invite nobody can
find, `revoke` stops a player, and `restore` brings one back.

Mint your own player first, and open your own invite. The first mint
switches access control on for the world. From then on, each player
surface wants a session, and the operator surfaces want the bearer
token.

## 14. Run a day

The loop: open, players play, close (this step spends through
OpenRouter), reveal. Each step is an operator action.

**The console** — the full view: day browser, rankings, the invite
panel. On the box: `sudo systemctl start starvector-dev`. On your
development machine:

```
ssh -L 8001:127.0.0.1:8001 you@<droplet-ip>
# in a second terminal
cd web && VITE_PROXY_TARGET=http://127.0.0.1:8001 pnpm dev
```

Open `http://localhost:5173/dev.html` and paste the operator token
into its field. Move the day with the control row. Stop the dev unit
at the end: `sudo systemctl stop starvector-dev`.

**The command line** — fast, on the box. The public process holds the
key and the token from its environment file, thus a localhost `curl`
with the bearer is sufficient:

```
sudo bash -c '. /etc/starvector/env; curl -s -X POST \
  -H "Authorization: Bearer $STARVECTOR_OPERATOR_TOKEN" \
  http://127.0.0.1:8000/api/day/open'
```

The same command with `/api/day/close` and `/api/day/reveal`. The
close encodes the stored submissions and can run for a minute. Its answer
names the row count and no score. To read the day with no console:

```
sudo -u starvector .venv/bin/python -m service.day \
    --service-config /etc/starvector/service.json status
```

A close at the development pool costs cents: some embedding posts for
each submission, cached for repeats. The lifecycle is deliberately
hand-driven. After the first week runs cleanly by hand, a systemd
timer around the two `curl` commands can automate it. Read the close
output for that first week.

## 15. Backups

The store is permanent play records (`CLAUDE.md` invariant I4). Back
it up off the box from the first day. A droplet disk is not yours: a
destroyed droplet takes its disk with it, and the store has no second
copy anywhere.

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
compromised box cannot delete its own history. Send the snapshots to a
provider that is not DigitalOcean. One account problem then cannot
remove the droplet and the backup together. Do the `restic restore`
drill after the first snapshot — the commands are in
`deploy/README.md` section 6.

## 16. Update the deployment

Code and pool artifacts move in one direction: development machine to
box.

```
# on the box
cd /srv/starvector/app
sudo -u starvector git pull
sudo -u starvector /usr/local/bin/uv sync
sudo systemctl restart starvector

# on the development machine, when the web app changed
cd web && pnpm build
rsync -a dist/ you@<droplet-ip>:staging/dist/

# then on the box
sudo rsync -a --chown=starvector:starvector \
    ~/staging/dist/ /srv/starvector/app/web/dist/
```

Two standing rules from the working agreement. Do not edit stored
days, earlier configs, or earlier releases — stored days rescore
against them forever. When the production pool lands, its release is a
new preparation adjacent to the earlier one. The move is one `rsync` of
new artifacts, one `service.json` edit, and one `systemctl restart`.

## 17. What is open and what is closed

| surface | exposure |
|---|---|
| 80 and 443 (Caddy) | the internet — app shell, `/api`, `/image`, `/join` |
| lifecycle, console, and mint paths | blocked at the edge (404) and bearer-gated in the process |
| 8000 and 8001 (uvicorn) | `127.0.0.1` alone |
| 22 (SSH) | the internet, keys alone, with a connection cap — and your address alone with a cloud firewall |
| player surfaces | 401 with no invited session |
| secrets | root-read file, spend-capped key, one-time invites |
| backups | off-box, append-only credential, not at this provider |

Each layer holds alone, on purpose. The edge blocks the operator
paths. The process gates them again on the bearer, and the dev unit is
not started at all in the usual condition.

Port 22 is the one row that reads differently from the home page,
which keeps SSH on the LAN and forwards nothing. Here the door is
open to the internet and the key is what shuts it. That is why
section 5.4 is not optional.

## 18. When you cannot sign in

A firewall rule or an `sshd` edit can close the door. DigitalOcean's
recovery console reaches the droplet through the hypervisor and not
through the network, thus it answers when SSH does not.

1. In the control panel, open the droplet and open Access, then
   `Launch Droplet Console`.
2. Sign in as `you` with the password `adduser` asked for in section
   5.2. When you do not have it, use `Reset Root Password` in the same
   panel. It mails a one-time password for `root`, and the console
   asks for a new one at the first login. `PermitRootLogin no` blocks
   root through SSH alone, and the console is not SSH.
3. Remove the change. For a firewall lockout:
   `ufw allow OpenSSH` or `ufw disable`. For an `sshd` typo:
   `sshd -t` names the line, then `systemctl restart ssh`.
4. Sign in again through SSH before you close the console.

A cloud firewall lockout wants no console at all: edit the rule in the
control panel, and it takes effect in seconds.
