"""Cross-layer acceptance and failure checks using disposable SQLite saves."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

from demand_engine import calculate_v2_demand
import v2_storage as game


def start_game(database, *, budget="2000.00"):
    session = game.create_game_session(database, starting_budget=budget)
    players = [game.join_game_session(database, session["join_code"], name)
               for name in ("Alice", "Bob", "Carol")]
    game.start_game_session(database, session["session_id"], session["host_credential"])
    for player, location in zip(players, ("carcavelos_nova_sbe", "chiado", "belem")):
        game.select_player_location(database, session["session_id"], player["player_id"], location)
    return session, players


def snapshot(database):
    with sqlite3.connect(database) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for (name,) in tables}


def test_three_players_complete_seven_days_with_reconciled_saved_results(tmp_path):
    database = tmp_path / "integration.sqlite3"
    session, players = start_game(database)
    sid = session["session_id"]
    assert session["trading_days"] == 7
    assert session["starting_budget_cents"] == 200_000
    menus = (("bica", "pastel_de_nata"), ("galao", "brownie"),
             ("fresh_orange_juice", "butter_croissant"))
    prices = ("0.90", "1.60", "3.20")
    for player, menu, price in zip(players, menus, prices):
        game.set_player_menu(database, sid, player["player_id"], list(menu), expected_day=1)
        game.set_player_selling_price(database, sid, player["player_id"], menu[0], price)

    # Finish each cafe separately: another player's day never moves with it.
    for index, player in enumerate(players):
        pid = player["player_id"]
        for day in range(1, 8):
            before = game.get_player_progress(database, sid, pid)
            cash = before["cash_cents"]
            for key in menus[index]:
                product = next(p for p in before["products"] if p["product_key"] == key)
                game.purchase_player_stock(database, sid, pid, key, 10)
                cash -= 10 * product["purchase_cost_cents"]
            stocked = game.get_player_progress(database, sid, pid)
            active = [p for p in stocked["products"] if p["is_active"]]
            demand = calculate_v2_demand(stocked["location"], active)
            assert demand == calculate_v2_demand(stocked["location"], active)
            revenue = sum(min(p["quantity"], demand["products"][p["product_key"]]["demand"])
                          * p["selected_price_cents"] for p in active)
            result = game.trade_player_day(database, sid, pid, expected_day=day)
            assert result["totals"]["revenue_cents"] == revenue
            assert result["cash_cents_after"] == cash + revenue - stocked["location"]["rent_per_day_cents"]
            saved = game.get_player_progress(database, sid, pid)
            for product in active:
                remaining = next(p for p in saved["products"] if p["product_key"] == product["product_key"])
                assert remaining["quantity"] == max(0, product["quantity"] - demand["products"][product["product_key"]]["demand"])
            assert saved["current_day"] == day + 1
            resumed = game.resume_player_by_credentials(
                database, session["join_code"], player["nickname"], player["recovery_credential"])
            assert resumed == saved
            assert len(game.load_player_trade_history(database, sid, pid)) == day
            for other in players[index + 1:]:
                assert game.get_player_progress(database, sid, other["player_id"])["current_day"] == 1
        report = game.get_player_final_report(database, sid, pid)
        history = game.load_player_trade_history(database, sid, pid)
        assert report["final_game_result_cents"] == saved["cash_cents"] - 200_000
        assert report["total_revenue_cents"] == sum(d["totals"]["revenue_cents"] for d in history)
        assert report["total_customers_served"] == sum(d["customers_served"] for d in history)
        assert report["ranking_is_final"] is (index == 2)
    assert game.get_game_session(database, sid)["status"] == "finished"
    board = game.get_session_leaderboard(database, sid)
    assert board["is_final"]
    assert [p["game_result_cents"] for p in board["players"]] == sorted(
        [p["game_result_cents"] for p in board["players"]], reverse=True)
    before = snapshot(database)
    game.initialize_v2_database(database)
    for player in players:
        game.get_player_progress(database, sid, player["player_id"])
        game.get_player_final_report(database, sid, player["player_id"])
    assert snapshot(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_three_concurrent_writers_preserve_player_balances(tmp_path):
    database = tmp_path / "writers.sqlite3"
    session, players = start_game(database)
    barrier = Barrier(3)
    def act(player):
        barrier.wait(timeout=10)
        pid = player["player_id"]
        game.purchase_player_stock(database, session["session_id"], pid, "bica", 10)
        return game.trade_player_day(database, session["session_id"], pid, expected_day=1)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(act, players))
    for player, result, rent in zip(players, results, (3000, 8000, 5500)):
        progress = game.get_player_progress(database, session["session_id"], player["player_id"])
        assert result["totals"]["revenue_cents"] == 900
        assert progress["cash_cents"] == 200_000 - 200 + 900 - rent
        assert progress["current_day"] == 2


def test_concurrent_purchases_cannot_spend_one_balance_twice(tmp_path):
    database = tmp_path / "overspend.sqlite3"
    session, players = start_game(database, budget="10.00")
    barrier = Barrier(2)
    def buy(_):
        barrier.wait(timeout=10)
        try:
            game.purchase_player_stock(database, session["session_id"], players[0]["player_id"], "bica", 30)
            return "accepted"
        except ValueError as error:
            assert "afford" in str(error)
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(buy, range(2))) == ["accepted", "rejected"]
    progress = game.get_player_progress(database, session["session_id"], players[0]["player_id"])
    assert progress["cash_cents"] == 400
    assert next(p for p in progress["products"] if p["product_key"] == "bica")["quantity"] == 30


@pytest.mark.parametrize("operation", ["trade", "purchase", "menu"])
def test_mid_write_failure_rolls_back_every_table(tmp_path, operation):
    database = tmp_path / "rollback.sqlite3"
    session, players = start_game(database)
    sid, pid = session["session_id"], players[0]["player_id"]
    game.purchase_player_stock(database, sid, pid, "bica", 10)
    table, event = {"trade": ("player_daily_results", "INSERT"),
                    "purchase": ("player_inventory", "UPDATE"),
                    "menu": ("player_menu", "INSERT")}[operation]
    with sqlite3.connect(database) as connection:
        connection.execute(f"CREATE TRIGGER fail_write BEFORE {event} ON {table} "
                           "BEGIN SELECT RAISE(ABORT, 'audit failure'); END")
    before = snapshot(database)
    with pytest.raises(sqlite3.IntegrityError, match="audit failure"):
        if operation == "trade":
            game.trade_player_day(database, sid, pid, expected_day=1)
        elif operation == "purchase":
            game.purchase_player_stock(database, sid, pid, "bica", 1)
        else:
            game.set_player_menu(database, sid, pid, ["bica"], expected_day=1)
    assert snapshot(database) == before


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "2", True])
def test_invalid_v2_quantities_leave_all_data_unchanged(tmp_path, quantity):
    database = tmp_path / "quantity.sqlite3"
    session, players = start_game(database)
    before = snapshot(database)
    with pytest.raises(ValueError):
        game.purchase_player_stock(database, session["session_id"], players[0]["player_id"], "bica", quantity)
    assert snapshot(database) == before


def test_price_larger_than_sqlite_integer_is_rejected_without_writes(tmp_path):
    database = tmp_path / "price-limit.sqlite3"
    session, players = start_game(database)
    before = snapshot(database)
    with pytest.raises(ValueError, match="price"):
        game.set_player_selling_price(database, session["session_id"], players[0]["player_id"],
                                      "bica", "92233720368547758.08")
    assert snapshot(database) == before


def test_saved_game_can_resume_in_a_new_python_process(tmp_path):
    database = tmp_path / "restart.sqlite3"
    session, players = start_game(database)
    player = players[0]
    game.purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 10)
    game.trade_player_day(database, session["session_id"], player["player_id"], expected_day=1)
    before = snapshot(database)
    # This tests a fresh storage process, not a real Streamlit server restart.
    script = """
