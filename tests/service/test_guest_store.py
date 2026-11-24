"""The stored records of a guest (spec IM1 sections 7.1, 7.4, 12.1)."""

import datetime
from pathlib import Path

import pytest

from service import auth, guests
from service.store import StoreError

NOW = datetime.datetime(2026, 11, 23, 10, 0, tzinfo=datetime.UTC)


def test_a_guest_identifier_is_not_a_username() -> None:
    from service import names

    for _ in range(50):
        guest = guests.make_guest_id()
        assert guests.is_guest_id(guest)
        assert len(guest) > names.USERNAME_MAX
    assert not guests.is_guest_id("guest-0123")
    assert not guests.is_guest_id("guest-0123456789ABCDEF")
    assert not guests.is_guest_id("guest-0123456789abcdef\n")
    assert not guests.is_guest_id("opal")


def test_a_made_guest_resolves_by_its_cookie_value(tmp_path: Path) -> None:
    guest, value = guests.make_guest(tmp_path, notice=3, instant=NOW)
    assert guests.resolve_guest(tmp_path, value) == guest
    assert guests.agreed(tmp_path, guest, 3)
    assert not guests.agreed(tmp_path, guest, 4)
    record = guests.read_guest_or_none(tmp_path, guest)
    name, secret = auth.parse_token(value)
    assert name == guest
    assert record.token_hash == auth.token_hash(secret)
    assert record.created_at == "2026-11-23T10:00:00+00:00"


@pytest.mark.parametrize("value", [
    None, "", "guest-0123456789abcdef", "opal." + "x" * 43,
    "guest-0123456789abcdef." + "x" * 43, "../../etc." + "x" * 43])
def test_other_text_resolves_to_no_guest(tmp_path: Path,
                                         value: object) -> None:
    guests.make_guest(tmp_path, notice=3, instant=NOW)
    assert guests.resolve_guest(tmp_path, value) is None


def test_a_claimed_guest_resolves_to_nothing(tmp_path: Path) -> None:
    guest, value = guests.make_guest(tmp_path, notice=3, instant=NOW)
    claim = guests.claim_guest(tmp_path, guest, "opal", NOW)
    assert guests.read_claim_or_none(tmp_path, guest) == claim
    assert guests.resolve_guest(tmp_path, value) is None
    assert guests.claims_by_player(tmp_path) == {"opal": (guest,)}


def test_one_guest_has_one_claim(tmp_path: Path) -> None:
    guest, _ = guests.make_guest(tmp_path, notice=3, instant=NOW)
    guests.claim_guest(tmp_path, guest, "opal", NOW)
    with pytest.raises(StoreError):
        guests.claim_guest(tmp_path, guest, "ruby", NOW)
    assert guests.read_claim_or_none(tmp_path, guest).player == "opal"


def test_the_first_agreement_keeps_its_time(tmp_path: Path) -> None:
    guest, _ = guests.make_guest(tmp_path, notice=3, instant=NOW)
    path = guests.consent_path(tmp_path, guest, 3)
    before = path.read_bytes()
    assert guests.write_consent(tmp_path, guest, 3, "a later time") is False
    assert path.read_bytes() == before
    assert guests.write_consent(tmp_path, guest, 4, "a later time") is True


def test_a_record_of_a_different_guest_does_not_read(
        tmp_path: Path) -> None:
    guest, _ = guests.make_guest(tmp_path, notice=3, instant=NOW)
    other = "guest-" + "f" * 16
    target = tmp_path / "guests" / other
    target.mkdir(parents=True)
    source = tmp_path / "guests" / guest / "guest.json"
    (target / "guest.json").write_bytes(source.read_bytes())
    with pytest.raises(StoreError):
        guests.read_guest_or_none(tmp_path, other)


def test_a_name_that_is_not_a_guest_names_no_file(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        guests.read_guest_or_none(tmp_path, "../players/ade")
    with pytest.raises(StoreError):
        guests.claim_guest(tmp_path, "opal", "opal", NOW)
    assert guests.claims_by_player(tmp_path) == {}


def test_the_cookie_has_the_attributes_of_the_session_cookie() -> None:
    header = guests.guest_cookie_header("guest-0123456789abcdef.secret")
    assert header == ("sv_guest=guest-0123456789abcdef.secret; Path=/; "
                      "Secure; HttpOnly; SameSite=Lax; Max-Age=15552000")
    plain = guests.guest_cookie_header("v", secure=False)
    assert "Secure" not in plain
    assert guests.clear_guest_cookie_header() == (
        "sv_guest=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0")
