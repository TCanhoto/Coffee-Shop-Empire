"""Streamlit acceptance tests for the V2 multiplayer lobby."""

from pathlib import Path
import sqlite3

from streamlit.testing.v1 import AppTest

from business_logic import format_euros
from demand_engine import calculate_v2_demand
from estimate_ranges import demand_estimate_range
import v2_storage


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
V2_LABEL = "Campus Tycoon 2.0 · Multiplayer"


def open_v2_app(monkeypatch, database):
    monkeypatch.setattr(v2_storage, "V2_DATABASE_PATH", database)
    app = AppTest.from_file(str(APP_PATH), default_timeout=15).run()
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
    range_text = [item.value for item in app.markdown if "Estimated demand range" in item.value]
    assert range_text
    assert all("units/day" in item and "planning range" in item for item in range_text)
    assert not any("Estimated menu demand at this price" in item.value for item in app.markdown)
    assert any("Profit is not forecast" in item.value for item in app.caption)
    preview_progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    preview_products = [item for item in preview_progress["products"] if item["is_active"]]
    exact_preview = calculate_v2_demand(
        preview_progress["location"], preview_products
    )["products"]["bica"]["demand"]
    assert f"{exact_preview} units/day" not in " ".join(range_text)
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
    assert app.selectbox[0].value == "Dashboard"
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
    app = click(app, "Continue to Day 2")
    assert app.selectbox[0].value == "Today"
    assert any(button.label == "Complete Day 2" for button in app.button)
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    ) == progress
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == history


def test_pretrade_demand_ranges_follow_each_players_own_menu_and_location(
    tmp_path, monkeypatch
):
    database = tmp_path / "player-range-isolation.sqlite3"
    session = v2_storage.create_game_session(database)
    alex = v2_storage.join_game_session(database, session["join_code"], "Alex")
    blair = v2_storage.join_game_session(database, session["join_code"], "Blair")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], alex["player_id"], "carcavelos_nova_sbe"
    )
    v2_storage.select_player_location(
        database, session["session_id"], blair["player_id"], "chiado"
    )
    v2_storage.set_player_menu(
        database, session["session_id"], alex["player_id"], ["bica", "pastel_de_nata"],
        expected_day=1,
    )
    v2_storage.set_player_menu(
        database, session["session_id"], blair["player_id"],
        ["fresh_orange_juice", "granola_bowl"], expected_day=1,
    )

    shown_ranges = []
    for player in (alex, blair):
        app = open_v2_app(monkeypatch, database)
        app = resume_in_app(app, session, player)
        app = navigate(app, "Today")
        assert not app.exception
        shown_ranges.append(
            [item.value for item in app.markdown if "Estimated demand range" in item.value]
        )

    assert shown_ranges[0] and shown_ranges[1]
    assert shown_ranges[0] != shown_ranges[1]

    alex_progress = v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )
    alex_products = [item for item in alex_progress["products"] if item["is_active"]]
    alex_demand = calculate_v2_demand(alex_progress["location"], alex_products)
    alex_key = alex_products[0]["product_key"]
    alex_bounds = demand_estimate_range(alex_demand["products"][alex_key]["demand"])
    assert any(
        f"**{alex_bounds[0]:,}–{alex_bounds[1]:,} units/day**" in message
        for message in shown_ranges[0]
    )


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


def test_sticky_business_header_tracks_authenticated_players_saved_finances(
    tmp_path, monkeypatch
):
    database = tmp_path / "sticky-header.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=3)
    alex = v2_storage.join_game_session(database, session["join_code"], "Alex")
    blair = v2_storage.join_game_session(database, session["join_code"], "Blair")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    for player in (alex, blair):
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
        )
    v2_storage.purchase_player_stock(
        database, session["session_id"], alex["player_id"], "bica", 1
    )
    v2_storage.purchase_player_stock(
        database, session["session_id"], blair["player_id"], "bica", 500
    )

    app = open_v2_app(monkeypatch, database)
    app = resume_in_app(app, session, alex)
    app = navigate(app, "Today")

    def header_metrics(current_app):
        return {metric.label: metric.value for metric in current_app.metric}

    metrics = header_metrics(app)
    assert metrics == {
        "Day / days": "1 / 3",
        "Available cash": "€1,999.80",
        "Profit / loss": "-€0.20",
        "Inventory units": "1",
    }
    assert "€1,900.00" not in metrics.values()
    assert "500" not in metrics.values()

    app = click(app, "Buy Bica")
    metrics = header_metrics(app)
    assert metrics["Available cash"] == "€1,999.60"
    assert metrics["Inventory units"] == "2"

    app = click(app, "Complete Day 1")
    app = click(app, "Confirm Complete Day")
    progress = v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )
    metrics = header_metrics(app)
    assert metrics["Day / days"] == "2 / 3"
    assert metrics["Available cash"] == format_euros(progress["cash_cents"])
    assert metrics["Profit / loss"] == format_euros(
        progress["cash_cents"] - progress["starting_cash_cents"]
    )
    assert metrics["Inventory units"] == str(
        sum(product["quantity"] for product in progress["products"])
    )


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
    assert any(button.label == "Sign the lease" for button in app.button)
    assert any(button.label == "Cancel" for button in app.button)
    assert sum(button.label in {"Sign the lease", "Cancel"} for button in app.button) == 2
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )["location"] is None
    dialog_text = " ".join(item.value for item in app.markdown)
    assert "Carcavelos / Nova SBE" in dialog_text
    assert "€30.00" in dialog_text
    assert any("cannot be changed" in item.value for item in app.warning)
    app = click(app, "Cancel")
    assert not any(button.label == "Sign the lease" for button in app.button)
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )["location"] is None

    app = click(app, "Choose this location")
    app = click(app, "Sign the lease")
    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert progress["location"]["location_key"] == "carcavelos_nova_sbe"
    assert not any("Day 0 — Choose your café location" in item.value for item in app.header)


