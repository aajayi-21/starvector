"""The instant records in memory (spec IM1 sections 6, 9, and 12.4).

A cache of store/instant/ (rule I4): the server builds it from the
store at its start, and each write of a start, a send, or a result
adds to it. It answers the questions that a scan of the store answers
slowly: the open start of an owner, the sends of a date, the sends
with no result, the head of the chain, the record of an owner, and
the set of targets.
"""

import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from core.types import TrialCounts
from service import instant, instant_store
from service.instant import Owner, RecordNumbers
from service.store import StoreError


@dataclass(frozen=True, slots=True)
class Entry:
    """What the book keeps of one trial.

    received_at, beacon_round, and chain_position are None before the
    send. p, counts, and target_id are None before the result.
    """

    date: str
    trial_id: str
    owner: Owner
    trial_code: str
    started_at: str
    received_at: str | None = None
    beacon_round: int | None = None
    chain_position: int | None = None
    p: float | None = None
    counts: TrialCounts | None = None
    target_id: str | None = None


@dataclass(frozen=True, slots=True)
class Head:
    """The last send of the chain (spec IM1 section 11)."""

    position: int
    chain_link: str
    received_at: str


def _result_facts(row: object, where: str) -> tuple[float, TrialCounts]:
    """The trial score and the three counts of one stored row."""
    if not isinstance(row, dict):
        raise StoreError(f"{where}: the row is not an object")
    try:
        p = float(row["p"])
        counts = TrialCounts(beaten=row["beaten"], tied=row["tied"],
                             decoy_count=row["decoy_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise StoreError(f"{where}: the row has no trial numbers") from error
    return p, counts


class InstantBook:
    """The trials of the store, by trial and by owner.

    Each method holds one lock, thus a path thread and the result loop
    read the same book.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        self._head: Head | None = None
        self._targets: set[str] = set()
        self._pending: set[str] = set()

    def add_start(self, date: str,
                  record: instant_store.StartRecord) -> None:
        with self._lock:
            self._entries[record.trial_id] = Entry(
                date=date, trial_id=record.trial_id,
                owner=Owner(record.owner_kind, record.owner),
                trial_code=record.trial_code,
                started_at=record.started_at)

    def add_send(self, record: instant_store.SendRecord) -> None:
        """Add a stored send. It must follow the head of the chain."""
        with self._lock:
            entry = self._entries.get(record.trial_id)
            if entry is None:
                raise StoreError(
                    f"trial {record.trial_id}: a send with no start")
            expected = 0 if self._head is None else self._head.position + 1
            previous = instant.CHAIN_START if self._head is None \
                else self._head.chain_link
            if record.chain_position != expected \
                    or record.chain_previous != previous:
                raise StoreError(
                    f"trial {record.trial_id}: the send does not follow "
                    f"the chain head at position {expected - 1}")
            self._entries[record.trial_id] = replace(
                entry, received_at=record.received_at,
                beacon_round=record.beacon_round,
                chain_position=record.chain_position)
            self._head = Head(position=record.chain_position,
                              chain_link=record.chain_link,
                              received_at=record.received_at)
            self._pending.add(record.trial_id)

    def add_result(self, record: instant_store.ResultRecord) -> None:
        p, counts = _result_facts(record.row, f"trial {record.trial_id}")
        with self._lock:
            entry = self._entries.get(record.trial_id)
            if entry is None or entry.received_at is None:
                raise StoreError(
                    f"trial {record.trial_id}: a result with no send")
            self._entries[record.trial_id] = replace(
                entry, p=p, counts=counts, target_id=record.target_id)
            self._targets.add(record.target_id)
            self._pending.discard(record.trial_id)

    def entry(self, trial_id: str) -> Entry | None:
        with self._lock:
            return self._entries.get(trial_id)

    def open_start(self, owners: Sequence[Owner]) -> Entry | None:
        """The last start of these owners that has no send, or None."""
        wanted = set(owners)
        with self._lock:
            found = [entry for entry in self._entries.values()
                     if entry.owner in wanted and entry.received_at is None]
        if not found:
            return None
        return max(found, key=lambda entry: (entry.started_at,
                                             entry.trial_id))

    def sent_on(self, owners: Sequence[Owner], date: str) -> int:
        """The stored sends of these owners on one UTC date."""
        wanted = set(owners)
        with self._lock:
            return sum(1 for entry in self._entries.values()
                       if entry.owner in wanted
                       and entry.received_at is not None
                       and instant.utc_date(entry.received_at) == date)

    def sent_total_on(self, date: str) -> int:
        """The stored sends of all owners on one UTC date."""
        with self._lock:
            return sum(1 for entry in self._entries.values()
                       if entry.received_at is not None
                       and instant.utc_date(entry.received_at) == date)

    def pending(self) -> tuple[Entry, ...]:
        """The sends with no result, in the sequence of the chain."""
        with self._lock:
            found = [self._entries[trial_id] for trial_id in self._pending]
        return tuple(sorted(found, key=lambda entry: entry.chain_position))

    def head(self) -> Head | None:
        with self._lock:
            return self._head

    def has_target(self, image_id: str) -> bool:
        """Tell if the image is the target of a trial with a result."""
        with self._lock:
            return image_id in self._targets

    def sends_of(self, owners: Sequence[Owner]) -> tuple[Entry, ...]:
        """The sends of these owners, in the sequence of the chain."""
        wanted = set(owners)
        with self._lock:
            found = [entry for entry in self._entries.values()
                     if entry.owner in wanted
                     and entry.received_at is not None]
        return tuple(sorted(found, key=lambda entry: entry.chain_position))

    def record_of(self, owners: Sequence[Owner]) -> RecordNumbers:
        """The instant record of these owners as one record."""
        sends = self.sends_of(owners)
        settled = [entry for entry in sends if entry.counts is not None]
        return instant.record_numbers(
            len(sends), [float(entry.p) for entry in settled],
            [entry.counts for entry in settled])


def build_book(store: Path) -> InstantBook:
    """Read the store into a new book, and check the chain.

    The scan reads each start, each send, and each result. A chain with
    a fault raises: a store with a removed or a changed send does not
    start as a good one.
    """
    book = InstantBook()
    sends: list[instant_store.SendRecord] = []
    results: list[instant_store.ResultRecord] = []
    for date in instant_store.list_dates(store):
        for trial_id in instant_store.list_trials(store, date):
            start = instant_store.read_start_or_none(store, date, trial_id)
            if start is None:
                raise StoreError(
                    f"instant trial {date}/{trial_id}: no start record")
            book.add_start(date, start)
            send = instant_store.read_send_or_none(store, date, trial_id)
            if send is None:
                continue
            sends.append(send)
            result = instant_store.read_result_or_none(store, date, trial_id)
            if result is not None:
                results.append(result)
    rows = [instant.ChainRow(
        position=send.chain_position, previous=send.chain_previous,
        digest=send.chain_link, trial_id=send.trial_id,
        send_digest=send.send_digest, commitment=send.commitment,
        received_at=send.received_at, beacon_round=send.beacon_round)
        for send in sends]
    faults = instant.chain_faults(rows)
    if faults:
        raise StoreError("the chain of the instant sends has a fault: "
                         + faults[0])
    for send in sorted(sends, key=lambda record: record.chain_position):
        book.add_send(send)
    for result in results:
        book.add_result(result)
    return book
