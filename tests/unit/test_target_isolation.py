"""Invariant 1: no module upstream of Layer 8 references the target.

Rule A scans each scoring module out of the sanctioned set for NAME
tokens that hold "target" — tokens, not raw text, thus prose in
comments and docstrings stays free. Rule B parses pipeline/score.py
and requires each load of the target name to be an argument given
to a Layer 8 function. The module tables are pinned: a new file is
scanned by default, and an exclusion is a reviewed diff.
"""

import ast
import io
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Rule A scope. core/ranking.py is Layer 8. core/types.py holds the
# TargetId and DecoySet aliases and no behavior. pipeline/score.py has
# its own AST rule (Rule B).
SCANNED_CORE = (
    "core/atoms.py",
    "core/canonical.py",
    "core/channels/__init__.py",
    "core/channels/element.py",
    "core/channels/outline.py",
    "core/fusion.py",
    "core/intake.py",
    "core/lineart.py",
    "core/normalize.py",
)
SCANNED_PIPELINE = (
    "pipeline/__init__.py",
    "pipeline/commonness.py",
    "pipeline/config.py",
    "pipeline/context.py",
)
LAYER_EIGHT_CALLS = {"decoy_set", "rank"}

# Reviewed exceptions to Rule A, one comment each. v2_target_seed is
# the V2 harness seed — a random seed, not a target identifier. The
# target it selects is drawn in validation/v2.py and enters scoring
# only through the Layer 8 arguments of score_trial (Rule B).
ALLOWED_TOKENS = {"v2_target_seed"}


def _name_tokens(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [token.string
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.NAME]


def test_the_scanned_module_tables_cover_the_packages() -> None:
    for package, table in (("core", SCANNED_CORE),
                           ("pipeline", SCANNED_PIPELINE)):
        found = {str(path.relative_to(REPO))
                 for path in (REPO / package).rglob("*.py")}
        sanctioned = set(table) | {"core/ranking.py", "core/types.py",
                                   "pipeline/score.py", "core/__init__.py"}
        assert found <= sanctioned, sorted(found - sanctioned)


def test_no_upstream_module_names_the_target() -> None:
    for relative in SCANNED_CORE + SCANNED_PIPELINE:
        for token in _name_tokens(REPO / relative):
            if token in ALLOWED_TOKENS:
                continue
            assert "target" not in token.lower(), (relative, token)


def test_core_types_holds_no_behavior() -> None:
    tree = ast.parse((REPO / "core/types.py").read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert functions == []


def test_score_trial_passes_the_target_only_into_layer_eight() -> None:
    tree = ast.parse((REPO / "pipeline/score.py").read_text(encoding="utf-8"))
    allowed_loads: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(
                callee, "attr", None)
            if name in LAYER_EIGHT_CALLS:
                for argument in list(node.args) + [
                        keyword.value for keyword in node.keywords]:
                    if isinstance(argument, ast.Name):
                        allowed_loads.add(id(argument))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and "target" in node.id.lower():
            if node.id == "TargetId":
                continue
            assert node.id == "target", node.id
            if isinstance(node.ctx, ast.Load):
                assert id(node) in allowed_loads, (
                    "the target flows somewhere before Layer 8")
