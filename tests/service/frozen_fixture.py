"""Helpers for the frozen stores of spec SC1.

Spec: docs/specs/store-compatibility.md. A frozen store is a small
trial store that an earlier release wrote. It is in the repository,
and its bytes do not change. The guard tests read it with the code of
today. The tool that makes a frozen store (tools/freeze_store.py)
reads the same helpers, thus the tool and the tests agree on each key.
"""

import hashlib
import io
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import numpy as np

from core.types import Vectors
from providers.protocols import InputRefused
from service import guests, index, instant_store, store

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST_NAME = "MANIFEST.sha256"
REPLAY_NAME = "encoder-replay.npz"
LINEAGE_NAME = "lineage.json"


def frozen_stores() -> list[Path]:
    """Each frozen store directory of the repository, sorted by name."""
    return sorted(path for path in FIXTURES.glob("frozen-store-*")
                  if path.is_dir())


# ---- the manifest ----


def manifest_of(root: Path) -> dict[str, str]:
    """The SHA-256 of each file below root, keyed by its POSIX path.

    The manifest file itself is not in the output, thus the manifest of
    a frozen store does not name its own digest.
    """
    return {
        path.relative_to(root).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_NAME
    }


def render_manifest(manifest: Mapping[str, str]) -> str:
    """The text of a manifest file: one `digest  path` line for each file."""
    return "".join(f"{digest}  {name}\n"
                   for name, digest in sorted(manifest.items()))


