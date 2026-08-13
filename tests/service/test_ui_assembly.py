"""The page logic fixture (spec S1 section 11).

The pinned wire record always clears Layer 0 - that half runs with
no JavaScript runtime. The node half replays the recorded
interaction through the shipped page core and must reproduce the
pinned record byte-for-structure.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from svc_fixture import mixed_wire_record

from core.intake import validate_submission
from core.types import IntakeGates

_FIXTURES = Path(__file__).parent / "fixtures"


def _expected() -> dict:
    return json.loads((_FIXTURES / "expected_record.json").read_text())


def test_the_pinned_record_clears_layer_zero() -> None:
    gates = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=2,
                        max_text_length=200, max_atoms=64)
    submission = validate_submission(_expected(), gates, 512)
    # Two impressions, two labeled groups, the full drawing, one
    # relation: six atoms.
    assert len(submission.atoms) == 6


def test_the_pinned_record_is_the_service_fixture_record() -> None:
    # One source of truth: the lifecycle tests send the same record
    # the page fixture pins.
    assert _expected() == mixed_wire_record()


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not installed")
def test_the_page_core_assembles_the_pinned_record() -> None:
    completed = subprocess.run(
        ["node", str(_FIXTURES / "run_assemble.js"),
         str(_FIXTURES / "interaction_script.json")],
        capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == _expected()


def _colored() -> dict:
    return json.loads((_FIXTURES / "colored_record.json").read_text())


def test_the_colored_pin_clears_layer_zero() -> None:
    gates = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=2,
                        max_text_length=200, max_atoms=64)
    submission = validate_submission(_colored(), gates, 512)
    drawing = [a for a in submission.atoms if a.type == "WHOLE-DRAWING"][0]
    assert drawing.stroke_colors == ("#1a73e8", None)


def test_the_ink_stroke_in_the_colored_pin_has_no_color_key() -> None:
    # The spec C1 interface rule: ink emits no key, thus a plain
    # sketch stays byte-for-byte equal to one from before the ruling.
    strokes = _colored()["canvas_strokes"]
    assert "color" in strokes[0]
    assert "color" not in strokes[1]


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not installed")
def test_the_page_core_assembles_the_colored_pin() -> None:
    completed = subprocess.run(
        ["node", str(_FIXTURES / "run_assemble.js"),
         str(_FIXTURES / "colored_script.json")],
        capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == _colored()