def test_location_dialog_refresh_repeated_sign_and_two_player_independence(
    tmp_path, monkeypatch
):
    database = tmp_path / "location-dialog.sqlite3"
    session = v2_storage.create_game_session(database)
    alex = v2_storage.join_game_session(database, session["join_code"], "Alex")
    blair = v2_storage.join_game_session(database, session["join_code"], "Blair")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])

    alex_app = open_v2_app(monkeypatch, database)
    alex_app = resume_in_app(alex_app, session, alex)
    alex_app = navigate(alex_app, "Café Setup")
    choose_chiado = next(
        button for button in alex_app.button
        if button.key == f"v2_choose_location_{alex['player_id']}_chiado"
    )
    choose_chiado.click()
    alex_app = alex_app.run()
    assert any(button.label == "Sign the lease" for button in alex_app.button)
    assert any(button.label == "Cancel" for button in alex_app.button)
    assert sum(
        button.label in {"Sign the lease", "Cancel"}
        for button in alex_app.button
    ) == 2

    # A Streamlit rerun (the AppTest equivalent of refreshing this page) must
    # keep the dialog pending without writing a lease to SQLite.
    alex_app = alex_app.run()
    assert any(button.label == "Sign the lease" for button in alex_app.button)
    assert v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )["location"] is None

    alex_app = click(alex_app, "Sign the lease")
    assert not any(button.label == "Sign the lease" for button in alex_app.button)
    assert v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )["location"]["location_key"] == "chiado"
    alex_app.run()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM player_locations WHERE session_id = ? AND player_id = ?",
            (session["session_id"], alex["player_id"]),
        ).fetchone()[0] == 1

    # A fresh browser can resume Alex's lease; Blair independently chooses a
    # different location without changing Alex's saved location.
    alex_resume = open_v2_app(monkeypatch, database)
    alex_resume = resume_in_app(alex_resume, session, alex)
    alex_progress = v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )
    assert alex_progress["location"]["location_key"] == "chiado"

    blair_app = open_v2_app(monkeypatch, database)
    blair_app = resume_in_app(blair_app, session, blair)
    blair_app = navigate(blair_app, "Café Setup")
    next(
        button for button in blair_app.button
        if button.key == f"v2_choose_location_{blair['player_id']}_belem"
    ).click()
    blair_app = blair_app.run()
    blair_app = click(blair_app, "Sign the lease")
    assert v2_storage.get_player_progress(
        database, session["session_id"], blair["player_id"]
    )["location"]["location_key"] == "belem"
    assert v2_storage.get_player_progress(
        database, session["session_id"], alex["player_id"]
    )["location"]["location_key"] == "chiado"


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

    menu = next(widget for widget in app.multiselect if widget.label == "Choose products")
    menu.set_value([
        "bica", "matcha_latte", "plant_based_toastie", "pastel_de_nata", "brownie"
    ]).run()
    assert any("5 of 5 products selected" in item.value for item in app.caption)
    assert any("Maximum reached" in item.value for item in app.info)
    app = click(app, "Save menu")
    assert any("5 of 5 products selected" in item.value for item in app.caption)

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert {item["product_key"] for item in progress["products"] if item["is_active"]} == {
        "bica",
        "matcha_latte",
        "plant_based_toastie",
        "pastel_de_nata",
        "brownie",
    }
    assert app.selectbox[0].value == "Today"
    assert any("menu was saved" in message.value for message in app.success)
    assert progress["current_day"] == 1
    app = navigate(app, "Café Setup")
    assert not any(item.label == "Buy Bica" for item in app.button)
    displayed_text = " ".join(str(frame.value) for frame in app.dataframe)
    assert "Category" in displayed_text
    assert "€0.90" in displayed_text
    assert all("Type" not in frame.value.columns for frame in app.dataframe)
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


