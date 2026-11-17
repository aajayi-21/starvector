"""The pool scores of a day and its day rank (spec AG1 section 5).

A cache in the data root, keyed by the scoring hash (I4): for each day,
the fused pool score of each send (players x N, float32, rows in the
sequence of the sorted player names) and an index file with the names
and the day rank. The close writes it with the trial rows, and the day
rank is served after the reveal alone, as the trial rows are (I7). A
rescore from the stored submissions makes it again.

A reader that finds no file raises and names the command that makes
it. It does not skip the day: a day check with a day missing is a
check on a sample that nobody chose.
"""

import io
import math
from pathlib import Path

import numpy as np

from pool.artifacts import write_bytes_atomic, write_json_pretty
from service import store

REBUILD_COMMAND = "uv run python -m service.day day-scores --date {day}"


class DayScoresError(ValueError):
    """A day-score file is missing or does not agree with its key."""


def cache_dir(data_root: Path, scoring_hash: str) -> Path:
    return data_root / "day-scores" / scoring_hash[:8]


def scores_path(data_root: Path, day: str, scoring_hash: str) -> Path:
    return cache_dir(data_root, scoring_hash) / f"{day}.npy"


def index_path(data_root: Path, day: str, scoring_hash: str) -> Path:
    return cache_dir(data_root, scoring_hash) / f"{day}.json"


def write_day_scores(data_root: Path, day: str, scoring_hash: str, *,
                     players: list[str], scores: np.ndarray,
                     rank: float) -> None:
    """Write the rows and the index of one day. Repeatable.

    players is the sorted name sequence, one row of scores for each.
    The index goes last, thus a reader that finds an index finds its
    rows.
    """
    if players != sorted(players):
        raise DayScoresError(f"day {day}: the player names must be sorted")
    if scores.ndim != 2 or scores.shape[0] != len(players):
        raise DayScoresError(
            f"day {day}: scores of shape {scores.shape} for "
            f"{len(players)} players")
    if not (math.isfinite(rank) and 0.0 < rank < 1.0):
        raise DayScoresError(f"day {day}: a day rank must sit in (0, 1), "
                             f"got {rank!r}")
    buffer = io.BytesIO()
    np.save(buffer, scores.astype(np.float32), allow_pickle=False)
    write_bytes_atomic(scores_path(data_root, day, scoring_hash),
                       buffer.getvalue())
    write_json_pretty(index_path(data_root, day, scoring_hash), {
        "day": day,
        "scoring_config_hash": scoring_hash,
        "players": players,
        "pool_count": int(scores.shape[1]),
        "day_rank": rank,
    })


def read_day_rank(data_root: Path, day: str, scoring_hash: str) -> float:
    """The day rank of one day at one configuration, or DayScoresError.

    The file name holds eight characters of the hash and the document
    holds the full one. This compares them, thus two configurations
    that share a prefix cannot silently share an entry.
    """
    path = index_path(data_root, day, scoring_hash)
    value = store.read_json_or_none(path)
    if value is None:
        raise DayScoresError(
            f"day {day} has no day-score file at {scoring_hash[:8]} - make "
            f"it with `{REBUILD_COMMAND.format(day=day)}`")
    if value.get("scoring_config_hash") != scoring_hash \
            or value.get("day") != day:
        raise DayScoresError(
            f"{path}: the stored day or scoring hash is not the one asked "
            "for")
    rank = value.get("day_rank")
    if not isinstance(rank, float) or not 0.0 < rank < 1.0:
        raise DayScoresError(f"{path}: the day rank must sit in (0, 1)")
    return rank


def has_day_scores(data_root: Path, day: str, scoring_hash: str) -> bool:
    return index_path(data_root, day, scoring_hash).is_file()