import json, sys
import v2_storage as game
database, code, nickname, credential = json.load(sys.stdin)
progress = game.resume_player_by_credentials(database, code, nickname, credential)
assert progress['cash_cents'] == 197700
assert progress['current_day'] == 2
assert len(game.load_player_trade_history(database, progress['session_id'], progress['player_id'])) == 1
print('resumed')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        input=json.dumps([str(database), session["join_code"], player["nickname"], player["recovery_credential"]]),
        text=True, capture_output=True, timeout=30,
        cwd=Path(__file__).resolve().parents[1], check=True,
    )
    assert result.stdout.strip() == "resumed"
    assert snapshot(database) == before


@pytest.mark.parametrize("action", ["price", "trade", "menu", "report"])
def test_wrong_session_player_pair_cannot_read_or_change_game(tmp_path, action):
    database = tmp_path / "cross-session.sqlite3"
    session, players = start_game(database)
    other = game.create_game_session(database)
    sid, pid = other["session_id"], players[0]["player_id"]
    before = snapshot(database)
    with pytest.raises(ValueError, match="not found"):
        if action == "price":
            game.set_player_selling_price(database, sid, pid, "bica", "1.00")
        elif action == "trade":
            game.trade_player_day(database, sid, pid, expected_day=1)
        elif action == "menu":
            game.set_player_menu(database, sid, pid, ["bica"], expected_day=1)
        else:
            game.get_player_final_report(database, sid, pid)
    assert snapshot(database) == before
