"""Integration: the rollups and the two boards (spec M1 B7).

The additive path and a full assembly must agree byte for byte, a
configuration change must fork the cache and keep the first set
unmoved, and the store must not move around a reveal.
"""

import json
from pathlib import Path

import pytest

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from core.types import TrialCounts
from service import day_scores, rollup, store
from service.day import close_day, open_day, reveal_day

DAYS = ("2026-08-10", "2026-08-11", "2026-08-12")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _played_world(tmp_path, *, players=("ade", "bru"), days=DAYS):
    """A world with some revealed days, played by some names."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    for index, day in enumerate(days):
        open_day(config, date=day, clock=lambda: FIXED_CLOCK,
                 pick_seed=chr(ord("a") + index) * 32, secret="b" * 64)
        for position, player in enumerate(players):
            store.write_once_json(
                store.submission_path(fixture["store"], day, player),
                {"day": day, "player": player,
                 "trial_id": f"{index}{position}" * 16,
                 "received_at": FIXED_CLOCK,
                 "record": mixed_wire_record()})
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)
    return fixture


def _hash_of(fixture) -> str:
    root = Path(fixture["service_config"].store_root)
    return store.read_day_record(root, DAYS[-1]).scoring_config_hash


def test_the_pair_field_set_is_strict(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    scoring_hash = _hash_of(fixture)
    path = rollup.skill_pair_path(data_root, "ade", scoring_hash)
    stored = json.loads(path.read_text())
    assert set(stored) == set(rollup._PAIR_FIELDS)
    assert stored["n"] == len(DAYS)
    assert stored["days"] == list(DAYS)
    assert stored["player"] == "ade"


def test_the_additive_path_agrees_with_a_full_assembly(tmp_path) -> None:
    """The reveal folds one day at a time and assemble builds from
    nothing. The two must land on equal bytes, which is what makes
    the repair path one a reader can trust."""
    fixture = _played_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    incremental = _snapshot(data_root)
    rollup.assemble(fixture["service_config"])
    assert _snapshot(data_root) == incremental


def test_a_second_rollup_writes_equal_bytes(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    before = _snapshot(data_root)
    record = store.read_day_record(Path(config.store_root), DAYS[-1])
    rollup.roll_up_day(config, record)
    rollup.roll_up_day(config, record)
    assert _snapshot(data_root) == before


def test_the_store_is_unmoved_around_a_reveal(tmp_path) -> None:
    """The rollup writes into the data root and not the store."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAYS[0], clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAYS[0], "ade"),
        {"day": DAYS[0], "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    before = _snapshot(Path(config.store_root))
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    after = _snapshot(Path(config.store_root))
    # The reveal moves the day record and nothing else.
    changed = {name for name in after if after[name] != before.get(name)}
    assert changed == {str(Path("days") / DAYS[0] / "day.json")}


def test_a_hash_with_no_stored_row_writes_nothing(tmp_path) -> None:
    """An assembly at a configuration with no rows writes no board.

    An empty board can claim a configuration ran when it did not,
    which is worse than no file.
    """
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    first = _snapshot(data_root)
    other = "9" * 64
    rollup.assemble(config, scoring_hash=other)
    assert _snapshot(data_root) == first
    assert not rollup.skill_board_path(data_root, other).is_file()


def test_a_rescore_forks_the_cache_and_leaves_the_first_unmoved(
        tmp_path) -> None:
    """The adjacent rescore rows build a full parallel board.

    This is the shape spec S1 R8 writes for a rescore: the rows of
    the other configuration sit adjacent to the canonical ones,
    thus a board for each configuration stands and no board moves.
    """
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    root = Path(config.store_root)
    data_root = Path(config.data_root)
    first_hash = _hash_of(fixture)
    other = "9" * 64
    # Hand-written adjacent rows, in the manner a rescore writes
    # them, with a moved trial score so the two boards are
    # different.
    for day in DAYS:
        for player in ("ade", "bru"):
            canonical = json.loads(store.trial_row_path(
                root, day, player).read_text())
            moved = {**canonical, "p": min(0.99, canonical["p"] * 0.5),
                     "beaten": canonical["beaten"] // 2}
            store.write_once_json(
                store.trial_row_path(root, day, player, other[:8]), moved)
        # A rescore writes the day ranks of its configuration (spec AG1
        # section 5). This one is hand-written, in the same manner.
        index = json.loads(day_scores.index_path(
            data_root, day, first_hash).read_text())
        target = day_scores.index_path(data_root, day, other)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**index,
                                      "scoring_config_hash": other}))
    first = _snapshot(data_root)
    rollup.assemble(config, scoring_hash=other)
    after = _snapshot(data_root)
    for name, payload in first.items():
        assert after[name] == payload, f"{name} moved"
    parallel = rollup.skill_board_path(data_root, other)
    assert parallel.is_file()
    assert json.loads(parallel.read_text())["player_count"] == 2
    assert first_hash[:8] != other[:8]
    board = json.loads(rollup.leaderboard_path(
        data_root, DAYS[-1], other).read_text())
    assert board["row_count"] == 2