def read_manifest(path: Path) -> dict[str, str]:
    """The stored manifest, in the shape manifest_of gives."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {name: digest for digest, name in
            (line.split("  ", 1) for line in lines)}


# ---- the encoder replay ----


def sketch_key(png: bytes) -> str:
    """The replay key of one rendered sketch: a digest of its pixels.

    The key reads the decoded pixels and the width and height, not the
    PNG bytes, thus a different compression of the same picture keeps
    its key. A render that moves one pixel gets a new key, and the
    replay then has no vector for it.
    """
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        pixels = image.convert("RGBA")
        header = f"{pixels.width}x{pixels.height}:".encode("ascii")
        return hashlib.sha256(header + pixels.tobytes()).hexdigest()


class ReplayTextEncoder:
    """The text encoder slot, answered from the recorded vectors.

    The config hash is the hash of the encoder that made the frozen
    store. A text with no recorded vector raises: the code of today
    gave the encoder a text that the earlier release did not.
    """

    def __init__(self, config_hash: str, vectors: Mapping[str, np.ndarray],
                 refused: frozenset[str], dimension: int) -> None:
        self.config_hash = config_hash
        self._vectors = vectors
        self._refused = refused
        self._dimension = dimension

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """One recorded unit-norm row for each text, float32 (B, d)."""
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        refused = [text for text in texts if text in self._refused]
        if refused:
            raise InputRefused(
                f"replay text encoder: refused {len(refused)} input(s) of "
                f"{len(texts)}")
        absent = [text for text in texts if text not in self._vectors]
        if absent:
            raise LookupError(
                f"the frozen store holds no vector for the text "
                f"{absent[0]!r} - Layer 0 or Layer 1 gives the encoder a "
                "different text than the release that wrote the store")
        return np.stack([self._vectors[text] for text in texts])   # (B, d)


class ReplaySketchEncoder:
    """The sketch encoder slot, answered from the recorded vectors."""

    def __init__(self, config_hash: str, vectors: Mapping[str, np.ndarray],
                 dimension: int) -> None:
        self.config_hash = config_hash
        self._vectors = vectors
        self._dimension = dimension

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """One recorded unit-norm row for each rendered sketch, (B, d)."""
        if not images:
            return np.zeros((0, self._dimension), dtype=np.float32)
        keys = [sketch_key(image) for image in images]
        absent = [key for key in keys if key not in self._vectors]
        if absent:
            raise LookupError(
                f"the frozen store holds no vector for a rendered sketch "
                f"(pixel digest {absent[0][:12]}) - the canonical render "
                "of a stored sketch moved, and the vector cache of a "
                "deployed store does not answer for the new picture")
        return np.stack([self._vectors[key] for key in keys])      # (B, d)


class RecordedHash:
    """A provider slot that the wiring reads for its config hash alone."""

    def __init__(self, config_hash: str) -> None:
        self.config_hash = config_hash


def write_replay(path: Path, text_vectors: Mapping[str, np.ndarray],
                 sketch_vectors: Mapping[str, np.ndarray]) -> None:
    """Write the recorded vectors: two key arrays and two (K, d) arrays."""
    text_keys = sorted(text_vectors)
    sketch_keys = sorted(sketch_vectors)
    np.savez(path,
             text_keys=np.array(text_keys, dtype=np.str_),
             text_vectors=np.stack([text_vectors[key] for key in text_keys]),
             sketch_keys=np.array(sketch_keys, dtype=np.str_),
             sketch_vectors=np.stack(
                 [sketch_vectors[key] for key in sketch_keys]))


def read_lineage(frozen: Path) -> dict:
    """The lineage record of one frozen store."""
    return json.loads((frozen / LINEAGE_NAME).read_text(encoding="utf-8"))


def replay_providers(frozen: Path) -> dict[str, object]:
    """The provider slots of one frozen store, answered from its files.

    The three slots are those that enter the scoring config hash. No
    slot reads providers/fake, thus an edit of a fake provider does not
    change what the guard tests calculate.
    """
    lineage = read_lineage(frozen)
    slots = lineage["slot_hashes"]
    with np.load(frozen / REPLAY_NAME, allow_pickle=False) as replay:
        text = {str(key): row.astype(np.float32) for key, row in
                zip(replay["text_keys"], replay["text_vectors"], strict=True)}
        sketch = {str(key): row.astype(np.float32) for key, row in
                  zip(replay["sketch_keys"], replay["sketch_vectors"],
                      strict=True)}
    dimension = int(lineage["dimension"])
    return {
        "text_encoder": ReplayTextEncoder(
            slots["text_encoder"], text,
            frozenset(lineage["refused_texts"]), dimension),
        "sketch_encoder": ReplaySketchEncoder(
            slots["sketch_encoder"], sketch, dimension),
        "sketch_pairs": RecordedHash(slots["sketch_pairs"]),
    }


# ---- the read walk ----


def _day(reader: Callable[[Path, str], object]) -> Callable:
    return lambda root, match: reader(root, match["day"])


def _day_player(reader: Callable[[Path, str, str], object]) -> Callable:
    return lambda root, match: reader(root, match["day"], match["player"])


def _player(reader: Callable[[Path, str], object]) -> Callable:
    return lambda root, match: reader(root, match["player"])


def _read_submission(root: Path, match: re.Match[str]) -> object:
    stored = store.read_json_or_none(
        store.submission_path(root, match["day"], match["player"]))
    if stored is None or set(stored) != {"day", "player", "trial_id",
                                         "received_at", "record"}:
        raise store.StoreError(
            f"{match.string}: the stored submission does not parse")
    return stored


def _read_trial(root: Path, match: re.Match[str]) -> object:
    row = json.loads((root / match.string).read_text(encoding="utf-8"))
    if not isinstance(row, dict) or row.get("player") != match["player"] \
            or row.get("day") != match["day"]:
        raise store.StoreError(
            f"{match.string}: the trial row does not name its day and "
            "its player")
    return row


def _read_session(root: Path, match: re.Match[str]) -> object:
    return store.read_session_or_none(root, match["player"], match["digest"])


def _read_consent(root: Path, match: re.Match[str]) -> object:
    return store.read_consent_or_none(root, match["player"],
                                      int(match["notice"]))


def _read_claim(root: Path, match: re.Match[str]) -> object:
    return store.read_claim_or_none(root, match["folded"])


def _read_operator_entry(root: Path, match: re.Match[str]) -> object:
    names = {store._operator_entry_name(entry)
             for entry in store.list_operator_entries(root)}
    return True if Path(match.string).name in names else None


def _read_rollover_run(root: Path, match: re.Match[str]) -> object:
    return store._read_run(root / match.string)


_DAY = r"(?P<day>\d{4}-\d{2}-\d{2})"
_NAME = r"(?P<player>[a-z0-9-]+)"

# One row for each record type that a store can hold today. A file of
# a frozen store must match one row and no more, and the reader of the
# row must answer a record. A new record type gets a new row and a new
# frozen store. A row is not changed for a record type that stands.
READERS: tuple[tuple[str, re.Pattern[str], Callable], ...] = tuple(
    (label, re.compile(pattern), reader) for label, pattern, reader in (
        ("day", rf"days/{_DAY}/day\.json", _day(store.read_day_record)),
        ("submission", rf"days/{_DAY}/submissions/{_NAME}\.json",
         _read_submission),
        ("trial", rf"days/{_DAY}/trials/{_NAME}(\.[0-9a-f]{{8}})?\.json",
         _read_trial),
        ("start", rf"days/{_DAY}/starts/{_NAME}\.json",
         _day_player(store.read_start_or_none)),
        ("quarantine", rf"days/{_DAY}/quarantine/{_NAME}\.json",
         _day_player(store.read_quarantine_or_none)),
        ("player", rf"players/{_NAME}\.json",
         _player(store.read_player_record)),
        ("account", rf"accounts/{_NAME}\.json",
         _player(store.read_account_or_none)),
        ("avatar", rf"accounts/{_NAME}\.avatar",
         _player(store.read_avatar_or_none)),
        ("credential", rf"credentials/{_NAME}\.json",
         _player(store.read_credential_or_none)),
        ("name claim", r"names/(?P<folded>[a-z0-9]+)\.json", _read_claim),
        ("session", rf"sessions/{_NAME}/(?P<digest>[0-9a-f]{{64}})\.json",
         _read_session),
        ("consent", rf"consents/{_NAME}/(?P<notice>\d+)\.json",
         _read_consent),
        ("withheld", rf"public/withheld/{_DAY}/{_NAME}\.json",
         _day_player(store.read_withheld_or_none)),
        ("identifier", rf"public/identifiers/{_NAME}\.json",
         _player(store.read_identifier_or_none)),
        ("deletion", rf"deleted/{_NAME}\.json",
         _player(store.read_deletion_or_none)),
        ("rollover control", r"rollover/control\.json",
         lambda root, match: store.read_rollover_control(root)),
        ("rollover run", r"rollover/runs/[^/]+\.json", _read_rollover_run),
        ("operator entry", r"operator-log/[^/]+\.json",
         _read_operator_entry),
    ))


def _read_instant(reader: Callable[[Path, str, str], object]) -> Callable:
    return lambda root, match: reader(root, match["day"], match["trial"])


def _read_guest_consent(root: Path, match: re.Match[str]) -> object:
    agreed = guests.agreed(root, match["guest"], int(match["notice"]))
    return True if agreed else None


_TRIAL = r"(?P<trial>[0-9a-f]{32})"
_GUEST = r"(?P<guest>guest-[0-9a-f]{16})"

# The first frozen store that holds the record types of spec IM1: the
# instant trial and the guest. An earlier frozen store has none of them,
# and it does not get one: a frozen store is not made again.
INSTANT_FIRST_STORE = "frozen-store-2026-11-im1"

# The rows of spec IM1. They are adjacent to READERS and not in it: a
# row of READERS is a record type that each frozen store holds.
INSTANT_READERS: tuple[tuple[str, re.Pattern[str], Callable], ...] = tuple(
    (label, re.compile(pattern), reader) for label, pattern, reader in (
        ("instant start", rf"instant/{_DAY}/{_TRIAL}/start\.json",
         _read_instant(instant_store.read_start_or_none)),
        ("instant send", rf"instant/{_DAY}/{_TRIAL}/send\.json",
         _read_instant(instant_store.read_send_or_none)),
        ("instant secret", rf"instant/{_DAY}/{_TRIAL}/secret\.json",
         _read_instant(instant_store.read_secret_or_none)),
        ("instant result", rf"instant/{_DAY}/{_TRIAL}/result\.json",
         _read_instant(instant_store.read_result_or_none)),
        ("instant withheld",
         rf"public/withheld-instant/{_DAY}/{_TRIAL}\.json",
         _read_instant(instant_store.read_withheld_or_none)),
        ("guest", rf"guests/{_GUEST}/guest\.json",
         lambda root, match: guests.read_guest_or_none(root, match["guest"])),
        ("guest consent", rf"guests/{_GUEST}/consents/(?P<notice>\d+)\.json",
         _read_guest_consent),
        ("guest claim", rf"guests/{_GUEST}/claim\.json",
         lambda root, match: guests.read_claim_or_none(root, match["guest"])),
    ))


def holds_instant(frozen: Path) -> bool:
    """Tell if a frozen store was made with the record types of spec
    IM1. The names sort by the time that the tool made them."""
    return frozen.name >= INSTANT_FIRST_STORE


def expected_labels(frozen: Path) -> list[str]:
    """The record types that one frozen store must hold: each type
    that had a reader when the tool made that store."""
    labels = [label for label, _, _ in READERS]
    if holds_instant(frozen):
        labels += [label for label, _, _ in INSTANT_READERS]
    return sorted(labels)


def read_walk(root: Path) -> dict[str, int]:
    """Read each file of a store through its reader of today.

    The output counts the files of each record type. Raises StoreError
    for a file that matches no row or more than one row, and for a file
    with a reader that answers no record. A reader raises its own error for a
    record that it does not accept.
    """
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        rows = [(label, pattern.fullmatch(name), reader)
                for label, pattern, reader in (*READERS, *INSTANT_READERS)
                if pattern.fullmatch(name) is not None]
        if len(rows) != 1:
            raise store.StoreError(
                f"{name}: {len(rows)} record types claim this file - a "
                "stored file must have one reader")
        label, match, reader = rows[0]
        if reader(root, match) is None:
            raise store.StoreError(
                f"{name}: the {label} reader of today answers no record")
        counts[label] = counts.get(label, 0) + 1
    return counts


def enumerated(root: Path) -> dict[str, int]:
    """The counts that the enumerators of the store give for a root.

    The read walk counts files on the disk. This counts what the code
    of today finds, thus a renamed directory shows as two counts that
    do not agree.
    """
    days = store.list_days(root)
    players = store.list_players(root)
    return {
        "day": len(days),
        "submission": sum(len(store.list_submissions(root, day))
                          for day in days),
        "trial": sum(1 for day in days
                     for _ in index._trial_files(root, day)),
        "quarantine": sum(len(store.list_quarantined(root, day))
                          for day in days),
        "player": len(players),
        "withheld": len(store.list_withheld(root)),
        "operator entry": len(store.list_operator_entries(root)),
        **_enumerated_instant(root),
    }


def _enumerated_instant(root: Path) -> dict[str, int]:
    """The counts that the enumerators of the instant trials and of the
    guests give. A store with none of them gives no count."""
    trials = [(date, trial_id)
              for date in instant_store.list_dates(root)
              for trial_id in instant_store.list_trials(root, date)]
    if not trials:
        return {}
    return {
        "instant start": len(trials),
        "instant send": sum(
            1 for date, trial_id in trials
            if instant_store.read_send_or_none(root, date, trial_id)
            is not None),
        "instant result": sum(
            1 for date, trial_id in trials
            if instant_store.read_result_or_none(root, date, trial_id)
            is not None),
        "instant withheld": len(instant_store.list_withheld(root)),
        "guest claim": sum(len(names) for names in
                           guests.claims_by_player(root).values()),
    }
