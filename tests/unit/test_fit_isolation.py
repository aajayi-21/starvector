"""The R1 fit-boundary scan (spec P4 section 4, I6).

The fit code path must have no path to a live player trial: fitting
on live trials with the target as the label makes a signal that is
not there (architecture section 19). No module that
stores or serves player submissions exists in this build — this scan
pins the import surface of the fit-side modules to an allowlist, thus
the moment such a module lands, importing it from the fit is a test
failure and a review conversation, not a silent capability.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The fit-side modules that the R1 boundary contains.
SCANNED = (
    "validation/fit.py",
    "validation/fitconfig.py",
    "validation/generator.py",
    "validation/generalize.py",
    "validation/v3.py",
    "validation/v4.py",
)

# The import allowlist: labeled data sources, the generator stack, the
# scoring pipeline, and the standard library. Reviewed exceptions go
# here with a comment, in the pattern that keeps the target isolated.
ALLOWED_PREFIXES = (
    "core.",
    "pipeline.",
    "pool.artifacts",
    "pool.preparation",
    "providers.",
    "validation.fit",
    "validation.fitconfig",
    "validation.generalize",
    "validation.generator",
    "validation.harness",
    "validation.splits",
    "validation.v1",
    "validation.v3",
    # Standard library modules the fit side uses.
    "argparse", "collections", "dataclasses", "json", "math", "numpy",
    "pathlib", "sys", "typing", "os",
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


def test_the_fit_side_imports_stay_on_the_allowlist() -> None:
    for module in SCANNED:
        for name in sorted(_imports(REPO / module)):
            allowed = any(name == prefix.rstrip(".")
                          or name.startswith(prefix)
                          for prefix in ALLOWED_PREFIXES)
            assert allowed, (
                f"{module} imports {name!r}, which is outside the R1 "
                "allowlist — extending the fit's reach is a review "
                "conversation (I6)")


def test_the_scan_covers_the_fit_modules_on_disk() -> None:
    on_disk = {f"validation/{path.name}"
               for path in (REPO / "validation").glob("*.py")}
    fit_side = {name for name in on_disk
                if name.split("/")[-1].startswith(("fit", "generator",
                                                   "generalize"))}
    assert fit_side <= set(SCANNED), sorted(fit_side - set(SCANNED))
