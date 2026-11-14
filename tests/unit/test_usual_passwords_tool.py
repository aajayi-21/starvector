"""Unit tests for the tool that makes the table of usual passwords
(spec A2 decision D4)."""

import json

from service import passwords
from tools import usual_passwords


def test_the_kept_entries_follow_the_sign_up_rule() -> None:
    lines = ["short", "PasswordPassword", "passwordpassword",
             "twelve chars", "y" * 129, "has\x00control!!", ""]
    assert usual_passwords.kept_entries(lines) \
        == ["passwordpassword", "twelve chars"]


def test_the_tool_writes_the_table_and_its_source_file(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("123456\nqwertyuiop123\nQwertyuiop123\n")
    out = tmp_path / "usual-passwords.txt"
    assert usual_passwords.main([
        "--input", str(source), "--source-url", "https://example.test/x",
        "--source-commit", "abc", "--license", "MIT",
        "--out", str(out)]) == 0
    assert passwords.load_usual_passwords(out) == frozenset({"qwertyuiop123"})
    sidecar = json.loads(out.with_suffix(".source.json").read_text())
    assert sidecar["entry_count"] == 1
    assert sidecar["license"] == "MIT"


def test_the_committed_table_agrees_with_its_source_file() -> None:
    import hashlib

    path = passwords.USUAL_PASSWORDS_PATH
    sidecar = json.loads(path.with_suffix(".source.json").read_text())
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sidecar["table_sha256"]
    assert len(passwords.load_usual_passwords()) == sidecar["entry_count"]
