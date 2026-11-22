"""Streamlit acceptance tests for the V2 multiplayer lobby."""

from pathlib import Path
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from business_logic import format_euros
from demand_engine import calculate_v2_demand
from estimate_ranges import demand_estimate_range
import v2_storage
import v2_events


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


def section_widget(app):
    return next(item for item in app.sidebar.selectbox if item.label == "Game section")


def selected_section(app):
    return section_widget(app).value


def navigate(app, section):
    section_widget(app).set_value(section)
    return app.run()


def choose_access_flow(app, action):
    next(radio for radio in app.radio if action in radio.options).set_value(action)
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


def test_game_section_is_in_sidebar_below_version_selector_without_main_duplicate(
    tmp_path, monkeypatch
):
    app = open_v2_app(monkeypatch, tmp_path / "sidebar-navigation.sqlite3")

    assert app.sidebar.radio[0].label == "Game version"
    assert app.sidebar.selectbox[0].label == "Game section"
    assert app.sidebar.selectbox[0].key == "v2_main_navigation"
    assert len(app.sidebar.selectbox) == 1
    assert len(app.main.selectbox) == 0
    assert app.sidebar.selectbox[0].options == [
        "Host / Join Game",
        "Café Setup",
        "Today",
        "Dashboard",
        "Leaderboard",
        "Final Report",
    ]

    for destination in app.sidebar.selectbox[0].options:
        app = navigate(app, destination)
        assert not app.exception
        assert selected_section(app) == destination


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


def test_rendering_and_navigation_do_not_assign_or_reveal_events(tmp_path, monkeypatch):
    database = tmp_path / "event-render.sqlite3"
    session = v2_storage.create_game_session(database)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], "chiado"
    )
    app = resume_in_app(open_v2_app(monkeypatch, database), session, player)
    app = navigate(app, "Today")
    app = navigate(app, "Dashboard")
    app = navigate(app, "Today")
    assert not app.exception
    assert not any("Location events" in item.value for item in app.subheader)
    assert not any("event has happened" in item.value for item in app.success)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM session_event_plans").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM player_day_events").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("location_key", "event_key", "polarity", "message_fragment", "effect"),
    [
        (
            "carcavelos_nova_sbe",
            "carcavelos_sunset_festival",
            "positive",
            "potential demand has increased by 75%",
            "demand_multiplier",
        ),
        (
            "belem",
            "belem_storm_charles",
            "negative",
            "60% of your inventory has been destroyed (6 units)",
            "inventory_loss",
        ),
    ],
)
def test_day_three_event_popup_shows_saved_effect_and_acknowledges_without_trading(
    tmp_path, monkeypatch, location_key, event_key, polarity, message_fragment, effect
):
    database = tmp_path / f"popup-{event_key}.sqlite3"
    session = v2_storage.create_game_session(database, trading_days=4)
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    v2_storage.select_player_location(
        database, session["session_id"], player["player_id"], location_key
    )
    v2_storage.trade_player_day(database, session["session_id"], player["player_id"], 1)
    v2_storage.trade_player_day(database, session["session_id"], player["player_id"], 2)
    if effect == "inventory_loss":
        for key, quantity in (("bica", 5), ("galao", 5)):
            v2_storage.purchase_player_stock(
                database, session["session_id"], player["player_id"], key, quantity
            )
    monkeypatch.setattr(
        v2_events,
        "choose_location_event",
        lambda location: v2_events.EVENTS_BY_KEY[event_key],
    )

    app = resume_in_app(open_v2_app(monkeypatch, database), session, player)
    app = navigate(app, "Today")
    app = click(app, "Complete Day 3")
    assert not any("Positive event!" == item.value for item in app.subheader)
    assert not any("Negative event!" == item.value for item in app.subheader)
    app = click(app, "Confirm Complete Day")

    assert not app.exception
    assert selected_section(app) == "Dashboard"
    assert any(item.value == "Day 3 results" for item in app.subheader)
    assert any(
        item.value == ("Positive event!" if polarity == "positive" else "Negative event!")
        for item in app.subheader
    )
    styled_alerts = app.success if polarity == "positive" else app.error
    assert any(message_fragment in item.value for item in styled_alerts)
    assert any(item.label == "View Day 3 Results" for item in app.button)

    before_progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    before_history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert [day["day"] for day in before_history if day["event"]] == [3]
    app = click(app, "View Day 3 Results")
    assert not app.exception
    assert selected_section(app) == "Dashboard"
    assert not any(item.label == "View Day 3 Results" for item in app.button)
    app.run()
    assert not any(item.label == "View Day 3 Results" for item in app.button)
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    ) == before_progress
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == before_history


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
    assert selected_section(app) == "Dashboard"
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
    assert history[0]["event"] is None
    app = click(app, "Continue to Day 2")
    assert selected_section(app) == "Today"
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
    assert selected_section(app) == "Today"
    assert any("menu was saved" in toast.proto.body for toast in app.get("toast"))
    assert progress["current_day"] == 1
    app = navigate(app, "Café Setup")
    assert any("5 of 5 products selected" in item.value for item in app.caption)
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
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
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
        # The active game status must recover navigation even if an app restart
        # cleared the temporary waiting-room marker from browser session state.
        del app.session_state["v2_waiting_player"]
        app.run()
        assert not app.exception
        assert selected_section(app) == "Café Setup"
    casey_app.run()
    assert selected_section(casey_app) == "Host / Join Game"

    v2_storage.select_player_location(
        database, session["session_id"], alex["player_id"], "carcavelos_nova_sbe"
    )
    v2_storage.trade_player_day(database, session["session_id"], alex["player_id"], 1)
    resumed = resume_in_app(open_v2_app(monkeypatch, database), session, alex)
    assert selected_section(resumed) == "Dashboard"
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
    assert selected_section(app) == "Café Setup"
    assert any("at least one drink" in message.value for message in app.error)

    app = navigate(app, "Today")
    app = click(app, "Complete Day 1")
    with monkeypatch.context() as patch:
        def reject_trade(*args, **kwargs):
            raise ValueError("Trade failed.")

        patch.setattr(v2_storage, "trade_player_day", reject_trade)
        app = click(app, "Confirm Complete Day")
    assert selected_section(app) == "Today"
    assert any("Trade failed." in message.value for message in app.error)
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == []

    app = click(app, "Complete Day 1")
    app = click(app, "Confirm Complete Day")
    assert selected_section(app) == "Dashboard"
    assert not any(button.label.startswith("Continue to Day") for button in app.button)
    app = click(app, "View Final Report")
    assert selected_section(app) == "Final Report"


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
    pending_quantities = (
        ("bica", "Units to buy (Bica)", 7),
        ("galao", "Units to buy (Galão)", 3),
        ("pastel_de_nata", "Units to buy (Pastel de nata)", 4),
    )
    quantity_keys = {}
    for product_key, label, quantity in pending_quantities:
        field = next(item for item in app.number_input if item.label == label)
        quantity_keys[product_key] = field.key
        assert product_key in field.key
        field.set_value(quantity)
        assert field.value == quantity

    # Unsubmitted form edits belong to the browser. AppTest's unrelated reruns
    # do not send those values, but must preserve form identity and saved state.
    for _ in range(2):
        app = app.run()
        assert not app.exception
        for product_key, label, _ in pending_quantities:
            field = next(item for item in app.number_input if item.label == label)
            assert field.key == quantity_keys[product_key]
        assert v2_storage.get_player_progress(
            database, session["session_id"], player["player_id"]
        ) == before

    app.number_input(key=quantity_keys["galao"]).set_value(3)
    app = click(app, "Buy Galão")
    assert not app.exception
    after = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    products = {product["product_key"]: product for product in after["products"]}
    assert products["bica"]["quantity"] == 0
    assert products["galao"]["quantity"] == 3
    assert products["pastel_de_nata"]["quantity"] == 0
    assert before["cash_cents"] - after["cash_cents"] == 3 * products["galao"]["purchase_cost_cents"]

    app.number_input(key=quantity_keys["pastel_de_nata"]).set_value(4)
    app = click(app, "Buy Pastel de nata")
    assert not app.exception
    final_progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    final_products = {
        product["product_key"]: product for product in final_progress["products"]
    }
    assert final_products["bica"]["quantity"] == 0
    assert final_products["galao"]["quantity"] == 3
    assert final_products["pastel_de_nata"]["quantity"] == 4
    assert after["cash_cents"] - final_progress["cash_cents"] == (
        4 * final_products["pastel_de_nata"]["purchase_cost_cents"]
    )