def test_independent_screen_sessions_do_not_inherit_login_or_replay_purchases(tmp_path, monkeypatch):
    database = tmp_path / "browser-isolation.sqlite3"
    session = v2_storage.create_game_session(database)
    alice = v2_storage.join_game_session(database, session["join_code"], "Alice")
    first = resume_in_app(open_v2_app(monkeypatch, database), session, alice)
    assert first.session_state["v2_player"]["player_id"] == alice["player_id"]
    second = open_v2_app(monkeypatch, database)
    assert "v2_player" not in second.session_state
    assert "v2_host_credential" not in second.session_state
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(database, session["session_id"], alice["player_id"], "carcavelos_nova_sbe")
    first = navigate(first, "Today")
    first = click(first, "Buy Bica")
    before = v2_storage.get_player_progress(database, session["session_id"], alice["player_id"])
    first.run()
    assert not first.exception
    assert v2_storage.get_player_progress(database, session["session_id"], alice["player_id"]) == before
    first = navigate(first, "Host / Join Game")
    first = choose_access_flow(first, "Resume Game")
    first = click(first, "Sign out of this player")
    assert "v2_player" not in first.session_state
    assert "v2_player" not in second.session_state



def test_host_start_routes_waiting_players_and_resume_recovers_saved_day(tmp_path, monkeypatch):
    database = tmp_path / "lobby.sqlite3"
    session = v2_storage.create_game_session(database)
    other_session = v2_storage.create_game_session(database)
    alex = v2_storage.join_game_session(database, session["join_code"], "Alex")
    blair = v2_storage.join_game_session(database, session["join_code"], "Blair")
    casey = v2_storage.join_game_session(database, other_session["join_code"], "Casey")
    alex_app = resume_in_app(open_v2_app(monkeypatch, database), session, alex)
    blair_app = resume_in_app(open_v2_app(monkeypatch, database), session, blair)
    casey_app = resume_in_app(open_v2_app(monkeypatch, database), other_session, casey)
    host_app = open_v2_app(monkeypatch, database)
    host_app.text_input[0].set_value(session["join_code"])
    host_app.text_input[1].set_value(session["host_credential"])
    host_app = click(host_app, "Resume Host Controls")
    click(host_app, "Start Game")

    # AppTest drives a rerun explicitly. A real browser drives the timed fragment.
    for app in (alex_app, blair_app):
        app.run()
        assert not app.exception
        assert app.selectbox[0].value == "Café Setup"
    assert casey_app.run().selectbox[0].value == "Host / Join Game"

    v2_storage.select_player_location(
        database, session["session_id"], alex["player_id"], "carcavelos_nova_sbe"
    )
    v2_storage.trade_player_day(database, session["session_id"], alex["player_id"], 1)
    resumed = resume_in_app(open_v2_app(monkeypatch, database), session, alex)
    assert resumed.selectbox[0].value == "Dashboard"
    assert any(item.value == "Day 1 results" for item in resumed.subheader)
    assert len(v2_storage.load_player_trade_history(
        database, session["session_id"], alex["player_id"]
    )) == 1


def test_failed_menu_and_trade_keep_current_section(tmp_path, monkeypatch):
    database = tmp_path / "rejected-actions.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=1)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
    )
    app = resume_in_app(open_v2_app(monkeypatch, database), session, player)
    app = navigate(app, "Café Setup")
    app.multiselect[0].set_value(["pastel_de_nata"]).run()
    app = click(app, "Save menu")
    assert app.selectbox[0].value == "Café Setup"
    assert any("at least one drink" in message.value for message in app.error)

    app = navigate(app, "Today")
    app = click(app, "Complete Day 1")
    with monkeypatch.context() as patch:
        def reject_trade(*args, **kwargs):
            raise ValueError("Trade failed.")

        patch.setattr(v2_storage, "trade_player_day", reject_trade)
        app = click(app, "Confirm Complete Day")
    assert app.selectbox[0].value == "Today"
    assert any("Trade failed." in message.value for message in app.error)
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == []

    app = click(app, "Complete Day 1")
    app = click(app, "Confirm Complete Day")
    assert app.selectbox[0].value == "Dashboard"
    assert not any(button.label.startswith("Continue to Day") for button in app.button)
    assert click(app, "View Final Report").selectbox[0].value == "Final Report"


def test_purchase_form_submits_only_the_selected_product(tmp_path, monkeypatch):
    database = tmp_path / "purchase-forms.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
    )
    app = resume_in_app(open_v2_app(monkeypatch, database), session, player)
    before = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    next(item for item in app.number_input if item.label == "Units to buy (Bica)").set_value(7)
    next(item for item in app.number_input if item.label == "Units to buy (Galão)").set_value(3)
    app.run()
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    ) == before

    # The browser sends the form value together with the submit action.
    next(item for item in app.number_input if item.label == "Units to buy (Galão)").set_value(3)
    app = click(app, "Buy Galão")
    assert not app.exception
    after = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    products = {product["product_key"]: product for product in after["products"]}
    assert products["bica"]["quantity"] == 0
    assert products["galao"]["quantity"] == 3
    assert before["cash_cents"] - after["cash_cents"] == 3 * products["galao"]["purchase_cost_cents"]
