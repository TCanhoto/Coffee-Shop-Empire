"""Acceptance tests for the shared-engine single-player mode."""

import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from streamlit.testing.v1 import AppTest

import storage as legacy_v1_storage
import v2_storage
from content import DEFAULT_MENU_KEYS
from demand_engine import calculate_v2_demand
import v2_events
from v2_interface import render


def create_started_multiplayer(database, *, trading_days=3, budget="2000.00"):
    session = v2_storage.create_game_session(
        database, trading_days=trading_days, starting_budget=budget
    )
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    return session, player


def test_solo_game_is_immediately_started_and_contains_one_isolated_player(tmp_path):
    database = tmp_path / "solo.sqlite3"
    solo = v2_storage.create_solo_game_session(
        database,
        trading_days=9,
        starting_budget="1250.75",
        nickname="My Café",
    )

    session = v2_storage.get_game_session(database, solo["session_id"])
    progress = v2_storage.get_player_progress(
        database, solo["session_id"], solo["player_id"]
    )
    with sqlite3.connect(database) as connection:
        players = connection.execute(
            "SELECT player_id FROM players WHERE session_id = ?",
            (solo["session_id"],),
        ).fetchall()
        mode = connection.execute(
            "SELECT mode FROM game_sessions WHERE session_id = ?",
            (solo["session_id"],),
        ).fetchone()[0]

    assert session["mode"] == mode == "single_player"
    assert session["status"] == "active"
    assert session["trading_days"] == 9
    assert session["starting_budget_cents"] == 125_075
    assert len(players) == 1
    assert progress["nickname"] == "My Café"
    assert progress["current_day"] == 1
    assert progress["cash_cents"] == progress["starting_cash_cents"] == 125_075
    assert all(product["quantity"] == 0 for product in progress["products"])
    assert {p["product_key"] for p in progress["products"] if p["is_active"]} == set(
        DEFAULT_MENU_KEYS
    )


def test_separate_solo_games_persist_without_sharing_player_state(tmp_path):
    database = tmp_path / "two-solo-games.sqlite3"
    first = v2_storage.create_solo_game_session(database, nickname="Alex")
    second = v2_storage.create_solo_game_session(database, nickname="Blair")

    assert first["session_id"] != second["session_id"]
    assert first["player_id"] != second["player_id"]
    assert first["join_code"] != second["join_code"]
    v2_storage.select_player_location(
        database, first["session_id"], first["player_id"], "chiado"
    )
    v2_storage.purchase_player_stock(
        database, first["session_id"], first["player_id"], "bica", 10
    )
    v2_storage.set_player_selling_price(
        database, first["session_id"], first["player_id"], "bica", "1.10"
    )

    first_saved = v2_storage.resume_solo_player_by_credentials(
        database,
        first["join_code"],
        "Alex",
        first["recovery_credential"],
    )
    second_saved = v2_storage.resume_solo_player_by_credentials(
        database,
        second["join_code"],
        "Blair",
        second["recovery_credential"],
    )
    assert first_saved["location"]["location_key"] == "chiado"
    assert next(p for p in first_saved["products"] if p["product_key"] == "bica")["quantity"] == 10
    assert next(p for p in first_saved["products"] if p["product_key"] == "bica")["selected_price_cents"] == 110
    assert second_saved["location"] is None
    assert all(p["quantity"] == 0 for p in second_saved["products"])
    assert second_saved["cash_cents"] == second_saved["starting_cash_cents"]


def test_single_and_multiplayer_sessions_cannot_join_or_resume_each_other(tmp_path):
    database = tmp_path / "mode-boundaries.sqlite3"
    solo = v2_storage.create_solo_game_session(database, nickname="Solo")
    multiplayer, player = create_started_multiplayer(database)

    with pytest.raises(ValueError, match="no longer accepting"):
        v2_storage.join_game_session(database, solo["join_code"], "Intruder")
    with pytest.raises(ValueError, match="mode"):
        v2_storage.resume_player_by_credentials(
            database,
            solo["join_code"],
            "Solo",
            solo["recovery_credential"],
        )
    with pytest.raises(ValueError, match="mode"):
        v2_storage.resume_solo_player_by_credentials(
            database,
            multiplayer["join_code"],
            player["nickname"],
            player["recovery_credential"],
        )
    with pytest.raises(ValueError, match="multiplayer"):
        v2_storage.start_game_session(
            database, solo["session_id"], "not-a-host-credential"
        )


