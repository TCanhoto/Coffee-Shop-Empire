"""Tests for creating and reopening the initial saved game."""

from storage import initialize_database, load_run


def test_first_load_creates_the_initial_run(tmp_path):
    database = tmp_path / "game.sqlite3"

    run = load_run(database)

    assert database.exists()
    assert run["cash_cents"] == 10_000
    assert run["current_day"] == 1
    assert [product["name"] for product in run["products"]] == [
        "Coffee",
        "Sandwich",
        "Cookie",
    ]
    assert [product["purchase_cost_cents"] for product in run["products"]] == [
        200,
        300,
        100,
    ]
    assert [product["reference_price_cents"] for product in run["products"]] == [
        400,
        600,
        200,
    ]
    assert all(product["quantity"] == 0 for product in run["products"])
    assert [product["selected_price_cents"] for product in run["products"]] == [
        400,
        600,
        200,
    ]


def test_initialization_and_reopening_do_not_reset_existing_run(tmp_path):
    database = tmp_path / "game.sqlite3"
    initialize_database(database)

    # Simulate saved changes so we can prove a subsequent app load preserves them.
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE game_run SET cash_cents = 7350, current_day = 3")
        connection.execute(
            "UPDATE inventory SET quantity = 4, selected_price_cents = 425 "
            "WHERE product_key = 'coffee'"
        )

    initialize_database(database)
    run = load_run(database)

    assert run["cash_cents"] == 7350
    assert run["current_day"] == 3
    assert run["products"][0]["quantity"] == 4
    assert run["products"][0]["selected_price_cents"] == 425
