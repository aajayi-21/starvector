"""The account moves of spec A2 on a temporary store - no server.

Sign-up, sign-in, recovery, the password change, and the two recovery
codes, with a digester that has no slow work.
"""

import datetime
import json
import threading

import pytest

from service import auth, signin, store
from svc_fixture import QuickDigester

NOW = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=datetime.UTC)
USUAL = frozenset({"passwordpassword"})
GOOD = "correct horse battery"
OTHER = "a second good password"


def _up(root, name="alice", password=GOOD, digester=None, **more):
    more.setdefault("agrees_public", True)
    return signin.sign_up(root, username=name, password=password,
                          digester=digester or QuickDigester(), usual=USUAL,
                          instant=NOW, **more)


def _in(root, name="alice", password=GOOD, digester=None):
    return signin.sign_in(root, username=name, password=password,
                          digester=digester or QuickDigester(), instant=NOW)


def test_sign_up_writes_the_three_records_and_no_secret(tmp_path) -> None:
    name, code = _up(tmp_path, name="Alice")
    assert name == "alice"
    assert auth.normalize_recovery_code(code) == code
    player = store.read_player_record(tmp_path, "alice")
    assert player.token_hash is None
    assert player.display_name == "alice"
    assert store.read_claim_or_none(tmp_path, "alice").player == "alice"
    credential = store.read_credential_or_none(tmp_path, "alice")
    assert credential.recovery_digest == auth.recovery_code_hash(code)
    assert credential.operator_digest is None
    stored = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert GOOD not in stored and code not in stored


@pytest.mark.parametrize("name, password, cause", [
    ("al", GOOD, "name-rule"),
    ("admin", GOOD, "name-reserved"),
    ("alice", "short", "password-rule"),
    ("alice", "my alice password", "password-rule"),
    ("alice", "PasswordPassword", "password-usual"),
    (7, GOOD, "name-rule"),
    ("alice", None, "password-rule"),
])
def test_sign_up_names_the_rule_that_refuses(tmp_path, name, password,
                                             cause) -> None:
    with pytest.raises(signin.Refused) as refused:
        _up(tmp_path, name=name, password=password)
    assert refused.value.cause == cause
    assert not (tmp_path / "players").exists()


def test_two_names_with_one_folded_shape_make_one_account(tmp_path) -> None:
    _up(tmp_path, name="no-one")
    for look_alike in ("no-one", "n0one", "noone", "n0-one"):
        with pytest.raises(signin.Refused) as refused:
            _up(tmp_path, name=look_alike)
        assert refused.value.cause == "name-taken"
    assert store.list_players(tmp_path) == ("no-one",)