def test_a_truncated_key_collision_refuses(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    scoring_hash = _hash_of(fixture)
    path = rollup.skill_pair_path(data_root, "ade", scoring_hash)
    stored = json.loads(path.read_text())
    stored["scoring_config_hash"] = "0" * 64
    path.write_text(json.dumps(stored))
    with pytest.raises(rollup.RollupError, match="collision"):
        rollup.read_pair(
            path, scoring_hash=scoring_hash,
            preparation_version_id=stored["preparation_version_id"])


def test_the_daily_board_ranks_each_player(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    board = json.loads(rollup.leaderboard_path(
        data_root, DAYS[-1], _hash_of(fixture)).read_text())
    assert board["row_count"] == 2
    assert board["day"] == DAYS[-1]
    ranks = [row["rank"] for row in board["rows"]]
    scores = [row["p"] for row in board["rows"]]
    assert ranks == sorted(ranks)
    assert scores == sorted(scores, reverse=True)
    assert {row["player"] for row in board["rows"]} == {"ade", "bru"}


def test_players_with_an_equal_score_share_a_rank() -> None:
    record = store.DayRecord(
        day=DAYS[0], trial_code="R7K2QX", target_id="t" * 64,
        pick_seed="s" * 32, secret="x" * 64, commitment="c" * 64,
        scoring_config_path="x.json", scoring_config_hash="h" * 64,
        preparation_version_id="p" * 64, status="revealed",
        opened_at=FIXED_CLOCK, closed_at=FIXED_CLOCK,
        revealed_at=FIXED_CLOCK)
    rows = [("cyd", {"p": 0.5, "decoy_count": 9, "target_rank": 5}),
            ("ade", {"p": 0.9, "decoy_count": 9, "target_rank": 1}),
            ("bru", {"p": 0.9, "decoy_count": 9, "target_rank": 1})]
    board = rollup.daily_board_value(record, rows)
    assert [(row["player"], row["rank"]) for row in board["rows"]] \
        == [("ade", 1), ("bru", 1), ("cyd", 3)]


def test_the_board_keeps_the_two_ranks_apart() -> None:
    """The board position and the target rank count different things.

    A board that carries the position alone makes the reader
    answer the decoy rank with it, which is what the reveal card
    prints with the decoy count.
    """
    record = store.DayRecord(
        day=DAYS[0], trial_code="R7K2QX", target_id="t" * 64,
        pick_seed="s" * 32, secret="x" * 64, commitment="c" * 64,
        scoring_config_path="x.json", scoring_config_hash="h" * 64,
        preparation_version_id="p" * 64, status="revealed",
        opened_at=FIXED_CLOCK, closed_at=FIXED_CLOCK,
        revealed_at=FIXED_CLOCK)
    rows = [("ade", {"p": 0.9, "decoy_count": 119, "target_rank": 12}),
            ("bru", {"p": 0.4, "decoy_count": 119, "target_rank": 72})]
    board = rollup.daily_board_value(record, rows)
    assert [(row["rank"], row["target_rank"]) for row in board["rows"]] \
        == [(1, 12), (2, 72)]
    assert rollup.board_is_current(board)


def test_a_board_from_before_the_target_rank_is_not_current() -> None:
    """The reader finds a stale board and assembles the rows again."""
    stale = {"rows": [{"player": "ade", "p": 0.9, "decoy_count": 119,
                       "rank": 1}]}
    assert not rollup.board_is_current(stale)
    assert rollup.board_is_current({"rows": []})


def test_the_skill_board_gates_itself_on_a_new_deployment(
        tmp_path) -> None:
    """Three days is below the trial floor, thus nobody is eligible
    and the board says so with no operator step."""
    fixture = _played_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    board = json.loads(rollup.skill_board_path(
        data_root, _hash_of(fixture)).read_text())
    assert board["active"] is False
    assert board["eligible_count"] == 0
    assert board["provisional"] is True
    assert board["eligibility_floor"] == 30
    assert board["fit_floor"] == 30
    assert board["rows"] == []
    assert board["population"] is None


def _synthetic_pairs(count: int, trials: int, scoring_hash: str,
                     preparation_version_id: str, *, spread: int = 40,
                     first: int = 0) -> list[dict]:
    """Pairs with no store behind them, for the board arithmetic."""
    import numpy as np

    rng = np.random.default_rng(5)
    pairs = []
    for index in range(count):
        n = trials + int(rng.integers(0, spread))
        pairs.append({
            "player": f"player-{first + index:03d}",
            "scoring_config_hash": scoring_hash,
            "preparation_version_id": preparation_version_id,
            "format": rollup.ROLLUP_FORMAT, "n": n,
            "s_statistic": float(rng.gamma(n, 1.0)),
            "t_statistic": float(rng.gamma(n, 1.0)),
            "days": [], "updated_at": FIXED_CLOCK})
    return pairs


def test_the_board_turns_on_at_one_eligible_player() -> None:
    pairs = _synthetic_pairs(1, 30, "h" * 64, "p" * 64)
    board = rollup.skill_board_value(
        pairs, scoring_hash="h" * 64, preparation_version_id="p" * 64,
        day=DAYS[0], seed=1, created_at=FIXED_CLOCK)
    assert board["active"] is True
    assert board["eligible_count"] == 1
    assert board["provisional"] is True
    assert len(board["rows"]) == 1
    # One player gives no variation and no monitor.
    assert board["variation"] is None
    assert board["population"] is not None


def test_a_full_population_reports_each_number() -> None:
    pairs = _synthetic_pairs(60, 40, "h" * 64, "p" * 64)
    board = rollup.skill_board_value(
        pairs, scoring_hash="h" * 64, preparation_version_id="p" * 64,
        day=DAYS[0], seed=7, created_at=FIXED_CLOCK,
        day_ranks=[(index + 0.5) / 50 for index in range(50)])
    assert board["active"] is True
    assert board["provisional"] is False
    assert board["format"] == rollup.ROLLUP_FORMAT
    assert board["eligible_count"] == 60
    assert len(board["rows"]) == 60
    assert board["variation"]["dof"] == 59
    assert board["day_check"]["day_count"] == 50
    assert board["day_check"]["significance"] > 0.5
    assert "baseline" not in board
    for row in board["rows"]:
        assert row["hit_number"] > 0
    assert board["discovery"]["tested"] == 60
    assert board["baseline_band"], "the funnel wants its band"
    # Ranked by the posterior expected rank, ascending.
    ranks = [row["expected_rank"] for row in board["rows"]]
    assert ranks == sorted(ranks)
    for row in board["rows"]:
        assert row["rank_low"] <= row["expected_rank"] <= row["rank_high"]


def test_each_player_holds_a_row_and_the_eligible_hold_a_rank() -> None:
    """Ruling 17 of 2026-08-16.

    A player below the trial floor keeps their skill number and
    their evidence value, which read their own pair alone. They
    hold no rank: the fit and the rank simulation read the eligible
    set, thus to give one of them a rank moves the rank of each
    other player. The fields are None and not a number a reader has
    to know to discard.
    """
    pairs = (_synthetic_pairs(40, 40, "h" * 64, "p" * 64)
             + _synthetic_pairs(12, 5, "h" * 64, "p" * 64,
                                spread=10, first=100))
    board = rollup.skill_board_value(
        pairs, scoring_hash="h" * 64, preparation_version_id="p" * 64,
        day=DAYS[0], seed=7, created_at=FIXED_CLOCK)
    assert board["player_count"] == 52
    assert board["eligible_count"] == 40
    assert len(board["rows"]) == 52
    ranked = [row for row in board["rows"] if row["eligible"]]
    rest = [row for row in board["rows"] if not row["eligible"]]
    assert len(ranked) == 40 and len(rest) == 12
    # The eligible run leads, ordered by the expected rank.
    assert board["rows"][:40] == ranked
    assert [row["expected_rank"] for row in ranked] \
        == sorted(row["expected_rank"] for row in ranked)
    for row in ranked:
        assert row["n"] >= board["eligibility_floor"]
        assert row["rank_low"] <= row["expected_rank"] <= row["rank_high"]
        assert row["shrunk"] is not None
    for row in rest:
        assert row["n"] < board["eligibility_floor"]
        assert row["expected_rank"] is None
        assert row["rank_low"] is None and row["rank_high"] is None
        assert row["shrunk"] is None
        # The chart plots them, thus these two travel.
        assert row["theta"] > 0
        assert row["v"] > 0
    # The ineligible run reads by trial count down.
    assert [row["n"] for row in rest] \
        == sorted((row["n"] for row in rest), reverse=True)
    # One population definition: the claim tests the eligible set.
    assert board["discovery"]["tested"] == 40
    assert board["variation"]["dof"] == 39
    # The band reaches each plotted player. A ladder that stops at
    # the floor leaves the low-trial dots with nothing behind them,
    # and those dots are what the chart exists for.
    band = board["baseline_band"]
    counts = [row["n"] for row in board["rows"]]
    assert min(point["n"] for point in band) <= min(counts)
    assert max(point["n"] for point in band) >= max(counts)
    # It gets narrower as the trial count rises.
    widths = [point["high"] - point["low"] for point in band]
    assert widths == sorted(widths, reverse=True)


def test_the_board_rows_hold_one_field_set() -> None:
    """A nullable field is a field. A screen reads one shape."""
    pairs = (_synthetic_pairs(2, 40, "h" * 64, "p" * 64)
             + _synthetic_pairs(2, 5, "h" * 64, "p" * 64,
                                spread=10, first=100))
    board = rollup.skill_board_value(
        pairs, scoring_hash="h" * 64, preparation_version_id="p" * 64,
        day=DAYS[0], seed=7, created_at=FIXED_CLOCK)
    shapes = {tuple(sorted(row)) for row in board["rows"]}
    assert len(shapes) == 1


def test_the_recomputed_floor_stays_a_report(tmp_path) -> None:
    """Ruling of 2026-08-16: membership is 30 and stays there.

    The recomputed value rides along as a report. Below the
    publishable player count it is not calculated at all.
    """
    pairs = _synthetic_pairs(60, 40, "h" * 64, "p" * 64)
    board = rollup.skill_board_value(
        pairs, scoring_hash="h" * 64, preparation_version_id="p" * 64,
        day=DAYS[0], seed=7, created_at=FIXED_CLOCK)
    assert board["eligibility_floor"] == 30
    assert board["recomputed_floor"] is None
    assert board["eligible_count"] == 60


def test_a_player_with_a_perfect_record_is_counted(tmp_path) -> None:
    """Spec AG1 section 3: the corrected score gives each history a value.

    A perfect run had S of zero, no skill number, and a "degenerate"
    mark that kept the player off this board. The corrected score of a
    first position is below one, thus S is positive and the player counts
    like each other player. One trial is below the floor, thus the
    board stays not active and lists no row, as for each player.
    """
    fixture = _played_world(tmp_path, players=("ade",), days=DAYS[:1])
    config = fixture["service_config"]
    root = Path(config.store_root)
    scoring_hash = store.read_day_record(root, DAYS[0]).scoring_config_hash
    row_path = store.trial_row_path(root, DAYS[0], "ade")
    row = json.loads(row_path.read_text())
    row.update(p=1.0, beaten=row["decoy_count"], tied=0, target_rank=1)
    row_path.write_text(json.dumps(row))

    counts = rollup.assemble(config, scoring_hash=scoring_hash)
    assert counts["players"] == 1
    pair = json.loads(rollup.skill_pair_path(
        Path(config.data_root), "ade", scoring_hash).read_text())
    assert pair["s_statistic"] > 0.0
    assert pair["t_statistic"] > pair["s_statistic"]
    board = json.loads(rollup.skill_board_path(
        Path(config.data_root), scoring_hash).read_text())
    assert board["player_count"] == 1
    assert board["active"] is False
    assert "degenerate_count" not in board


def test_the_fold_is_repeatable_for_one_day() -> None:
    counts = TrialCounts(beaten=900, tied=2, decoy_count=1392)
    base = dict(player="ade", day=DAYS[0], counts=counts,
                scoring_hash="h" * 64, preparation_version_id="p" * 64,
                updated_at=FIXED_CLOCK)
    once = rollup.fold_day(None, **base)
    twice = rollup.fold_day(once, **base)
    assert once == twice
    assert once["n"] == 1
    assert once["format"] == rollup.ROLLUP_FORMAT
    other = TrialCounts(beaten=100, tied=0, decoy_count=1392)
    later = rollup.fold_day(once, **{**base, "day": DAYS[1],
                                     "counts": other})
    first_s, first_t = rollup.aggregate.trial_terms(counts)
    second_s, second_t = rollup.aggregate.trial_terms(other)
    assert later["n"] == 2
    assert later["s_statistic"] == pytest.approx(first_s + second_s)
    assert later["t_statistic"] == pytest.approx(first_t + second_t)
    assert later["days"] == [DAYS[0], DAYS[1]]


def test_a_row_with_bad_counts_stops_the_fold() -> None:
    with pytest.raises(rollup.RollupError, match="beaten"):
        rollup.counts_of({"beaten": 3.0, "tied": 0, "decoy_count": 10})
    with pytest.raises(rollup.RollupError, match="decoy_count"):
        rollup.counts_of({"beaten": 3, "tied": 0})


def test_a_pair_of_an_earlier_format_is_made_again(tmp_path) -> None:
    """Spec AG1 section 6: a stale pair is not folded into.

    The reveal finds a pair of the first format (S of the trial score
    with the clamp) and assembles each pair from the trial rows, thus
    the result equals a full assembly.
    """
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    scoring_hash = _hash_of(fixture)
    rollup.assemble(config, scoring_hash=scoring_hash)
    expected = _snapshot(data_root / "skill")
    path = rollup.skill_pair_path(data_root, "ade", scoring_hash)
    stale = json.loads(path.read_text())
    for name in ("format", "t_statistic"):
        stale.pop(name)
    stale.update(clamp_count=0, degenerate=False, s_statistic=99.0)
    path.write_text(json.dumps(stale))
    root = Path(config.store_root)
    rollup.roll_up_day(config, store.read_day_record(root, DAYS[-1]))
    assert _snapshot(data_root / "skill") == expected


def test_a_missing_day_score_file_stops_the_board(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    scoring_hash = _hash_of(fixture)
    day_scores.index_path(data_root, DAYS[1], scoring_hash).unlink()
    with pytest.raises(rollup.RollupError,
                       match=f"service.day day-scores --date {DAYS[1]}"):
        rollup.assemble(config, scoring_hash=scoring_hash)


def test_the_board_holds_the_day_check_of_the_played_days(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    scoring_hash = _hash_of(fixture)
    board = json.loads(rollup.skill_board_path(
        data_root, scoring_hash).read_text())
    assert board["day_check"]["day_count"] == len(DAYS)
    for day in DAYS:
        rank = day_scores.read_day_rank(data_root, day, scoring_hash)
        assert 0.0 < rank < 1.0


def test_the_board_seed_is_a_function_of_recorded_inputs() -> None:
    first = rollup.board_seed("h" * 64, DAYS[0])
    assert first == rollup.board_seed("h" * 64, DAYS[0])
    assert first != rollup.board_seed("h" * 64, DAYS[1])
    assert first != rollup.board_seed("g" * 64, DAYS[0])


def test_assemble_repairs_a_removed_artifact(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    before = _snapshot(data_root)
    for path in list(data_root.rglob("*.json")):
        if "skill" in str(path) or "leaderboards" in str(path):
            path.unlink()
    rollup.assemble(config)
    assert _snapshot(data_root) == before


def test_the_rollup_refuses_a_day_that_is_not_revealed(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAYS[0], clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    record = store.read_day_record(Path(config.store_root), DAYS[0])
    with pytest.raises(rollup.RollupError, match="revealed"):
        rollup.roll_up_day(config, record)


def test_the_assemble_command_reports_its_counts(tmp_path, capsys) -> None:
    fixture = _played_world(tmp_path)
    config = fixture["service_config"]
    config_path = tmp_path / "service.json"
    config_path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}))
    code = rollup.main(["--service-config", str(config_path), "assemble"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "days=3" in printed
    assert "players=2" in printed
