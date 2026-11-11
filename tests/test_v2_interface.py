"""Streamlit acceptance tests for the V2 multiplayer lobby."""

from pathlib import Path
import sqlite3

from streamlit.testing.v1 import AppTest

import v2_storage


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
V2_LABEL = "Campus Tycoon 2.0 · Multiplayer"


def open_v2_app(monkeypatch, database):
    monkeypatch.setattr(v2_storage, "V2_DATABASE_PATH", database)
    app = AppTest.from_file(str(APP_PATH)).run()
    app.radio[0].set_value(V2_LABEL).run()
    return app


def click(app, label):
    next(button for button in app.button if button.label == label).click()
    return app.run()


def navigate(app, section):
    app.selectbox[0].set_value(section)
    return app.run()


def choose_access_flow(app, action):
    app.radio[0].set_value(action)
    return app.run()


def resume_in_app(app, session, player):
    app = choose_access_flow(app, "Resume Game")
    app.text_input[0].set_value(session["join_code"])
    app.text_input[1].set_value(player["nickname"])
    app.text_input[2].set_value(player["recovery_credential"])
    return click(app, "Resume Game")


def test_host_creates_once_and_reruns_do_not_duplicate_sessions(tmp_path, monkeypatch):
    database = tmp_path / "v2.sqlite3"
    app = open_v2_app(monkeypatch, database)
    assert not app.exception
    app = click(app, "Create Game")
    assert not app.exception
    assert any(code.value and len(code.value) == 6 for code in app.code)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0] == 1
    app.run()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0] == 1


def test_join_rejects_invalid_code_and_successful_reruns_do_not_duplicate_player(
    tmp_path, monkeypatch
):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database)
    app = open_v2_app(monkeypatch, database)
    app = choose_access_flow(app, "Join Game")
    app.text_input[0].set_value("NOPE00")
    app.text_input[1].set_value("Alex")
    app = click(app, "Join Game")
    assert not app.exception
    assert any("not found" in error.value for error in app.error)

    app.text_input[0].set_value(session["join_code"])
    app = click(app, "Join Game")
    assert not app.exception
    assert any("recovery credential" in warning.value for warning in app.warning)
    app.run()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM players WHERE session_id = ?", (session["session_id"],)
        ).fetchone()[0] == 1


def test_player_can_resume_and_wrong_secret_does_not_authenticate(tmp_path, monkeypatch):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    app = open_v2_app(monkeypatch, database)
    app = choose_access_flow(app, "Resume Game")
    app.text_input[0].set_value(session["join_code"])
    app.text_input[1].set_value("Alex")
    app.text_input[2].set_value("wrong-secret")
    app = click(app, "Resume Game")
    assert any("could not be resumed" in error.value for error in app.error)

    app.text_input[2].set_value(player["recovery_credential"])
    app = click(app, "Resume Game")
    assert not app.exception
    assert any("Resumed as Alex" in item.value for item in app.success)


def test_waiting_player_sees_clear_host_wait_message_and_no_trade_actions(
    tmp_path, monkeypatch
):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)

    assert not app.exception
    assert any("host has not started" in message.value for message in app.info)
    assert not any(button.label.startswith("Complete Day") for button in app.button)
    assert not any(button.label.startswith("Buy ") for button in app.button)


def test_active_player_can_buy_set_price_and_complete_day_once(tmp_path, monkeypatch):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=2)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)
    app = navigate(app, "Café Setup")

    assert not app.exception
    assert any("Day 0 — Choose your café location" in item.value for item in app.header)
    app = click(app, "Choose this location")
    assert not app.exception
    app = click(app, "Sign the lease")
    assert not app.exception
    app = navigate(app, "Today")
    assert any(button.label == "Complete Day 1" for button in app.button)
    app = click(app, "Buy Bica")
    assert not app.exception
    price = next(field for field in app.text_input if field.label == "Selling price for Bica (€)")
    price.set_value("1.20")
    app = app.run()
    app = click(app, "Save price for Bica")
    assert not app.exception
    app = click(app, "Complete Day 1")
    assert any(button.label == "Confirm Complete Day" for button in app.button)
    assert len(v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )) == 0
    app = click(app, "Confirm Complete Day")
    assert not app.exception
    assert any(button.label == "Complete Day 2" for button in app.button)
    assert any(item.value == "Day 1 results" for item in app.subheader)
    assert any("Rent:" in item.value for item in app.caption)

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    coffee = next(product for product in progress["products"] if product["product_key"] == "bica")
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert progress["current_day"] == 2
    assert coffee["selected_price_cents"] == 120
    assert len(history) == 1
    assert history[0]["day"] == 1


