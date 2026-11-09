"""Purchase tests, including rejection without changing saved data."""

import sqlite3

import pytest

from storage import load_run, purchase_stock


def coffee_state(run):
    return next(product for product in run["products"] if product["product_key"] == "coffee")


def test_purchase_within_budget_then_reject_overspend(tmp_path):
    database = tmp_path / "game.sqlite3"

    purchase_stock(database, "coffee", 10)
    after_first_purchase = load_run(database)

    assert after_first_purchase["cash_cents"] == 8_000
    assert coffee_state(after_first_purchase)["quantity"] == 10

    before_rejected_purchase = load_run(database)
    with pytest.raises(ValueError, match="afford"):
        purchase_stock(database, "coffee", 41)
    after_rejected_purchase = load_run(database)

    assert after_rejected_purchase == before_rejected_purchase
    assert after_rejected_purchase["cash_cents"] == 8_000
    assert coffee_state(after_rejected_purchase)["quantity"] == 10


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "2", True])
def test_invalid_quantity_is_rejected_without_database_changes(tmp_path, quantity):
    database = tmp_path / "game.sqlite3"
    before = load_run(database)

    with pytest.raises(ValueError, match="quantity"):
        purchase_stock(database, "coffee", quantity)

    assert load_run(database) == before


def test_rejected_purchase_does_not_change_any_database_rows(tmp_path):
    database = tmp_path / "game.sqlite3"
    load_run(database)

    def snapshot():
        with sqlite3.connect(database) as connection:
            return {
                table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("products", "game_run", "inventory")
            }

    before = snapshot()
    with pytest.raises(ValueError):
        purchase_stock(database, "coffee", 51)

    assert snapshot() == before


def test_successful_purchase_is_saved_and_survives_reopening(tmp_path):
    database = tmp_path / "game.sqlite3"

    purchase_stock(database, "coffee", 10)

    # Loading through a new call models closing and reopening the application.
    reopened_run = load_run(database)
    assert reopened_run["cash_cents"] == 8_000
    assert coffee_state(reopened_run)["quantity"] == 10


def test_purchase_never_makes_cash_or_stock_negative(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 10)

    with pytest.raises(ValueError):
        purchase_stock(database, "coffee", 41)

    run = load_run(database)
    assert run["cash_cents"] >= 0
    assert all(product["quantity"] >= 0 for product in run["products"])
