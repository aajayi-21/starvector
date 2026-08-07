"""Pool preparation pipeline. Spec: docs/specs/pool-preparation.md.

Public API: run_preparation and format_report (pool.preparation.run),
load_preparation_config and PreparationConfig (pool.preparation.config),
PreparationReport, StageReport, and STAGE_NAMES
(pool.preparation.types). The attributes load lazily, and importing
the package stays cheap.
"""

from typing import Any

__all__ = [
    "PreparationConfig",
    "PreparationReport",
    "STAGE_NAMES",
    "StageReport",
    "format_report",
    "load_preparation_config",
    "run_preparation",
]


def __getattr__(name: str) -> Any:
    if name in ("run_preparation", "format_report"):
        from pool.preparation import run

        return getattr(run, name)
    if name in ("PreparationConfig", "load_preparation_config"):
        from pool.preparation import config

        return getattr(config, name)
    if name in ("PreparationReport", "StageReport", "STAGE_NAMES"):
        from pool.preparation import types

        return getattr(types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
