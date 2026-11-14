# Querying the results

The server keeps one SQLite file for programs to read:

```bash
uv run python -m service.index path
```

*Note, 2026-11-13 (spec R1):* this file is the operator's private
index. The file for each other reader is the public database, which
`python -m service.public build` makes from the store. It holds the
revealed days of a production pool alone, and its `README.md` says what
each table means. Do not publish the file of this document: it holds
the responses of the day in play and the text of each account.

The usual path is `data/index/results-v2.sqlite`. The file is a cache of
the store (I4). A reveal builds it, and a console read builds it when the
store moved. To build it by hand:

```bash
uv run python -m service.index build
```

## The rule for this data

**Do not use this data to fit weights (I6).** With no player ability
there is no signal to find, but there is a noise optimum, and an
optimizer finds it. The result looks the same as ability and is not.
Fusion weights come from data where correspondence exists by construction
(architecture section 19). A test scans the fit-side packages and refuses
an import of `service`.

Use this data to read what happened. Do not use it to tune the scoring.

## What the file holds

Trial rows enter for revealed days alone, and a day's `target_id` and
`secret` stay NULL until its reveal (I7). Credentials are not in it. A
copy of the file thus holds no score of a day that is not public. It does
hold each raw submission of an open day, thus keep a copy private.

| Table or view | One row is | Columns of note |
|---|---|---|
| `meta` | A fact about the build | `schema_version`, `store_fingerprint`, `built_at` |
| `players` | A player | `player`, `display_name`, `status`, `created_at` |
| `accounts` | A player's account text | `description`, `avatar_hash`, `updated_at` |
| `days` | A day | `day`, `trial_code`, `status`, `target_id`, `scoring_config_hash`, `opened_at`, `closed_at`, `revealed_at` |
| `submissions` | A send | `day`, `player`, `received_at`, the counts, `record_json` |
| `trials` | A trial row | `day`, `player`, `scoring_config_hash`, `pinned`, `p`, `target_rank`, `decoy_count`, `beaten`, `tied` |
| `trial_atoms` | One atom of a trial report | `pinned`, `position`, `atom_text`, `element`, `weight`, `similarity`, `rarity` |
| `trial_channels` | One channel of a trial | `pinned`, `channel`, `standardized`, `p` |
| `revealed_trials` | A view: the pinned trial rows of revealed days | The `trials` columns, `trial_code`, `target_id`, `received_at` |

**`pinned`.** A rescore with a different config writes a second row for the
same player and day. `pinned = 1` marks the row that the day published.
A count with no `pinned` filter counts each rescore again.

**`trial_channels`** holds rows only for a scoring config that turns on
`report.channel_scores` (spec PL1 section 7). A row of an earlier config
has none, and it stays byte-equal.

## With sqlite3

Open the file read-only:

```bash
sqlite3 -readonly data/index/results-v2.sqlite
```

Each player's mean trial score. Chance is 0.5.

```sql
SELECT player, COUNT(*) AS trials, ROUND(AVG(p), 3) AS mean_p
FROM revealed_trials
GROUP BY player
ORDER BY trials DESC;
```

The words that came up most, with each rescore counted one time:

```sql
SELECT atom_text AS word, COUNT(*) AS uses,
       ROUND(AVG(similarity), 3) AS mean_similarity
FROM trial_atoms
WHERE atom_text IS NOT NULL AND pinned = 1
GROUP BY atom_text
ORDER BY uses DESC
LIMIT 50;
```

Outline against element, for configs that store channel scores:

```sql
SELECT channel, COUNT(*) AS trials, ROUND(AVG(p), 3) AS mean_p
FROM trial_channels
WHERE pinned = 1
GROUP BY channel;
```

The points of each stroke, through `json_each`:

```sql
SELECT s.day, s.player, stroke.key AS stroke,
       json_array_length(stroke.value, '$.points') AS points
FROM submissions AS s, json_each(s.record_json, '$.canvas_strokes') AS stroke
ORDER BY s.day, s.player, stroke.key;
```

The words of each send, through `json_each`:

```sql
SELECT s.day, s.player, word.value AS word
FROM submissions AS s, json_each(s.record_json, '$.impressions') AS word
ORDER BY s.day, s.player, word.key;
```

The `Results` tab of the console takes the same SQL, one `SELECT` at a time.

## With DuckDB

DuckDB reads the file through its `sqlite` extension, which it downloads
one time. Tested with DuckDB 2.0.0.

```sql
INSTALL sqlite;
LOAD sqlite;
ATTACH 'data/index/results-v2.sqlite' AS results (TYPE sqlite, READ_ONLY);
SELECT player, COUNT(*) AS trials, ROUND(AVG(p), 3) AS mean_p
FROM results.revealed_trials
GROUP BY player;
```

To count the strokes of each send, use the JSON functions of DuckDB:

```sql
SELECT day, player,
       json_array_length(record_json, '$.canvas_strokes') AS strokes
FROM results.submissions;
```

## From a script

`GET /api/ops/trials` answers the pinned rows of revealed days as JSON, and
takes `from`, `to`, and `player`. It needs the operator bearer, and it is not
public at the edge. It holds 5,000 rows at most. When `truncated` is `true`,
send it again with `from` set to the last day you read.

The research export replaces each player's name with a salted digest:

```bash
uv run python -m service.index export --out exports/ --format csv
```
