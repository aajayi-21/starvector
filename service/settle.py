"""The instant trial at work: the start, the send, and the result.

Spec IM1 section 5. This module is the shell of the instant trial. It
reads the clock, the store, the beacon, and the encoders, and it gives
each of them to the pure rules of instant.py and pick_rule.py. No
target is in scope before the pulse of a trial: the start and the send
read no image, and the result step gives the target to Layer 8 alone.
"""

import datetime
import logging
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.canonical import JsonValue
from core.types import Submission
from pipeline.score import encode_submission
from service import instant, instant_store, pool_keys, scoring
from service.beacon import BeaconSource, BeaconUnavailable
from service.instant import Owner
from service.instant_book import Entry, InstantBook
from service.pick_rule import instant_commitment, instant_index
from service.pool_root import leaf_salt, proof_agrees, proof_of
from service.pulse import Pulse, PulseError, chain_named, checked_pulse, \
    pulse_time
from service.store import StoreError

_JOURNAL = logging.getLogger("starvector.instant")

# The pause before a second try of the clock measurement, in seconds:
# the backoff cap of the beacon reads (beacon.py).
CLOCK_RETRY_SECONDS = 30.0


class Refused(Exception):
    """A start or a send that the rules refuse, with its HTTP answer."""

    def __init__(self, status: int, cause: str) -> None:
        super().__init__(cause)
        self.status = status
        self.cause = cause


@dataclass(frozen=True, slots=True)
class InstantWorld:
    """The fixed facts of the instant trials of one server.

    day_cap_all is the cap on the sends of all owners on one UTC date
    (decision D4). pool_root and pool_count are the committed pool
    root of the pool that the server scores against.
    """

    root: Path
    day_cap_all: int
    source: BeaconSource
    pool_key: bytes
    pool_root: str
    pool_count: int
    scoring_config_path: str
    notice: int


def instant_world(*, root: Path, data_root: Path, roots_dir: Path,
                  day_cap_all: int, source: BeaconSource,
                  wired: scoring.WiredScoring, scoring_config_path: str,
                  notice: int) -> InstantWorld:
    """Read the pool key and check the committed pool root.

    The root that the key and the pool give must equal the committed
    one, as it must at the open of a day (spec VP1 section 3.1).
    """
    version = wired.preparation_version_id
    key = pool_keys.read_key(pool_keys.key_path(data_root, version))
    root_file = pool_keys.checked_root(
        wired.context.index.image_ids, key, roots_dir, version)
    return InstantWorld(
        root=root, day_cap_all=day_cap_all, source=source, pool_key=key,
        pool_root=root_file.pool_root, pool_count=root_file.pool_count,
        scoring_config_path=scoring_config_path, notice=notice)


def _utc_date(now: datetime.datetime) -> str:
    return now.astimezone(datetime.UTC).date().isoformat()


def _check_limits(world: InstantWorld, book: InstantBook,
                  owners: Sequence[Owner], day_cap: int, today: str) -> None:
    """The two caps of spec IM1 section 6, or Refused."""
    if instant.sends_left(book.sent_on(owners, today), day_cap) == 0:
        raise Refused(429, "instant-limit")
    if book.sent_total_on(today) >= world.day_cap_all:
        raise Refused(503, "instant-full")


def start_trial(world: InstantWorld, book: InstantBook, owner: Owner,
                owners: Sequence[Owner], day_cap: int,
                now: datetime.datetime,
                make_code: Callable[[], str]) -> Entry:
    """Make a trial for the owner, or give the open one (spec IM1 5.1).

    owners holds the owner and each guest that the owner claimed: the
    cap counts the sends of all of them. An owner has no more than one
    start with no send, thus a second start gives the same trial.
    """
    today = _utc_date(now)
    held = book.open_start(owner)
    if held is not None and not instant.start_expired(held.date, today):
        return held
    _check_limits(world, book, owners, day_cap, today)
    record = instant_store.StartRecord(
        trial_id=secrets.token_hex(16), owner_kind=owner.kind,
        owner=owner.key, trial_code=make_code(),
        started_at=now.astimezone(datetime.UTC).isoformat())
    instant_store.write_start(world.root, today, record)
    book.add_start(today, record)
    entry = book.entry(record.trial_id)
    assert entry is not None
    return entry


