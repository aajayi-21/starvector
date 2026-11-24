# Spec SC1 — store compatibility: the frozen stores and their guard tests

**Status:** ruled 2026-11-19 (§8), built on branch
`feat/footer-and-store-guard`.
**Phase:** before the first public day. The owner changes the app and adds
items to it continuously, and no change must edit or break the stored
responses of the players.
**Architecture sections:** §21 (storage and versioning).
**Working agreement:** `CLAUDE.md` §2 (I4), §3 (errors), §9, §10.
**Input:** spec S1 §5 (the store), and the specs M1, A1, A2, R1, CR1, MD1,
VP1, and OC1, which each added data to the store.

This spec is written for implementation by an AI agent. Where a value is
not given by the architecture or an earlier spec, §8 says so and records
the ruling.

---

## 1. Purpose

1. **Write down the rule that each earlier spec obeyed.** Each spec that
   added data to the store added a new directory or an optional field, and
   changed no stored play record. No document gave that rule as a rule.
2. **Prove the rule on each change.** A small store that an earlier release
   wrote is in the repository. The test suite reads it with the code of
   today. A change that the stored history of a deployment cannot survive
   fails `uv run pytest` on the development machine.

The spec adds no server path, no stored record type, and no scoring step.

## 2. What stands today, with evidence

- **The store is a tree of JSON files.** `service/store.py` writes one file
  for each record. Submissions and trial rows go through `write_once_json`,
  which refuses a second write to the same path.
- **The readers are strict.** A record with a field that the reader does
  not know raises, and a record that does not have a field of the reader
  raises (`_read_record`, `read_day_record`, `read_account_or_none`). A
  release that adds a required field to a record type thus cannot read the
  records of the release before it.
- **The store has no version number and no migration sequence.** The
  architecture says why in §21: a stored submission is the source of truth,
  and a new configuration scores it again. One backfill command stands
  (`service.day migrate`, spec S1 §14b).
- **The rescore invariant had no store of an earlier release.** `test_rescore_invariant.py`
  makes a store with the code of today and scores it again with the code of
  today. It cannot find a change that breaks a store of an earlier release.
- **A rescore stopped on a day with a quarantine record.** The first frozen
  store found this defect. Spec CR1 §15 records the repair.

## 3. The rule

1. **New data goes in a new directory or in an optional field.** A record
   without the optional field keeps its bytes, and its reader gives the
   field a default that the spec of the change names.
2. **No release adds a required field to a stored record type**, and no
   release removes or renames a field of one.
3. **No release changes a stored file of a play record.** A day record
   moves through its statuses and gets its pick, as spec S1 and spec VP1
   say. A submission, a trial row, a start record, and a quarantine record
   do not change after the write.
4. **A new scoring configuration writes adjacent rows.** It does not
   replace the rows of the pinned configuration (architecture §21).
5. **A frozen store is not made again and is not edited.** When a release
   adds a record type or an optional field, the builder makes a new frozen
   store adjacent to the earlier ones. The earlier ones stay, and the tests
   read all of them.
6. **A guard test that fails is a stop.** The repair is in the code of the
   change. If the change cannot keep the rule, the builder tells the
   owner that the change and the rule do not agree, and waits for a ruling.

## 4. The frozen store

A frozen store is one directory, `tests/service/fixtures/frozen-store-<label>/`:

| Path | Contents |
|---|---|
| `world/store/` | The trial store. |
| `world/pool/` | The preparation record, its artifacts, and the commonness tables. |
| `world/*.json`, `world/pool-roots/` | The scoring configs, the pool release record, and the committed pool root. |
| `encoder-replay.npz` | The vector that each encoder gave for each text and each rendered sketch. |
| `lineage.json` | The commit, the hashes of each config, the hashes of the provider slots, and the fixture password and pepper. |
| `MANIFEST.sha256` | The SHA-256 of each other file. |

**The paths are relative.** A deployment runs with relative paths below its
working directory, and a day record keeps the path of its scoring config as
text. The tool builds the world with the world as its working directory. A
test copies the world and reads the copy with the copy as its working
directory.

**The vectors are recorded.** The fake encoders make a vector from the bytes
of a PNG file and from the random stream of NumPy. A new release of Pillow,
zlib, or NumPy can change those, and a frozen store has no legal repair. The
replay table has the same function as the vector cache of a deployment. It
answers by the text, and by a digest of the decoded pixels of a rendered
sketch. A change of the canonical render moves the digest, and the replay
then has no vector: that is a correct failure, because the vector cache of a
deployment does not answer for the new picture.

**What is not in it:** the pool key, the photographs, the day-score files,
the results index, the boards, and the notice file of the store. The code
makes each cache again. The pool key is a secret of a deployment, and no
reader, rescore, index build, or snapshot build reads it.

**The values in it open nothing.** The credential records hold Argon2id
digests of one fixture password with one fixture pepper. `lineage.json` names
the two, thus a test proves that a stored digest reads. No deployment has
that pepper.

**The first frozen store, `frozen-store-2026-11`,** holds five days and five
players, 92 files:

- Three days of the `commit-v1` protocol and two days of the `vp1` protocol,
  one of them open.
- A mixed send, a send of text alone, a send of a sketch alone, and a send
  with a color on each stroke.
- Start records, and trial rows with and without the channel scores.
- Adjacent rows of a second scoring configuration.
- A send with a quarantine record that the operator decided.
- An account with a description and an avatar, credentials, name claims,
  sessions, and consents.
