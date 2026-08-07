"""Pool curation pipeline. Spec: docs/specs/pool-curation.md.

Public API: run_curation and format_funnel (pool.curation.run),
load_curation_config and CurationConfig (pool.curation.config),
RunReport, StageReport, and STAGE_NAMES (pool.curation.types). The
attributes load lazily, and importing the package stays cheap.
"""

from typing import Any

__all__ = [
    "CurationConfig",
    "RunReport",
    "STAGE_NAMES",
    "StageReport",
    "format_funnel",
    "load_curation_config",
    "run_curation",
]


def __getattr__(name: str) -> Any:
    if name in ("run_curation", "format_funnel"):
        from pool.curation import run

        return getattr(run, name)
    if name in ("CurationConfig", "load_curation_config"):
        from pool.curation import config

        return getattr(config, name)
    if name in ("RunReport", "StageReport", "STAGE_NAMES"):
        from pool.curation import types

        return getattr(types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
