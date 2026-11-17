"""The day lifecycle commands: open, close, reveal, status, rescore.

Spec: S1 (in docs/specs/) section 6, with the BR1 amendments of
docs/specs/beta-readiness.md section 3. Each status move is
deliberate, repeatable, and refuses to run out of sequence. Open
publishes the commitment and spends nothing (R5). Close is the one
live step: it moves the day to "closing" before it scores, thus a
late send refuses. Reveal publishes the secret.

With the pick after the close (spec VP1) the open stores no target. It
names the beacon pulse that picks it, from the scheduled close. The
close gets that pulse, records the pick with its pool proof, and then
scores as before. No command prints
score information while the day is open (R3 covers the terminal).
"""

import argparse
import datetime
import secrets
import string
import sys
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING
from pathlib import Path

from core.canonical import canonical_json_pretty, sha256_hex
from pipeline.config import ConfigError, load_scoring_config
from service import day_scores, pool_keys, schedule, scoring, store

if TYPE_CHECKING:
    import numpy as np
from service.beacon import BeaconSource, fetch_pulse, make_source
from service.pick_rule import pick_index
from service.pool_root import leaf_salt, proof_agrees, proof_of
from service.pulse import day_pulse_number
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)
from validation import harness


def pick_target(image_ids: tuple[str, ...], day: str,
                pick_seed: str) -> str:
    """The day's target: a seeded, equally likely pick (R6).

    `pick_rule.py` holds the rule, so a reader runs the same one.
    """
    return image_ids[pick_index(len(image_ids), day, pick_seed)]


def day_commitment(target_id: str, secret: str) -> str:
    """The published digest: SHA-256 of "target:secret" (D-OP8)."""
    return sha256_hex(f"{target_id}:{secret}")