- A withheld response, a revoked player, an account that the operator
  deleted, the two identifier records, and the operator journal of that
  deletion.
- A rollover control record and one rollover record.

A device code is not in it: a device code lives for 10 minutes.

*Note, 2026-11-24 (spec IM1 §17):* **the second frozen store,
`frozen-store-2026-11-im1`,** holds the record types of the first one
and the record types of spec IM1, 114 files:

- Three instant trials with a result: one of an account, one of a guest,
  and one of a guest that an account claimed.
- An instant send with no result, and a start with no send.
- The secret record of each send, and a withheld instant response.
- Two guest records, their consent records, and one claim.

The first frozen store did not change. Its consent records are of
notice version 2, and those of the second one are of version 3.

`tools/freeze_store.py` makes a frozen store: `uv run python -m
tools.freeze_store --label <label>`. It refuses a label that has a
directory.

## 5. The guard tests

`tests/service/test_frozen_store.py` does each test for each directory
`frozen-store-*`. `tests/service/frozen_fixture.py` holds the helpers.

| Test | What it proves | A change that it stops |
|---|---|---|
| `test_the_frozen_bytes_are_the_committed_bytes` | Each file has the digest of the manifest, and the manifest names no other file. | An edit of a frozen file. |
| `test_each_stored_file_reads` | Each file agrees with one row of the reader table, and its reader of today answers a record. The enumerators of the store count the same files as the disk. | A new required field. A removed field. A renamed directory. |
| `test_the_lineage_stands` | The wiring of today gives the stored scoring hash, commonness hash, and preparation version of each config. | A change of what a config hash reads. |
| `test_a_rescore_gives_each_stored_row_again` | A rescore with the pinned config of each day compares each stored trial row and finds it byte-equal. A rescore with the config of the adjacent rows writes nothing. | A change of Layers 0 to 8, of the render, of a default of the config path, or of the shape of a trial row. |
| `test_no_stored_file_changes` | The store has the same manifest before and after: the read walk, each rescore, the day-score files, the boards, the results index and its check, and a public snapshot and its check. | A reader or a build that writes to the store. |
| `test_the_frozen_store_holds_no_deployment_secret` | No pool key is in the directory. | A frozen store that copies a key. |
| `test_a_stored_password_digest_reads` | The digester of today accepts the fixture password for a stored digest. | A change of the digest parameters that locks each player out. |

*Note, 2026-11-24 (spec IM1 §17):* two more tests, for a frozen store
with the record types of spec IM1. An earlier frozen store does not do
them.

| Test | What it proves | A change that it stops |
|---|---|---|
| `test_a_rescore_gives_each_stored_instant_row_again` | A second scoring of each stored instant send, with its pinned config and its stored target, gives the stored trial row byte for byte. | A change of Layers 0 to 8 or of the shape of an instant trial row. |
| `test_the_chain_of_the_stored_instant_sends_stands` | The book of today reads each stored instant trial, and the chain of the sends has no fault. | A change of the chain rule or of a field of a send record. |

`tests/service/frozen_fixture.py` holds the rows of the new record
types in a second table, `INSTANT_READERS`. A row of `READERS` is a
record type that each frozen store holds, and the first frozen store
holds no instant trial. `test_no_stored_file_changes` also does the
second scoring of the instant sends and builds the book.

The rescore test compares counts. With a hash that moved, a rescore compares
nothing, writes new rows adjacent, and raises no error. The counts make that
condition a failure.

## 6. Integrity

- **The target (I1).** The guard tests score with the server shell, which
  reads the target of a day record at Layer 8, as the close does. No module
  before `core/ranking.py` gets a new argument.
- **No fit (I6).** The frozen store holds fixture sends, and no code reads
  it to set a weight.
- **Raw inputs (I4).** The frozen store keeps the raw sends and the trial
  rows, and it keeps no cache. The tests make each cache again from the raw
  sends.
- **The public snapshot.** The world has no network, thus its `vp1` days
  name the fake beacon chain. The tool and the tests name that chain as
  public for the fixture alone. A deployment refuses it, and
  `test_post_close_pick_public.py` proves that refusal.

## 7. What the guard does not do

- It is not a protection for the files of a deployment. The backup of spec PL1 is
  the copy of the store, and the update steps of the deployment documents
  do not make a backup first.
- It does not run by itself before a merge. A person runs `uv run
  pytest` before a merge (`CLAUDE.md` §9).
- It does not prove a release that goes back. An earlier release cannot
  read a record with a field that a newer release added.

## 8. Decisions, ruled 2026-11-19

| # | Decision | Ruling |
|---|---|---|
| D1 | Which protection this branch adds | The frozen store and its guard tests. No workflow that runs the tests before each merge, no deploy script, and no move of the store out of the checkout in this branch. |
| D2 | The quarantine defect of §2 | Repaired in this branch (spec CR1 §15). |
| D3 | The rule in `CLAUDE.md` | Added to §9 and §10. |
| D4 | Live fake encoders or recorded vectors | Recorded vectors (§4), decided at build time. |

## 9. Out of scope, with causes

- **A workflow that runs the tests before each merge.** The owner
  declined it for this branch. Without it, the guard depends on a person
  who runs the suite.
- **A deploy script with a backup first and a procedure to go back.** The owner declined
  it for this branch.
- **A store that is not in the code checkout.** The store of a deployment is in
  `/srv/starvector/app/store`. A move is a change on the deployed machine,
  and the owner declined it for this branch.
- **A version number in the store.** The architecture rules it out (§21).
