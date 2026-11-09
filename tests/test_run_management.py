"""Tests for progress, history, completion, and starting a new run."""

import sqlite3

import pytest

from storage import (
    get_final_results,
    load_latest_trade,
    load_run,
    load_trade_history,
    purchase_stock,
    reset_run,
    set_selling_price,
    trade_day,
)
from business_logic import format_euros


def snapshot_database(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in (
                "products",
                "game_run",
                "inventory",
                "trading_days",
                "daily_results",
            )
        }


def find_product(run, key):
    return next(product for product in run["products"] if product["product_key"] == key)


def test_reopening_preserves_run_and_does_not_repeat_a_completed_trade(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    completed_day = trade_day(database)

    saved_state = load_run(database)
    saved_history = load_trade_history(database)
    saved_cash = saved_state["cash_cents"]

    # Separate reads model closing and reopening the application.
    reopened_state = load_run(database)
    reopened_history = load_trade_history(database)

    assert reopened_state == saved_state
    assert reopened_history == saved_history
    assert reopened_state["cash_cents"] == saved_cash == 9_605
    assert reopened_state["current_day"] == 2
    assert find_product(reopened_state, "coffee")["quantity"] == 7
    assert find_product(reopened_state, "coffee")["selected_price_cents"] == 401
    assert len(reopened_history) == 1
    assert reopened_history[0]["day"] == completed_day["day"] == 1
    assert load_latest_trade(database) == completed_day


def test_five_trades_create_five_days_with_product_results_and_totals(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 3)
    set_selling_price(database, "coffee", "8.01")

    for _ in range(5):
        trade_day(database)

    history = load_trade_history(database)
    run = load_run(database)
    assert [entry["day"] for entry in history] == [1, 2, 3, 4, 5]
    assert all(len(entry["products"]) == 3 for entry in history)
    assert all(entry["totals"]["units_sold"] == 0 for entry in history)
    assert run["current_day"] == 6
    assert get_final_results(database) == {
        "cash_cents": 9_400,
        "remaining_stock_value_cents": 600,
        "overall_gain_loss_cents": 0,
    }


def test_final_results_calculate_and_format_a_loss(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 10)
    set_selling_price(database, "coffee", "1.00")
    for _ in range(5):
        trade_day(database)

    assert get_final_results(database) == {
        "cash_cents": 9_000,
        "remaining_stock_value_cents": 0,
        "overall_gain_loss_cents": -1_000,
    }
    assert format_euros(-50) == "-€0.50"


def test_completed_run_rejects_purchase_price_change_and_trade(tmp_path):
    database = tmp_path / "game.sqlite3"
    for _ in range(5):
        trade_day(database)
    before = snapshot_database(database)

    with pytest.raises(ValueError, match="complete"):
        purchase_stock(database, "coffee", 1)
    with pytest.raises(ValueError, match="complete"):
        set_selling_price(database, "coffee", "4.00")
    with pytest.raises(ValueError, match="complete"):
        trade_day(database)

    assert snapshot_database(database) == before


def test_cancelling_new_run_preserves_everything(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    trade_day(database)
    before = snapshot_database(database)

    assert reset_run(database, confirmed=False) is False

    assert snapshot_database(database) == before


def test_confirming_new_run_restores_all_starting_values_and_clears_history(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    for _ in range(2):
        trade_day(database)

    assert reset_run(database, confirmed=True) is True

    run = load_run(database)
    assert run["cash_cents"] == 10_000
    assert run["current_day"] == 1
    assert all(product["quantity"] == 0 for product in run["products"])
    assert [product["selected_price_cents"] for product in run["products"]] == [
        400,
        600,
        200,
    ]
    assert load_trade_history(database) == []
    assert load_latest_trade(database) is None
