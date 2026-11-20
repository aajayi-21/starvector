# Production cutover

**Added:** 2026-11-19.
**Purpose:** one sequence that moves a deployed box of the test season to
the production pool. Four changes go in together, and their sequence is
important:

1. The pool changes to `prod-wit-001-ba15d5b3` (1,393 images, spec PP1),
   with the scoring config `configs/scoring/prod-wit-mixed.json`.
2. The store starts again with no player (spec R1 ruling D9).
3. The server picks each target from a drand pulse after the close
   (spec VP1 ruling D8).
4. Sign-up opens to each visitor (spec A2).

The steps come from `deploy/README.md` §8 and §9, and from sections 9,
13, and 15a of `docs/droplet-deployment.md`. Those pages hold the causes.
This page holds the sequence, and the one step that no spec wrote: the
new store.

**You do each step on the box.** The provider key and the pepper stay
out of each transcript. `<box>` is your SSH address of the box, and
`<domain>` is the public domain.

---

## 1. Before you set the date

- **Two rulings of spec PL1 §10 are open.** Item 3: does the copy use
  the words `remote viewing`? Item 4: are the limit values in
  `service/limits.py` correct for a public site?
- **The spend cap.** With sign-up open, the practice limits let each
  player score 30 practice sketches an hour, and let all players together
  score 600 an hour. That is 14,400 practice sketches a day at the limit.
  Set the OpenRouter spend cap to a value that you accept for that
  day.
- **The cutover time.** Select a day. The last test day closes at
  `closes_at_utc`, and the cutover starts after its reveal. Plan two
  hours. The first production day opens at the end of the cutover and
  closes at the next `closes_at_utc` (00:00 UTC, ruling of 2026-11-13).

## 2. Copy the pool and the app build (on a day before)

The copy adds new directories adjacent to the test-season data and replaces
nothing that the server reads. The box keeps the test season until
section 4.

On the development machine, from the repository root, build the app:

```
cd web && pnpm install && pnpm build && cd ..
```

Write the names of the 1,393 pool photographs to a file, from the
release manifest.
The server reads a photograph at `data/images/raw/<first two
characters>/<image id>` (`pool/artifacts.py`):

```
python3 -c 'import json
for line in open("data/curation/f655d713/d9c7558d/s09-release/manifest.jsonl"):
    i = json.loads(line)["image_id"]
    print(f"images/raw/{i[:2]}/{i}")' > /tmp/prod-wit-001-images.txt
wc -l /tmp/prod-wit-001-images.txt      # 1393
```

Send the four data trees and the build to a staging directory on the
box:

```
ssh <box> 'mkdir -p staging/dist staging/data/preparation/ba15d5b3 staging/data/curation/f655d713'
rsync -a web/dist/ <box>:staging/dist/
rsync -a --info=progress2 \
    data/preparation/ba15d5b3/ea1ee02b <box>:staging/data/preparation/ba15d5b3/
rsync -a data/curation/f655d713/d9c7558d <box>:staging/data/curation/f655d713/
rsync -a data/commonness <box>:staging/data/
rsync -a --info=progress2 --files-from=/tmp/prod-wit-001-images.txt \
    data/ <box>:staging/data/
```

| tree | on disk | what reads it |
|---|---|---|
| `data/preparation/ba15d5b3/ea1ee02b` | 173 MB | the scoring context |
| `data/curation/f655d713/d9c7558d` | 76 MB | the credit line of the reveal, and the public snapshot (spec R1) |
| `data/commonness` | 1 MB | Layer 5 |
| 1,393 files in `data/images/raw` | 538 MB | `/image` and the reveal |

On the box, copy the data to the app directory. Keep `staging/dist`
for section 4:

```
sudo rsync -a --chown=starvector:starvector \
    ~/staging/data/ /srv/starvector/app/data/
ls /srv/starvector/app/data/preparation/ba15d5b3/ea1ee02b/p00-intake/records.jsonl
find /srv/starvector/app/data/curation/f655d713/d9c7558d/s09-release -name manifest.jsonl
```

## 3. The secrets (on a day before)

In `/etc/starvector/env` (`sudo nano /etc/starvector/env`):

