"""The start script of the operator command (spec OC1 section 5).

The script is `deploy/sv`. It needs root to do its work, thus these
tests read its text and start it as a user that is not root.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "sv"


def _code_lines() -> list[str]:
    """The lines of the script that are not comments."""
    return [line.strip() for line in SCRIPT.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_the_script_is_legal_shell_and_can_start() -> None:
    assert os.access(SCRIPT, os.X_OK)
    checked = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="the refusal is for a "
                    "caller that is not root")
def test_the_script_refuses_a_caller_that_is_not_root() -> None:
    answer = subprocess.run(["sh", str(SCRIPT), "status"],
                            capture_output=True, text=True)
    assert answer.returncode == 1
    assert answer.stderr.startswith("refused: start this command with sudo")
    assert answer.stdout == ""


def test_the_script_reads_two_values_and_does_not_run_the_env_file() -> None:
    lines = _code_lines()
    # No line runs the env file as a script, and no line exports each
    # value that a shell reads.
    assert not any(line.startswith(". ") or line.startswith("source ")
                   for line in lines)
    assert "set -a" not in lines
    read = [line for line in lines if "value_of " in line and "=$(" in line]
    assert read == ["token=$(value_of STARVECTOR_OPERATOR_TOKEN)",
                    "provider_key=$(value_of OPENROUTER_API_KEY)"]


def test_the_pepper_does_not_go_to_the_command() -> None:
    text = "\n".join(_code_lines())
    assert "STARVECTOR_PASSWORD_PEPPER" in text.split("unset ", 1)[1] \
        .split("\nif ", 1)[0]
    exported = [line for line in _code_lines() if line.startswith("export ")]
    assert not any("PEPPER" in line for line in exported)
    assert not any("value_of STARVECTOR_PASSWORD_PEPPER" in line
                   for line in _code_lines())


def test_no_secret_is_an_argument_of_a_process() -> None:
    lines = _code_lines()
    start = lines.index(next(line for line in lines
                             if line.startswith("exec setpriv")))
    command = " ".join(lines[start:])
    assert "$token" not in command and "$provider_key" not in command
    assert "TOKEN=" not in command and "KEY=" not in command
    # The script does not start the command through `env NAME=value`.
    assert not any(line.startswith(("env ", "exec env ")) for line in lines)


def test_the_script_becomes_the_store_owner_with_no_new_rights() -> None:
    text = " ".join(_code_lines())
    assert "RUN_AS=starvector" in text
    assert '--reuid="$RUN_AS" --regid="$RUN_AS" --init-groups' in text
    assert "--no-new-privs" in text
    assert "-m service.operator_cli" in text
    assert '--service-config "$CONFIG" "$@"' in text
    # Python does not read its start values from the caller.
    assert "python\" -E -s" in text
    assert "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP" in text


def test_the_script_checks_the_env_file_before_it_reads_it() -> None:
    lines = _code_lines()
    owner = next(index for index, line in enumerate(lines)
                 if 'stat -c %u "$ENV_FILE"' in line)
    first_read = next(index for index, line in enumerate(lines)
                      if line.startswith("token=$(value_of"))
    assert owner < first_read
    assert any(line.startswith("600 | 400)") for line in lines)


def test_the_script_gives_the_login_name_and_its_source() -> None:
    text = "\n".join(_code_lines())
    assert "/proc/self/loginuid" in text
    assert "login_source=login-uid" in text
    assert "login_source=sudo-user" in text
    assert 'export STARVECTOR_OPERATOR_LOGIN="$login"' in text
    assert ('export STARVECTOR_OPERATOR_LOGIN_SOURCE="$login_source"'
            in text)
    # The login-uid source comes first: it stays the same through su.
    assert text.index("login_source=login-uid") \
        < text.index("login_source=sudo-user")