def test_canceling_day_confirmation_does_not_trade_or_advance(tmp_path, monkeypatch):
    database = tmp_path / "cancel-confirmation.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=2)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
    )
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)
    app = navigate(app, "Today")
    app = click(app, "Complete Day 1")
    assert any(button.label == "Confirm Complete Day" for button in app.button)
    app = click(app, "Cancel")

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert progress["current_day"] == 1
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == []
    assert any(button.label == "Complete Day 1" for button in app.button)


def test_day_zero_shows_location_cards_but_hides_gameplay_until_lease_is_signed(
    tmp_path, monkeypatch
):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)
    app = navigate(app, "Café Setup")

    assert not app.exception
    assert any("Day 0 — Choose your café location" in item.value for item in app.header)
    displayed_text = " ".join(
        item.value for item in [*app.markdown, *app.subheader]
    )
    assert all(name in displayed_text for name in ("Carcavelos / Nova SBE", "Chiado", "Príncipe Real", "Belém"))
    assert "Daily foot traffic" in displayed_text
    assert "Daily rent" in displayed_text
    assert "1,200 people" in displayed_text
    assert "€30.00" in displayed_text
    assert "Persona mix" not in displayed_text
    assert not any(button.label.startswith("Complete Day") for button in app.button)
    assert not any(button.label.startswith("Buy ") for button in app.button)
    assert not any(field.label.startswith("Selling price") for field in app.text_input)

    app = click(app, "Choose this location")
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )["location"] is None
    app = click(app, "Sign the lease")
    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert progress["location"]["location_key"] == "carcavelos_nova_sbe"
    assert not any("Day 0 — Choose your café location" in item.value for item in app.header)


def test_player_can_edit_menu_and_only_active_products_have_actions(tmp_path, monkeypatch):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=2)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)
    app = navigate(app, "Café Setup")
    app = click(app, "Choose this location")
    app = click(app, "Sign the lease")
    app = navigate(app, "Café Setup")

    menu = next(widget for widget in app.multiselect if widget.label == "Choose up to 10 products")
    menu.set_value(["bica", "matcha_latte", "plant_based_toastie"]).run()
    app = click(app, "Save menu")

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert {item["product_key"] for item in progress["products"] if item["is_active"]} == {
        "bica",
        "matcha_latte",
        "plant_based_toastie",
    }
    assert not any(item.label == "Buy Bica" for item in app.button)
    displayed_text = " ".join(str(frame.value) for frame in app.dataframe)
    assert "Category" in displayed_text
    assert "€0.90" in displayed_text
    app = navigate(app, "Today")
    assert any(item.label == "Buy Bica" for item in app.button)
    assert any(item.label == "Buy Matcha latte" for item in app.button)
    assert not any(item.label == "Buy Galão" for item in app.button)