def test_repeated_bica_purchases_keep_card_order_and_quantity_keys(tmp_path, monkeypatch):
    database = tmp_path / "repeated-bica.sqlite3"
    session = v2_storage.create_game_session(database)
    session_id = session["session_id"]
    player = v2_storage.join_game_session(database, session["join_code"], "Alex")
    player_id = player["player_id"]
    v2_storage.start_game_session(database, session_id, session["host_credential"])
    v2_storage.select_player_location(database, session_id, player_id, "carcavelos_nova_sbe")
    v2_storage.set_player_menu(
        database, session_id, player_id, ["bica", "brownie", "galao"], expected_day=1
    )
    app = resume_in_app(open_v2_app(monkeypatch, database), session, player)
    before = v2_storage.get_player_progress(database, session_id, player_id)

    def quantity_fields():
        return [(field.label, field.key) for field in app.number_input]

    initial_fields = quantity_fields()
    assert [label for label, _ in initial_fields] == [
        "Units to buy (Bica)", "Units to buy (Brownie)", "Units to buy (Galão)"
    ]
    initial_buttons = {button.label: button.key for button in app.button if button.label.startswith("Buy ")}
    for quantity in (2, 1, 3):
        app.number_input(key=initial_fields[0][1]).set_value(quantity)
        app = click(app, "Buy Bica")
        assert not app.exception
        assert quantity_fields() == initial_fields
        buttons = {button.label: button.key for button in app.button if button.label.startswith("Buy ")}
        assert list(buttons) == list(initial_buttons)
        assert buttons["Buy Bica"] != initial_buttons["Buy Bica"]
        assert buttons["Buy Brownie"] == initial_buttons["Buy Brownie"]
        assert buttons["Buy Galão"] == initial_buttons["Buy Galão"]
        assert app.number_input(key=initial_fields[0][1]).value == 1
        assert not any("Bought" in message.value for message in app.success)

    after = v2_storage.get_player_progress(database, session_id, player_id)
    assert after["cash_cents"] == before["cash_cents"] - 120
    assert after["current_day"] == before["current_day"]
    for product_before, product_after in zip(before["products"], after["products"], strict=True):
        expected = dict(product_before)
        if expected["product_key"] == "bica":
            expected["quantity"] += 6
        assert product_after == expected
    assert v2_storage.load_player_trade_history(database, session_id, player_id) == []

    app.number_input(key=initial_fields[0][1]).set_value(100_000)
    app = click(app, "Buy Bica")
    assert not app.exception
    assert any("afford" in toast.proto.body for toast in app.get("toast"))
    assert quantity_fields() == initial_fields
    assert v2_storage.get_player_progress(database, session_id, player_id) == after