def check_send(world: InstantWorld, book: InstantBook, owner: Owner,
               owners: Sequence[Owner], day_cap: int, date: str,
               trial_id: str, now: datetime.datetime,
               clock_offset: float | None) -> Entry:
    """Steps 3 to 5 of the send path (spec IM1 section 12.3), or Refused.

    The steps read the book and the clock measurement. They read no
    record of a day and no image.
    """
    entry = book.entry(trial_id)
    if entry is None or entry.date != date or entry.owner != owner:
        raise Refused(404, "not-found")
    if entry.received_at is not None:
        raise Refused(409, "instant-sent")
    today = _utc_date(now)
    if instant.start_expired(entry.date, today):
        raise Refused(409, "instant-expired")
    _check_limits(world, book, owners, day_cap, today)
    if instant.clock_refuses(clock_offset, instant.CLOCK_BOUND_SECONDS):
        raise Refused(503, "clock")
    return entry


def encode_send(wired: scoring.WiredScoring, submission: Submission) -> None:
    """Step 7: encode the send before its record is written.

    The vectors go to the provider cache, and the result step reads
    them there. A provider that refuses gives Refused, and nothing is
    stored (spec IM1 section 5.4).
    """
    try:
        encode_submission(submission, wired.context.render, wired.encoders)
    except Exception as error:
        _JOURNAL.warning("an instant send was not encoded: %s", error)
        raise Refused(503, "encoder") from error


def store_send(world: InstantWorld, book: InstantBook,
               wired: scoring.WiredScoring, entry: Entry,
               owners: Sequence[Owner], day_cap: int,
               wire_record: JsonValue,
               clock: Callable[[], datetime.datetime],
               ) -> instant_store.SendRecord:
    """Step 8: the time, the pulse, the nonce, the chain, and the write.

    The write lock holds from the read of the clock to the write of
    the send record. The caps are read again with the lock, thus two
    sends at one moment do not get the one last send of a cap.
    """
    chain = world.source.chain
    with instant_store.instant_write_lock(world.root):
        now = clock()
        _check_limits(world, book, owners, day_cap, _utc_date(now))
        if instant_store.read_send_or_none(
                world.root, entry.date, entry.trial_id) is not None:
            raise Refused(409, "instant-sent")
        received_at = now.astimezone(datetime.UTC).isoformat()
        beacon_round = instant.send_pulse_number(
            received_at, instant.MARGIN_SECONDS, chain)
        # A stop between the two writes of an earlier try leaves a
        # secret with no send. That nonce is the nonce of the trial.
        nonce = instant_store.read_secret_or_none(
            world.root, entry.date, entry.trial_id)
        if nonce is None:
            nonce = secrets.token_hex(32)
            instant_store.write_secret(world.root, entry.date,
                                       entry.trial_id, nonce)
        head = book.head()
        previous = instant.CHAIN_START if head is None else head.chain_link
        digest = instant.send_digest(wire_record)
        commitment = instant_commitment(entry.trial_id, nonce)
        record = instant_store.SendRecord(
            trial_id=entry.trial_id, owner_kind=entry.owner.kind,
            owner=entry.owner.key, received_at=received_at,
            record=wire_record, send_digest=digest, commitment=commitment,
            beacon_chain=chain.name, beacon_round=beacon_round,
            preparation_version_id=wired.preparation_version_id,
            pool_root=world.pool_root, pool_count=world.pool_count,
            scoring_config_path=world.scoring_config_path,
            scoring_config_hash=wired.scoring_hash, notice=world.notice,
            chain_position=0 if head is None else head.position + 1,
            chain_previous=previous,
            chain_link=instant.chain_digest(
                previous, trial_id=entry.trial_id, send_digest=digest,
                commitment=commitment, received_at=received_at,
                beacon_round=beacon_round))
        instant_store.write_send(world.root, entry.date, record)
        book.add_send(record)
    return record


