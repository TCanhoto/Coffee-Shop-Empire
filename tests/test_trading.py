"""Tests for one-day sales, accounting, and durable trade results."""

import sqlite3

import pytest

from storage import (
    load_latest_trade,
    load_run,
    purchase_stock,
    set_selling_price,
    trade_day,
)


def product_result(trade, key):
    return next(product for product in trade["products"] if product["product_key"] == key)


def product_state(run, key):
    return next(product for product in run["products"] if product["product_key"] == key)


def test_trade_day_reconciles_coffee_sales_and_cash(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 10)
    set_selling_price(database, "coffee", "4.00")

    trade = trade_day(database)
    coffee = product_result(trade, "coffee")

    assert trade["day"] == 1
    assert coffee["demand"] == 10
    assert coffee["units_sold"] == 10
    assert coffee["revenue_cents"] == 4_000
    assert coffee["cost_of_goods_sold_cents"] == 2_000
    assert coffee["gross_profit_cents"] == 2_000
    assert trade["totals"] == {
        "demand": 30,
        "units_sold": 10,
        "revenue_cents": 4_000,
        "cost_of_goods_sold_cents": 2_000,
        "gross_profit_cents": 2_000,
    }

    run = load_run(database)
    assert run["cash_cents"] == 12_000
    assert run["current_day"] == 2
    assert product_state(run, "coffee")["quantity"] == 0


def test_trade_sells_only_available_inventory(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 3)

    trade = trade_day(database)

    assert product_result(trade, "coffee")["demand"] == 10
    assert product_result(trade, "coffee")["units_sold"] == 3
    assert product_result(trade, "coffee")["revenue_cents"] == 1_200
    assert product_result(trade, "coffee")["cost_of_goods_sold_cents"] == 600
    assert product_result(trade, "coffee")["gross_profit_cents"] == 600
    run = load_run(database)
    assert product_state(run, "coffee")["quantity"] == 0
    assert all(product["quantity"] >= 0 for product in run["products"])


def test_zero_stock_sells_zero_units_and_totals_reconcile(tmp_path):
    database = tmp_path / "game.sqlite3"

    trade = trade_day(database)

    assert all(product["units_sold"] == 0 for product in trade["products"])
    assert trade["totals"]["units_sold"] == 0
    assert trade["totals"]["revenue_cents"] == 0
    assert trade["totals"]["cost_of_goods_sold_cents"] == 0
    assert trade["totals"]["gross_profit_cents"] == 0
    assert load_run(database)["cash_cents"] == 10_000


def test_trade_result_and_state_are_saved_once_and_survive_reload(tmp_path):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 10)
    expected_trade = trade_day(database)

    reopened_trade = load_latest_trade(database)
    reopened_run = load_run(database)

    assert reopened_trade == expected_trade
    assert reopened_run["cash_cents"] == 12_000
    assert reopened_run["current_day"] == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM trading_days").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM daily_results").fetchone()[0] == 3


def test_each_trade_advances_one_day_and_run_stops_after_day_five(tmp_path):
    database = tmp_path / "game.sqlite3"

    for day in range(1, 6):
        trade = trade_day(database)
        assert trade["day"] == day

    run_after_day_five = load_run(database)
    assert run_after_day_five["current_day"] == 6
    cash_before_rejected_trade = run_after_day_five["cash_cents"]
    with pytest.raises(ValueError, match="complete"):
        trade_day(database)

    assert load_run(database)["cash_cents"] == cash_before_rejected_trade
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM trading_days").fetchone()[0] == 5
