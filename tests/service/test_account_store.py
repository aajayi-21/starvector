"""Unit: the account record and the avatar bytes (spec A1 item A1).

Pure store tests on a temporary directory - no pool, no server.
The two hazards the spec names are pinned here: the phantom player
(an account file must not read as a player) and the write sequence
of the avatar bytes and the record.
"""

from pathlib import Path

import pytest

from core.canonical import sha256_hex
from service import store

CLOCK = "2026-08-21T00:00:00+00:00"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 24
WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"x" * 16
GIF = b"GIF89a" + b"x" * 24


def test_the_description_check_takes_the_legal_shapes() -> None:
    store.check_description("", "description")
    store.check_description("a" * store.DESCRIPTION_LIMIT, "description")
    store.check_description("two lines\nwith a newline", "description")


@pytest.mark.parametrize("bad", [
    "a" * (store.DESCRIPTION_LIMIT + 1),
    "tab\tinterior",
    " leading space",
    "trailing newline\n",
    None,
    7,
])
def test_the_description_check_refuses(bad) -> None:
    with pytest.raises(store.StoreError):
        store.check_description(bad, "description")


def test_the_media_type_reads_the_four_kinds() -> None:
    assert store.avatar_media_type(PNG) == "image/png"
    assert store.avatar_media_type(JPEG) == "image/jpeg"
    assert store.avatar_media_type(WEBP) == "image/webp"
    assert store.avatar_media_type(GIF) == "image/gif"
    assert store.avatar_media_type(b"not an image") is None
    assert store.avatar_media_type(b"") is None


def test_the_avatar_writer_refuses_the_cap_before_the_magic(
        tmp_path: Path) -> None:
    # Oversized junk must name the cap, thus the sequence is pinned:
    # the cap first, the magic bytes second (spec A1 section 9).
    oversized = b"j" * (store.AVATAR_BYTE_CAP + 1)
    with pytest.raises(store.StoreError, match="at most"):
        store.write_avatar_bytes(tmp_path, "ade", oversized)
    with pytest.raises(store.StoreError, match="not a PNG"):
        store.write_avatar_bytes(tmp_path, "ade", b"j" * 32)
    assert not store.avatar_path(tmp_path, "ade").exists()


def test_the_avatar_writer_stores_and_answers_the_digest(
        tmp_path: Path) -> None:
    digest = store.write_avatar_bytes(tmp_path, "ade", PNG)
    assert digest == sha256_hex(PNG)
    assert store.read_avatar_or_none(tmp_path, "ade") == PNG


def test_the_avatar_reader_answers_none_for_an_illegal_name(
        tmp_path: Path) -> None:
    assert store.read_avatar_or_none(tmp_path, "../escape") is None
    assert store.read_avatar_or_none(tmp_path, "ade") is None
    with pytest.raises(store.StoreError):
        store.write_avatar_bytes(tmp_path, "../escape", PNG)


def test_the_account_record_writes_and_reads_back_equal(
        tmp_path: Path) -> None:
    written = store.set_account_description(
        tmp_path, "ade", "I sketch coastlines.", timestamp=CLOCK)
    read = store.read_account_or_none(tmp_path, "ade")
    assert read == written
    assert read.description == "I sketch coastlines."
    assert read.avatar_hash is None
    assert read.updated_at == CLOCK


def test_a_missing_account_reads_as_the_empty_account(
        tmp_path: Path) -> None:
    assert store.read_account_or_none(tmp_path, "ade") is None


def test_the_account_record_is_replaceable(tmp_path: Path) -> None:
    store.set_account_description(tmp_path, "ade", "first",
                                  timestamp=CLOCK)
    moved = store.set_account_description(tmp_path, "ade", "second",
                                          timestamp=CLOCK)
    assert moved.description == "second"
    assert store.read_account_or_none(tmp_path,
                                      "ade").description == "second"


def test_a_record_with_an_unknown_field_refuses_loudly(
        tmp_path: Path) -> None:
    store.set_account_description(tmp_path, "ade", "text",
                                  timestamp=CLOCK)
    path = store.account_record_path(tmp_path, "ade")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"player"', '"extra": 1,\n  "player"'),
                    encoding="utf-8")
    with pytest.raises(store.StoreError, match="fields"):
        store.read_account_or_none(tmp_path, "ade")


