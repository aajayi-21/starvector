"""The image credit for a revealed target (spec BR1 section 6).

The pool's images come from Wikimedia Commons, and each one wants a
credit and a pointer to its file page, where the author and the
license are named. The release manifest of the curation run holds
each image's source address. This module turns it into the credit a
reveal shows.

The credit is display text for a revealed day alone. The reveal
endpoint carries it after its revealed gate, thus no answer about an
open day holds it (R3).
"""

import json
import sys
import urllib.parse
from pathlib import Path

_COMMONS_UPLOAD_HOST = "upload.wikimedia.org"
_COMMONS_PAGE = "https://commons.wikimedia.org/wiki/File:"


def commons_credit(source_key: str) -> dict[str, str] | None:
    """The credit for one source address, or None for other text.

    A Commons upload address ends in the file name, and the file page
    is that name below /wiki/File:. An address from a different host
    gets its host as the source and itself as the page.
    """
    if not isinstance(source_key, str):
        return None
    parts = urllib.parse.urlsplit(source_key)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if parts.netloc == _COMMONS_UPLOAD_HOST and "/commons/" in parts.path:
        encoded = parts.path.rsplit("/", 1)[-1]
        name = urllib.parse.unquote(encoded)
        if not name:
            return None
        return {
            "source": "Wikimedia Commons",
            "title": name.rsplit(".", 1)[0].replace("_", " "),
            "page": _COMMONS_PAGE + urllib.parse.quote(name),
        }
    return {"source": parts.netloc, "title": parts.netloc,
            "page": source_key}


def manifest_path(data_root: Path, release_record: dict) -> Path:
    """The s09 release manifest a pool release record names."""
    return (Path(data_root) / "curation"
            / str(release_record["corpus_id"])[:8]
            / str(release_record["curation_config_hash"])[:8]
            / "s09-release" / "manifest.jsonl")


def load_credits(release_record_path: Path,
                 data_root: Path) -> dict[str, dict[str, str]]:
    """Each pool image's credit, keyed by image id.

    A missing release record or manifest answers an empty map and a
    warning on the error stream: the credit is display text, and a
    box with no curation tree continues to run each day. A
    manifest that is there and does not parse raises.
    """
    if not Path(release_record_path).is_file():
        print(f"warning: no pool release record at {release_record_path} - "
              "reveals show no image credit", file=sys.stderr)
        return {}
    release = json.loads(Path(release_record_path).read_text(
        encoding="utf-8"))
    path = manifest_path(data_root, release)
    if not path.is_file():
        print(f"warning: no release manifest at {path} - reveals show no "
              "image credit", file=sys.stderr)
        return {}
    credits: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        credit = commons_credit(row.get("source_key"))
        if credit is not None:
            credits[str(row["image_id"])] = credit
    return credits
