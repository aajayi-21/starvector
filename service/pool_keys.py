"""The pool key and the committed pool root (spec VP1 sections 3.1 and 6).

The pool key is 32 random bytes for each pool version, in the data root
and not in the repository. The pool root goes into the repository as
`configs/pool-roots/<preparation_version_id>.json`, and its commit must
be on the public default branch before the first day of that pool
version opens: the history of the public repository is its timestamp.

The make command of this module (the runbook in deploy/README.md gives
it) makes the key when there is none and writes the root file. It refuses
to change a root file that holds a different root.
"""

import argparse
import datetime
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from core.canonical import canonical_json_pretty
from service.pool_root import pool_root

_KEY_RULE = re.compile(r"[0-9a-f]{64}")


class PoolKeyError(ValueError):
    """A pool key or a pool root file is missing or does not agree."""


@dataclass(frozen=True, slots=True)
class PoolRootFile:
    preparation_version_id: str
    pool_count: int
    pool_root: str
    made: str


def key_path(data_root: Path, preparation_version_id: str) -> Path:
    return data_root / "pool-keys" / f"{preparation_version_id}.key"


def root_file_path(roots_dir: Path, preparation_version_id: str) -> Path:
    return roots_dir / f"{preparation_version_id}.json"


def make_key(path: Path) -> bytes:
    """Write a new key, mode 600. It refuses to replace a key."""
    if path.exists():
        raise PoolKeyError(f"{path}: a pool key exists - it is not replaced")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key.hex() + "\n")
    return key


def read_key(path: Path) -> bytes:
    """The stored key, or PoolKeyError. A missing key stops the caller."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PoolKeyError(
            f"{path}: cannot read the pool key: {error} - make it with "
            "`uv run python -m service.pool_keys make`") from error
    if not _KEY_RULE.fullmatch(text):
        raise PoolKeyError(f"{path}: expected 64 lowercase hex characters")
    return bytes.fromhex(text)


def read_root_file(path: Path) -> PoolRootFile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PoolKeyError(
            f"{path}: cannot read the pool root file: {error}") from error
    if not isinstance(raw, dict) or set(raw) != {
            "preparation_version_id", "pool_count", "pool_root", "made"}:
        raise PoolKeyError(f"{path}: unexpected fields")
    return PoolRootFile(**raw)


def checked_root(image_ids: tuple[str, ...], key: bytes, roots_dir: Path,
                 preparation_version_id: str) -> PoolRootFile:
    """The committed root file, after a check that the pool agrees.

    The open calls this: the root that the key and the pool give must
    equal the committed one, or the day does not open.
    """
    path = root_file_path(roots_dir, preparation_version_id)
    found = read_root_file(path)
    calculated = pool_root(image_ids, key)
    if found.pool_root != calculated or found.pool_count != len(image_ids) \
            or found.preparation_version_id != preparation_version_id:
        raise PoolKeyError(
            f"{path}: the committed pool root does not agree with the pool "
            "and the key - the pool or the key changed after the commit")
    return found


def write_root_file(image_ids: tuple[str, ...], key: bytes, roots_dir: Path,
                    preparation_version_id: str, made: str) -> PoolRootFile:
    """Write the root file, or keep an equal one. A different one raises."""
    path = root_file_path(roots_dir, preparation_version_id)
    value = PoolRootFile(preparation_version_id=preparation_version_id,
                         pool_count=len(image_ids),
                         pool_root=pool_root(image_ids, key), made=made)
    if path.exists():
        found = read_root_file(path)
        if (found.pool_root, found.pool_count) \
                != (value.pool_root, value.pool_count):
            raise PoolKeyError(
                f"{path}: a different root is committed - a new pool "
                "version gets a new file")
        return found
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_pretty({
        "preparation_version_id": value.preparation_version_id,
        "pool_count": value.pool_count,
        "pool_root": value.pool_root,
        "made": value.made,
    }) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    from pipeline.config import load_scoring_config
    from service import scoring
    from service.config import load_service_config

    parser = argparse.ArgumentParser(prog="service.pool_keys")
    parser.add_argument("command", choices=("make",))
    parser.add_argument("--service-config", required=True)
    args = parser.parse_args(argv)
    config = load_service_config(Path(args.service_config))
    scoring_config = load_scoring_config(Path(config.scoring_config))
    wired = scoring.wire_for_open(scoring_config, config.scoring_config,
                                  Path(config.data_root))
    version = wired.preparation_version_id
    path = key_path(Path(config.data_root), version)
    key = read_key(path) if path.exists() else make_key(path)
    found = write_root_file(
        wired.context.index.image_ids, key, Path(config.pool_roots_dir),
        version, datetime.date.today().isoformat())
    print(f"pool {version[:8]}: {found.pool_count} images, root "
          f"{found.pool_root}")
    print(f"commit {root_file_path(Path(config.pool_roots_dir), version)} "
          "and push it before the first day of this pool opens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
