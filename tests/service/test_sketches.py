"""The sketch of a stored send (spec SS1 section 5): pure functions."""

import json

import pytest

from svc_fixture import colored_wire_record, mixed_wire_record

from service import sketches

SENTINEL = "zq-sentinel"


def _record_with_text() -> dict:
    """A wire record with the sentinel in each text field."""
    return {
        "impressions": [f"{SENTINEL}-word"],
        "canvas_strokes": [
            {"points": [[0.1, 0.2], [0.3, 0.4]],
             "group_id": f"{SENTINEL}-group"},
            {"points": [[0.5, 0.5, 0.7, 12.0], [0.6, 0.5]],
             "group_id": None, "color": "#bf616a"},
        ],
        "groups": [{"id": f"{SENTINEL}-group", "label": f"{SENTINEL}-label"}],
        "relations": [{"relation": f"{SENTINEL}-relation",
                       "of": [f"{SENTINEL}-group", f"{SENTINEL}-group"]}],
        "pasted_text": f"{SENTINEL}-note",
    }


def test_the_sketch_holds_the_points_and_the_color_alone() -> None:
    sketch = sketches.sketch_of(_record_with_text())
    assert sketch == [
        {"points": [[0.1, 0.2], [0.3, 0.4]]},
        # The numbers after the two coordinates do not go out.
        {"points": [[0.5, 0.5], [0.6, 0.5]], "color": "#bf616a"},
    ]
    assert SENTINEL not in json.dumps(sketch)
    assert {key for stroke in sketch for key in stroke} \
        <= {"points", "color"}


def test_the_stored_records_of_the_tests_give_their_strokes() -> None:
    mixed = sketches.sketch_of(mixed_wire_record())
    assert len(mixed) == 2 and sketches.point_count(mixed) == 10
    assert all("color" not in stroke for stroke in mixed)
    colored = sketches.sketch_of(colored_wire_record())
    assert any("color" in stroke for stroke in colored)


def test_a_record_with_no_stroke_gives_an_empty_sketch() -> None:
    record = {**mixed_wire_record(), "canvas_strokes": []}
    assert sketches.sketch_of(record) == []
    assert sketches.point_count([]) == 0


@pytest.mark.parametrize("record", [
    None,
    [],
    {"impressions": []},
    {"canvas_strokes": "lines"},
    {"canvas_strokes": [["not", "a", "stroke"]]},
    {"canvas_strokes": [{"points": "none"}]},
    {"canvas_strokes": [{"points": [[0.1]]}]},
    {"canvas_strokes": [{"points": [[0.1, "y"]]}]},
    {"canvas_strokes": [{"points": [[True, 0.2]]}]},
    {"canvas_strokes": [{"points": [[0.1, 0.2]], "color": "red"}]},
    {"canvas_strokes": [{"points": [[0.1, 0.2]], "color": "#BF616A"}]},
])
def test_a_record_of_a_different_shape_stops(record) -> None:
    with pytest.raises(sketches.SketchError):
        sketches.sketch_of(record)


@pytest.mark.parametrize(("has_strokes", "withheld", "shows", "state"), [
    (True, False, True, "sketch"),
    (False, False, True, "words-only"),
    # A withheld send says nothing more, in each other condition.
    (True, True, True, "withheld"),
    (False, True, False, "withheld"),
    # A send that waits for the reveal does not say if it has a sketch.
    (True, False, False, "after-reveal"),
    (False, False, False, "after-reveal"),
])
def test_the_state_of_an_entry(has_strokes, withheld, shows, state) -> None:
    assert sketches.entry_state(has_strokes=has_strokes, withheld=withheld,
                                shows=shows) == state


def test_a_page_takes_its_first_entry_and_stops_at_a_cap() -> None:
    room = sketches.page_has_room
    # The first entry is always in the page, also with more points
    # than the cap.
    assert room(taken=0, points=0, more=10_000, entry_cap=3, point_cap=100)
    assert room(taken=1, points=40, more=60, entry_cap=3, point_cap=100)
    assert not room(taken=1, points=40, more=61, entry_cap=3, point_cap=100)
    assert room(taken=2, points=0, more=0, entry_cap=3, point_cap=100)
    assert not room(taken=3, points=0, more=0, entry_cap=3, point_cap=100)