def make_trial_code() -> str:
    """Six random characters, A-Z and 0-9 - the player-facing
    identifier of the hidden target (section 14b ruling). No
    derivation from the image (section 22)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def utc_now() -> datetime.datetime:
    """The current instant in UTC - one seam for the tests to pin.

    The day calendar reads UTC alone (spec BR1 section 3). The local
    date of the D8 ruling put the label and the countdown on two
    clocks.
    """
    return datetime.datetime.now(datetime.UTC)


def choose_open_date(service_config: ServiceConfig,
                     instant: datetime.datetime) -> str:
    """The label the next open takes (spec BR1 section 3).

    The current day by the UTC calendar, or the day after the latest
    stored day when that one holds the current label. The status
    rule - the latest day must be revealed - is open_day's to check.
    """
    latest = store.latest_day(Path(service_config.store_root))
    return schedule.next_open_label(latest, instant,
                                    service_config.closes_at_utc)


def _check_open_sequence(root: Path, day: str) -> None:
    """Refuse an open out of sequence: one active day at a time.

    The latest stored day must be revealed, and the new label must
    come after it. An open adjacent to a closed day strands that day:
    the reveal endpoint acts on the latest day alone.
    """
    latest = store.latest_day(root)
    if latest is None:
        return
    status = store.read_day_record(root, latest).status
    if status != "revealed":
        raise store.StoreError(
            f"day {latest} has status {status!r} - reveal it before a new "
            "day opens")
    if day <= latest:
        raise store.StoreError(
            f"day {day} is not after the latest stored day {latest} - "
            "open refuses to go back")


def _resolve_day(service_config: ServiceConfig, date: str | None) -> str:
    """The named day, or the latest stored one."""
    if date is not None:
        return date
    day = store.latest_day(Path(service_config.store_root))
    if day is None:
        raise store.StoreError(
            "the store holds no day - open one first")
    return day


def open_day(service_config: ServiceConfig, *, date: str | None = None,
             scoring_config_path: str | None = None,
             clock: Callable[[], str] | None = None,
             pick_seed: str | None = None,
             secret: str | None = None,
             trial_code: str | None = None,
             now: Callable[[], datetime.datetime] | None = None,
             wired: scoring.WiredScoring | None = None,
             ) -> store.DayRecord:
    """Open one day: wire warm, pick, commit, write (spec section 6).

    With no date the label comes from choose_open_date. A named date
    must be a calendar date after the latest stored day, and with a
    rollover hour configured it must not be more than one day after
    the current day. The latest stored day must be revealed.

    A caller with a resident context hands it in through wired, in the
    manner of close_day, thus the process loads no second copy of the
    pool (spec PL1 section 5). That context comes from the server's
    config, thus a config override and a context together refuse.
    """
    if wired is not None and scoring_config_path not in (
            None, service_config.scoring_config):
        raise ValueError("a resident context serves the server's own config "
                         "- a named config wires by itself")
    clock = clock or harness.default_clock
    instant = (now or utc_now)()
    root = Path(service_config.store_root)
    day = date if date is not None \
        else choose_open_date(service_config, instant)
    try:
        schedule.check_open_label(day, instant,
                                  service_config.closes_at_utc)
    except schedule.ScheduleError as error:
        raise store.StoreError(str(error)) from error
    if store.day_record_path(root, day).is_file():
        raise store.StoreError(f"day {day} exists - open refuses a rewrite")
    _check_open_sequence(root, day)
    config_path = scoring_config_path or service_config.scoring_config
    if wired is None:
        config = load_scoring_config(Path(config_path))
        wired = scoring.wire_for_open(config, config_path,
                                      Path(service_config.data_root))
    trial_code = trial_code or make_trial_code()
    if service_config.pick_protocol == "vp1":
        if pick_seed is not None or secret is not None:
            raise ValueError("a vp1 day takes no seed and no secret at the "
                             "open - the pulse after the close picks it")
        record = _vp1_open_record(service_config, wired, day, trial_code,
                                  config_path, clock())
        store.ensure_store(root)
        store.write_day_record(root, record)
        return record
    pick_seed = pick_seed or secrets.token_hex(16)
    secret = secret or secrets.token_hex(32)
    target_id = pick_target(wired.context.index.image_ids, day, pick_seed)
    record = store.DayRecord(
        day=day, trial_code=trial_code, target_id=target_id,
        pick_seed=pick_seed, secret=secret,
        commitment=day_commitment(target_id, secret),
        scoring_config_path=config_path,
        scoring_config_hash=wired.scoring_hash,
        preparation_version_id=wired.preparation_version_id,
        status="open", opened_at=clock(), closed_at=None, revealed_at=None)
    store.ensure_store(root)
    store.write_day_record(root, record)
    return record


def _vp1_open_record(service_config: ServiceConfig,
                     wired: scoring.WiredScoring, day: str, trial_code: str,
                     config_path: str, opened_at: str) -> store.DayRecord:
    """The record of a vp1 day at the open: no target, a named pulse.

    The committed pool root must agree with the pool and the pool key,
    or the day does not open (spec VP1 section 3.1).
    """
    beacon = service_config.beacon
    assert beacon is not None and service_config.closes_at_utc is not None
    version = wired.preparation_version_id
    key = pool_keys.read_key(
        pool_keys.key_path(Path(service_config.data_root), version))
    root_file = pool_keys.checked_root(
        wired.context.index.image_ids, key,
        Path(service_config.pool_roots_dir), version)
    closes_at = schedule.closes_at_for(day, service_config.closes_at_utc)
    number = day_pulse_number(int(closes_at.timestamp()),
                              beacon.margin_seconds, beacon.chain)
    return store.DayRecord(
        day=day, trial_code=trial_code, target_id=None, pick_seed=None,
        secret=None, commitment=None, scoring_config_path=config_path,
        scoring_config_hash=wired.scoring_hash,
        preparation_version_id=version, status="open", opened_at=opened_at,
        closed_at=None, revealed_at=None, protocol="vp1",
        pool_root=root_file.pool_root, pool_count=root_file.pool_count,
        beacon_chain=beacon.chain.name, beacon_round=number)


def _vp1_source(service_config: ServiceConfig, record: store.DayRecord,
                beacon: BeaconSource | None) -> BeaconSource:
    """The source of the day's pulse, which must be on the day's chain."""
    if service_config.beacon is None:
        raise store.StoreError(
            f"day {record.day} is a vp1 day and the server config has no "
            "beacon block")
    source = beacon or make_source(service_config.beacon)
    if source.chain.name != record.beacon_chain:
        raise store.StoreError(
            f"day {record.day} names the beacon {record.beacon_chain!r} and "
            f"the server reads {source.chain.name!r}")
    return source


def _check_vp1_due(record: store.DayRecord, source: BeaconSource,
                   service_config: ServiceConfig, now: float) -> None:
    """Refuse a close that starts too long before the pulse (spec VP1 §5).

    The close waits for its pulse, and a close that starts hours before
    it waits for hours and ends play before its time. The window is the margin plus
    the grace, so the timer firing at the close instant goes through.
    """
    assert service_config.beacon is not None and record.beacon_round
    early = source.ready_at(record.beacon_round) - now
    window = service_config.beacon.margin_seconds \
        + service_config.beacon.grace_seconds
    if early > window:
        raise store.StoreError(
            f"day {record.day}: its pulse {record.beacon_round} comes in "
            f"{int(early)} s - close it at its scheduled close")


def _record_vp1_pick(service_config: ServiceConfig, record: store.DayRecord,
                     wired: scoring.WiredScoring, source: BeaconSource,
                     now: Callable[[], float],
                     sleep: Callable[[float], None]) -> store.DayRecord:
    """Get the pulse, pick, prove, and record the pick (spec VP1 §3.3)."""
    assert service_config.beacon is not None and record.beacon_round
    root = Path(service_config.store_root)
    image_ids = wired.context.index.image_ids
    if len(image_ids) != record.pool_count:
        raise store.StoreError(
            f"day {record.day}: the pool holds {len(image_ids)} images and "
            f"the open committed {record.pool_count}")
    pulse = fetch_pulse(source, record.beacon_round, service_config.beacon,
                        now=now, sleep=sleep)
    index = pick_index(len(image_ids), record.day, pulse.randomness)
    target_id = image_ids[index]
    key = pool_keys.read_key(pool_keys.key_path(
        Path(service_config.data_root), record.preparation_version_id))
    salt = leaf_salt(key, target_id)
    steps = proof_of(image_ids, key, index)
    if not proof_agrees(target_id, salt, index, len(image_ids), steps,
                        str(record.pool_root)):
        raise store.StoreError(
            f"day {record.day}: the proof does not give the committed pool "
            "root - the pool or the key changed after the open")
    with store.day_write_lock(root, record.day):
        return store.record_pick(
            root, record.day, target_id=target_id,
            pick_seed=pulse.randomness, beacon_signature=pulse.signature,
            target_index=index, target_salt=salt, target_proof=steps)


# The pauses before the fast retries of a refused send (spec CR1 ruling
# D5): three more tries, about three and a half minutes in all.
FAST_RETRY_PAUSES = (30.0, 60.0, 120.0)

# The guard of spec CR1 ruling D6: the close skips refused sends by
# itself while they are at most this share of the day's sends.
QUARANTINE_SHARE = 0.10


class CloseHeld(store.StoreError):
    """The close found more refused sends than the guard allows.

    Spec CR1 section 4 step 6: that many refusals are read as an outage,
    thus the close writes no record, the day stays in "closing", and the
    message names each refused player.
    """


def _blind_run(stored_by_player: Mapping[str, dict],
               wired: scoring.WiredScoring,
               sleep: Callable[[float], None],
               ) -> tuple[dict[str, "np.ndarray"], dict[str, tuple[str, int]]]:
    """Layers 0 to 6 for each send, with no target (spec CR1 section 4).

    The output is the fused pool scores of each send that got a score,
    and for each send that did not, the error text and the try count. A
    refusal of the provider (InputRefused) gets the fast retries. An
    IntakeError or NoActiveChannels of a stored send cannot change with
    a wait, thus it counts as a refusal at the first try. Each other
    error raises: a skip of that send is a skip that an outage or a
    defect decided.
    """
    from core.fusion import NoActiveChannels
    from core.intake import IntakeError
    from pipeline.score import fused_pool_scores
    from providers.protocols import InputRefused

    # The batch fills the caches. A refusal of one input refuses the full
    # batch, thus the run below encodes each send alone and finds it.
    try:
        harness.prewarm_records(
            [stored["record"] for stored in stored_by_player.values()],
            wired.context.gates, wired.context.render, wired.encoders)
    except (InputRefused, IntakeError):
        pass
    rows: dict[str, np.ndarray] = {}
    refused: dict[str, tuple[str, int]] = {}
    for player in sorted(stored_by_player):
        record = stored_by_player[player]["record"]
        tries = 0
        while True:
            tries += 1
            try:
                rows[player] = fused_pool_scores(record, wired.context,
                                                 wired.encoders)
                break
            except (IntakeError, NoActiveChannels) as error:
                refused[player] = (str(error), tries)
                break
            except InputRefused as error:
                if tries > len(FAST_RETRY_PAUSES):
                    refused[player] = (str(error), tries)
                    break
                sleep(FAST_RETRY_PAUSES[tries - 1])
    return rows, refused


def _quarantine_refused(root: Path, day: str, refused: Mapping[str, tuple],
                        stored_by_player: Mapping[str, dict],
                        send_count: int, clock: Callable[[], str]) -> None:
    """The guard, then a record for each refused send (spec CR1 §4, §6).

    At most QUARANTINE_SHARE of the day's sends: a record for each, with
    decided_by "close". Above it, no record, and CloseHeld names each.
    """
    if not refused:
        return
    if len(refused) > QUARANTINE_SHARE * send_count:
        names = "; ".join(f"{player}: {error[:160]}"
                          for player, (error, _) in sorted(refused.items()))
        raise CloseHeld(
            f"day {day}: {len(refused)} of {send_count} sends were refused, "
            f"above the guard of {QUARANTINE_SHARE:.0%} - read as an outage, "
            f"no send is skipped ({names}). A send the guard holds can be "
            "skipped with `service.day quarantine`.")
    for player, (error, tries) in sorted(refused.items()):
        store.write_quarantine(root, store.QuarantineRecord(
            day=day, player=player,
            trial_id=str(stored_by_player[player]["trial_id"]),
            submission_digest=store.submission_digest(root, day, player),
            cause="input-refused", error=error[:500], tries=tries,
            decided_by="close", note=None, quarantined_at=clock()))


def _write_day_scores(service_config: ServiceConfig, day: str,
                      target_id: str, stored_by_player: Mapping[str, dict],
                      wired: scoring.WiredScoring,
                      rows: Mapping[str, "np.ndarray"] | None = None) -> None:
    """The pool scores of the day's sends and the day rank (spec AG1 §5).

    One row of fused pool scores for each send, in the sequence of the
    sorted names, then the day rank from Layer 8. A day with no send has
    no day number, thus nothing is written for it.
    """
    import numpy as np

    from core.ranking import day_rank
    from pipeline.score import fused_pool_scores

    players = sorted(stored_by_player)
    if not players:
        return
    scores = np.stack([
        rows[player] if rows is not None else
        fused_pool_scores(stored_by_player[player]["record"],
                          wired.context, wired.encoders)
        for player in players]).astype(np.float32)        # (players, N)
    rank = day_rank(scores, target_id, wired.context.index)
    day_scores.write_day_scores(Path(service_config.data_root), day,
                                wired.scoring_hash, players=players,
                                scores=scores, rank=rank)


def close_day(service_config: ServiceConfig, *, date: str | None = None,
              providers: Mapping[str, object] | None = None,
              clock: Callable[[], str] | None = None,
              wired: scoring.WiredScoring | None = None,
              beacon: BeaconSource | None = None,
              now: Callable[[], float] | None = None,
              sleep: Callable[[float], None] | None = None) -> int:
    """Close one day: stop the sends, score each one, flip the status.

    The sequence (spec BR1 section 3): wire and check the pinned
    hash, move "open" to "closing" with the day's write lock held, read
    the submissions, score, write the rows, move "closing" to
    "closed". The wiring comes first, thus a missing provider key or
    a moved config refuses while the day is open. A send that
    held the lock before the move is in the submissions this close
    reads, and a send after it meets "closing" and refuses.

    Repeatable after a stop: a day in "closing" continues, a stored
    trial row that equals the recomputation is kept, a different one
    raises, and the move to "closed" is the completeness marker. The
    output is the count of trial rows. A caller with a resident
    context hands it in through wired (P5 R1) - the day record's
    hash guard runs the same, thus a context that does not match the
    pinned config refuses loudly. With no wired context the wiring
    comes from the day record's pinned config path, as before.

    Spec CR1: each send runs Layers 0 to 6 with no target first, with
    fast retries for a refusal of the provider. A refused send gets a
    quarantine record while the guard allows, and the close skips it.
    Above the guard, CloseHeld raises and the day stays in "closing".

    A vp1 day (spec VP1) gets its pulse after that run and records the
    pick before it scores. The beacon, clock, and sleep
    arguments are the seams of the tests. A pulse that does not come raises, and the
    day stays in "closing" for a subsequent close.
    """
    import time

    clock = clock or harness.default_clock
    now = now or time.time
    sleep = sleep or time.sleep
    root = Path(service_config.store_root)
    day = _resolve_day(service_config, date)
    record = store.read_day_record(root, day)
    if record.status not in ("open", "closing"):
        raise store.StoreError(
            f"day {day} has status {record.status!r} - close needs 'open' "
            "or 'closing'")
    if wired is None:
        config = load_scoring_config(Path(record.scoring_config_path))
        wired = scoring.wire_for_close(config, record.scoring_config_path,
                                       Path(service_config.data_root),
                                       providers)
    if wired.scoring_hash != record.scoring_config_hash:
        raise store.StoreError(
            f"the scoring config hash moved since open "
            f"({wired.scoring_hash[:8]} against "
            f"{record.scoring_config_hash[:8]}) - the config file changed "
            "after the day opened")
    source = None
    if record.protocol == "vp1" and record.target_id is None:
        source = _vp1_source(service_config, record, beacon)
        if record.status == "open":
            _check_vp1_due(record, source, service_config, now())
    if record.status == "open":
        with store.day_write_lock(root, day):
            store.update_day_status(root, day, expect_status="open",
                                    new_status="closing",
                                    timestamp_field=None, timestamp=None)
    # Read and check each submission first. A submission that does not
    # parse stops the close before a row write. A send with a
    # quarantine record is not read again (spec CR1 section 4).
    sends = store.list_submissions(root, day)
    held = set(store.list_quarantined(root, day))
    stored_by_player: dict[str, dict] = {}
    for player in sends:
        if player in held:
            continue
        stored = store.read_json_or_none(
            store.submission_path(root, day, player))
        if stored is None or "record" not in stored \
                or "trial_id" not in stored:
            raise store.StoreError(
                f"day {day}: the submission of {player} does not parse")
        stored_by_player[player] = stored
    # The blind run, the guard, and the records, before the pick: a skip
    # is decided while no target is read (spec CR1 ruling D3).
    rows, refused = _blind_run(stored_by_player, wired, sleep)
    _quarantine_refused(root, day, refused, stored_by_player, len(sends),
                        clock)
    for player in refused:
        stored_by_player.pop(player)
    if source is not None:
        record = _record_vp1_pick(service_config, record, wired, source,
                                  now, sleep)
    count = 0
    for player, stored in stored_by_player.items():
        trial, report = scoring.score_stored_submission(
            stored["record"], record.target_id, wired)
        value = scoring.trial_row_value(
            day, player, str(stored["trial_id"]), trial, report, wired,
            channel_scores=scoring.channel_score_values(
                stored["record"], record.target_id, wired))
        row_path = store.trial_row_path(root, day, player)
        rendered = canonical_json_pretty(value) + "\n"
        if row_path.is_file():
            if row_path.read_text(encoding="utf-8") != rendered:
                raise store.StoreError(
                    f"{row_path}: a stored trial row differs from the "
                    "recomputation - the lineage moved between close runs")
        else:
            store.write_once_json(row_path, value)
        count += 1
    # The day-score file goes before the move to "closed": a closed day
    # has its day rank, and a close that stops here writes it again.
    _write_day_scores(service_config, day, str(record.target_id),
                      stored_by_player, wired, rows=rows)
    store.update_day_status(root, day, expect_status="closing",
                            new_status="closed",
                            timestamp_field="closed_at", timestamp=clock())
    return count


def reveal_day(service_config: ServiceConfig, *,
               date: str | None = None,
               clock: Callable[[], str] | None = None) -> store.DayRecord:
    """Reveal one closed day: the status move that opens the report.

    The status moves first and the rollup follows (the 2026-08-16
    ruling), thus the boards do not go stale while the process
    runs. Each rollup write is repeatable, and a stop part of the
    procedure is repaired by a second reveal or by the assemble
    command of the rollup module.
    """
    from service import rollup

    clock = clock or harness.default_clock
    root = Path(service_config.store_root)
    day = _resolve_day(service_config, date)
    record = store.update_day_status(root, day, expect_status="closed",
                                     new_status="revealed",
                                     timestamp_field="revealed_at",
                                     timestamp=clock())
    rollup.roll_up_day(service_config, record)
    _build_results_index(service_config)
    return record


def _build_results_index(service_config: ServiceConfig) -> None:
    """Make the results index current after a reveal (spec PL1 section 7).

    The index is a cache that the next read builds when it is stale,
    thus a build that stops writes to the journal, and the reveal that
    players can read stays as it is.
    """
    import sqlite3

    from service import index

    root = Path(service_config.store_root)
    try:
        index.build(root, index.index_path(Path(service_config.data_root)))
    except (index.ResultsIndexError, store.StoreError, sqlite3.Error,
            OSError) as error:
        print(f"the results index did not build after the reveal: {error}",
              file=sys.stderr)


def _first_difference(stored: dict, recomputed: dict) -> str:
    """The first field where two trial rows disagree, for the error."""
    for key in sorted(set(stored) | set(recomputed)):
        if stored.get(key) != recomputed.get(key):
            return key
    return "the byte shape"


def rescore_days(service_config: ServiceConfig, *, config_path: str,
                 from_date: str | None = None, to_date: str | None = None,
                 providers: Mapping[str, object] | None = None,
                 ) -> dict[str, int]:
    """Re-run stored submissions with a named config (S1 R8).

    With the pinned config the recomputation must equal the stored
    rows byte-for-byte - a difference names the day, the player, and
    the first differing field, and nothing is written. With a
    different config the rows land adjacent
    (trials/<player>.<hash8>.json), repeatable, and the stored rows
    and day records stay untouched (architecture section 21:
    rescore, do not migrate). Open and closing days are skipped with
    one count - they hold no complete set of rows at this time.
    """
    import json

    root = Path(service_config.store_root)
    named = load_scoring_config(Path(config_path))
    wired = scoring.wire_for_close(named, config_path,
                                   Path(service_config.data_root),
                                   providers)
    counts = {"days": 0, "compared": 0, "equal": 0, "written": 0,
              "skipped_open": 0}
    for day in store.list_days(root):
        if from_date is not None and day < from_date:
            continue
        if to_date is not None and day > to_date:
            continue
        record = store.read_day_record(root, day)
        if record.status in ("open", "closing"):
            counts["skipped_open"] += 1
            continue
        if record.preparation_version_id != wired.preparation_version_id:
            raise store.StoreError(
                f"day {day} was scored against preparation "
                f"{record.preparation_version_id[:8]} and the named config "
                f"wires {wired.preparation_version_id[:8]} - a rescore "
                "across preparations needs its own ruling")
        counts["days"] += 1
        pinned = wired.scoring_hash == record.scoring_config_hash
        rescored: dict[str, dict] = {}
        for player in store.list_submissions(root, day):
            stored = store.read_json_or_none(
                store.submission_path(root, day, player))
            if stored is None:
                raise store.StoreError(
                    f"day {day}: the submission of {player} does not parse")
            rescored[player] = stored
            trial, report = scoring.score_stored_submission(
                stored["record"], record.target_id, wired)
            value = scoring.trial_row_value(
                day, player, str(stored["trial_id"]), trial, report, wired,
                channel_scores=scoring.channel_score_values(
                    stored["record"], record.target_id, wired))
            rendered = canonical_json_pretty(value) + "\n"
            if pinned:
                row_path = store.trial_row_path(root, day, player)
                if not row_path.is_file():
                    raise store.StoreError(
                        f"{row_path}: a closed day has no stored trial row")
                counts["compared"] += 1
                current = row_path.read_text(encoding="utf-8")
                if current != rendered:
                    field = _first_difference(json.loads(current), value)
                    raise store.StoreError(
                        f"rescore mismatch on day {day}, player {player}: "
                        f"the first differing field is {field} - the "
                        "pinned config no longer reproduces the stored "
                        "trial row (CLAUDE.md section 9)")
                counts["equal"] += 1
            else:
                adjacent = store.trial_row_path(
                    root, day, player, wired.scoring_hash[:8])
                if adjacent.is_file():
                    if adjacent.read_text(encoding="utf-8") != rendered:
                        raise store.StoreError(
                            f"{adjacent}: an earlier rescore wrote a "
                            "different row for the same config hash")
                    continue
                store.write_once_json(adjacent, value)
                counts["written"] += 1
        # A rescore at a new configuration gets the day ranks of that
        # configuration, for its parallel board (spec AG1 section 5).
        if not pinned:
            _write_day_scores(service_config, day, str(record.target_id),
                              rescored, wired)
    return counts


def quarantine_send(service_config: ServiceConfig, *, date: str,
                    player: str, note: str,
                    providers: Mapping[str, object] | None = None,
                    clock: Callable[[], str] | None = None,
                    ) -> store.QuarantineRecord:
    """The operator's skip of one send that the guard held (spec CR1 §6).

    For a day in "closing" alone, and a send with no trial row. The
    command runs the blind run on that send first, one try, and refuses
    unless the provider refuses it, thus no operator can skip a send
    that scores. The run reads no target, and on a vp1 day held before
    its pick no target exists. Each other error raises: an outage does
    not make the decision of a skip.
    """
    from core.fusion import NoActiveChannels
    from core.intake import IntakeError
    from pipeline.score import fused_pool_scores
    from providers.protocols import InputRefused

    clock = clock or harness.default_clock
    root = Path(service_config.store_root)
    record = store.read_day_record(root, date)
    if record.status != "closing":
        raise store.StoreError(
            f"day {date} has status {record.status!r} - a quarantine needs a "
            "day in 'closing'")
    if not note.strip():
        raise store.StoreError("a quarantine needs a note")
    stored = store.read_json_or_none(store.submission_path(root, date, player))
    if stored is None:
        raise store.StoreError(f"day {date}: {player} has no stored send")
    if store.trial_row_path(root, date, player).is_file():
        raise store.StoreError(
            f"day {date}: the send of {player} has a trial row - it scored")
    config = load_scoring_config(Path(record.scoring_config_path))
    wired = scoring.wire_for_close(config, record.scoring_config_path,
                                   Path(service_config.data_root), providers)
    if wired.scoring_hash != record.scoring_config_hash:
        raise store.StoreError(
            f"day {date}: the pinned config file now hashes to "
            f"{wired.scoring_hash[:8]}, not {record.scoring_config_hash[:8]}")
    try:
        fused_pool_scores(stored["record"], wired.context, wired.encoders)
    except (InputRefused, IntakeError, NoActiveChannels) as error:
        quarantine = store.QuarantineRecord(
            day=date, player=player, trial_id=str(stored["trial_id"]),
            submission_digest=store.submission_digest(root, date, player),
            cause="input-refused", error=str(error)[:500], tries=1,
            decided_by="operator", note=note, quarantined_at=clock())
        store.write_quarantine(root, quarantine)
        return quarantine
    raise store.StoreError(
        f"day {date}: the send of {player} scores in the blind run - a send "
        "that scores is not skipped")


def build_day_scores(service_config: ServiceConfig, *,
                     date: str | None = None,
                     providers: Mapping[str, object] | None = None,
                     ) -> dict[str, int]:
    """Make the day-score files of closed and revealed days again.

    With a date, that day. With none, each closed or revealed day that
    has sends and no file at its pinned configuration. The sends score
    again through the day's pinned config, and the providers answer
    from their caches. A day of a vp1 protocol with no pick, or an open
    day, does not get a score.
    """
    root = Path(service_config.store_root)
    data_root = Path(service_config.data_root)
    days = [date] if date is not None else store.list_days(root)
    counts = {"days": 0, "written": 0, "present": 0}
    for day in days:
        record = store.read_day_record(root, day)
        if record.status not in ("closed", "revealed"):
            if date is not None:
                raise store.StoreError(
                    f"day {day} has status {record.status!r} - a day-score "
                    "file needs a closed or revealed day")
            continue
        players = store.list_submissions(root, day)
        if not players:
            continue
        counts["days"] += 1
        if date is None and day_scores.has_day_scores(
                data_root, day, record.scoring_config_hash):
            counts["present"] += 1
            continue
        config = load_scoring_config(Path(record.scoring_config_path))
        wired = scoring.wire_for_close(config, record.scoring_config_path,
                                       data_root, providers)
        if wired.scoring_hash != record.scoring_config_hash:
            raise store.StoreError(
                f"day {day}: the pinned config file now hashes to "
                f"{wired.scoring_hash[:8]}, not {record.scoring_config_hash[:8]}")
        stored = {}
        for player in players:
            value = store.read_json_or_none(
                store.submission_path(root, day, player))
            if value is None or "record" not in value:
                raise store.StoreError(
                    f"day {day}: the submission of {player} does not parse")
            stored[player] = value
        _write_day_scores(service_config, day, str(record.target_id),
                          stored, wired)
        counts["written"] += 1
    return counts


def migrate_store(service_config: ServiceConfig) -> dict[str, int]:
    """Backfill day records from before the section 14b rulings.

    A legacy record - the section 5 fields with no trial_code - gets
    one new random code, written atomically. Records with the full
    field set stay untouched, thus the command is repeatable. Play
    data (submissions, trial rows) is not read and not written.
    """
    import json

    root = Path(service_config.store_root)
    counts = {"days": 0, "backfilled": 0}
    for day in store.list_days(root):
        counts["days"] += 1
        path = store.day_record_path(root, day)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "trial_code" not in raw:
            raw["trial_code"] = make_trial_code()
            from pool.artifacts import write_json_pretty

            write_json_pretty(path, raw)
            counts["backfilled"] += 1
        # The strict reader checks the moved record in full.
        store.read_day_record(root, day)
    return counts


def day_status_lines(service_config: ServiceConfig) -> list[str]:
    """The status text: day, status, and if a submission is stored."""
    root = Path(service_config.store_root)
    day = store.latest_day(root)
    if day is None:
        return ["no day open"]
    record = store.read_day_record(root, day)
    submitted = service_config.player in store.list_submissions(root, day)
    held = store.list_quarantined(root, day)
    return [
        f"day {day}",
        f"trial code {record.trial_code}",
        f"status {record.status}",
        f"commitment {record.commitment}",
        f"submission stored: {'yes' if submitted else 'no'}",
    ] + ([f"quarantined {len(held)}"] if held else [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.day")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    open_parser = commands.add_parser("open")
    open_parser.add_argument("--config", default=None,
                             help="scoring config override")
    open_parser.add_argument("--date", default=None)
    close_parser = commands.add_parser("close")
    close_parser.add_argument("--date", default=None)
    reveal_parser = commands.add_parser("reveal")
    reveal_parser.add_argument("--date", default=None)
    commands.add_parser("status")
    commands.add_parser("migrate")
    rescore_parser = commands.add_parser("rescore")
    rescore_parser.add_argument("--config", required=True,
                                help="the scoring config to rescore with")
    rescore_parser.add_argument("--from", dest="from_date", default=None)
    rescore_parser.add_argument("--to", dest="to_date", default=None)
    quarantine_parser = commands.add_parser(
        "quarantine", help="skip one refused send of a held day (spec CR1)")
    quarantine_parser.add_argument("--date", required=True)
    quarantine_parser.add_argument("--player", required=True)
    quarantine_parser.add_argument("--note", required=True)
    scores_parser = commands.add_parser(
        "day-scores", help="make the day-score files of spec AG1 again")
    scores_parser.add_argument("--date", default=None,
                               help="one day; with none, each day that "
                                    "has no file")
    arguments = parser.parse_args(argv)

    try:
        service_config = load_service_config(Path(arguments.service_config))
        if arguments.command == "open":
            record = open_day(service_config, date=arguments.date,
                              scoring_config_path=arguments.config)
            print(f"day {record.day} open")
            print(f"trial code {record.trial_code}")
            print(f"commitment {record.commitment}")
        elif arguments.command == "close":
            count = close_day(service_config, date=arguments.date)
            day = arguments.date or store.latest_day(
                Path(service_config.store_root))
            print(f"day {day} closed  trial_rows={count}")
        elif arguments.command == "reveal":
            record = reveal_day(service_config, date=arguments.date)
            print(f"day {record.day} revealed")
            print(f"target {record.target_id}")
            print(f"secret {record.secret}")
            print("check: printf '%s:%s' TARGET SECRET | sha256sum")
        elif arguments.command == "status":
            for line in day_status_lines(service_config):
                print(line)
        elif arguments.command == "migrate":
            counts = migrate_store(service_config)
            print(f"migrate days={counts['days']} "
                  f"backfilled={counts['backfilled']}")
        elif arguments.command == "rescore":
            counts = rescore_days(service_config,
                                  config_path=arguments.config,
                                  from_date=arguments.from_date,
                                  to_date=arguments.to_date)
            print("rescore "
                  + "  ".join(f"{name}={value}"
                              for name, value in sorted(counts.items())))
        elif arguments.command == "quarantine":
            quarantine = quarantine_send(service_config, date=arguments.date,
                                         player=arguments.player,
                                         note=arguments.note)
            print(f"day {quarantine.day}: the send of {quarantine.player} is "
                  "quarantined - close the day again")
        elif arguments.command == "day-scores":
            counts = build_day_scores(service_config, date=arguments.date)
            print("day-scores "
                  + "  ".join(f"{name}={value}"
                              for name, value in sorted(counts.items())))
    except (ServiceConfigError, ConfigError, store.StoreError,
            ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
