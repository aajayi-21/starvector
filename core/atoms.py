"""Layer 1 atom assembly: interface fields to the atom set.

Implements docs/ARCHITECTURE.md section 9 through
docs/specs/scoring-path.md section 10. Frozen tier (R6): this module
has no configuration, reads no model, and does not change. Its output
must be reproducible byte-for-byte from the raw stored submission
forever. The input record must have cleared
core.intake.validate_submission — assembly assumes checked input.
"""

from core.canonical import JsonValue
from core.types import Atom, StrokePath, Submission

# Fragment separators for a pasted free-text value (architecture
# section 6): newlines and commas, one atom for each fragment, with no
# model. A fixed rule is permitted here because it is not a versioned
# artifact.
_NEWLINES = ("\r\n", "\r")


def split_pasted_text(text: str) -> tuple[str, ...]:
    """Split one pasted free-text value into atom fragments.

    Splits on newlines and commas, removes whitespace at each end of
    a fragment, and drops empty fragments (agreed 2026-08-08).
    Deterministic and frozen — a change here moves stored atom
    boundaries, which R6 forbids.
    """
    for marker in _NEWLINES:
        text = text.replace(marker, "\n")
    fragments = []
    for line in text.split("\n"):
        for piece in line.split(","):
            stripped = piece.strip()
            if stripped:
                fragments.append(stripped)
    return tuple(fragments)


def _stroke_path(raw_stroke: JsonValue) -> StrokePath:
    """Read one stroke's points as (x, y) pairs.

    Point entries 3 and 4 (optional time and pressure) stay in the
    raw record and are not read by scoring (agreed 2026-08-08).
    """
    points = raw_stroke["points"]
    return tuple((float(point[0]), float(point[1])) for point in points)


def assemble_atoms(record: JsonValue) -> Submission:
    """Assemble the atom set from one checked submission record.

    Emission sequence, with identifiers a1..an assigned in sequence
    (spec P2 section 10):

    1. One DESCRIPTION atom for each impressions row.
    2. One DESCRIPTION atom for each pasted_text fragment.
    3. One DESCRIPTION atom for each group: its member strokes in
       canvas sequence, plus the label text when the label is not
       empty. A group with no member stroke gets strokes=None
       (agreed 2026-08-08).
    4. One WHOLE-DRAWING atom with all canvas strokes, emitted when
       canvas_strokes is not empty.
    5. One RELATION atom for each relations row, with refers_to
       mapped from group identifiers to the atom identifiers of
       step 3.

    subtype is None on each atom — the frozen wire shape has no
    subtype field (agreed 2026-08-08).
    """
    atoms: list[Atom] = []

    def next_id() -> str:
        return f"a{len(atoms) + 1}"

    for text in record["impressions"]:
        atoms.append(Atom(id=next_id(), type="DESCRIPTION", subtype=None,
                          text=text, strokes=None, refers_to=None,
                          relation=None))

    pasted = record["pasted_text"]
    if pasted is not None:
        for fragment in split_pasted_text(pasted):
            atoms.append(Atom(id=next_id(), type="DESCRIPTION", subtype=None,
                              text=fragment, strokes=None, refers_to=None,
                              relation=None))

    raw_strokes = record["canvas_strokes"]
    atom_id_by_group: dict[str, str] = {}
    for group in record["groups"]:
        members = tuple(_stroke_path(stroke) for stroke in raw_strokes
                        if stroke["group_id"] == group["id"])
        label = group["label"]
        atom_id = next_id()
        atom_id_by_group[group["id"]] = atom_id
        atoms.append(Atom(id=atom_id, type="DESCRIPTION", subtype=None,
                          text=label if label else None,
                          strokes=members if members else None,
                          refers_to=None, relation=None))

    if raw_strokes:
        all_strokes = tuple(_stroke_path(stroke) for stroke in raw_strokes)
        atoms.append(Atom(id=next_id(), type="WHOLE-DRAWING", subtype=None,
                          text=None, strokes=all_strokes, refers_to=None,
                          relation=None))

    for row in record["relations"]:
        first, second = row["of"]
        atoms.append(Atom(id=next_id(), type="RELATION", subtype=None,
                          text=None, strokes=None,
                          refers_to=(atom_id_by_group[first],
                                     atom_id_by_group[second]),
                          relation=row["relation"]))

    return Submission(atoms=tuple(atoms))
