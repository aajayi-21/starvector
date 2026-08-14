"""Unit and integration: the day lifecycle (spec S1 section 6).

Open, close, reveal, and status against the warm offline fixture -
the refusals, the commitment, the seeded pick, the empty day, and
the repeatable close.
"""

import pytest

from pathlib import Path

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from core.canonical import sha256_hex
from service import store
from service.day import (close_day, day_commitment, day_status_lines,
                         open_day, pick_target, reveal_day)

DAY = "2026-08-12"


def _open(fixture, date=DAY):
    return open_day(fixture["service_config"], date=date,
                    clock=lambda: FIXED_CLOCK,
                    pick_seed="a" * 32, secret="b" * 64)


def _submit(fixture, day=DAY, player="ade", record=None):
    store.write_once_json(
        store.submission_path(fixture["store"], day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK,
         "record": record or mixed_wire_record()})


def test_open_writes_the_committed_day(tmp_path) -> None:
    import re

    fixture = build_service_fixture(tmp_path)
    record = _open(fixture)
    assert record.status == "open"
    assert re.match(r"^[A-Z0-9]{6}$", record.trial_code)
    assert record.target_id in fixture["image_ids"]
    assert record.commitment == sha256_hex(
        f"{record.target_id}:{'b' * 64}")
    stored = store.read_day_record(fixture["store"], DAY)
    assert stored == record
    with pytest.raises(store.StoreError, match="refuses a rewrite"):
        _open(fixture)


