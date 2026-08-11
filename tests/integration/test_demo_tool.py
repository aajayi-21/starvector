"""Smoke test for the demo tool (docs/specs/demo-tool.md).

The fixture path end to end: the report builds, holds the dev-only
banner, the ranking, and the trial score, and a second run gives
equal bytes (R12).
"""

from tools.demo import main


def test_the_fixture_demo_writes_a_report(tmp_path) -> None:
    out = tmp_path / "report.html"
    code = main(["--fixture", "--fixture-root", str(tmp_path / "pool"),
                 "--level", "0", "--seed", "3", "--out", str(out)])
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "DEV-ONLY" in text
    assert "trial score" in text
    assert "fused z" in text
    assert "source image" in text

    again = tmp_path / "again.html"
    code = main(["--fixture", "--fixture-root", str(tmp_path / "pool"),
                 "--level", "0", "--seed", "3", "--out", str(again)])
    assert code == 0
    assert again.read_text(encoding="utf-8") == text


def test_a_level_out_of_range_stops(tmp_path) -> None:
    code = main(["--fixture", "--fixture-root", str(tmp_path / "pool"),
                 "--level", "9", "--seed", "3",
                 "--out", str(tmp_path / "report.html")])
    assert code == 2
