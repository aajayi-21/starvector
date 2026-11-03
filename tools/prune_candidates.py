"""Remove rejected candidates from the materialized image tree (spec PP1 B6).

Spec: docs/specs/production-pool.md build item B6. A production funnel
materializes about 5 candidates for each pool image, and each one stays
on disk with no use after its run. This tool lists the images that a
complete curation tree rejected. It keeps each image of each release,
and each image of a tree with no release, because a resume reads those.
An image that no curation tree names, for example a V1 photograph, is
not a candidate and stays. The default prints the count and removes
nothing. Provider caches stay, thus a new run gets its answers at no
cost.
"""

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from pool.artifacts import image_path


class PrunePlan(NamedTuple):
    """The images to remove, and the count that each rule kept."""

    remove: tuple[str, ...]
    kept_released: int
    kept_incomplete: int


def _manifest_ids(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as lines:
        return {str(json.loads(line)["image_id"]) for line in lines if line.strip()}


def prune_plan(trees: Iterable[Path]) -> PrunePlan:
    """Read each curation tree and split its images by the rule above."""
    materialized: set[str] = set()
    released: set[str] = set()
    incomplete: set[str] = set()
    for tree in trees:
        fetched = tree / "s02-materialize" / "manifest.jsonl"
        if not fetched.is_file():
            continue
        ids = _manifest_ids(fetched)
        release = tree / "s09-release" / "manifest.jsonl"
        if release.is_file():
            materialized |= ids
            released |= _manifest_ids(release)
        else:
            incomplete |= ids
    keep = released | incomplete
    return PrunePlan(remove=tuple(sorted(materialized - keep)),
                     kept_released=len(released), kept_incomplete=len(incomplete))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.prune_candidates")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--apply", action="store_true",
                        help="remove the files; with no flag, print the count")
    arguments = parser.parse_args(argv)
    trees = sorted(arguments.data_root.glob("curation/*/*"))
    plan = prune_plan(trees)
    paths = [image_path(arguments.data_root, image_id) for image_id in plan.remove]
    present = [path for path in paths if path.is_file()]
    size = sum(path.stat().st_size for path in present)
    print(f"{len(present)} rejected images on disk, {size / 1e9:.2f} GB; kept "
          f"{plan.kept_released} released, {plan.kept_incomplete} in trees "
          "with no release")
    if arguments.apply:
        for path in present:
            path.unlink()
        print(f"removed {len(present)} files")
    else:
        print("nothing removed - use --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