- `STARVECTOR_OPERATOR_TOKEN` has a value.
- `STARVECTOR_PASSWORD_PEPPER` has a value. Make it with
  `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, and
  put a copy in your password manager. If the pepper is gone, each
  stored password stops.
- `STARVECTOR_ALTCHA_KEY` has a value (spec PW1 §3.4). Make it with
  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. It
  needs no copy: a new value makes each open sign-up challenge refuse
  one time.
- No value has quotation marks. systemd removes them, but `sv` reads
  each value as it is in the file, and the operator token then does not
  agree.

The server reads the file at its next start, in section 4.

## 4. The cutover

### 4.1 Stop the days

On the day before, pause the schedule. A paused timer moves no day, thus
it does not open a test day at the next `closes_at_utc`:

```
sudo sv schedule pause --note "production cutover"
```

After `closes_at_utc`, close and reveal the last test day by hand, then
stop the timer:

```
sudo sv day close
sudo sv day reveal
sudo sv status                     # the latest day is revealed, and no day is open
sudo systemctl disable --now starvector-day.timer
sudo systemctl stop starvector-dev
```

The pause alone does not stop the days here. The pause is a
record in the store, and the new store of step 4.4 does not have it. The
day unit also starts the server when it starts (`Requires=`).

### 4.2 Back up the test season

```
sudo systemctl start restic-backup.service
sudo bash -c 'set -a; . /etc/starvector/restic-env; set +a; restic snapshots'
```

Keep this snapshot. It is the backup of the test-season store.

### 4.3 Stop the server and update the code

```
sudo systemctl stop starvector
cd /srv/starvector/app
sudo -u starvector git pull
sudo -u starvector /usr/local/bin/uv sync
sudo rsync -a --chown=starvector:starvector \
    ~/staging/dist/ /srv/starvector/app/web/dist/
rm -r ~/staging
```

### 4.4 Start the store again

Raw inputs are permanent (`CLAUDE.md` invariant I4), thus the test-season
store moves to an archive and is not deleted. Five entries of `data/`
are caches that the server made from that store. They move with it:

- `data/day-scores/`, `data/skill/`, and `data/leaderboards/`, the files
  of the boards.
- `data/skill-board.*.json`, the skill board.
- `data/index/`, the results index.

These caches are keyed by the scoring config hash alone, not by the
store. If test days on the box used `prod-wit-mixed.json`, a reveal
on the new store adds its day to the skill pairs of the test season.
Players of the test season then show on the new boards, and a new
account with an earlier username gets their trials. Move the caches in
each condition: the server makes them again from the new store.

```
cd /srv/starvector/app
sudo -u starvector mkdir -p /srv/starvector/archive/test-season/data
sudo -u starvector mv store /srv/starvector/archive/test-season/store
for entry in day-scores skill leaderboards index; do
    [ -e data/$entry ] && sudo -u starvector mv data/$entry /srv/starvector/archive/test-season/data/
done
sudo -u starvector find data -maxdepth 1 -name 'skill-board.*.json' \
    -exec mv -t /srv/starvector/archive/test-season/data {} +
sudo -u starvector mkdir store
sudo cp /etc/starvector/service.json /srv/starvector/archive/test-season/service.json
```

Do not move `data/pool-keys/`, `data/cache/`, or the pool trees. The
daily backup does not hold `/srv/starvector/archive`. The snapshot of
step 4.2 holds the test season.

### 4.5 The server config

```
sudo tee /etc/starvector/service.json >/dev/null <<'JSON'
{
  "config_version": 1,
  "player": "<your-handle>",
  "scoring_config": "configs/scoring/prod-wit-mixed.json",
  "data_root": "data",
  "store_root": "store",
  "port": 8000,
  "closes_at_utc": "00:00",
  "signup": "open",
  "pick_protocol": "vp1",
  "beacon": {"kind": "drand"}
}
JSON
sudo chown root:starvector /etc/starvector/service.json
sudo chmod 640 /etc/starvector/service.json
```

Keep `player` at the value of the test season. With sign-up open, no
caller plays as that player (spec A2 §10.2).

### 4.6 The pool key and the pool root

This command also loads the pool from `data/`. It prints
`pool fff3dddd: 1393 images`. A different count, or a stop, means that
the copy of section 2 is not complete:

```
cd /srv/starvector/app
sudo -u starvector .venv/bin/python -m service.pool_keys make \
    --service-config /etc/starvector/service.json
