"""Unit tests for the Layer 1 assembler and the frozen wire shape."""

from core.atoms import assemble_atoms, split_pasted_text
from core.types import Atom

_RECORD = {
    "impressions": ["tall vertical structure", "cold and exposed"],
    "canvas_strokes": [
        {"points": [[0.1, 0.2], [0.3, 0.4]], "group_id": "g1"},
        {"points": [[0.5, 0.5], [0.6, 0.6]], "group_id": None},
    ],
    "groups": [
        {"id": "g1", "label": "tower"},
        {"id": "g2", "label": ""},
    ],
    "relations": [{"relation": "left-of", "of": ["g1", "g2"]}],
    "pasted_text": "water nearby, metallic\nwindy",
}


def test_paste_split_on_newlines_and_commas_drops_empties() -> None:
    assert split_pasted_text("a, b\nc") == ("a", "b", "c")
    assert split_pasted_text(" a ,, \n , b ") == ("a", "b")
    assert split_pasted_text("\r\nx\r y") == ("x", "y")
    assert split_pasted_text("") == ()


def test_emission_sequence_and_identifiers_are_pinned() -> None:
    submission = assemble_atoms(_RECORD)
    assert submission.atoms == (
        Atom(id="a1", type="DESCRIPTION", subtype=None,
             text="tall vertical structure", strokes=None,
             refers_to=None, relation=None),
        Atom(id="a2", type="DESCRIPTION", subtype=None,
             text="cold and exposed", strokes=None,
             refers_to=None, relation=None),
        Atom(id="a3", type="DESCRIPTION", subtype=None,
             text="water nearby", strokes=None, refers_to=None,
             relation=None),
        Atom(id="a4", type="DESCRIPTION", subtype=None,
             text="metallic", strokes=None, refers_to=None, relation=None),
        Atom(id="a5", type="DESCRIPTION", subtype=None,
             text="windy", strokes=None, refers_to=None, relation=None),
        Atom(id="a6", type="DESCRIPTION", subtype=None, text="tower",
             strokes=(((0.1, 0.2), (0.3, 0.4)),), refers_to=None,
             relation=None),
        Atom(id="a7", type="DESCRIPTION", subtype=None, text=None,
             strokes=None, refers_to=None, relation=None),
        Atom(id="a8", type="WHOLE-DRAWING", subtype=None, text=None,
             strokes=(((0.1, 0.2), (0.3, 0.4)),
                      ((0.5, 0.5), (0.6, 0.6))),
             refers_to=None, relation=None),
        Atom(id="a9", type="RELATION", subtype=None, text=None,
             strokes=None, refers_to=("a6", "a7"), relation="left-of"),
    )


def test_assembly_is_reproducible() -> None:
    assert assemble_atoms(_RECORD) == assemble_atoms(_RECORD)


def test_no_canvas_strokes_means_no_drawing_atom() -> None:
    record = {"impressions": ["one"], "canvas_strokes": [], "groups": [],
              "relations": [], "pasted_text": None}
    submission = assemble_atoms(record)
    assert [atom.type for atom in submission.atoms] == ["DESCRIPTION"]


def test_optional_point_entries_are_not_read() -> None:
    record = {
        "impressions": [],
        "canvas_strokes": [
            {"points": [[0.1, 0.2, 3.5, 0.9], [0.3, 0.4, 3.6, 0.8]],
             "group_id": None}],
        "groups": [], "relations": [], "pasted_text": None,
    }
    submission = assemble_atoms(record)
    assert submission.atoms[0].strokes == (((0.1, 0.2), (0.3, 0.4)),)
