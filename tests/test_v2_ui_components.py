"""Tests for reusable, read-only multiplayer UI components."""

from v2_ui_components import business_header_values


def sample_progress(**updates):
    progress = {
        "cash_cents": 178_240,
        "starting_cash_cents": 200_000,
        "current_day": 3,
        "is_bankrupt": False,
        "location": {"location_key": "chiado"},
        "products": [
            {"quantity": 4},
            {"quantity": 7},
            {"quantity": 0},
        ],
    }
    progress.update(updates)
    return progress


def test_business_header_values_match_dashboard_cash_result_and_stock():
    values = business_header_values(sample_progress(), total_days=7)

    assert values == {
        "day": "3 / 7",
        "cash": "€1,782.40",
        "profit_loss": "-€217.60",
        "inventory_units": "11",
    }


def test_business_header_shows_day_zero_before_location_setup():
    progress = sample_progress(current_day=1, location=None)

    values = business_header_values(progress, total_days=7)

    assert values["day"] == "0 / 7"


def test_business_header_clamps_finished_and_bankrupt_day_numbers():
    finished = business_header_values(sample_progress(current_day=8), total_days=7)
    bankrupt = business_header_values(
        sample_progress(current_day=4, is_bankrupt=True), total_days=7
    )

    assert finished["day"] == "7 / 7"
    assert bankrupt["day"] == "3 / 7"


def test_business_header_uses_only_the_passed_players_progress():
    alex = business_header_values(sample_progress(), total_days=7)
    blair = business_header_values(
        sample_progress(
            cash_cents=800_000,
            starting_cash_cents=200_000,
            current_day=6,
            products=[{"quantity": 900}],
        ),
        total_days=7,
    )

    assert alex["cash"] == "€1,782.40"
    assert alex["inventory_units"] == "11"
    assert blair["cash"] == "€8,000.00"
    assert blair["inventory_units"] == "900"