def test_racing_sign_ups_for_one_folded_shape_make_one_account(
        tmp_path) -> None:
    outcomes = []

    def attempt(name: str) -> None:
        try:
            outcomes.append(_up(tmp_path, name=name)[0])
        except signin.Refused as refused:
            outcomes.append(refused.cause)

    threads = [threading.Thread(target=attempt, args=(name,))
               for name in ("r0se", "rose", "ro-se", "r-o-s-e")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("name-taken") == 3
    assert len(store.list_players(tmp_path)) == 1


def test_a_name_of_a_stored_player_with_no_claim_is_taken(tmp_path) -> None:
    store.write_player_record(tmp_path, store.PlayerRecord(
        player="bru", display_name="Bru", token_hash="a" * 64,
        created_at=NOW.isoformat(), status="active"))
    with pytest.raises(signin.Refused) as refused:
        _up(tmp_path, name="bru")
    assert refused.value.cause == "name-taken"


def test_a_torn_sign_up_signs_nobody_in(tmp_path) -> None:
    store.claim_name(tmp_path, store.NameClaim(
        folded="alice", player="alice", claimed_at=NOW.isoformat()))
    assert _in(tmp_path) is None
    with pytest.raises(signin.Refused) as refused:
        _up(tmp_path)
    assert refused.value.cause == "name-taken"


def test_sign_in_agrees_for_the_pair_alone(tmp_path) -> None:
    _up(tmp_path)
    assert _in(tmp_path) == "alice"
    assert _in(tmp_path, name="ALICE") == "alice"
    assert _in(tmp_path, password=OTHER) is None
    assert _in(tmp_path, name="nobody") is None
    assert _in(tmp_path, name=7) is None
    assert _in(tmp_path, password=None) is None


def test_no_account_costs_one_absent_compare(tmp_path) -> None:
    _up(tmp_path)
    digester = QuickDigester()
    assert _in(tmp_path, name="nobody", digester=digester) is None
    assert _in(tmp_path, name="not a name", digester=digester) is None
    assert digester.absent_count == 2
    assert _in(tmp_path, digester=digester) == "alice"
    assert digester.absent_count == 2


def test_a_revoked_account_does_not_sign_in_or_recover(tmp_path) -> None:
    _name, code = _up(tmp_path)
    store.set_player_status(tmp_path, "alice", expect_status="active",
                            new_status="revoked")
    assert _in(tmp_path) is None
    assert signin.recover(
        tmp_path, username="alice", recovery_code=code, password=OTHER,
        digester=QuickDigester(), usual=USUAL, instant=NOW) is None


def test_a_stale_digest_is_written_again_at_sign_in(tmp_path) -> None:
    _up(tmp_path, digester=QuickDigester(level=1))
    before = store.read_credential_or_none(tmp_path, "alice").password_digest
    assert before.startswith("quick$1$")
    assert _in(tmp_path, digester=QuickDigester(level=2)) == "alice"
    after = store.read_credential_or_none(tmp_path, "alice").password_digest
    assert after.startswith("quick$2$")
    assert _in(tmp_path) == "alice"


def _recover(root, code, password=OTHER, name="alice", instant=NOW):
    return signin.recover(root, username=name, recovery_code=code,
                          password=password, digester=QuickDigester(),
                          usual=USUAL, instant=instant)


def test_recovery_replaces_the_password_and_the_code(tmp_path) -> None:
    _name, code = _up(tmp_path)
    store.write_session_record(tmp_path, "d" * 64, store.SessionRecord(
        player="alice", label="Test device", created_at=NOW.isoformat()))
    typed = auth.display_recovery_code(code).lower().replace("-", " ")
    name, new_code = _recover(tmp_path, typed)
    assert name == "alice" and new_code != code
    assert _in(tmp_path) is None
    assert _in(tmp_path, password=OTHER) == "alice"
    # One time: the used code is dead, and each earlier session ended.
    assert _recover(tmp_path, code, password=GOOD) is None
    assert store.list_sessions(tmp_path, "alice") == ()
    assert _recover(tmp_path, new_code, password=GOOD)[0] == "alice"


def test_racing_recoveries_with_one_code_give_one_new_code(tmp_path) -> None:
    _name, code = _up(tmp_path)
    outcomes = []

    def attempt(password: str) -> None:
        outcomes.append(_recover(tmp_path, code, password=password))

    threads = [threading.Thread(target=attempt, args=(f"new password {n}!",))
               for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for outcome in outcomes if outcome is not None) == 1


@pytest.mark.parametrize("code", ["", "not a code", None,
                                  "ABCDEFGHJKMNPQRSTUVWXYZ2"])
def test_recovery_refuses_each_bad_code_alike(tmp_path, code) -> None:
    _up(tmp_path)
    assert _recover(tmp_path, code) is None
    assert _recover(tmp_path, code, name="nobody") is None
    assert _in(tmp_path) == "alice"


def test_recovery_refuses_a_bad_new_password_before_the_code(
        tmp_path) -> None:
    _name, code = _up(tmp_path)
    with pytest.raises(signin.Refused) as refused:
        _recover(tmp_path, code, password="short")
    assert refused.value.cause == "password-rule"
    # The code is not used up by the refusal.
    assert _recover(tmp_path, code)[0] == "alice"


def test_a_password_change_wants_the_current_password(tmp_path) -> None:
    _name, code = _up(tmp_path)
    with pytest.raises(signin.WrongPassword):
        signin.set_password(tmp_path, player="alice", current_password="no",
                            password=OTHER, digester=QuickDigester(),
                            usual=USUAL, instant=NOW)
    with pytest.raises(signin.Refused):
        signin.set_password(tmp_path, player="alice", current_password=GOOD,
                            password="short", digester=QuickDigester(),
                            usual=USUAL, instant=NOW)
    assert signin.set_password(
        tmp_path, player="alice", current_password=GOOD, password=OTHER,
        digester=QuickDigester(), usual=USUAL, instant=NOW) is None
    assert _in(tmp_path, password=OTHER) == "alice"
    # The recovery code does not move with a password change.
    assert _recover(tmp_path, code, password=GOOD)[0] == "alice"


def test_a_player_of_before_sets_a_first_password(tmp_path) -> None:
    store.write_player_record(tmp_path, store.PlayerRecord(
        player="bru", display_name="Bru", token_hash="a" * 64,
        created_at=NOW.isoformat(), status="active"))
    assert not signin.has_password(tmp_path, "bru")
    assert _in(tmp_path, name="bru") is None
    code = signin.set_password(
        tmp_path, player="bru", current_password=None, password=GOOD,
        digester=QuickDigester(), usual=USUAL, instant=NOW)
    assert auth.normalize_recovery_code(code) == code
    assert signin.has_password(tmp_path, "bru")
    assert _in(tmp_path, name="bru") == "bru"


def test_a_new_recovery_code_wants_the_password_and_ends_the_old_code(
        tmp_path) -> None:
    _name, code = _up(tmp_path)
    with pytest.raises(signin.WrongPassword):
        signin.new_recovery_code(tmp_path, player="alice",
                                 current_password="no",
                                 digester=QuickDigester(), instant=NOW)
    new_code = signin.new_recovery_code(
        tmp_path, player="alice", current_password=GOOD,
        digester=QuickDigester(), instant=NOW)
    assert _recover(tmp_path, code) is None
    assert _recover(tmp_path, new_code)[0] == "alice"


def test_the_operator_code_has_its_own_slot_and_a_hold(tmp_path) -> None:
    _name, own = _up(tmp_path)
    store.write_session_record(tmp_path, "d" * 64, store.SessionRecord(
        player="alice", label="Test device", created_at=NOW.isoformat()))
    code, usable_at = signin.issue_operator_code(
        tmp_path, player="alice", instant=NOW)
    hold = datetime.timedelta(seconds=signin.OPERATOR_HOLD_SECONDS)
    assert usable_at == (NOW + hold).isoformat()
    assert hold == datetime.timedelta(hours=24)
    # The password, the player's own code, and the session stay.
    assert _in(tmp_path) == "alice"
    assert len(store.list_sessions(tmp_path, "alice")) == 1
    view = signin.operator_code_view(tmp_path, "alice")
    assert view == {"issued_at": NOW.isoformat(), "usable_at": usable_at}
    # In the hold the code opens nothing.
    assert _recover(tmp_path, code) is None
    assert _recover(tmp_path, code,
                    instant=NOW + hold - datetime.timedelta(seconds=1)) is None
    # After the hold it works one time, and the two codes go.
    assert _recover(tmp_path, code, instant=NOW + hold)[0] == "alice"
    assert signin.operator_code_view(tmp_path, "alice") is None
    assert _recover(tmp_path, own, instant=NOW + hold) is None


def test_the_player_stops_an_operator_code(tmp_path) -> None:
    _name, own = _up(tmp_path)
    code, _usable = signin.issue_operator_code(
        tmp_path, player="alice", instant=NOW)
    assert signin.stop_operator_code(tmp_path, player="alice", instant=NOW)
    assert not signin.stop_operator_code(tmp_path, player="alice",
                                         instant=NOW)
    later = NOW + datetime.timedelta(days=2)
    assert _recover(tmp_path, code, instant=later) is None
    assert _recover(tmp_path, own, instant=later)[0] == "alice"


def test_an_operator_code_serves_a_player_with_no_credential(
        tmp_path) -> None:
    store.write_player_record(tmp_path, store.PlayerRecord(
        player="bru", display_name="Bru", token_hash="a" * 64,
        created_at=NOW.isoformat(), status="active"))
    code, _usable = signin.issue_operator_code(tmp_path, player="bru",
                                               instant=NOW)
    later = NOW + datetime.timedelta(days=1)
    assert _recover(tmp_path, code, name="bru", instant=later)[0] == "bru"
    assert _in(tmp_path, name="bru", password=OTHER) == "bru"
    with pytest.raises(store.StoreError):
        signin.issue_operator_code(tmp_path, player="nobody", instant=NOW)


def test_a_credential_record_that_does_not_parse_raises(tmp_path) -> None:
    _up(tmp_path)
    path = store.credential_record_path(tmp_path, "alice")
    raw = json.loads(path.read_text())
    raw.pop("operator_digest")
    path.write_text(json.dumps(raw))
    with pytest.raises(store.StoreError, match="must have the fields"):
        _in(tmp_path)
    raw["operator_digest"] = "f" * 64   # one field of a part of three
    path.write_text(json.dumps(raw))
    with pytest.raises(store.StoreError, match="set together"):
        _in(tmp_path)


def test_the_credential_file_is_not_a_player_or_a_claim(tmp_path) -> None:
    _up(tmp_path)
    assert store.list_players(tmp_path) == ("alice",)
    assert store.any_credential(tmp_path)
    assert not store.any_credential(tmp_path / "elsewhere")


def test_claim_names_covers_the_players_of_before(tmp_path) -> None:
    for name in ("ade", "bru"):
        store.write_player_record(tmp_path, store.PlayerRecord(
            player=name, display_name=name.title(), token_hash="a" * 64,
            created_at=NOW.isoformat(), status="active"))
    assert signin.unclaimed_players(tmp_path) == ["ade", "bru"]
    assert signin.claim_stored_names(tmp_path, NOW) == ["ade", "bru"]
    assert signin.unclaimed_players(tmp_path) == []
    assert signin.claim_stored_names(tmp_path, NOW) == []
    with pytest.raises(signin.Refused):
        _up(tmp_path, name="a-de")


def test_claim_names_stops_on_two_names_with_one_folded_shape(
        tmp_path) -> None:
    for name in ("no-one", "n0one"):
        store.write_player_record(tmp_path, store.PlayerRecord(
            player=name, display_name=name, token_hash=None,
            created_at=NOW.isoformat(), status="active"))
    with pytest.raises(store.StoreError, match="one folded shape"):
        signin.claim_stored_names(tmp_path, NOW)
    assert not (tmp_path / "names").exists()