def settle_one(world: InstantWorld, wired: scoring.WiredScoring,
               entry: Entry, pulse: Pulse,
               clock: Callable[[], datetime.datetime],
               ) -> instant_store.ResultRecord:
    """Pick the target of one send, score it, and write the result.

    The pool and the scoring configuration must be the ones that the
    send record names. A server that changed one of them with a send
    pending raises here, and the trial stays pending.
    """
    send = instant_store.read_send_or_none(world.root, entry.date,
                                           entry.trial_id)
    nonce = instant_store.read_secret_or_none(world.root, entry.date,
                                              entry.trial_id)
    if send is None or nonce is None:
        raise StoreError(f"trial {entry.trial_id}: no send or no secret")
    image_ids = wired.context.index.image_ids
    if len(image_ids) != send.pool_count \
            or wired.preparation_version_id != send.preparation_version_id \
            or wired.scoring_hash != send.scoring_config_hash:
        raise StoreError(
            f"trial {entry.trial_id}: the pool or the scoring "
            "configuration changed after the send")
    index = instant_index(send.pool_count, send.trial_id, send.send_digest,
                          nonce, pulse.randomness)
    target_id = image_ids[index]
    salt = leaf_salt(world.pool_key, target_id)
    steps = proof_of(image_ids, world.pool_key, index)
    if not proof_agrees(target_id, salt, index, send.pool_count, steps,
                        send.pool_root):
        raise StoreError(
            f"trial {entry.trial_id}: the proof does not give the "
            "committed pool root")
    trial, report = scoring.score_stored_submission(send.record, target_id,
                                                    wired)
    row = scoring.instant_row_value(
        send.trial_id, trial, report, wired,
        channel_scores=scoring.channel_score_values(send.record, target_id,
                                                    wired))
    result = instant_store.ResultRecord(
        trial_id=send.trial_id, beacon_signature=pulse.signature,
        randomness=pulse.randomness, nonce=nonce, target_index=index,
        target_id=target_id, target_salt=salt, target_proof=tuple(steps),
        settled_at=clock().astimezone(datetime.UTC).isoformat(), row=row)
    instant_store.write_result(world.root, entry.date, result,
                               send.commitment)
    return result


def settle_due(world: InstantWorld, book: InstantBook,
               wired: Callable[[], scoring.WiredScoring], now: float,
               clock: Callable[[], datetime.datetime]) -> int:
    """Give a result to each pending send with a pulse that is there.

    The second-to-last argument is the Unix time. A pulse that the source does not have, a
    pulse that does not check, and a send that does not score each
    keep their trials pending for a subsequent try, and no default is
    written (spec IM1 section 5.6). The answer is the count of new
    results.
    """
    by_pulse: dict[int, list[Entry]] = {}
    for entry in book.pending():
        assert entry.beacon_round is not None
        if world.source.ready_at(entry.beacon_round) <= now:
            by_pulse.setdefault(entry.beacon_round, []).append(entry)
    count = 0
    for number in sorted(by_pulse):
        try:
            pulse = checked_pulse(world.source.answers(number), number)
        except BeaconUnavailable:
            continue
        except PulseError as error:
            _JOURNAL.warning("pulse %d did not check: %s", number, error)
            continue
        for entry in by_pulse[number]:
            try:
                result = settle_one(world, wired(), entry, pulse, clock)
            except Exception as error:
                _JOURNAL.warning("trial %s has no result: %s",
                                 entry.trial_id, error)
                continue
            book.add_result(result)
            count += 1
    return count


def receipt_value(send: instant_store.SendRecord) -> dict[str, JsonValue]:
    """The receipt of one send (spec IM1 section 12.3)."""
    chain = chain_named(send.beacon_chain)
    return {
        "trial_id": send.trial_id, "received_at": send.received_at,
        "beacon_round": send.beacon_round,
        "pulse_time": pulse_time(send.beacon_round, chain),
        "send_digest": send.send_digest, "commitment": send.commitment,
        "chain_position": send.chain_position,
        "chain_link": send.chain_link,
    }


