"""Tests for the broad, rounded ranges shown for pre-trading estimates."""

import pytest

from estimate_ranges import demand_estimate_range, profit_estimate_range


def test_demand_estimate_range_is_non_negative_and_rounded_outward():
    lower, upper = demand_estimate_range(100)

    assert (lower, upper) == (50, 175)
    assert 0 <= lower <= 100 <= upper


def test_zero_demand_still_displays_a_useful_non_negative_range():
    assert demand_estimate_range(0) == (0, 5)


def test_range_bounds_hide_the_exact_demand_baseline():
    displayed = demand_estimate_range(100)

    # Several distinct internal estimates produce the same broad, rounded bounds.
    assert [value for value in range(95, 101) if demand_estimate_range(value) == displayed]
    assert displayed != (100, 100)


def test_positive_profit_range_uses_coarse_euro_rounding():
    lower, upper = profit_estimate_range(6_500)

    assert (lower, upper) == (2_000, 12_000)
    assert lower % 500 == upper % 500 == 0


def test_zero_and_negative_profit_ranges_are_ordered_and_support_loss():
    assert profit_estimate_range(0) == (-500, 500)
    lower, upper = profit_estimate_range(-6_500)
    assert (lower, upper) == (-12_000, -2_000)
    assert lower < -6_500 < upper


def test_profit_range_rounding_is_independent_for_each_player():
    first_player = profit_estimate_range(6_500)
    second_player = profit_estimate_range(10_000)

    assert first_player == (2_000, 12_000)
    assert second_player == (5_000, 17_500)
    assert first_player != second_player


@pytest.mark.parametrize("baseline", [-1, True, 1.5, "10"])
def test_demand_range_rejects_invalid_baselines(baseline):
    with pytest.raises(ValueError):
        demand_estimate_range(baseline)


@pytest.mark.parametrize("baseline", [True, 1.5, "10"])
def test_profit_range_rejects_invalid_baselines(baseline):
    with pytest.raises(ValueError):
        profit_estimate_range(baseline)
