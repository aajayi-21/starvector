"""A short run of the Layer 9 simulations of spec AG1 section 2."""

from validation.aggregate_null import (NullConfig, day_level_rate,
                                       population_rates, power_rows)

SHORT = NullConfig(reps=12, players=60, days=60, power_trials=100,
                   power_reps=300, day_pool=80, day_players=20,
                   day_season=40)


def test_the_clamp_fires_the_variation_report_and_the_correction_does_not(
) -> None:
    first = population_rates(SHORT, corrected=False)
    repaired = population_rates(SHORT, corrected=True)
    assert first["variation"] >= 0.75
    assert repaired["variation"] <= 0.25


def test_the_two_directions_see_the_strong_hits() -> None:
    rows = power_rows(SHORT)
    assert rows["strong_hits"]["two_directions"] \
        > rows["strong_hits"]["skill_side"] + 0.3
    assert rows["constant_edge"]["two_directions"] > 0.3
    assert rows["no_skill"]["two_directions"] < 0.12


def test_the_day_check_holds_its_level_with_correlated_players() -> None:
    assert day_level_rate(SHORT, 0.10) <= 0.25