def test_old_sessions_migrate_to_multiplayer_without_changing_saved_state(tmp_path):
    database = tmp_path / "pre-mode.sqlite3"
    session, player = create_started_multiplayer(database)
    before = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER single_player_session_one_player")
        connection.execute("ALTER TABLE game_sessions DROP COLUMN mode")

    v2_storage.initialize_v2_database(database)

    after = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert v2_storage.get_game_session(database, session["session_id"])["mode"] == "multiplayer"
    assert after == before


def test_solo_and_multiplayer_modes_use_the_same_business_rules(tmp_path, monkeypatch):
    database = tmp_path / "parity.sqlite3"
    solo = v2_storage.create_solo_game_session(database, nickname="Solo")
    multiplayer, player = create_started_multiplayer(database)
    monkeypatch.setattr(v2_storage.v2_events, "choose_location_event", lambda *_: None)

    for session, participant in ((solo, solo), (multiplayer, player)):
        sid, pid = session["session_id"], participant["player_id"]
        v2_storage.select_player_location(database, sid, pid, "carcavelos_nova_sbe")
        v2_storage.set_player_menu(database, sid, pid, ["bica", "pastel_de_nata"], expected_day=1)
        v2_storage.set_player_selling_price(database, sid, pid, "bica", "1.10")
        v2_storage.purchase_player_stock(database, sid, pid, "bica", 9)
        v2_storage.purchase_player_stock(database, sid, pid, "pastel_de_nata", 8)

    solo_before = v2_storage.get_player_progress(database, solo["session_id"], solo["player_id"])
    multi_before = v2_storage.get_player_progress(database, multiplayer["session_id"], player["player_id"])
    assert calculate_v2_demand(solo_before["location"], [p for p in solo_before["products"] if p["is_active"]]) == calculate_v2_demand(
        multi_before["location"], [p for p in multi_before["products"] if p["is_active"]]
    )

    solo_day = v2_storage.trade_player_day(database, solo["session_id"], solo["player_id"], 1)
    multi_day = v2_storage.trade_player_day(
        database, multiplayer["session_id"], player["player_id"], 1
    )
    assert solo_day["products"] == multi_day["products"]
    assert solo_day["totals"] == multi_day["totals"]
    assert solo_day["rent_paid_cents"] == multi_day["rent_paid_cents"]
    assert solo_day["cash_cents_after"] == multi_day["cash_cents_after"]
    assert v2_storage.get_player_progress(database, solo["session_id"], solo["player_id"])["products"] == v2_storage.get_player_progress(
        database, multiplayer["session_id"], player["player_id"]
    )["products"]


def test_solo_game_completes_seven_days_and_saves_one_day_three_event(
    tmp_path, monkeypatch
):
    database = tmp_path / "solo-seven-days.sqlite3"
    game = v2_storage.create_solo_game_session(database, trading_days=7, nickname="Seven")
    v2_storage.select_player_location(
        database, game["session_id"], game["player_id"], "chiado"
    )
    event = v2_events.EVENTS_BY_KEY["chiado_christmas_lights"]
    monkeypatch.setattr(
        v2_storage.v2_events, "choose_location_event", lambda *_: event
    )

    results = [
        v2_storage.trade_player_day(
            database, game["session_id"], game["player_id"], expected_day=day
        )
        for day in range(1, 8)
    ]
    history = v2_storage.load_player_trade_history(
        database, game["session_id"], game["player_id"]
    )
    progress = v2_storage.get_player_progress(
        database, game["session_id"], game["player_id"]
    )
    report = v2_storage.get_player_final_report(
        database, game["session_id"], game["player_id"]
    )

    assert [item["day"] for item in history] == list(range(1, 8))
    assert [item["event"]["key"] for item in results if item["event"]] == [
        "chiado_christmas_lights"
    ]
    assert [item["day"] for item in history if item["event"]] == [3]
    assert progress["current_day"] == 8
    assert v2_storage.get_game_session(database, game["session_id"])["status"] == "finished"
    assert report["final_game_result_cents"] == progress["cash_cents"] - progress["starting_cash_cents"]
    assert len(v2_storage.load_player_trade_history(
        database, game["session_id"], game["player_id"]
    )) == 7


