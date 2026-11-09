"""Tests for price validation, demand tiers, and saved prices."""

import pytest

from business_logic import calculate_demand, price_to_cents
from storage import load_run, set_selling_price


@pytest.mark.parametrize(
    ("price", "expected_demand"),
    [("4.00", 10), ("4.01", 5), ("8.00", 5), ("8.01", 0)],
)
def test_coffee_demand_price_boundaries(price, expected_demand):
    assert calculate_demand(price_to_cents(price), reference_price_cents=400) == expected_demand


@pytest.mark.parametrize("price", ["0", "0.00", "-0.01", "-1", "4.001", "4.000", "abc", "NaN", "Infinity"])
def test_invalid_prices_are_rejected(price):
    with pytest.raises(ValueError):
        price_to_cents(price)


def test_valid_price_is_saved_immediately_and_survives_reopening(tmp_path):
    database = tmp_path / "game.sqlite3"

    set_selling_price(database, "coffee", "4.01")

    reopened_run = load_run(database)
    coffee = next(product for product in reopened_run["products"] if product["product_key"] == "coffee")
    assert coffee["selected_price_cents"] == 401
    assert calculate_demand(coffee["selected_price_cents"], coffee["reference_price_cents"]) == 5


def test_invalid_price_does_not_change_saved_prices(tmp_path):
    database = tmp_path / "game.sqlite3"
    before = load_run(database)

    with pytest.raises(ValueError):
        set_selling_price(database, "coffee", "4.001")

    assert load_run(database) == before


def test_unknown_product_is_rejected(tmp_path):
    database = tmp_path / "game.sqlite3"
    before = load_run(database)

    with pytest.raises(ValueError, match="product"):
        set_selling_price(database, "tea", "2.00")

    assert load_run(database) == before
