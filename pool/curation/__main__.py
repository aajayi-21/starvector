"""Command-line entry for the curation pipeline.

Thin wrapper: parse flags, load the config, start run_curation, print
the funnel. Exit codes: 0 when the requested stages are complete, 3
when the run halted at the s08 review gate.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pool.curation.config import ConfigError, load_curation_config
from pool.curation.run import format_funnel, run_curation


def _git_code_version(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pool.curation")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--releases-root", type=Path, default=Path("pool/releases"))
    parser.add_argument("--through", default=None, help="last stage to run, s00..s09")
    parser.add_argument("--force-from", default=None, help="delete and run again from this stage")
    parser.add_argument(
        "--report", action="store_true", help="read and print the funnel, run nothing"
    )
    arguments = parser.parse_args(argv)

    try:
        config = load_curation_config(arguments.config)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    print(f"config ok: {arguments.config}")

    try:
        report = run_curation(
            config,
            config_path=arguments.config,
            data_root=arguments.data_root,
            releases_root=arguments.releases_root,
            code_version=_git_code_version(Path.cwd()),
            through=arguments.through,
            force_from=arguments.force_from,
            report_only=arguments.report,
        )
    except Exception as error:
        if arguments.report:
            print(f"no funnel to report: {type(error).__name__}: {error}", file=sys.stderr)
            return 0
        print(f"run stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise

    print(format_funnel(report))
    if not arguments.report and report.halted_at is not None:
        sheet = "see the s08-review directory for contact_sheet.html and write review.json"
        print(f"halted: {report.halt_reason} - {sheet}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