def test_simultaneous_solo_users_create_and_change_separate_games(tmp_path):
    database = tmp_path / "concurrent-solo.sqlite3"
    barrier = Barrier(2)

    def create_and_buy(nickname):
        game = v2_storage.create_solo_game_session(database, nickname=nickname)
        barrier.wait(timeout=10)
        v2_storage.purchase_player_stock(
            database, game["session_id"], game["player_id"], "bica", 10
        )
        return game

    with ThreadPoolExecutor(max_workers=2) as executor:
        alex, blair = list(executor.map(create_and_buy, ("Alex", "Blair")))

    assert alex["session_id"] != blair["session_id"]
    for game in (alex, blair):
        progress = v2_storage.get_player_progress(
            database, game["session_id"], game["player_id"]
        )
        bica = next(item for item in progress["products"] if item["product_key"] == "bica")
        assert bica["quantity"] == 10
        assert progress["cash_cents"] == 200_000 - 10 * bica["purchase_cost_cents"]


@pytest.mark.parametrize(
    "options",
    [
        {"trading_days": 0},
        {"trading_days": 31},
        {"starting_budget": "0.99"},
        {"starting_budget": "2000.001"},
        {"nickname": "   "},
    ],
)
def test_invalid_solo_setup_is_rejected_without_creating_a_session(tmp_path, options):
    database = tmp_path / "invalid-solo-setup.sqlite3"
    with pytest.raises(ValueError):
        v2_storage.create_solo_game_session(database, **options)
    if database.exists():
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0] == 0


def open_app(monkeypatch, database):
    monkeypatch.setattr(v2_storage, "V2_DATABASE_PATH", database)
    path = Path(__file__).resolve().parents[1] / "app.py"
    return AppTest.from_file(str(path), default_timeout=15).run()


def click(app, label):
    next(button for button in app.button if button.label == label).click()
    return app.run()


def test_single_player_entry_offers_solo_start_and_resume_without_multiplayer_controls(
    tmp_path, monkeypatch
):
    app = open_app(monkeypatch, tmp_path / "solo-ui.sqlite3")

    assert not app.exception
    assert app.radio[0].options == [
        "Campus Tycoon 1.0 · Single Player",
        "Campus Tycoon 2.0 · Multiplayer",
    ]
    assert any(item.value == "Single Player Game" for item in app.header)
    assert any(button.label == "Start Solo Game" for button in app.button)
    assert not any(button.label == "Create Game" for button in app.button)
    assert not any(button.label == "Join Game" for button in app.button)
    assert not any(item.value == "Multiplayer Leaderboard" for item in app.header)


def test_switching_versions_keeps_solo_identity_and_navigation_separate(
    tmp_path, monkeypatch
):
    database = tmp_path / "mode-switch.sqlite3"
    app = open_app(monkeypatch, database)
    app = click(app, "Start Solo Game")
    solo = app.session_state["solo_player"]
    solo_nav = next(item for item in app.sidebar.radio if item.label == "GAME SECTION")
    assert solo_nav.value == "Café Setup"

    app.sidebar.radio[0].set_value("Campus Tycoon 2.0 · Multiplayer").run()
    multiplayer_nav = next(
        item for item in app.sidebar.radio if item.label == "GAME SECTION"
    )
    assert multiplayer_nav.options == ["Host / Join Game"]
    assert "v2_player" not in app.session_state

    app.sidebar.radio[0].set_value("Campus Tycoon 1.0 · Single Player").run()
    solo_nav = next(item for item in app.sidebar.radio if item.label == "GAME SECTION")
    assert solo_nav.value == "Café Setup"
    assert app.session_state["solo_player"] == solo
    assert v2_storage.get_player_progress(
        database, solo["session_id"], solo["player_id"]
    )["current_day"] == 1


