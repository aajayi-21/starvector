"""Unit tests for the sign-up rules (spec A2 sections 4, 5.1, and 6)."""

import pytest

from service import auth, names, passwords

USUAL = frozenset({"passwordpassword", "qwertyuiop123"})


@pytest.mark.parametrize("name", ["ade", "no-one", "a2c", "x" * 20,
                                  "night-owl-7"])
def test_a_legal_username_has_no_refusal(name: str) -> None:
    assert names.username_refusal(name) is None


@pytest.mark.parametrize("name", [
    "ab",                # below the minimum
    "x" * 21,            # above the maximum
    "1abc",              # the first character is not a letter
    "-abc",
    "abc-",              # the last character is a hyphen
    "ab--cd",            # two hyphens together
    "Abc",               # a capital: the caller normalizes first
    "ab c", "ab_c", "ab.c", "abç",
    "",
])
def test_a_name_out_of_the_rule_is_refused(name: str) -> None:
    assert names.username_refusal(name) == names.NAME_RULE


@pytest.mark.parametrize("name", ["admin", "root", "r00t", "ad-min",
                                  "nu11", "starvector", "api"])
def test_a_reserved_name_is_refused_through_its_folded_shape(
        name: str) -> None:
    assert names.username_refusal(name) == names.NAME_RESERVED


def test_normalize_maps_ascii_capitals_alone() -> None:
    assert names.normalize_username("No-One") == "no-one"
    # U+212A, the Kelvin sign, becomes the ASCII k with str.lower.
    assert names.normalize_username("Kay") == "Kay"
    assert names.username_refusal(names.normalize_username("Kay")) \
        == names.NAME_RULE
    assert names.normalize_username(7) is None


def test_the_folded_shape_makes_one_name_of_look_alikes() -> None:
    assert names.folded_name("no-one") == names.folded_name("n0one")
    assert names.folded_name("al1ce") == names.folded_name("allce")
    assert names.folded_name("alice") != names.folded_name("alicia")


def test_a_good_password_has_no_refusal() -> None:
    assert passwords.password_refusal(
        "correct horse battery", "ade", USUAL) is None
    # No rule on character classes: small letters alone are legal.
    assert passwords.password_refusal("x" * 12, "ade", USUAL) is None
    assert passwords.password_refusal("y" * 128, "ade", USUAL) is None


@pytest.mark.parametrize("password", [
    "x" * 11,                   # below the minimum
    "y" * 129,                  # above the maximum
    "twelve chars\x00",         # a control character
    "has-ADE-inside-it",        # holds the username, in capitals
])
def test_a_password_out_of_the_rule_is_refused(password: str) -> None:
    assert passwords.password_refusal(password, "ade", USUAL) \
        == passwords.PASSWORD_RULE


def test_a_usual_password_is_refused_in_each_mix_of_capitals() -> None:
    assert passwords.password_refusal("PasswordPassword", "zed", USUAL) \
        == passwords.PASSWORD_USUAL


def test_the_length_counts_code_points_after_nfkc() -> None:
    # The ligature U+FB01 is one code point and NFKC makes it two.
    eleven = "ﬁ" + "x" * 10
    assert len(eleven) == 11
    normalized = passwords.normalize_password(eleven)
    assert len(normalized) == 12
    assert passwords.password_refusal(normalized, "ade", USUAL) is None
    assert passwords.normalize_password(None) is None


def test_the_committed_table_reads_and_holds_usual_passwords() -> None:
    table = passwords.load_usual_passwords()
    assert "passwordpassword" in table
    assert all(passwords.PASSWORD_MIN <= len(entry) <= passwords.PASSWORD_MAX
               for entry in table)
    assert all(entry == entry.casefold() for entry in table)


def test_a_missing_table_stops_the_read(tmp_path) -> None:
    with pytest.raises(OSError):
        passwords.load_usual_passwords(tmp_path / "none.txt")


def test_a_recovery_code_has_24_alphabet_characters() -> None:
    code = auth.make_recovery_code()
    assert len(code) == 24
    assert set(code) <= set(auth.DEVICE_CODE_ALPHABET)
    assert auth.make_recovery_code() != code


def test_a_typed_recovery_code_ignores_spaces_hyphens_and_capitals() -> None:
    code = "ABCDEFGHJKMNPQRSTUVWXYZ2"
    shown = auth.display_recovery_code(code)
    assert shown == "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2"
    assert auth.normalize_recovery_code(shown.lower()) == code
    assert auth.normalize_recovery_code("abcd efgh jkmn pqrs tuvw xyz2") \
        == code


@pytest.mark.parametrize("text", [
    "ABCDEFGHJKMNPQRSTUVWXYZ",        # 23 characters
    "ABCDEFGHJKMNPQRSTUVWXYZ23",      # 25 characters
    "ABCDEFGHJKMNPQRSTUVWXYZ0",       # 0 is not in the alphabet
    "A" * 65, None, 7,
])
def test_other_text_is_not_a_recovery_code(text) -> None:
    assert auth.normalize_recovery_code(text) is None


def test_the_recovery_digest_is_apart_from_the_device_code_digest() -> None:
    code = "ABCDEFGHJKMNPQRSTUVWXYZ2"
    assert auth.recovery_code_hash(code) != auth.device_code_hash(code)
    assert len(auth.recovery_code_hash(code)) == 64
