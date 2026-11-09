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


def resume_in_app(app, session, player):
    app.selectbox[0].set_value("Resume Game").run()
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
    app.selectbox[0].set_value("Join Game").run()
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
    app.selectbox[0].set_value("Resume Game").run()
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

    assert not app.exception
    assert any(button.label == "Complete Day 1" for button in app.button)
    app = click(app, "Buy Coffee")
    assert not app.exception
    price = next(field for field in app.text_input if field.label == "Selling price for Coffee (€)")
    price.set_value("4.50")
    app = app.run()
    app = click(app, "Save price for Coffee")
    assert not app.exception
    app = click(app, "Complete Day 1")
    assert not app.exception
    assert any(button.label == "Complete Day 2" for button in app.button)

    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    coffee = next(product for product in progress["products"] if product["product_key"] == "coffee")
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert progress["current_day"] == 2
    assert coffee["selected_price_cents"] == 450
    assert len(history) == 1
    assert history[0]["day"] == 1