def pending_value(send: instant_store.SendRecord) -> dict[str, JsonValue]:
    """The answer before the result. It is a function of the pulse
    alone, thus each trial of one pulse has the same body."""
    chain = chain_named(send.beacon_chain)
    return {"status": "pending", "beacon_round": send.beacon_round,
            "pulse_time": pulse_time(send.beacon_round, chain)}


_TRIAL_NAMES = ("p", "decoy_count", "beaten", "tied", "target_rank")


def result_value(start: instant_store.StartRecord,
                 send: instant_store.SendRecord,
                 result: instant_store.ResultRecord,
                 ) -> dict[str, JsonValue]:
    """The answer after the result (spec IM1 section 5.5).

    Each value comes from the three stored records, thus a read does
    no scoring. It holds the trial score and the counts, and no cutoff
    and no hit mark (rule I2).
    """
    row: Mapping[str, JsonValue] = result.row  # type: ignore[assignment]
    chain = chain_named(send.beacon_chain)
    return {
        "status": "settled",
        "trial_id": send.trial_id,
        "trial_code": start.trial_code,
        "started_at": start.started_at,
        "received_at": send.received_at,
        "settled_at": result.settled_at,
        "target_id": result.target_id,
        "trial": {name: row[name] for name in _TRIAL_NAMES},
        "report": row["report"],
        "pick": {
            "beacon_chain": send.beacon_chain,
            "beacon_round": send.beacon_round,
            "pulse_time": pulse_time(send.beacon_round, chain),
            "beacon_signature": result.beacon_signature,
            "randomness": result.randomness,
            "nonce": result.nonce,
            "commitment": send.commitment,
            "send_digest": send.send_digest,
            "target_index": result.target_index,
            "target_salt": result.target_salt,
            "target_proof": list(result.target_proof),
            "pool_count": send.pool_count,
            "pool_root": send.pool_root,
        },
    }


class SettleLoop:
    """The loop of the server process that settles the pending sends.

    One tick measures the clock when no measurement is there, and
    settles what is due. The server thread calls start, and a test
    calls tick. One lock holds a tick, thus two callers do not score
    one send two times.
    """

    def __init__(self, *, world: Callable[[], InstantWorld],
                 book: InstantBook,
                 wired: Callable[[], scoring.WiredScoring],
                 clock: Callable[[], datetime.datetime],
                 read_offset: Callable[[], float]) -> None:
        self._world = world
        self._book = book
        self._wired = wired
        self._clock = clock
        self._read_offset = read_offset
        self._lock = threading.Lock()
        self._offset: float | None = None
        self._measured_at: float | None = None
        self._stop = threading.Event()

    @property
    def clock_offset(self) -> float | None:
        """The last measured offset of the server clock, or None."""
        return self._offset

    def measure(self) -> None:
        """Measure the clock against the beacon source, one time.

        A measurement that does not come keeps the last value.
        """
        now = self._clock().timestamp()
        self._measured_at = now
        try:
            self._offset = float(self._read_offset())
        except Exception as error:
            _JOURNAL.warning("the clock was not measured: %s", error)

    def tick(self) -> int:
        """One turn of the loop. The answer is the count of new results."""
        with self._lock:
            now = self._clock().timestamp()
            waited = None if self._measured_at is None \
                else now - self._measured_at
            if self._offset is None and (
                    waited is None or waited >= CLOCK_RETRY_SECONDS):
                self.measure()
            if not self._book.pending():
                return 0
            count = settle_due(self._world(), self._book, self._wired, now,
                               self._clock)
            if count:
                # Each batch of results measures the clock again (spec
                # IM1 section 5.3): the guard reads a new value while
                # the players send.
                self.measure()
            return count

    def start(self, pause_seconds: float = 1.0) -> threading.Thread:
        """Start the loop on a daemon thread, with one tick each pause."""

        def run() -> None:
            while not self._stop.wait(pause_seconds):
                try:
                    self.tick()
                except Exception:
                    _JOURNAL.exception("a tick of the result loop stopped")

        thread = threading.Thread(target=run, name="instant-settle",
                                  daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
