"""The stored records of an instant trial (spec IM1 section 12)."""

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from service import instant, instant_store
from service.pick_rule import instant_commitment
from service.store import StoreError

DATE = "2026-11-23"
TRIAL = "0123456789abcdef0123456789abcdef"
NONCE = "ab" * 32
WIRE = {"canvas_strokes": [], "groups": [], "impressions": ["a tower"],
        "pasted_text": "", "relations": []}


def _start(**changes: object) -> instant_store.StartRecord:
    record = instant_store.StartRecord(
        trial_id=TRIAL, owner_kind=instant.GUEST,
        owner="guest-0123456789abcdef", trial_code="KXQ-4471",
        started_at="2026-11-23T10:00:00+00:00")
    return replace(record, **changes)


def _send(**changes: object) -> instant_store.SendRecord:
    fields = {
        "trial_id": TRIAL, "owner_kind": instant.GUEST,
        "owner": "guest-0123456789abcdef",
        "received_at": "2026-11-23T10:02:00.250000+00:00",
        "record": WIRE, "send_digest": instant.send_digest(WIRE),
        "commitment": instant_commitment(TRIAL, NONCE),
        "beacon_chain": "fake", "beacon_round": 30_000_000,
        "preparation_version_id": "c8" * 32, "pool_root": "1f" * 32,
        "pool_count": 40, "scoring_config_path": "configs/scoring/x.json",
        "scoring_config_hash": "9c" * 32, "notice": 3,
        "chain_position": 0, "chain_previous": instant.CHAIN_START,
    }
    fields.update(changes)
    if "chain_link" not in fields:
        fields["chain_link"] = instant.chain_digest(
            fields["chain_previous"], trial_id=fields["trial_id"],
            send_digest=fields["send_digest"],
            commitment=fields["commitment"],
            received_at=fields["received_at"],
            beacon_round=fields["beacon_round"])
    return instant_store.SendRecord(**fields)


def _result(**changes: object) -> instant_store.ResultRecord:
    record = instant_store.ResultRecord(
        trial_id=TRIAL, beacon_signature="cd" * 48, randomness="11" * 32,
        nonce=NONCE, target_index=7, target_id="image-007",
        target_salt="2e" * 32, target_proof=("R:" + "aa" * 32,),
        settled_at="2026-11-23T10:02:06+00:00",
        row={"trial_id": TRIAL, "p": 0.5, "decoy_count": 39,
             "beaten": 19, "tied": 1})
    return replace(record, **changes)


def test_each_record_comes_back_as_it_was_written(tmp_path: Path) -> None:
    instant_store.write_start(tmp_path, DATE, _start())
    instant_store.write_secret(tmp_path, DATE, TRIAL, NONCE)
    instant_store.write_send(tmp_path, DATE, _send())
    instant_store.write_result(tmp_path, DATE, _result(),
                               _send().commitment)
    assert instant_store.read_start_or_none(tmp_path, DATE, TRIAL) \
        == _start()
    assert instant_store.read_secret_or_none(tmp_path, DATE, TRIAL) \
        == NONCE
    assert instant_store.read_send_or_none(tmp_path, DATE, TRIAL) \
        == _send()
    assert instant_store.read_result_or_none(tmp_path, DATE, TRIAL) \
        == _result()


def test_a_trial_with_no_file_reads_as_none(tmp_path: Path) -> None:
    assert instant_store.read_start_or_none(tmp_path, DATE, TRIAL) is None
    assert instant_store.read_send_or_none(tmp_path, DATE, TRIAL) is None
    assert instant_store.read_secret_or_none(tmp_path, DATE, TRIAL) is None
    assert instant_store.read_result_or_none(tmp_path, DATE, TRIAL) is None


def test_the_files_are_in_the_directory_of_the_trial(
        tmp_path: Path) -> None:
    instant_store.write_start(tmp_path, DATE, _start())
    assert (tmp_path / "instant" / DATE / TRIAL / "start.json").is_file()


def test_one_trial_has_one_send(tmp_path: Path) -> None:
    instant_store.write_send(tmp_path, DATE, _send())
    before = (tmp_path / "instant" / DATE / TRIAL / "send.json").read_bytes()
    other = dict(WIRE, impressions=["a different send"])
    with pytest.raises(StoreError):
        instant_store.write_send(tmp_path, DATE, _send(
            record=other, send_digest=instant.send_digest(other)))
    after = (tmp_path / "instant" / DATE / TRIAL / "send.json").read_bytes()
    assert before == after


@pytest.mark.parametrize("write", ["start", "secret", "result"])
def test_each_other_file_is_written_one_time(tmp_path: Path,
                                             write: str) -> None:
    def once() -> None:
        if write == "start":
            instant_store.write_start(tmp_path, DATE, _start())
        elif write == "secret":
            instant_store.write_secret(tmp_path, DATE, TRIAL, NONCE)
        else:
            instant_store.write_result(tmp_path, DATE, _result(),
                                       _send().commitment)

    once()
    with pytest.raises(StoreError):
        once()


