"""Command-line entry for the preparation pipeline.

Thin wrapper: parse flags, load the config, start run_preparation,
print the report. Exit code 0 when the requested stages are complete,
2 on a config error. Other errors propagate.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pool.preparation.config import ConfigError, load_preparation_config
from pool.preparation.run import format_report, run_preparation


def _git_code_version(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pool.preparation")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--releases-root", type=Path, default=Path("pool/preparations"))
    parser.add_argument("--through", default=None, help="last stage to run, p00..p09")
    parser.add_argument("--force-from", default=None, help="delete and run again from this stage")
    parser.add_argument(
        "--report", action="store_true", help="read and print the report, run nothing"
    )
    arguments = parser.parse_args(argv)

    try:
        config = load_preparation_config(arguments.config)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    print(f"config ok: {arguments.config}")

    try:
        report = run_preparation(
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
            print(f"no report to print: {type(error).__name__}: {error}", file=sys.stderr)
            return 0
        print(f"run stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise

    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
