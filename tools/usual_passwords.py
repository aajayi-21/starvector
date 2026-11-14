"""Make the table of usual passwords (spec A2 section 5.1, decision D4).

The input is one public table of breached passwords, one entry for
each line. The output keeps each entry that the sign-up rule can get:
12 to 128 code points after NFKC, printable characters alone. Each
kept entry is in its casefold shape, and the output is sorted with no
entry two times. The sidecar file names the input, thus a person can
make the table again from the same bytes.

Dev-only tooling. The server reads the output file and not this
module.
"""

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path

from service.passwords import PASSWORD_MAX, PASSWORD_MIN


def kept_entries(lines: list[str]) -> list[str]:
    """The entries of the table, from the lines of the input.

    lines hold no line end. The output is sorted and each entry is in
    it one time.
    """
    kept: set[str] = set()
    for line in lines:
        entry = unicodedata.normalize("NFKC", line).casefold()
        if PASSWORD_MIN <= len(entry) <= PASSWORD_MAX and entry.isprintable():
            kept.add(entry)
    return sorted(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.usual_passwords")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--out", type=Path,
                        default=Path("service/data/usual-passwords.txt"))
    arguments = parser.parse_args(argv)
    raw = arguments.input.read_bytes()
    lines = raw.decode("utf-8", errors="replace").split("\n")
    entries = kept_entries(lines)
    text = "\n".join(entries) + "\n"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(text, encoding="utf-8")
    sidecar = {
        "source_url": arguments.source_url,
        "source_commit": arguments.source_commit,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_line_count": len(lines),
        "license": arguments.license,
        "rule": f"NFKC, casefold, {PASSWORD_MIN} to {PASSWORD_MAX} code "
                "points, printable",
        "entry_count": len(entries),
        "table_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    arguments.out.with_suffix(".source.json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"entries={len(entries)} of {len(lines)} lines -> {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
