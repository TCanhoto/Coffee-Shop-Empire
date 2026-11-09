"""Streamlit tests for the new-run confirmation flow."""

from streamlit.testing.v1 import AppTest
from pathlib import Path

import storage
from storage import (
    get_final_results as real_get_final_results,
    initialize_database,
    load_run as real_load_run,
    load_trade_history as real_load_trade_history,
    purchase_stock,
    reset_run,
    set_selling_price,
    trade_day,
)


def click_button(app, label):
    button = next(button for button in app.button if button.label == label)
    button.click()
    return app.run()


def use_test_database(monkeypatch, database):
    initialize_database(database)
    monkeypatch.setattr(storage, "DATABASE_PATH", database)
    monkeypatch.setattr(storage, "load_run", lambda *_: real_load_run(database))
    monkeypatch.setattr(
        storage,
        "load_trade_history",
        lambda *_: real_load_trade_history(database),
    )
    monkeypatch.setattr(
        storage,
        "get_final_results",
        lambda *_: real_get_final_results(database),
    )
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    return AppTest.from_file(str(app_path)).run()


def test_reopening_dashboard_does_not_repeat_saved_trade(tmp_path, monkeypatch):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    trade_day(database)
    before = real_load_run(database)
    before_history = real_load_trade_history(database)

    # Starting the dashboard runs its normal database initialization and reads.
    app = use_test_database(monkeypatch, database)

    assert not app.exception
    assert real_load_run(database) == before
    assert real_load_trade_history(database) == before_history
    assert len(real_load_trade_history(database)) == 1


def test_ui_cancellation_leaves_the_saved_run_unchanged(tmp_path, monkeypatch):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    for _ in range(5):
        trade_day(database)
    before = real_load_run(database)
    before_history = real_load_trade_history(database)

    app = use_test_database(monkeypatch, database)
    assert not app.exception
    assert any(item.value == "Final results" for item in app.subheader)
    assert not any(button.label == "Trade Day" for button in app.button)
    assert next(button for button in app.button if button.label == "Buy").disabled
    assert all(button.disabled for button in app.button if button.label == "Save selling price")
    app = click_button(app, "New Run")
    assert any("will be replaced" in warning.value for warning in app.warning)
    app = click_button(app, "Cancel")

    assert not app.exception
    assert real_load_run(database) == before
    assert real_load_trade_history(database) == before_history
    assert any(item.value == "Final results" for item in app.subheader)
    assert not any(button.label == "Trade Day" for button in app.button)


def test_ui_confirmation_resets_saved_run_and_history(tmp_path, monkeypatch):
    database = tmp_path / "game.sqlite3"
    purchase_stock(database, "coffee", 12)
    set_selling_price(database, "coffee", "4.01")
    for _ in range(5):
        trade_day(database)

    app = use_test_database(monkeypatch, database)
    assert not app.exception
    assert any(item.value == "Final results" for item in app.subheader)
    assert any(item.value == "Trading history" for item in app.subheader)
    assert not any(button.label == "Trade Day" for button in app.button)
    assert next(button for button in app.button if button.label == "Buy").disabled
    assert all(button.disabled for button in app.button if button.label == "Save selling price")
    app = click_button(app, "New Run")
    app = click_button(app, "Confirm New Run")

    assert not app.exception
    # A fresh AppTest models the reopened dashboard. Some Streamlit versions
    # retain elements from prior reruns in the same AppTest tree.
    reopened_app = use_test_database(monkeypatch, database)
    assert not reopened_app.exception
    assert not any(item.value == "Final results" for item in reopened_app.subheader)
    run = real_load_run(database)
    assert run["cash_cents"] == 10_000
    assert run["current_day"] == 1
    assert all(product["quantity"] == 0 for product in run["products"])
    assert [product["selected_price_cents"] for product in run["products"]] == [
        400,
        600,
        200,
    ]
    coffee_price_field = next(
        field for field in app.text_input if field.label == "Selling price for Coffee (€)"
    )
    assert coffee_price_field.value == "4.00"
    assert real_load_trade_history(database) == []
    assert reset_run(database, confirmed=False) is False
