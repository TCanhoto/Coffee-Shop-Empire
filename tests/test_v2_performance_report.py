"""Acceptance tests for personalized, saved-data V2 final reports."""

import sqlite3

import pytest

from content import PERSONAS
import v2_storage


def started_game(database, *, days=2, starting_cash="2000.00"):
    session = v2_storage.create_game_session(
        database, trading_days=days, starting_budget=starting_cash
    )
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
    )
    return session, player


def complete_sales_report_game(database):
    session, player = started_game(database)
    v2_storage.set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        ["bica", "pistachio_croissant"],
        expected_day=1,
    )
    v2_storage.set_player_selling_price(
        database,
        session["session_id"],
        player["player_id"],
        "pistachio_croissant",
        "8.01",
    )
    for day in (1, 2):
        v2_storage.purchase_player_stock(
            database, session["session_id"], player["player_id"], "bica", 10
        )
        if day == 1:
            v2_storage.purchase_player_stock(
                database,
                session["session_id"],
                player["player_id"],
                "pistachio_croissant",
                190,
            )
        v2_storage.trade_player_day(
            database, session["session_id"], player["player_id"], expected_day=day
        )
    return session, player


def test_final_report_summarizes_player_results_products_stockouts_and_personas(
    tmp_path,
):
    database = tmp_path / "report.sqlite3"
    session, player = complete_sales_report_game(database)

    report = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )

    assert report["final_game_result_cents"] == report["final_cash_cents"] - 200_000
    assert report["ranking_position"] == 1
    assert report["ranking_is_final"] is True
    assert report["total_revenue_cents"] > 0
    assert report["total_customers_served"] > 0
    assert report["best_product"]["name"] == "Bica"
    assert report["worst_product"]["name"] == "Pistachio croissant"
    assert report["remaining_inventory_units"] == 190
    assert report["remaining_inventory_value_cents"] == 20_900
    assert report["lost_sales_units"] > 0
    assert report["persona_data_complete"] is True
    assert 2 <= len(report["recommendations"]) <= 3
    persona_totals = {
        persona.key: sum(
            day["served_customers_by_persona"][persona.key]
            for day in v2_storage.load_player_trade_history(
                database, session["session_id"], player["player_id"]
            )
        )
        for persona in PERSONAS
    }
    expected_persona = max(
        PERSONAS, key=lambda persona: persona_totals[persona.key]
    )
    assert report["most_served_persona"]["name"] == expected_persona.name
    assert report["most_served_persona"]["customers_served"] == persona_totals[
        expected_persona.key
    ]
    assert {item["rule"] for item in report["recommendations"]} >= {
        "unsold_inventory",
        "repeated_stockouts",
        "zero_demand_product",
    }


def test_only_finished_players_can_load_a_report_and_other_players_stay_private(
    tmp_path,
):
    database = tmp_path / "player-access.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=1)
    completed = v2_storage.join_game_session(database, session["join_code"], "Completed")
    unfinished = v2_storage.join_game_session(database, session["join_code"], "Unfinished")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    for player in (completed, unfinished):
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
        )
    v2_storage.trade_player_day(
        database, session["session_id"], completed["player_id"], expected_day=1
    )

    with pytest.raises(ValueError, match="not finished"):
        v2_storage.get_player_final_report(
            database, session["session_id"], unfinished["player_id"]
        )
    report = v2_storage.get_player_final_report(
        database, session["session_id"], completed["player_id"]
    )
    assert report["nickname"] == "Completed"
    assert report["ranking_is_final"] is False
    assert "Unfinished" not in str(report)


def test_empty_sales_report_is_valid_and_explains_zero_persona_service(tmp_path):
    database = tmp_path / "empty-sales.sqlite3"
    session, player = started_game(database, days=1)
    v2_storage.set_player_menu(
        database, session["session_id"], player["player_id"], ["bica"], expected_day=1
    )
    v2_storage.trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )

    report = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )

    assert report["total_revenue_cents"] == 0
    assert report["total_customers_served"] == 0
    assert report["best_product"] is None
    assert report["worst_product"] is None
    assert report["most_served_persona"] is None
    assert report["lost_sales_units"] > 0


def test_best_product_is_selected_from_products_with_recorded_sales(tmp_path):
    database = tmp_path / "negative-margin.sqlite3"
    session, player = started_game(database, days=1)
    v2_storage.set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        ["bica", "pistachio_croissant"],
        expected_day=1,
    )
    v2_storage.set_player_selling_price(
        database, session["session_id"], player["player_id"], "bica", "0.01"
    )
    v2_storage.set_player_selling_price(
        database,
        session["session_id"],
        player["player_id"],
        "pistachio_croissant",
        "8.01",
    )
    v2_storage.purchase_player_stock(
        database, session["session_id"], player["player_id"], "bica", 10
    )
    v2_storage.trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )

    report = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )

    assert report["best_product"]["name"] == "Bica"
    assert report["best_product"]["units_sold"] > 0


def test_missing_persona_history_is_reported_without_guessing(tmp_path):
    database = tmp_path / "missing-persona.sqlite3"
    session, player = started_game(database, days=1)
    v2_storage.trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "ALTER TABLE player_trading_days "
            "DROP COLUMN served_customers_by_persona_json"
        )

    v2_storage.initialize_v2_database(database)
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert history[0]["served_customers_by_persona"] is None

    report = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )

    assert report["persona_data_complete"] is False
    assert report["most_served_persona"] is None
    assert any("persona" in note.lower() for note in report["missing_data"])


def test_report_refresh_does_not_modify_player_progress_or_history(tmp_path):
    database = tmp_path / "report-refresh.sqlite3"
    session, player = complete_sales_report_game(database)
    before_progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    before_history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )

    first = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )
    second = v2_storage.get_player_final_report(
        database, session["session_id"], player["player_id"]
    )

    assert second == first
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    ) == before_progress
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == before_history


def test_unsold_stock_recommendation_preserves_euro_cents(tmp_path):
    database = tmp_path / "report-cents.sqlite3"
    session, player = started_game(database, days=1)
    sid, pid = session["session_id"], player["player_id"]
    v2_storage.set_player_menu(database, sid, pid, ["bica", "pistachio_croissant"], expected_day=1)
    v2_storage.purchase_player_stock(database, sid, pid, "pistachio_croissant", 191)
    v2_storage.trade_player_day(database, sid, pid, expected_day=1)
    report = v2_storage.get_player_final_report(database, sid, pid)
    assert report["remaining_inventory_value_cents"] == 21_010
    recommendation = next(r for r in report["recommendations"] if r["rule"] == "unsold_inventory")
    assert "€210.10" in recommendation["text"]
