"""Unit tests for the s04 rules in pool.curation.stages.classify."""

import numpy as np

from pool.curation.stages.classify import (
    NO_WINNER_REASON,
    class_decisions,
    reason_for_label,
    rendered_labels,
    winning_label,
)

_LABELS = (
    "photograph",
    "diagram",
    "chart",
    "logo",
    "map",
    "screenshot",
    "coat of arms",
    "line drawing",
)


def _row(winner_index: int, winner_value: float) -> list[float]:
    remainder = (1.0 - winner_value) / (len(_LABELS) - 1)
    row = [remainder] * len(_LABELS)
    row[winner_index] = winner_value
    return row


def test_rendered_labels_fill_the_template() -> None:
    assert rendered_labels(("photograph", "coat of arms"), "a {label}") == (
        "a photograph",
        "a coat of arms",
    )


def test_reason_for_label_turns_spaces_into_hyphens() -> None:
    assert reason_for_label("coat of arms") == "class-coat-of-arms"
    assert reason_for_label("diagram") == "class-diagram"


def test_photograph_argmax_stays() -> None:
    probabilities = np.array([_row(0, 0.75)], dtype=np.float32)
    result = class_decisions(["a"], probabilities, _LABELS, "photograph")
    assert result.survivors == ("a",)
    assert result.rejections == ()


def test_diagram_winner_gets_rejected_with_its_probability() -> None:
    probabilities = np.array([_row(1, 0.75)], dtype=np.float32)
    result = class_decisions(["a"], probabilities, _LABELS, "photograph")
    assert result.survivors == ()
    rejection = result.rejections[0]
    assert rejection.key == "a"
    assert rejection.stage == "s04-class"
    assert rejection.reason == "class-diagram"
    assert rejection.measured == 0.75


def test_coat_of_arms_winner_gets_a_hyphenated_reason() -> None:
    probabilities = np.array([_row(6, 0.5)], dtype=np.float32)
    result = class_decisions(["a"], probabilities, _LABELS, "photograph")
    assert result.rejections[0].reason == "class-coat-of-arms"


def test_equal_winning_values_have_no_winner() -> None:
    # Indices 0 and 2 hold the same winning value. Before the s04 note
    # of 2026-11-11 index 0 won, and the keep label stayed by its
    # position alone.
    row = [0.03125] * len(_LABELS)
    row[0] = 0.375
    row[2] = 0.375
    probabilities = np.array([row], dtype=np.float32)
    result = class_decisions(["a"], probabilities, _LABELS, "photograph")
    assert result.survivors == ()
    rejection = result.rejections[0]
    assert rejection.reason == NO_WINNER_REASON == "class-no-winner"
    assert rejection.measured == 0.375


def test_a_row_with_no_information_does_not_keep_the_candidate() -> None:
    probabilities = np.full((1, len(_LABELS)), 1.0 / len(_LABELS), dtype=np.float32)
    result = class_decisions(["a"], probabilities, _LABELS, "photograph")
    assert result.survivors == ()
    assert result.rejections[0].reason == NO_WINNER_REASON


def test_a_stated_label_below_its_row_has_no_winner() -> None:
    # The screener row of a contradictory answer: the stated label is
    # below each other label. That holds for the keep label and for a
    # different stated label, which must not let the keep label win.
    for stated in (0, 4):
        probabilities = np.array([_row(stated, 0.05)], dtype=np.float32)
        result = class_decisions(["a"], probabilities, _LABELS, "photograph")
        assert result.survivors == ()
        assert result.rejections[0].reason == NO_WINNER_REASON


def test_winning_label_gives_the_one_winner_or_none() -> None:
    assert winning_label(np.array(_row(4, 0.6), dtype=np.float32), _LABELS) == "map"
    assert winning_label(np.array(_row(4, 0.05), dtype=np.float32), _LABELS) is None


def test_accounting_and_input_sequence() -> None:
    probabilities = np.array(
        [_row(0, 0.9), _row(4, 0.6), _row(0, 0.51), _row(5, 0.99)],
        dtype=np.float32,
    )
    result = class_decisions(["a", "b", "c", "d"], probabilities, _LABELS, "photograph")
    assert result.survivors == ("a", "c")
    assert [r.key for r in result.rejections] == ["b", "d"]
    assert [r.reason for r in result.rejections] == ["class-map", "class-screenshot"]
    assert len(result.survivors) + len(result.rejections) == 4
