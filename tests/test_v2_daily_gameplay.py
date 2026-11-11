"""Integration tests for V2 rents, progression, and player end results."""

import pytest

from v2_storage import (
    create_game_session,
    get_game_session,
    get_player_progress,
    join_game_session,
    load_player_trade_history,
    purchase_player_stock,
    select_player_location,
    set_player_selling_price,
    start_game_session,
    trade_player_day,
)


def active_game(database, *, days=7, starting_cash="2000.00"):
    session = create_game_session(
        database, trading_days=days, starting_budget=starting_cash
    )
    player = join_game_session(database, session["join_code"], "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    return session, player


def choose_location(database, session, player, location_key="carcavelos_nova_sbe"):
    return select_player_location(
        database, session["session_id"], player["player_id"], location_key
    )


def test_daily_revenue_pays_rent_once_without_double_deducting_cost_of_goods(tmp_path):
    database = tmp_path / "rent.sqlite3"
    session, player = active_game(database)
    choose_location(database, session, player)
    purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 10)

    result = trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )

    # €2.00 stock purchase, €9.00 sales, then one €30.00 rent payment.
    assert result["totals"]["revenue_cents"] == 900
    assert result["totals"]["cost_of_goods_sold_cents"] == 200
    assert result["totals"]["gross_profit_cents"] == 700
    assert result["rent_due_cents"] == result["rent_paid_cents"] == 3_000
    assert result["rent_shortfall_cents"] == 0
    assert result["cash_cents_after"] == 197_700
    progress = get_player_progress(database, session["session_id"], player["player_id"])
    assert progress["cash_cents"] == 197_700
    assert next(row for row in progress["products"] if row["product_key"] == "bica")["quantity"] == 0


def test_rent_shortfall_ends_only_that_player_at_zero_cash(tmp_path):
    database = tmp_path / "bankruptcy.sqlite3"
    session, player = active_game(database, days=7, starting_cash="10.00")
    choose_location(database, session, player, "chiado")
    for key, price in (("bica", "1.81"), ("galao", "3.01")):
        set_player_selling_price(database, session["session_id"], player["player_id"], key, price)

    result = trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )

    assert result["rent_due_cents"] == 8_000
    assert result["rent_paid_cents"] == 1_000
    assert result["rent_shortfall_cents"] == 7_000
    assert result["cash_cents_after"] == 0
    assert result["bankrupt"] is True
    progress = get_player_progress(database, session["session_id"], player["player_id"])
    assert progress["is_bankrupt"] is True
    assert progress["current_day"] == 2
    assert progress["final_game_result_cents"] == -1_000
    assert get_game_session(database, session["session_id"])["status"] == "finished"

    history = load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert len(history) == 1
    assert history[0]["rent_due_cents"] == 8_000
    assert history[0]["rent_paid_cents"] == 1_000
    assert history[0]["rent_shortfall_cents"] == 7_000
    assert history[0]["bankrupt"] is True

    for action in (
        lambda: purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 1),
        lambda: set_player_selling_price(database, session["session_id"], player["player_id"], "bica", "0.90"),
        lambda: trade_player_day(database, session["session_id"], player["player_id"], expected_day=2),
    ):
        with pytest.raises(ValueError, match="bankrupt"):
            action()


def test_seven_day_game_charges_seven_rents_and_has_final_cash_only_score(tmp_path):
    database = tmp_path / "seven-days.sqlite3"
    session, player = active_game(database)
    assert session["trading_days"] == 7
    assert session["starting_budget_cents"] == 200_000
    choose_location(database, session, player)

    results = []
    for day in range(1, 8):
        purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 40)
        results.append(
            trade_player_day(
                database, session["session_id"], player["player_id"], expected_day=day
            )
        )

    progress = get_player_progress(database, session["session_id"], player["player_id"])
    history = load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert [item["day"] for item in history] == list(range(1, 8))
    assert [item["rent_paid_cents"] for item in history] == [3_000] * 7
    assert progress["current_day"] == 8
    assert progress["cash_cents"] == 198_600
    assert progress["final_game_result_cents"] == -1_400
    assert sum(item["totals"]["units_sold"] for item in history) == 280
    assert get_game_session(database, session["session_id"])["status"] == "finished"
    with pytest.raises(ValueError, match="completed all trading days"):
        trade_player_day(
            database, session["session_id"], player["player_id"], expected_day=8
        )


def test_two_players_pay_their_own_location_rent_and_bankruptcy_is_isolated(tmp_path):
    database = tmp_path / "two-players.sqlite3"
    session = create_game_session(
        database, trading_days=2, starting_budget="50.00"
    )
    first = join_game_session(database, session["join_code"], "First")
    second = join_game_session(database, session["join_code"], "Second")
    start_game_session(database, session["session_id"], session["host_credential"])
    choose_location(database, session, first, "chiado")
    choose_location(database, session, second, "carcavelos_nova_sbe")
    purchase_player_stock(database, session["session_id"], second["player_id"], "bica", 10)

    first_result = trade_player_day(
        database, session["session_id"], first["player_id"], expected_day=1
    )
    second_result = trade_player_day(
        database, session["session_id"], second["player_id"], expected_day=1
    )

    assert first_result["bankrupt"] is True
    assert first_result["rent_due_cents"] == 8_000
    assert second_result["bankrupt"] is False
    assert second_result["rent_due_cents"] == 3_000
    first_progress = get_player_progress(database, session["session_id"], first["player_id"])
    second_progress = get_player_progress(database, session["session_id"], second["player_id"])
    assert first_progress["cash_cents"] == 0
    assert first_progress["is_bankrupt"] is True
    assert second_progress["cash_cents"] == 2_700
    assert second_progress["is_bankrupt"] is False
    assert second_progress["current_day"] == 2
    assert get_game_session(database, session["session_id"])["status"] == "active"

    with pytest.raises(ValueError, match="bankrupt"):
        trade_player_day(database, session["session_id"], first["player_id"], expected_day=2)
    assert get_player_progress(database, session["session_id"], second["player_id"]) == second_progress