def test_management_dashboard_numbers_history_charts_and_player_isolation(
    tmp_path, monkeypatch
):
    database = tmp_path / "v2.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=3)
    player_a = v2_storage.join_game_session(database, session["join_code"], "Alex")
    player_b = v2_storage.join_game_session(database, session["join_code"], "Blair")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    for player in (player_a, player_b):
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
        )
    for day, quantity in ((1, 50), (2, 60)):
        v2_storage.purchase_player_stock(
            database, session["session_id"], player_a["player_id"], "bica", quantity
        )
        v2_storage.trade_player_day(
            database, session["session_id"], player_a["player_id"], expected_day=day
        )

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player_a["player_id"]
    )
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player_a["player_id"]
    )
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player_a)
    app = navigate(app, "Dashboard")

    assert not app.exception
    assert any(item.value == "Management Dashboard" for item in app.subheader)
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Available cash"] == f"€{progress['cash_cents'] // 100:,}.{progress['cash_cents'] % 100:02d}"
    assert metrics["Current day"] == "3 of 3"
    assert metrics["Accumulated revenue"] == f"€{sum(day['totals']['revenue_cents'] for day in history) // 100:,}.{sum(day['totals']['revenue_cents'] for day in history) % 100:02d}"
    assert metrics["Accumulated game result"] == f"€{progress['final_game_result_cents'] // 100:,}.{progress['final_game_result_cents'] % 100:02d}"
    assert metrics["Customers served"] == str(sum(day["customers_served"] for day in history))
    assert metrics["Inventory units"] == str(
        sum(product["quantity"] for product in progress["products"])
    )
    assert all(
        any(item.value == heading for item in app.subheader)
        for heading in (
            "Revenue by completed day",
            "Cash balance over time",
            "Units sold by product",
            "Best-selling products",
            "Daily results history",
        )
    )
    frames = [frame.value for frame in app.dataframe]
    product_sales = next(
        frame
        for frame in frames
        if "Rank" in frame.columns and "Units sold" in frame.columns
    )
    bica_sales = sum(
        item["units_sold"]
        for day in history
        for item in day["products"]
        if item["product_key"] == "bica"
    )
    assert int(
        product_sales.loc[product_sales["Product"] == "Bica", "Units sold"].iloc[0]
    ) == bica_sales
    assert product_sales["Units sold"].tolist() == sorted(
        product_sales["Units sold"].tolist(), reverse=True
    )
    inventory_table = next(
        frame
        for frame in frames
        if "Units in stock" in frame.columns and "Product" in frame.columns
    )
    bica_stock = next(
        item["quantity"]
        for item in progress["products"]
        if item["product_key"] == "bica"
    )
    assert int(
        inventory_table.loc[
            inventory_table["Product"] == "Bica", "Units in stock"
        ].iloc[0]
    ) == bica_stock
    history_table = next(
        frame
        for frame in frames
        if "Day" in frame.columns and "Cash after day" in frame.columns
    )
    assert history_table["Day"].tolist() == [1, 2]
    expected_revenue = [day["totals"]["revenue_cents"] for day in history]
    assert history_table["Revenue"].tolist() == [
        f"€{value // 100:,}.{value % 100:02d}" for value in expected_revenue
    ]
    assert any(item.value == "Daily results history" for item in app.subheader)
    assert all("Blair" not in str(frame) for frame in frames)

    before = v2_storage.get_player_progress(
        database, session["session_id"], player_a["player_id"]
    )
    before_history = v2_storage.load_player_trade_history(
        database, session["session_id"], player_a["player_id"]
    )
    app.run()
    after = v2_storage.get_player_progress(
        database, session["session_id"], player_a["player_id"]
    )
    assert after == before
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player_a["player_id"]
    ) == before_history


def test_empty_management_dashboard_has_guidance_and_current_inventory(
    tmp_path, monkeypatch
):
    database = tmp_path / "empty-v2.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
    )
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, player)
    app = navigate(app, "Dashboard")

    assert not app.exception
    assert any("No trading days have been completed" in item.value for item in app.info)
    assert any(item.value == "Current inventory" for item in app.subheader)
    assert not any(item.value == "Revenue by completed day" for item in app.subheader)


def test_finished_player_sees_personalized_provisional_final_report(
    tmp_path, monkeypatch
):
    database = tmp_path / "final-report-ui.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=1)
    completed = v2_storage.join_game_session(database, session["join_code"], "Completed")
    still_playing = v2_storage.join_game_session(
        database, session["join_code"], "Still Playing"
    )
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    for player in (completed, still_playing):
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
        )
    v2_storage.purchase_player_stock(
        database, session["session_id"], completed["player_id"], "bica", 10
    )
    v2_storage.trade_player_day(
        database, session["session_id"], completed["player_id"], expected_day=1
    )
    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, completed)
    app = navigate(app, "Final Report")

    assert not app.exception
    assert any(item.value == "Final Performance Report" for item in app.subheader)
    assert any(item.label == "Provisional ranking" for item in app.metric)
    assert any("Most successfully served persona" in item.value for item in app.markdown)
    assert any("Recommendations based on your saved results" in item.value for item in app.markdown)

    unfinished_app = open_v2_app(monkeypatch, database)
    unfinished_app = resume_in_app(unfinished_app, session, still_playing)
    unfinished_app = navigate(unfinished_app, "Final Report")
    assert not unfinished_app.exception
    assert not any(
        item.value == "Final Performance Report" for item in unfinished_app.subheader
    )