def test_the_pick_is_seeded_and_covers_the_pool(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    ids = fixture["image_ids"]
    first = pick_target(ids, DAY, "a" * 32)
    assert first == pick_target(ids, DAY, "a" * 32)
    assert first in ids
    picks = {pick_target(ids, DAY, f"{seed:032x}") for seed in range(64)}
    assert len(picks) > 8
    assert day_commitment("t", "s") == sha256_hex("t:s")


def test_open_with_cold_tables_names_the_build_command(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    # A cold lineage: point the day commands at an empty data root.
    cold = fixture["service_config"].__class__(
        player="ade", scoring_config=fixture["scoring_config_path"],
        data_root=str(tmp_path / "cold-data"),
        store_root=str(tmp_path / "cold-store"), port=8399)
    with pytest.raises(Exception, match="cannot read"):
        open_day(cold, date=DAY)
    # A pool that loads, with no tables: strip the commonness artifacts.
    import shutil
    shutil.rmtree(fixture["data"] / "commonness")
    with pytest.raises(ValueError, match="validation.v2 --config"):
        _open(fixture)


def test_close_and_reveal_refuse_out_of_sequence(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    with pytest.raises(store.StoreError, match="no day"):
        close_day(fixture["service_config"])
    _open(fixture)
    with pytest.raises(store.StoreError, match="needs 'closed'"):
        reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    with pytest.raises(store.StoreError, match="needs 'open'"):
        close_day(fixture["service_config"],
                  providers=fixture["providers"])
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    assert store.read_day_record(fixture["store"], DAY).status == "revealed"


def test_an_empty_day_closes_to_an_empty_trial_set(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    count = close_day(fixture["service_config"],
                      providers=fixture["providers"],
                      clock=lambda: FIXED_CLOCK)
    assert count == 0
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_close_scores_the_stored_submission(tmp_path) -> None:
    from pipeline.config import load_scoring_config
    from pathlib import Path
    from service.scoring import (score_stored_submission, trial_row_value,
                                 wire_for_close)

    fixture = build_service_fixture(tmp_path)
    day_record = _open(fixture)
    _submit(fixture)
    count = close_day(fixture["service_config"],
                      providers=fixture["providers"],
                      clock=lambda: FIXED_CLOCK)
    assert count == 1
    row = store.read_json_or_none(
        store.trial_row_path(fixture["store"], DAY, "ade"))
    assert row is not None
    assert 0.0 <= row["p"] <= 1.0
    assert row["decoy_count"] == len(fixture["image_ids"]) - 1
    assert row["target_rank"] == row["decoy_count"] - row["beaten"] \
        - row["tied"] + 1
    # The row equals a plain recomputation through the same functions.
    config = load_scoring_config(Path(fixture["scoring_config_path"]))
    wired = wire_for_close(config, fixture["scoring_config_path"],
                           fixture["data"], fixture["providers"])
    trial, report = score_stored_submission(
        mixed_wire_record(), day_record.target_id, wired)
    assert trial_row_value(DAY, "ade", "f" * 32, trial, report,
                           wired) == row


def test_close_is_repeatable_after_a_stop(tmp_path) -> None:
    from pipeline.config import load_scoring_config
    from pathlib import Path
    from service.scoring import (score_stored_submission, trial_row_value,
                                 wire_for_close)

    fixture = build_service_fixture(tmp_path)
    day_record = _open(fixture)
    _submit(fixture)
    # As if an earlier close wrote the row and stopped before the
    # status flip: the re-run keeps the equal row and completes.
    config = load_scoring_config(Path(fixture["scoring_config_path"]))
    wired = wire_for_close(config, fixture["scoring_config_path"],
                           fixture["data"], fixture["providers"])
    trial, report = score_stored_submission(
        mixed_wire_record(), day_record.target_id, wired)
    store.write_once_json(
        store.trial_row_path(fixture["store"], DAY, "ade"),
        trial_row_value(DAY, "ade", "f" * 32, trial, report, wired))
    assert close_day(fixture["service_config"],
                     providers=fixture["providers"],
                     clock=lambda: FIXED_CLOCK) == 1
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_a_differing_stored_row_stops_the_close(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    _submit(fixture)
    store.write_once_json(
        store.trial_row_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "tampered": True})
    with pytest.raises(store.StoreError, match="differs"):
        close_day(fixture["service_config"],
                  providers=fixture["providers"])


def test_migrate_backfills_a_legacy_day_record(tmp_path) -> None:
    import json
    import re

    from service.day import migrate_store

    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    path = store.day_record_path(fixture["store"], DAY)
    raw = json.loads(path.read_text())
    del raw["trial_code"]
    path.write_text(json.dumps(raw))
    with pytest.raises(store.StoreError, match="migrate"):
        store.read_day_record(fixture["store"], DAY)
    counts = migrate_store(fixture["service_config"])
    assert counts == {"days": 1, "backfilled": 1}
    record = store.read_day_record(fixture["store"], DAY)
    assert re.match(r"^[A-Z0-9]{6}$", record.trial_code)
    # Repeatable: a complete record stays untouched.
    assert migrate_store(fixture["service_config"]) \
        == {"days": 1, "backfilled": 0}
    assert store.read_day_record(fixture["store"], DAY) == record


def test_status_prints_no_score_and_no_target(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    record = _open(fixture)
    _submit(fixture)
    lines = day_status_lines(fixture["service_config"])
    text = "\n".join(lines)
    assert f"day {DAY}" in text
    assert f"trial code {record.trial_code}" in text
    assert "status open" in text
    assert "submission stored: yes" in text
    assert record.target_id not in text
    assert record.secret not in text
    assert '"p"' not in text


def test_the_resident_close_equals_the_fresh_wire(tmp_path) -> None:
    # P5 R1: the row a resident-context close stores equals the row
    # a CLI-style wire from the day record's pinned path computes -
    # byte for byte, in one world.
    from fastapi.testclient import TestClient

    from pipeline.config import load_scoring_config
    from service import scoring as service_scoring
    from service.server import create_app

    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date="2026-08-13",
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], "2026-08-13", "ade"),
        {"day": "2026-08-13", "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})

    client = TestClient(create_app(fixture["service_config"]))
    answer = client.post("/api/day/close")
    assert answer.status_code == 200
    stored_row = store.trial_row_path(
        fixture["store"], "2026-08-13", "ade").read_text(encoding="utf-8")

    record = store.read_day_record(fixture["store"], "2026-08-13")
    config = load_scoring_config(Path(record.scoring_config_path))
    fresh = service_scoring.wire_for_close(
        config, record.scoring_config_path,
        Path(fixture["service_config"].data_root))
    trial, report = service_scoring.score_stored_submission(
        mixed_wire_record(), record.target_id, fresh)
    value = service_scoring.trial_row_value(
        "2026-08-13", "ade", "f" * 32, trial, report, fresh)
    from core.canonical import canonical_json_pretty
    assert canonical_json_pretty(value) + "\n" == stored_row


def test_a_mismatched_wired_context_refuses(tmp_path) -> None:
    # The day record's hash guard runs on a handed-in context too: a
    # context wired from a different config stops the close.
    import json as json_module

    from service import scoring as service_scoring

    fixture = build_service_fixture(tmp_path)
    other_path = tmp_path / "other-scoring.json"
    document = json_module.loads(
        Path(fixture["scoring_config_path"]).read_text())
    document["fusion"]["weights"] = {"outline": 2.0, "element": 1.0}
    other_path.write_text(json_module.dumps(document, indent=2) + "\n",
                          encoding="utf-8")
    open_day(fixture["service_config"], date="2026-08-13",
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    from pipeline.config import load_scoring_config
    other = load_scoring_config(other_path)
    mismatched = service_scoring.wire_for_close(
        other, str(other_path), Path(fixture["service_config"].data_root),
        fixture["providers"])
    with pytest.raises(store.StoreError, match="hash moved"):
        close_day(fixture["service_config"], wired=mismatched,
                  clock=lambda: FIXED_CLOCK)


def test_the_close_prewarm_batches_across_players(tmp_path) -> None:
    # P5 R7: one batched encode across the day's submissions before
    # the loop - the first sketch batch holds each drawing.
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date="2026-08-13",
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    for player in ("ade", "kit"):
        store.write_once_json(
            store.submission_path(fixture["store"], "2026-08-13", player),
            {"day": "2026-08-13", "player": player, "trial_id": "f" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})

    class _Counting:
        def __init__(self, inner):
            self._inner = inner
            self.batches: list[int] = []

        @property
        def config_hash(self):
            return self._inner.config_hash

        def encode_images(self, images):
            self.batches.append(len(images))
            return self._inner.encode_images(images)

        def encode_texts(self, texts):
            self.batches.append(len(texts))
            return self._inner.encode_texts(texts)

    providers = dict(fixture["providers"])
    sketch = _Counting(providers["sketch_encoder"])
    text = _Counting(providers["text_encoder"])
    providers["sketch_encoder"] = sketch
    providers["text_encoder"] = text
    count = close_day(fixture["service_config"], providers=providers,
                      clock=lambda: FIXED_CLOCK)
    assert count == 2
    # Two players, one drawing each: the prewarm batch holds the
    # two drawings in one POST group before the one-at-a-time loop.
    assert sketch.batches[0] == 2
    assert text.batches[0] > 2
