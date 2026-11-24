"""The instant switch, its guards, and its limits (spec IM1 6, 12.5)."""

import pytest

from service import instant, limits
from service.config import ServiceConfigError, parse_service_config


def _config(**changes: object) -> dict:
    value = {"config_version": 1, "player": "ade",
             "scoring_config": "configs/scoring/x.json",
             "data_root": "data", "store_root": "store", "port": 8000}
    value.update(changes)
    return value


def test_a_config_with_no_field_has_instant_off() -> None:
    config = parse_service_config(_config(), "test")
    assert config.instant == "off"
    assert config.instant_day_cap is None


@pytest.mark.parametrize("mode", ["accounts", "open"])
def test_instant_parses_with_a_beacon_and_a_cap(mode: str) -> None:
    config = parse_service_config(_config(
        instant=mode, instant_day_cap=400, beacon={"kind": "fake"}), "test")
    assert config.instant == mode
    assert config.instant_day_cap == 400


def test_an_unknown_instant_value_is_refused() -> None:
    with pytest.raises(ServiceConfigError, match="instant"):
        parse_service_config(_config(instant="guests"), "test")


@pytest.mark.parametrize("mode", ["accounts", "open"])
def test_instant_needs_a_beacon(mode: str) -> None:
    with pytest.raises(ServiceConfigError, match="beacon"):
        parse_service_config(
            _config(instant=mode, instant_day_cap=400), "test")


@pytest.mark.parametrize("mode", ["accounts", "open"])
def test_instant_needs_the_cap_of_all_owners(mode: str) -> None:
    # Decision D4: no instant trial before the owner sets the cap.
    with pytest.raises(ServiceConfigError, match="instant_day_cap"):
        parse_service_config(
            _config(instant=mode, beacon={"kind": "fake"}), "test")


@pytest.mark.parametrize("cap", [0, -3, True, "400", 1.5])
def test_a_bad_cap_is_refused(cap: object) -> None:
    with pytest.raises(ServiceConfigError, match="instant_day_cap"):
        parse_service_config(_config(
            instant="accounts", instant_day_cap=cap,
            beacon={"kind": "fake"}), "test")


def test_instant_off_keeps_a_cap_that_is_given() -> None:
    config = parse_service_config(_config(instant_day_cap=400), "test")
    assert config.instant == "off" and config.instant_day_cap == 400


def test_the_day_caps_are_ruling_5() -> None:
    assert limits.instant_day_cap(instant.GUEST) == 5
    assert limits.instant_day_cap(instant.ACCOUNT) == 20
    with pytest.raises(ValueError):
        limits.instant_day_cap("operator")


def test_the_guest_limiter_has_the_values_of_decision_d5() -> None:
    limiter = limits.guest_limiter()
    for _ in range(limits.GUEST_CLIENT_CAP):
        assert limiter.allowed("203.0.113.9")
        limiter.record("203.0.113.9")
    assert not limiter.allowed("203.0.113.9")
    assert limiter.allowed("203.0.113.10")
    assert limits.GUEST_CLIENT_CAP == 10
    assert limits.GUEST_GLOBAL_CAP == 1_000
    assert limits.GUEST_WINDOW_SECONDS == 24 * 60 * 60


def test_the_start_guard_names_what_is_missing() -> None:
    assert instant.start_refusal(
        mode="off", has_pool_key=False, has_proof_key=False) is None
    assert "pool key" in instant.start_refusal(
        mode="accounts", has_pool_key=False, has_proof_key=True)
    assert instant.start_refusal(
        mode="accounts", has_pool_key=True, has_proof_key=False) is None
    assert "ALTCHA" in instant.start_refusal(
        mode="open", has_pool_key=True, has_proof_key=False)
    assert instant.start_refusal(
        mode="open", has_pool_key=True, has_proof_key=True) is None
