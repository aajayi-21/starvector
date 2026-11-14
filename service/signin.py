"""Accounts with a username and a password (spec A2).

This module composes the rules, the digest, and the store into the
moves of an account: make one, sign in, the recovery, the password
change, and the two recovery codes. The handlers of the server and the
operator's command line use it. It reads no environment and no clock:
each function gets the instant, the digester, and the table of usual
passwords as arguments.

Each move that changes a credential record holds the record's lock for
its read, its check, and its write (the store's credential_lock).
"""

import datetime
import secrets
from collections.abc import Container
from dataclasses import replace
from pathlib import Path

from service import auth, names, notice, passwords, store
from service.digests import PasswordDigester

# Decision D9 of spec A2: the operator's code works from this long
# after the operator made it.
OPERATOR_HOLD_SECONDS = 24 * 60 * 60

NAME_TAKEN = "name-taken"


class Refused(ValueError):
    """A sign-up or a new password that a rule refuses, with the cause
    that the answer names."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


class WrongPassword(ValueError):
    """The current password of an account move did not agree."""


def _iso(instant: datetime.datetime) -> str:
    return instant.astimezone(datetime.UTC).isoformat()


def _parse(stamp: str) -> datetime.datetime:
    moment = datetime.datetime.fromisoformat(stamp)
    if moment.tzinfo is None:
        raise store.StoreError(f"a stored timestamp has no zone: {stamp!r}")
    return moment


def _checked_password(password: object, username: str,
                      usual: Container[str]) -> str:
    """The NFKC shape of a new password, or Refused with its cause."""
    normalized = passwords.normalize_password(password)
    if normalized is None:
        raise Refused(passwords.PASSWORD_RULE)
    cause = passwords.password_refusal(normalized, username, usual)
    if cause is not None:
        raise Refused(cause)
    return normalized


def _empty_credential(player: str, stamp: str) -> store.CredentialRecord:
    return store.CredentialRecord(
        player=player, password_digest=None, password_set_at=None,
        recovery_digest=None, recovery_issued_at=None,
        operator_digest=None, operator_issued_at=None,
        operator_usable_at=None, updated_at=stamp)


def sign_up(root: Path, *, username: object, password: object,
            agrees_public: object,
            digester: PasswordDigester, usual: Container[str],
            instant: datetime.datetime,
            recovery_code: str | None = None) -> tuple[str, str]:
    """Make one account, and answer its name and its recovery code.

    The sequence: the rules, the digest, the claim of the folded shape,
    the player record, the credential record. The claim is the
    exclusive step: of two sign-ups for one folded shape, one gets it
    (spec A2 section 7.2). A stop after the claim leaves a claimed name
    with no account, which signs nobody in.

    Without agrees_public the sign-up is refused: publication is a
    condition of the
    account (spec R1 section 3), and the screen sends it when it showed
    the notice. The sign-up writes the consent record with the account.

    recovery_code arrives as an argument for the tests that pin one.

    Raises Refused with the cause notice, name-rule, name-reserved,
    password-rule, password-usual, or name-taken.
    """
    if agrees_public is not True:
        raise Refused(notice.NOTICE_REFUSED)
    name = names.normalize_username(username)
    if name is None:
        raise Refused(names.NAME_RULE)
    cause = names.username_refusal(name)
    if cause is not None:
        raise Refused(cause)
    normalized = _checked_password(password, name, usual)
    folded = names.folded_name(name)
    # The two reads come before the slow digest, thus a claimed name
    # costs the caller no digest of the server.
    if store.read_claim_or_none(root, folded) is not None \
            or store.read_player_or_none(root, name) is not None:
        raise Refused(NAME_TAKEN)
    digest = digester.digest(normalized)
    stamp = _iso(instant)
    store.ensure_store(root)
    try:
        store.claim_name(root, store.NameClaim(
            folded=folded, player=name, claimed_at=stamp))
        store.write_player_record(root, store.PlayerRecord(
            player=name, display_name=name, token_hash=None,
            created_at=stamp, status="active"))
    except store.StoreError as error:
        raise Refused(NAME_TAKEN) from error
    notice.record_agreement(root, name, instant)
    code = recovery_code or auth.make_recovery_code()
    with store.credential_lock(root, name):
        store.write_credential_record(root, replace(
            _empty_credential(name, stamp),
            password_digest=digest, password_set_at=stamp,
            recovery_digest=auth.recovery_code_hash(code),
            recovery_issued_at=stamp))
    return name, code


def sign_in(root: Path, *, username: object, password: object,
            digester: PasswordDigester,
            instant: datetime.datetime) -> str | None:
    """The player that a username and a password sign in, or None.

    None covers each refusal alike: a name that is not a name, no
    account, no password on the account, a bad password, and a revoked
    account. Each of them costs one compare of the digester, thus the
    time of the answer does not say which one it was (spec A2 section
    9.3).

    A stored digest with parameters that are not the current ones gets
    a new digest from the typed password.
    """
    name = names.normalize_username(username)
    typed = passwords.normalize_password(password) or ""
    player = None if name is None else store.read_player_or_none(root, name)
    credential = None if player is None \
        else store.read_credential_or_none(root, player.player)
    if credential is None or credential.password_digest is None:
        digester.absent(typed)
        return None
    agreed = digester.agrees(typed, credential.password_digest)
    if not agreed or player.status != "active":
        return None
    if digester.stale(credential.password_digest):
        new_digest = digester.digest(typed)
        with store.credential_lock(root, player.player):
            current = store.read_credential_or_none(root, player.player)
            # A password change between the two reads wins: the new
            # digest is for the password of before.
            if current is not None \
                    and current.password_digest == credential.password_digest:
                stamp = _iso(instant)
                store.write_credential_record(root, replace(
                    current, password_digest=new_digest, updated_at=stamp))
    return player.player


def _code_agrees(code_digest: str, stored: str | None) -> bool:
    """Compare in constant time. A slot with no code compares against a
    fixed digest, thus the two slots cost equal work."""
    return secrets.compare_digest(code_digest, stored or "0" * 64) \
        and stored is not None


def recover(root: Path, *, username: object, recovery_code: object,
            password: object, digester: PasswordDigester,
            usual: Container[str],
            instant: datetime.datetime) -> tuple[str, str] | None:
    """Trade a recovery code for a new password (spec A2 section 3.3).

    Answers the player and a new recovery code, or None. None covers no
    account, a revoked account, text that is not a code, a code that is
    not the live one, and an operator's code before its time.

    On agreement the password is replaced, the two codes are removed, a
    new code of the player is set, and each session of the player
    ends. The caller opens the new session.

    Raises Refused for a new password that the rules refuse. That check
    reads the typed values alone, thus it says nothing about the
    account.
    """
    name = names.normalize_username(username)
    typed_name = name if isinstance(name, str) else ""
    normalized = _checked_password(password, typed_name, usual)
    code = auth.normalize_recovery_code(recovery_code)
    player = None if name is None else store.read_player_or_none(root, name)
    if code is None or player is None or player.status != "active":
        return None
    code_digest = auth.recovery_code_hash(code)
    with store.credential_lock(root, player.player):
        credential = store.read_credential_or_none(root, player.player)
        if credential is None:
            return None
        own = _code_agrees(code_digest, credential.recovery_digest)
        operator = _code_agrees(code_digest, credential.operator_digest) \
            and instant >= _parse(credential.operator_usable_at)
        if not (own or operator):
            return None
        stamp = _iso(instant)
        new_code = auth.make_recovery_code()
        store.write_credential_record(root, replace(
            credential,
            password_digest=digester.digest(normalized),
            password_set_at=stamp,
            recovery_digest=auth.recovery_code_hash(new_code),
            recovery_issued_at=stamp,
            operator_digest=None, operator_issued_at=None,
            operator_usable_at=None, updated_at=stamp))
    store.delete_player_sessions(root, player.player)
    return player.player, new_code


def has_password(root: Path, player: str) -> bool:
    """The player has a password set."""
    credential = store.read_credential_or_none(root, player)
    return credential is not None and credential.password_digest is not None


def set_password(root: Path, *, player: str, current_password: object,
                 password: object, digester: PasswordDigester,
                 usual: Container[str],
                 instant: datetime.datetime) -> str | None:
    """Replace the password of a signed-in player.

    With a password set, current_password must agree. With no password
    set - a player from before spec A2 - the session is sufficient,
    and the answer is the first recovery code of the player. In the
    other path the answer is None and the recovery code does not move.
    The caller ends the other sessions.

    Raises WrongPassword, and Refused for the new password.
    """
    normalized = _checked_password(password, player, usual)
    typed = passwords.normalize_password(current_password) or ""
    with store.credential_lock(root, player):
        stamp = _iso(instant)
        credential = store.read_credential_or_none(root, player) \
            or _empty_credential(player, stamp)
        first = credential.password_digest is None
        if not first and not digester.agrees(
                typed, credential.password_digest):
            raise WrongPassword(player)
        moved = replace(credential,
                        password_digest=digester.digest(normalized),
                        password_set_at=stamp, updated_at=stamp)
        code = None
        if first:
            code = auth.make_recovery_code()
            moved = replace(moved,
                            recovery_digest=auth.recovery_code_hash(code),
                            recovery_issued_at=stamp)
        store.write_credential_record(root, moved)
    return code


def new_recovery_code(root: Path, *, player: str, current_password: object,
                      digester: PasswordDigester,
                      instant: datetime.datetime) -> str:
    """A new recovery code of the player. The earlier one is dead.

    Raises WrongPassword, also for a player with no password: such a
    player sets a password first.
    """
    typed = passwords.normalize_password(current_password) or ""
    with store.credential_lock(root, player):
        credential = store.read_credential_or_none(root, player)
        if credential is None or credential.password_digest is None:
            digester.absent(typed)
            raise WrongPassword(player)
        if not digester.agrees(typed, credential.password_digest):
            raise WrongPassword(player)
        stamp = _iso(instant)
        code = auth.make_recovery_code()
        store.write_credential_record(root, replace(
            credential, recovery_digest=auth.recovery_code_hash(code),
            recovery_issued_at=stamp, updated_at=stamp))
    return code


def issue_operator_code(root: Path, *, player: str,
                        instant: datetime.datetime,
                        code: str | None = None) -> tuple[str, str]:
    """The operator's recovery code for one player, and when it works.

    The code has its own slot: the player's own code, the password,
    and each session stay as they are (spec A2 section 6.1). A second
    operator's code replaces the first, and its hold starts again.

    Raises StoreError for a name with no player record.
    """
    store.read_player_record(root, player)
    chosen = code or auth.make_recovery_code()
    stamp = _iso(instant)
    usable = _iso(instant + datetime.timedelta(seconds=OPERATOR_HOLD_SECONDS))
    with store.credential_lock(root, player):
        credential = store.read_credential_or_none(root, player) \
            or _empty_credential(player, stamp)
        store.write_credential_record(root, replace(
            credential, operator_digest=auth.recovery_code_hash(chosen),
            operator_issued_at=stamp, operator_usable_at=usable,
            updated_at=stamp))
    return chosen, usable


def stop_operator_code(root: Path, *, player: str,
                       instant: datetime.datetime) -> bool:
    """Remove the operator's code of one player, and say if one was
    there. A session is sufficient for this move."""
    with store.credential_lock(root, player):
        credential = store.read_credential_or_none(root, player)
        if credential is None or credential.operator_digest is None:
            return False
        store.write_credential_record(root, replace(
            credential, operator_digest=None, operator_issued_at=None,
            operator_usable_at=None, updated_at=_iso(instant)))
    return True


def operator_code_view(root: Path, player: str) -> dict[str, str] | None:
    """The two times of the player's live operator code, or None.

    The notice of the account screen reads this. It holds no code and
    no digest.
    """
    credential = store.read_credential_or_none(root, player)
    if credential is None or credential.operator_digest is None:
        return None
    return {"issued_at": credential.operator_issued_at,
            "usable_at": credential.operator_usable_at}


def unclaimed_players(root: Path) -> list[str]:
    """Each stored player with no claim of its folded shape that names
    it. An open sign-up needs this to be empty (spec A2 section 10.3)."""
    missing = []
    for player in store.list_players(root):
        claim = store.read_claim_or_none(root, names.folded_name(player))
        if claim is None or claim.player != player:
            missing.append(player)
    return missing


def claim_stored_names(root: Path, instant: datetime.datetime) -> list[str]:
    """Claim the folded shape of each stored player that has no claim.

    Raises StoreError before a write when two stored names have one
    folded shape, and names the pair. The operator then revokes one of
    the two by hand: a claim cannot make one name of two accounts.
    """
    by_folded: dict[str, str] = {}
    for player in store.list_players(root):
        folded = names.folded_name(player)
        if folded in by_folded:
            raise store.StoreError(
                f"the stored names {by_folded[folded]!r} and {player!r} "
                f"have one folded shape, {folded!r}")
        claim = store.read_claim_or_none(root, folded)
        if claim is not None and claim.player != player:
            raise store.StoreError(
                f"the stored name {player!r} has the folded shape "
                f"{folded!r}, which {claim.player!r} claims")
        by_folded[folded] = player
    claimed = []
    stamp = _iso(instant)
    for folded, player in sorted(by_folded.items()):
        if store.read_claim_or_none(root, folded) is None:
            store.claim_name(root, store.NameClaim(
                folded=folded, player=player, claimed_at=stamp))
            claimed.append(player)
    return claimed
