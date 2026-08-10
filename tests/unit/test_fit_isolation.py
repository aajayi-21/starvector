"""The R1 fit-boundary scan (spec P4 section 4, I6).

The fit code path must have no path to a live player trial: fitting
on live trials with the target as the label makes a signal that is
not there (architecture section 19). No module that
stores or serves player submissions exists in this build — this scan
pins the import surface of the fit side to an allowlist, thus the
moment such a module lands, importing it from the fit is a test
failure and a review conversation, not a silent capability.

The scan is transitive across `validation/`: SCANNED must equal the
import closure of the runner modules, thus a new fit-side module is
scanned the moment a runner imports it — no edit necessary. The
closure stops at the package boundary: `core`, `pipeline`,
`providers`, and `pool.preparation` are trusted as packages, which is
what §17a decision 8 authorizes.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The fit-side entry points: the fit itself and the V3 through V6
# runners.
SEEDS = (
    "validation/fit.py",
    "validation/v3.py",
    "validation/v4.py",
    "validation/v5.py",
    "validation/v6.py",
)

# The scanned set: the import closure of SEEDS across validation/.
# A test below pins this table to the measured closure, thus an
# extension of the fit side is a diff here plus a review.
SCANNED = (
    "validation/fit.py",
    "validation/fitconfig.py",
    "validation/generalize.py",
    "validation/generator.py",
    "validation/harness.py",
    "validation/splits.py",
    "validation/v1.py",
    "validation/v2.py",
    "validation/v3.py",
    "validation/v4.py",
    "validation/v5.py",
    "validation/v6.py",
)

# The import allowlist for names that are not in validation/: labeled
# data sources, the generator stack, the scoring pipeline, and the
# standard library. Reviewed exceptions go here with a comment, in
# the pattern that keeps the target isolated. A validation/ name must
# be in SCANNED — this table does not cover it.
ALLOWED_PREFIXES = (
    "core.",
    "pipeline.",
    "pool.artifacts",
    "pool.preparation",
    "providers.",
    # v1 reads the dataset membership hash — labeled data, reviewed.
    "pool.curation.stages.release",
    # Standard library modules the fit side uses.
    "argparse", "collections", "dataclasses", "datetime", "io", "json",
    "math", "numpy", "pathlib", "sys", "typing", "os",
)


def _imports(path: Path) -> set[str]:
    """Each imported name in full: `from a import b` reads as a.b."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(f"{node.module}.{alias.name}"
                         for alias in node.names)
    return names


def _validation_module(name: str) -> str | None:
    """The validation/ file behind one imported name, or None."""
    parts = name.split(".")
    if parts[0] != "validation" or len(parts) < 2:
        return None
    return f"validation/{parts[1]}.py"


def _closure(seeds: tuple[str, ...]) -> set[str]:
    """The import closure of the seeds across validation/ files."""
    pending = list(seeds)
    seen: set[str] = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        for name in _imports(REPO / module):
            dependency = _validation_module(name)
            if dependency and (REPO / dependency).is_file():
                pending.append(dependency)
    return seen


def test_the_fit_side_imports_stay_on_the_allowlist() -> None:
    for module in SCANNED:
        for name in sorted(_imports(REPO / module)):
            dependency = _validation_module(name)
            if dependency is not None:
                assert dependency in SCANNED, (
                    f"{module} imports {name!r}, which is outside the "
                    "scanned set — add the module to SCANNED after "
                    "review (I6)")
                continue
            allowed = any(name == prefix.rstrip(".")
                          or name.startswith(prefix)
                          for prefix in ALLOWED_PREFIXES)
            assert allowed, (
                f"{module} imports {name!r}, which is outside the R1 "
                "allowlist — extending the fit's reach is a review "
                "conversation (I6)")


def test_the_scan_equals_the_runner_import_closure() -> None:
    assert _closure(SEEDS) == set(SCANNED), (
        "SCANNED does not equal the import closure of the runners — "
        "bring the list up to date so each fit-side module is scanned")