```

Make the key one time. The key goes to `data/pool-keys/`, and the daily
backup holds it.

Put the root file in the public repository before the first production
day opens. On the development machine:

```
scp <box>:/srv/starvector/app/configs/pool-roots/fff3dddd*.json configs/pool-roots/
git add configs/pool-roots && git commit -m "Pool root of prod-wit-001"
git push
```

Then, on the box:

```
cd /srv/starvector/app
sudo -u starvector rm configs/pool-roots/fff3dddd*.json
sudo -u starvector git pull
```

### 4.7 The clock and the beacon

```
timedatectl                        # System clock synchronized: yes
ROUND=$(curl -s https://api.drand.sh/52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971/public/latest \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["round"])')
sudo -u starvector .venv/bin/python -m service.beacon "$ROUND"
```

### 4.8 Start the server

```
sudo systemctl start starvector
sudo journalctl -u starvector -n 30
curl -s http://127.0.0.1:8000/api/about
```

- The journal shows `Uvicorn running on http://127.0.0.1:8000` and no
  `refused:` line. An empty store with sign-up open starts when the
  token, the pepper, and the ALTCHA key have a value.
- The journal holds no `warning: no pool release record` and no
  `warning: no release manifest`. With one of them, the reveal shows no
  credit line. Copy `data/curation/f655d713/d9c7558d` again.
- `/api/about` holds `"test_season": false`, `"photo_count": 1393`,
  `"closes_at_utc": "00:00"`, and `"pick_protocol": "vp1"`.

### 4.9 Smoke checks

Do the checks in `deploy/README.md` §9, from a network that is not the
network of the box. Then make your own account at the sign-up screen of
`https://<domain>/`, and agree to the notice. Check it with the operator
command:

```
sudo sv players list
```

This is also the first use of `/usr/local/sbin/sv` as `root` on a deployed
box (spec OC1). If it refuses, `deploy/README.md` §7 has the rules that
it checks.

### 4.10 Open the first production day

```
sudo sv day open
sudo sv status
```

In your signed-in browser, `https://<domain>/api/day` holds
`"protocol": "vp1"` and the pulse number. Then start the timer again:

```
sudo systemctl enable --now starvector-day.timer
systemctl list-timers starvector-day.timer
```

The new store holds no pause record, thus the timer moves the days from
its next firing.

## 5. After the first production reveal

- The reveal screen shows the photograph with its credit line and the
  pointer to the Wikimedia Commons file page.
- The daily board and the skill board show the new accounts alone.
- `restic snapshots` shows a snapshot of the new store. Do the
  `restic restore` drill of `deploy/README.md` §6 one time.
- `sudo systemctl reboot`. The site comes back with no hand work.
- Make and publish the first results snapshot
  (`docs/droplet-deployment.md` §15a), then put its address in
  `public_data_url` and start the server again.
- Measure the capacity on this box. In `/srv/starvector/app`,
  `sudo -u starvector .venv/bin/python -m tools.load` starts its own
  server on a temporary store with fake providers, and does not touch
  the live store. Do it at an hour when the site is quiet: the test uses the
  processor of the box. The laptop number of spec PL1 §9 is 877 active
  players.

## 6. Back out

**Before step 4.10, and before a second account exists,** you can put
the test season back:

```
sudo systemctl stop starvector
cd /srv/starvector/app
sudo -u starvector mv store /srv/starvector/archive/production-start
sudo -u starvector mv /srv/starvector/archive/test-season/store store
sudo -u starvector mv /srv/starvector/archive/test-season/data/* data/
sudo cp /srv/starvector/archive/test-season/service.json /etc/starvector/service.json
sudo systemctl start starvector
sudo systemctl enable --now starvector-day.timer
sudo sv schedule resume
```

The pool root in the repository stays. It is a record of the pool, and
it opens no day.

**After step 4.10,** a player can send to the production day, and that
store is permanent (I4). Correct the fault on the new store, and do not
put the test season back.
