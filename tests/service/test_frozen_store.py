"""Invariant: the code of today reads each frozen store (spec SC1).

Spec: docs/specs/store-compatibility.md. Each directory
fixtures/frozen-store-* is a trial store that an earlier release
wrote. These tests prove four things about each one: its bytes are the
committed bytes, each stored file reads, a rescore gives each stored
trial row again byte-for-byte, and no reader, rescore, index build, or
snapshot build changes a stored file.

A test that fails here is a stop. The repair is in the code of the
change, not in the frozen store: do not edit a frozen file, and do not
make a frozen store again. When a release adds a record type, add a new
frozen store adjacent to the earlier ones (tools/freeze_store.py).
"""

import datetime
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from frozen_fixture import (MANIFEST_NAME, enumerated, expected_labels,
                            frozen_stores, holds_instant, manifest_of,
                            read_lineage, read_manifest, read_walk,
                            replay_providers)

from pipeline.config import load_scoring_config
from service import (digests, index, instant_book, instant_store, public,
                     rollup, scoring, settle, sketches, store)
from service.config import ServiceConfig
from service.day import build_day_scores, rescore_days

NOW = datetime.datetime(2027, 1, 1, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(params=frozen_stores(), ids=lambda path: path.name)
def frozen(request) -> Path:
    return request.param


@pytest.fixture
def world(frozen, tmp_path, monkeypatch) -> SimpleNamespace:
    """A copy of one frozen world, with the copy as the working
    directory: the stored paths are relative, as in a deployment."""
    copy = tmp_path / "world"
    shutil.copytree(frozen / "world", copy)
    monkeypatch.chdir(copy)
    lineage = read_lineage(frozen)
    # The world has no network, thus its vp1 days name the fake chain.
    monkeypatch.setattr(public, "PUBLIC_CHAINS",
                        (*public.PUBLIC_CHAINS, "fake"))
    return SimpleNamespace(
        frozen=frozen, lineage=lineage, out=tmp_path / "out",
        root=Path(lineage["store_root"]), data=Path(lineage["data_root"]),
        providers=replay_providers(frozen),
        config=ServiceConfig(
            player="ade", scoring_config=sorted(lineage["configs"])[0],
            data_root=lineage["data_root"],
            store_root=lineage["store_root"], port=8399))


def _scored_days(root: Path) -> list[store.DayRecord]:
    records = [store.read_day_record(root, day)
               for day in store.list_days(root)]
    return [record for record in records
            if record.status in ("closed", "revealed")]


def _rescore_each_day(world: SimpleNamespace) -> dict[str, int]:
    """Rescore each day that has trial rows with its pinned config, then
    with each config of an adjacent row. The output sums the counts."""
    by_prefix = {values["scoring_config_hash"][:8]: path
                 for path, values in world.lineage["configs"].items()}
    total = {"compared": 0, "equal": 0, "written": 0, "pinned_rows": 0,
             "adjacent_days": 0}
    for record in _scored_days(world.root):
        trials = store.day_dir(world.root, record.day) / "trials"
        names = sorted(path.name for path in trials.iterdir())
        pinned_rows = [name for name in names if name.count(".") == 1]
        prefixes = {name.split(".")[1] for name in names
                    if name.count(".") == 2}
        paths = [record.scoring_config_path,
                 *(by_prefix[prefix] for prefix in sorted(prefixes))]
        for path in paths:
            counts = rescore_days(
                world.config, config_path=path, from_date=record.day,
                to_date=record.day, providers=world.providers)
            for key in ("compared", "equal", "written"):
                total[key] += counts[key]
        total["pinned_rows"] += len(pinned_rows)
        total["adjacent_days"] += len(prefixes)
    return total


def test_the_frozen_bytes_are_the_committed_bytes(frozen) -> None:
    """Do not make this directory again and do not edit a file in it.
    A new record type gets a new frozen store adjacent to this one."""
    assert manifest_of(frozen) == read_manifest(frozen / MANIFEST_NAME)


def test_each_stored_file_reads(world) -> None:
    counts = read_walk(world.root)
    # The frozen store holds each record type that had a reader when the
    # tool made it, thus no reader goes without a stored record.
    assert sorted(counts) == expected_labels(world.frozen)
    found = enumerated(world.root)
    assert {label: counts[label] for label in found} == found
    assert len(store.list_rollover_runs(world.root, 100)) \
        == counts["rollover run"]


def test_the_lineage_stands(world) -> None:
    known = set()
    for path, values in world.lineage["configs"].items():
        wired = scoring.wire_for_close(load_scoring_config(Path(path)), path,
                                       world.data, world.providers)
        assert wired.scoring_hash == values["scoring_config_hash"]
        assert wired.commonness_hash == values["commonness_config_hash"]
        assert wired.preparation_version_id \
            == values["preparation_version_id"]
        known.add(wired.scoring_hash)
    for day in store.list_days(world.root):
        assert store.read_day_record(world.root, day).scoring_config_hash \
            in known
    for _date, send in public.instant_sends(world.root):
        assert send.scoring_config_hash in known


def test_a_rescore_gives_each_stored_row_again(world) -> None:
    total = _rescore_each_day(world)
    # The counts are necessary: with a hash that moved, a rescore compares
    # nothing and writes new rows adjacent, and raises no error.
    assert total["pinned_rows"] > 0 and total["adjacent_days"] > 0
    assert total["compared"] == total["pinned_rows"]
    assert total["equal"] == total["pinned_rows"]
    assert total["written"] == 0


def _rescore_the_instant_trials(world: SimpleNamespace) -> dict[str, int]:
    """Score each stored instant send again with each config of the
    lineage, and sum the counts (spec IM1 section 17, I4)."""
    total = {"compared": 0, "equal": 0, "other": 0}
    for path in world.lineage["configs"]:
        wired = scoring.wire_for_close(load_scoring_config(Path(path)), path,
                                       world.data, world.providers)
        counts = settle.rescore_compare(world.root, wired)
        for key in total:
            total[key] += counts[key]
    return total


def test_a_rescore_gives_each_stored_instant_row_again(world) -> None:
    """The stored instant send and its pinned config give the stored
    trial row byte for byte (spec IM1 section 17)."""
    if not holds_instant(world.frozen):
        pytest.skip("this frozen store is from before the instant trial")
    results = sum(
        1 for date in instant_store.list_dates(world.root)
        for trial_id in instant_store.list_trials(world.root, date)
        if instant_store.read_result_or_none(world.root, date, trial_id)
        is not None)
    total = _rescore_the_instant_trials(world)
    # The counts are necessary: with a hash that moved, each send is a
    # send of a different config, and the walk compares nothing.
    assert results > 0
    assert total["compared"] == results
    assert total["equal"] == results


def test_the_chain_of_the_stored_instant_sends_stands(world) -> None:
    """The book of today reads each stored instant trial and checks the
    chain of the sends (spec IM1 section 11)."""
    if not holds_instant(world.frozen):
        pytest.skip("this frozen store is from before the instant trial")
    book = instant_book.build_book(world.root)
    sends = public.instant_sends(world.root)
    head = book.head()
    assert head is not None and head.position == len(sends) - 1
    assert head.chain_link == sends[-1][1].chain_link
    # One send waits for its pulse, and one start has no send.
    assert len(book.pending()) == 1


def test_no_stored_file_changes(world) -> None:
    before = manifest_of(world.root)
    read_walk(world.root)
    _rescore_each_day(world)
    _rescore_the_instant_trials(world)
    instant_book.build_book(world.root)
    build_day_scores(world.config, providers=world.providers)
    rollup.assemble(world.config)
    target = world.out / "index.sqlite"
    index.build(world.root, target)
    assert index.verify(world.root, target) == []
    public.build(world.root, world.data, world.out / "public",
                 snapshot_date=NOW.date().isoformat(),
                 built_at=NOW.isoformat(), version="frozen-store-test")
    assert public.check(world.out / "public") == []
    assert manifest_of(world.root) == before


def test_each_stored_send_gives_its_sketch(world) -> None:
    """Spec SS1 section 5: the sketch reader of today reads each send
    of a frozen store, gives the strokes alone, and writes no file."""
    before = manifest_of(world.root)
    count = 0
    for day in store.list_days(world.root):
        for name in store.list_submissions(world.root, day):
            stored = store.read_json_or_none(
                store.submission_path(world.root, day, name))
            sketch = sketches.sketch_of(stored["record"])
            assert len(sketch) == len(stored["record"]["canvas_strokes"])
            assert {key for stroke in sketch for key in stroke} \
                <= {"points", "color"}
            count += 1
    assert count > 0
    assert manifest_of(world.root) == before


def test_the_frozen_store_holds_no_deployment_secret(frozen) -> None:
    names = [path.relative_to(frozen).as_posix()
             for path in frozen.rglob("*")]
    assert not [name for name in names
                if "pool-keys" in name or name.endswith(".key")]


def test_a_stored_password_digest_reads(world) -> None:
    fixture = world.lineage["fixture_only"]
    digester = digests.Argon2Digester(
        pepper=fixture["pepper"].encode("utf-8"))
    credential = store.read_credential_or_none(world.root, "ade")
    assert credential is not None
    assert digester.agrees(fixture["password"], credential.password_digest)
    assert not digester.agrees("a different password",
                               credential.password_digest)