def test_set_avatar_moves_the_bytes_and_the_record_together(
        tmp_path: Path) -> None:
    moved = store.set_account_avatar(tmp_path, "ade", PNG,
                                     timestamp=CLOCK)
    assert moved.avatar_hash == sha256_hex(PNG)
    assert store.read_avatar_or_none(tmp_path, "ade") == PNG
    stored = store.read_account_or_none(tmp_path, "ade")
    assert stored.avatar_hash == sha256_hex(
        store.read_avatar_or_none(tmp_path, "ade"))


def test_clear_avatar_removes_the_bytes_and_the_hash(
        tmp_path: Path) -> None:
    store.set_account_avatar(tmp_path, "ade", PNG, timestamp=CLOCK)
    store.set_account_description(tmp_path, "ade", "kept",
                                  timestamp=CLOCK)
    moved = store.clear_account_avatar(tmp_path, "ade", timestamp=CLOCK)
    assert moved.avatar_hash is None
    assert moved.description == "kept"
    assert store.read_avatar_or_none(tmp_path, "ade") is None
    # Clearing an account with no picture is legal.
    again = store.clear_account_avatar(tmp_path, "ade", timestamp=CLOCK)
    assert again.avatar_hash is None


def test_a_stop_between_the_bytes_and_the_record_heals(
        tmp_path: Path) -> None:
    """The write sequence of spec A1 section 3: the bytes land
    first and the record follows. A stop between the two gives a
    stale avatar_hash - a cache key, not a claim - and the next
    write heals it."""
    store.set_account_avatar(tmp_path, "ade", PNG, timestamp=CLOCK)
    # The stop: the bytes moved and the record write did not run.
    store.write_avatar_bytes(tmp_path, "ade", GIF)
    stale = store.read_account_or_none(tmp_path, "ade")
    assert stale.avatar_hash == sha256_hex(PNG)
    assert store.read_avatar_or_none(tmp_path, "ade") == GIF
    healed = store.set_account_avatar(tmp_path, "ade", JPEG,
                                      timestamp=CLOCK)
    assert healed.avatar_hash == sha256_hex(JPEG)
    assert store.read_avatar_or_none(tmp_path, "ade") == JPEG


def test_concurrent_account_writes_do_not_collide(tmp_path: Path) -> None:
    """Each write gets its own temporary sibling.

    With one fixed .tmp sibling, two concurrent writers race on
    it: the loser's os.replace raises and a reader can read a
    torn document. The barrier starts the writers together, thus
    the earlier shape did not survive its first iteration here.
    """
    import threading

    count = 8
    errors: list[Exception] = []
    barrier = threading.Barrier(count)

    def write(index: int) -> None:
        try:
            barrier.wait()
            for _ in range(25):
                store.set_account_description(
                    tmp_path, "ade", f"text {index}", timestamp=CLOCK)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=write, args=(index,))
               for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    stored = store.read_account_or_none(tmp_path, "ade")
    assert stored is not None and stored.description.startswith("text ")
    # No temporary sibling survives the storm.
    leftovers = [path.name for path in store.accounts_dir(tmp_path).iterdir()
                 if path.name.endswith(".tmp")]
    assert leftovers == []


def test_an_account_file_is_not_a_phantom_player(tmp_path: Path) -> None:
    """The spec A1 phantom player: list_players and any_player read
    each .json name below store/players/ as a player, thus the
    account class lives in its own directory and must not move
    what they answer."""
    assert store.any_player(tmp_path) is False
    store.set_account_description(tmp_path, "ade", "text",
                                  timestamp=CLOCK)
    store.set_account_avatar(tmp_path, "bru", PNG, timestamp=CLOCK)
    assert store.list_players(tmp_path) == ()
    assert store.any_player(tmp_path) is False
    store.write_player_record(tmp_path, store.PlayerRecord(
        player="ade", display_name="Ade", token_hash="0" * 64,
        created_at=CLOCK, status="active"))
    assert store.list_players(tmp_path) == ("ade",)
