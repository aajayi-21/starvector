"""The generalization table: one broader phrase for each vocabulary entry.

Spec: docs/specs/fuse-and-validate.md section 8.2 (decision D2). The
table is a keyed artifact (I4): built one time through the
generalization slot, stored at
data/generalization/<vocab_digest[:8]>/<slot_hash[:8]>/, and read by
the synthetic submission generator. Answers go through the p02
normalization rules before storage, thus the generalized strings live
in the same string space as the atoms. An answer normalization
empties keeps the initial entry, and the meta file counts those.
"""

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from core.canonical import JsonValue, canonical_json, sha256_hex
from pipeline.config import ConfigError, load_scoring_config
from pipeline.context import load_pool_index
from pool.artifacts import ManifestError, write_json_pretty, write_jsonl
from pool.preparation.stages.normalize import normalize_element
from validation.fitconfig import (FitConfig, generalize_slot_hash,
                                  load_fit_config, wire_generalizer)

_TABLE_FILE = "table.jsonl"
_META_FILE = "meta.json"

# How many entries go to the slot in one run. The provider chunks
# its own posts. This limits the memory of one run.
_CHUNK = 256


def vocabulary_digest(vocabulary: tuple[str, ...]) -> str:
    """The content digest of one pool vocabulary, entry strings alone."""
    return sha256_hex(canonical_json(list(vocabulary)))


def table_dir(data_root: Path, vocab_digest: str, slot_hash: str) -> Path:
    """The artifact directory (spec P4 section 14)."""
    return (data_root / "generalization" / vocab_digest[:8] / slot_hash[:8])


def build_table(vocabulary: tuple[str, ...], generalizer: object,
                ) -> tuple[dict[str, str], int]:
    """The table plus the count of entries normalization kept as-is.

    Each phrase goes through normalize_element one time. An empty
    normalization result keeps the initial entry — the generator then
    samples the entry unchanged, which is a weaker degradation, and
    the meta file records how frequently that happened.
    """
    table: dict[str, str] = {}
    kept = 0
    for start in range(0, len(vocabulary), _CHUNK):
        chunk = list(vocabulary[start:start + _CHUNK])
        phrases = generalizer.generalize(chunk)
        if len(phrases) != len(chunk):
            raise ValueError(
                f"the generalizer answered {len(phrases)} of {len(chunk)} "
                "entries")
        for entry, phrase in zip(chunk, phrases):
            normalized = normalize_element(phrase)
            if not normalized:
                normalized = entry
                kept += 1
            table[entry] = normalized
    return table, kept


def ensure_table(*, data_root: Path, vocabulary: tuple[str, ...],
                 config: FitConfig, clock,
                 generalizer: object | None = None) -> dict[str, str]:
    """Read the table at its key, or build and store it one time.

    The meta file is the completeness marker, written last (the P1b
    resume rule). A warm read makes no provider post.
    """
    digest = vocabulary_digest(vocabulary)
    slot_hash = generalize_slot_hash(config)
    directory = table_dir(data_root, digest, slot_hash)
    table_path = directory / _TABLE_FILE
    meta_path = directory / _META_FILE
    if meta_path.is_file():
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for name, expected in (("vocabulary_digest", digest),
                               ("generalize_slot_hash", slot_hash)):
            if meta.get(name) != expected:
                raise ManifestError(
                    f"{meta_path}: {name} does not agree with the requested "
                    "table — a truncated-key collision")
        rows = [json.loads(line) for line in
                table_path.read_text(encoding="utf-8").splitlines()]
        table = {str(row["element"]): str(row["phrase"]) for row in rows}
        if set(table) != set(vocabulary):
            raise ManifestError(
                f"{table_path}: the stored entries do not cover the "
                "vocabulary")
        return table

    wired = generalizer or wire_generalizer(config, data_root)
    posts_before = int(getattr(wired, "post_count", 0))
    hits_before = int(getattr(wired, "cache_hit_count", 0))
    table, kept = build_table(vocabulary, wired)
    write_jsonl(table_path, [
        {"element": entry, "phrase": table[entry]}
        for entry in sorted(table)])
    meta: dict[str, JsonValue] = {
        "vocabulary_digest": digest,
        "generalize_slot_hash": slot_hash,
        "entry_count": len(table),
        "kept_as_is": kept,
        "provider_posts": int(getattr(wired, "post_count", 0)) - posts_before,
        "provider_cache_hits":
            int(getattr(wired, "cache_hit_count", 0)) - hits_before,
        "created_at": clock(),
    }
    write_json_pretty(meta_path, meta)
    return table


def table_hash(table: Mapping[str, str]) -> str:
    """The content digest of one built table, for generator identity."""
    return sha256_hex(canonical_json(
        {entry: table[entry] for entry in sorted(table)}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.generalize")
    parser.add_argument("--config", required=True,
                        help="the fit config file")
    parser.add_argument("--scoring-config", required=True,
                        help="the scoring config that names the preparation")
    parser.add_argument("--data-root", default="data")
    arguments = parser.parse_args(argv)
    try:
        fit_config = load_fit_config(Path(arguments.config))
        scoring = load_scoring_config(Path(arguments.scoring_config))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    from validation import harness

    loaded = load_pool_index(Path(scoring.input.preparation_record),
                             Path(arguments.data_root),
                             dev_only=scoring.report.dev_only)
    # Rarity is pool-defined, and so is the table: the first V entries
    # are the pool vocabulary (spec P3 section 12).
    entry_count = len(loaded.index.pool_frequency)
    table = ensure_table(
        data_root=Path(arguments.data_root),
        vocabulary=loaded.index.vocabulary[:entry_count],
        config=fit_config, clock=harness.default_clock)
    print(f"table entries={len(table)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
