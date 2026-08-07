"""Unit tests for the p02 normalization rules and the D7 table."""

import unicodedata

import pytest

from pool.preparation.stages.normalize import (
    normalize_element,
    normalize_elements,
    normalize_flatten,
)
from pool.preparation.types import ElementResponse

D7_TABLE = [
    ("berries", "berry"),
    ("boxes", "box"),
    ("dishes", "dish"),
    ("glasses", "glass"),
    ("grass", "grass"),
    ("boss", "boss"),
    ("bus", "bus"),
    ("gas", "gas"),
    ("cars", "car"),
    ("the lighthouse", "lighthouse"),
    ("a  tall   tower", "tall tower"),
    ("the", "the"),
    ("an", "an"),
    ("", ""),
    ("   ", ""),
    ("Stones", "stone"),
]


@pytest.mark.parametrize("raw,expected", D7_TABLE)
def test_d7_v1_table(raw: str, expected: str) -> None:
    assert normalize_element(raw) == expected


@pytest.mark.parametrize("raw,expected", D7_TABLE)
def test_normalization_is_idempotent(raw: str, expected: str) -> None:
    assert normalize_element(normalize_element(raw)) == normalize_element(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [("houses", "hous"), ("horses", "hors"), ("nurses", "nurs")],
)
def test_sibilant_stem_words_are_single_pass(raw: str, expected: str) -> None:
    # The d7-v1 -es rule fires on these stems, and a second run
    # decreases the output again. The pipeline and the atom path each
    # normalize one time - the docstring pins that contract.
    assert normalize_element(raw) == expected
    assert normalize_element(expected) != expected


def test_nfc_composition() -> None:
    decomposed = "café"  # 'e' plus a combining acute accent
    composed = unicodedata.normalize("NFC", decomposed)
    assert normalize_element(decomposed) == normalize_element(composed) == "café"


def test_article_stripped_only_when_a_word_follows() -> None:
    assert normalize_element("a stone") == "stone"
    assert normalize_element("an apple") == "apple"
    assert normalize_element("a") == "a"


def test_flatten_sequence_is_the_field_sequence() -> None:
    response = ElementResponse(
        objects=("o1", "o2"),
        materials=("m1",),
        colors=("c1", "c2"),
        shapes=("s1",),
        scale="close-up",
        setting="indoor",
        ambience=("a1",),
    )
    assert normalize_flatten(response) == (
        "o1", "o2", "m1", "c1", "c2", "s1", "close-up", "indoor", "a1",
    )


def test_scale_and_sixth_field_contribute_one_entry_each() -> None:
    response = ElementResponse(
        objects=(), materials=(), colors=(), shapes=(),
        scale="wide", setting="outdoor", ambience=(),
    )
    assert normalize_flatten(response) == ("wide", "outdoor")


def test_normalize_elements_dedupes_and_keeps_first() -> None:
    response = ElementResponse(
        objects=("Trees", "rock"),
        materials=("stone",),
        colors=("red", "Red"),
        shapes=("round",),
        scale="wide",
        setting="tree",     # duplicates "tree" after singularization
        ambience=("calm",),
    )
    assert normalize_elements(response) == (
        "tree", "rock", "stone", "red", "round", "wide", "calm",
    )


def test_normalize_elements_drops_emptied_entries() -> None:
    response = ElementResponse(
        objects=("  ", "rock"),
        materials=(), colors=(), shapes=(),
        scale="wide", setting="indoor", ambience=(),
    )
    assert normalize_elements(response) == ("rock", "wide", "indoor")
