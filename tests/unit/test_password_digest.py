"""Unit tests for the password digest (spec A2 section 5.2).

Each test here does the work of Argon2id, thus the count of the tests
is small.
"""

import pytest

from service.digests import (ARGON2_ITERATIONS, ARGON2_LANES,
                             ARGON2_MEMORY_KIB, Argon2Digester,
                             digester_from_pepper, peppered)

PEPPER = b"test-pepper-not-a-secret"


@pytest.fixture(scope="module")
def digester() -> Argon2Digester:
    return Argon2Digester(pepper=PEPPER)


def test_the_stored_text_names_the_ruled_parameters(digester) -> None:
    stored = digester.digest("correct horse battery")
    assert stored.startswith(
        f"$argon2id$v=19$m={ARGON2_MEMORY_KIB},t={ARGON2_ITERATIONS},"
        f"p={ARGON2_LANES}$")
    assert "correct horse battery" not in stored
    assert not digester.stale(stored)


def test_a_digest_agrees_with_its_password_alone(digester) -> None:
    stored = digester.digest("correct horse battery")
    assert digester.agrees("correct horse battery", stored)
    assert not digester.agrees("correct horse batterz", stored)
    # Each digest has its own salt.
    assert digester.digest("correct horse battery") != stored


def test_a_second_pepper_does_not_agree(digester) -> None:
    stored = digester.digest("correct horse battery")
    other = Argon2Digester(pepper=b"a-different-pepper")
    assert not other.agrees("correct horse battery", stored)


def test_a_digest_of_other_parameters_is_stale(digester) -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(
        peppered("correct horse battery", PEPPER))
    assert digester.stale(weak)
    # The earlier digest continues to agree: the text holds its parameters.
    assert digester.agrees("correct horse battery", weak)


def test_text_that_is_not_argon2_raises(digester) -> None:
    with pytest.raises(ValueError, match="not Argon2 text"):
        digester.agrees("correct horse battery", "plain text")


def test_the_absent_compare_answers_nothing(digester) -> None:
    assert digester.absent("correct horse battery") is None


def test_the_pepper_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="pepper is empty"):
        Argon2Digester(pepper=b"")
    assert digester_from_pepper(None) is None
    assert digester_from_pepper("") is None
    assert isinstance(digester_from_pepper("a pepper"), Argon2Digester)


def test_the_pepper_step_gives_hex_text_for_each_input() -> None:
    assert len(peppered("x" * 128, PEPPER)) == 64
    assert peppered("a", PEPPER) != peppered("a", b"other")