@pytest.mark.parametrize("date, trial_id", [
    ("2026-11-23", "../../../etc"), ("..", TRIAL), ("2026-11-23\n", TRIAL),
    ("2026-11-23", TRIAL.upper()), ("2026-11-23", TRIAL + "\n"),
    ("2026-11-23", TRIAL[:-1])])
def test_a_name_that_is_not_its_rule_names_no_file(
        tmp_path: Path, date: str, trial_id: str) -> None:
    with pytest.raises(StoreError):
        instant_store.read_send_or_none(tmp_path, date, trial_id)


@pytest.mark.parametrize("changes", [
    {"owner_kind": "operator"}, {"owner": "Not A Name"},
    {"started_at": "2026-11-23T10:00:00"}, {"trial_code": ""}])
def test_a_bad_start_is_refused(tmp_path: Path, changes: dict) -> None:
    with pytest.raises(StoreError):
        instant_store.write_start(tmp_path, DATE, _start(**changes))
    assert instant_store.list_dates(tmp_path) in ((), (DATE,))
    assert instant_store.read_start_or_none(tmp_path, DATE, TRIAL) is None


@pytest.mark.parametrize("changes", [
    {"send_digest": "00" * 32}, {"chain_link": "00" * 32},
    {"received_at": "now"}, {"beacon_round": 0}, {"pool_count": 0},
    {"notice": True}, {"record": ["not", "an", "object"]},
    {"chain_position": -1}, {"commitment": "short"}])
def test_a_bad_send_is_refused(tmp_path: Path, changes: dict) -> None:
    with pytest.raises(StoreError):
        instant_store.write_send(tmp_path, DATE, _send(**changes))
    assert instant_store.read_send_or_none(tmp_path, DATE, TRIAL) is None


def test_a_result_with_a_changed_nonce_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        instant_store.write_result(tmp_path, DATE, _result(nonce="ef" * 32),
                                   _send().commitment)
    assert instant_store.read_result_or_none(tmp_path, DATE, TRIAL) is None


@pytest.mark.parametrize("changes", [
    {"row": {"trial_id": "f" * 32}}, {"target_index": -1},
    {"randomness": "11"}, {"settled_at": ""}, {"target_proof": ("R", 4)}])
def test_a_bad_result_is_refused(tmp_path: Path, changes: dict) -> None:
    with pytest.raises(StoreError):
        instant_store.write_result(tmp_path, DATE, _result(**changes),
                                   _send().commitment)


def test_a_stored_send_that_changed_does_not_read(tmp_path: Path) -> None:
    instant_store.write_send(tmp_path, DATE, _send())
    path = tmp_path / "instant" / DATE / TRIAL / "send.json"
    path.write_text(path.read_text().replace("a tower", "a bridge"))
    with pytest.raises(StoreError):
        instant_store.read_send_or_none(tmp_path, DATE, TRIAL)


def test_a_file_of_a_different_trial_does_not_read(tmp_path: Path) -> None:
    instant_store.write_start(tmp_path, DATE, _start())
    source = tmp_path / "instant" / DATE / TRIAL / "start.json"
    other = "f" * 32
    target = tmp_path / "instant" / DATE / other
    target.mkdir(parents=True)
    (target / "start.json").write_bytes(source.read_bytes())
    with pytest.raises(StoreError):
        instant_store.read_start_or_none(tmp_path, DATE, other)


def test_a_file_with_one_more_field_does_not_read(tmp_path: Path) -> None:
    instant_store.write_start(tmp_path, DATE, _start())
    path = tmp_path / "instant" / DATE / TRIAL / "start.json"
    path.write_text(path.read_text().replace(
        '"owner":', '"extra": 1,\n  "owner":'))
    with pytest.raises(StoreError):
        instant_store.read_start_or_none(tmp_path, DATE, TRIAL)


def test_the_dates_and_the_trials_come_sorted(tmp_path: Path) -> None:
    assert instant_store.list_dates(tmp_path) == ()
    assert instant_store.list_trials(tmp_path, DATE) == ()
    second = "f" * 32
    instant_store.write_start(tmp_path, "2026-11-24",
                              _start(trial_id=second))
    instant_store.write_start(tmp_path, DATE, _start())
    instant_store.write_start(tmp_path, DATE, _start(trial_id=second))
    assert instant_store.list_dates(tmp_path) == (DATE, "2026-11-24")
    assert instant_store.list_trials(tmp_path, DATE) == (TRIAL, second)


def test_the_write_lock_holds_one_writer_at_a_time(tmp_path: Path) -> None:
    inside = []
    most = []

    def writer() -> None:
        with instant_store.instant_write_lock(tmp_path):
            inside.append(1)
            most.append(len(inside))
            threading.Event().wait(0.01)
            inside.pop()

    threads = [threading.Thread(target=writer) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most == [1] * 6
    assert instant_store.list_dates(tmp_path) == ()