def test_solo_startup_does_not_change_legacy_v1_database(tmp_path, monkeypatch):
    legacy_database = tmp_path / "legacy-v1.sqlite3"
    legacy_v1_storage.initialize_database(legacy_database)
    legacy_v1_storage.purchase_stock(legacy_database, "coffee", 2)
    with sqlite3.connect(legacy_database) as connection:
        before = {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }

    app = open_app(monkeypatch, tmp_path / "new-v2-format.sqlite3")
    assert not app.exception
    assert any(item.value == "Single Player Game" for item in app.header)
    with sqlite3.connect(legacy_database) as connection:
        after = {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    assert after == before


def test_solo_creation_enters_shared_cafe_setup_and_can_be_resumed(
    tmp_path, monkeypatch
):
    database = tmp_path / "solo-create-resume.sqlite3"
    app = open_app(monkeypatch, database)
    app.number_input[0].set_value(7)
    app.text_input[0].set_value("1750.25")
    app.text_input[1].set_value("Afonso's Café")
    app = click(app, "Start Solo Game")

    assert not app.exception
    assert next(item for item in app.sidebar.radio if item.label == "GAME SECTION").value == "Café Setup"
    assert any("Day 0 — Choose your café location" in item.value for item in app.header)
    assert any("Save this private solo recovery credential" in item.value for item in app.warning)
    identity = app.session_state["solo_player"]
    progress = v2_storage.get_player_progress(
        database, identity["session_id"], identity["player_id"]
    )
    assert progress["starting_cash_cents"] == 175_025
    assert progress["nickname"] == "Afonso's Café"

    reopened = open_app(monkeypatch, database)
    reopened.radio[0].set_value("Campus Tycoon 1.0 · Single Player").run()
    section = next(item for item in reopened.sidebar.radio if item.label == "GAME SECTION")
    section.set_value("Solo Game").run()
    assert any("Resume a saved solo game" in item.value for item in reopened.subheader)
    assert "solo_player" not in reopened.session_state


def test_solo_workflow_uses_same_setup_trade_dashboard_and_final_report(
    tmp_path, monkeypatch
):
    database = tmp_path / "solo-full-ui.sqlite3"
    app = open_app(monkeypatch, database)
    app.number_input[0].set_value(1)
    app = click(app, "Start Solo Game")
    app = click(app, "Choose this location")
    app = click(app, "Sign the lease")
    assert not app.exception
    section = next(item for item in app.sidebar.radio if item.label == "GAME SECTION")
    assert section.value == "Café Setup"
    menu = next(widget for widget in app.multiselect if widget.label == "Choose products")
    menu.set_value(["bica", "pastel_de_nata"]).run()
    app = click(app, "Save menu")
    assert not app.exception
    assert next(item for item in app.sidebar.radio if item.label == "GAME SECTION").value == "Today"
    assert any(toast.proto.body and "menu was saved" in toast.proto.body for toast in app.get("toast"))
    app = click(app, "Buy Bica")
    app = click(app, "Complete Day 1")
    app = click(app, "Confirm Complete Day")
    assert not app.exception
    assert next(item for item in app.sidebar.radio if item.label == "GAME SECTION").value == "Dashboard"
    assert any(item.value == "Management Dashboard" for item in app.subheader)
    assert any(button.label == "View Final Report" for button in app.button)
    app = click(app, "View Final Report")
    assert next(item for item in app.sidebar.radio if item.label == "GAME SECTION").value == "Final Report"
    assert not any("Leaderboard" in item.value for item in app.subheader)
    assert any("personal result" in item.value.lower() for item in app.caption)

