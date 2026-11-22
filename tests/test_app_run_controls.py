"""Single-player app startup, persistence, and safe new-game controls."""

from pathlib import Path
import sqlite3

from streamlit.testing.v1 import AppTest

import v2_storage


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def open_app(monkeypatch, database):
    monkeypatch.setattr(v2_storage, "V2_DATABASE_PATH", database)
    return AppTest.from_file(str(APP_PATH), default_timeout=15).run()


def click(app, label):
    next(button for button in app.button if button.label == label).click()
    return app.run()


def solo_identity(app):
    return app.session_state["solo_player"]


def create_solo_from_ui(app, *, days=2, cash="2000.00", nickname="Alex"):
    app.number_input[0].set_value(days)
    next(field for field in app.text_input if field.key == "solo_starting_cash").set_value(cash)
    next(field for field in app.text_input if field.key == "solo_cafe_name").set_value(nickname)
    return click(app, "Start Solo Game")


def test_reopening_dashboard_does_not_repeat_saved_solo_trade(tmp_path, monkeypatch):
    database = tmp_path / "saved-solo.sqlite3"
    game = v2_storage.create_solo_game_session(
        database, trading_days=3, nickname="Alex"
    )
    v2_storage.select_player_location(
        database, game["session_id"], game["player_id"], "carcavelos_nova_sbe"
    )
    v2_storage.purchase_player_stock(
        database, game["session_id"], game["player_id"], "bica", 6
    )
    v2_storage.trade_player_day(
        database, game["session_id"], game["player_id"], expected_day=1
    )
    before = v2_storage.get_player_progress(
        database, game["session_id"], game["player_id"]
    )
    history = v2_storage.load_player_trade_history(
        database, game["session_id"], game["player_id"]
    )

    app = open_app(monkeypatch, database)
    next(field for field in app.text_input if field.label == "Solo recovery code").set_value(
        game["join_code"]
    )
    next(field for field in app.text_input if field.label == "Saved player or café name").set_value(
        game["nickname"]
    )
    next(
        field for field in app.text_input
        if field.label == "Private solo recovery credential"
    ).set_value(game["recovery_credential"])
    app = click(app, "Resume Solo Game")

    assert not app.exception
    assert next(item for item in app.sidebar.radio if item.label == "GAME SECTION").value == "Dashboard"
    assert any(item.value == "Day 1 results" for item in app.subheader)
    assert v2_storage.get_player_progress(
        database, game["session_id"], game["player_id"]
    ) == before
    assert v2_storage.load_player_trade_history(
        database, game["session_id"], game["player_id"]
    ) == history
    assert len(history) == 1


def test_cancelling_another_solo_game_preserves_the_current_saved_game(
    tmp_path, monkeypatch
):
    database = tmp_path / "cancel-solo-game.sqlite3"
    app = create_solo_from_ui(open_app(monkeypatch, database), nickname="Current Café")
    original_identity = solo_identity(app)
    original_progress = v2_storage.get_player_progress(
        database, original_identity["session_id"], original_identity["player_id"]
    )

    navigation = next(item for item in app.sidebar.radio if item.label == "GAME SECTION")
    app = navigation.set_value("Solo Game").run()
    app = click(app, "Start Another Solo Game")
    assert any("remain available to resume" in item.value for item in app.warning)
    app = click(app, "Cancel")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0] == 1
    assert solo_identity(app) == original_identity
    assert v2_storage.get_player_progress(
        database, original_identity["session_id"], original_identity["player_id"]
    ) == original_progress


def test_confirmed_new_solo_game_creates_a_separate_save(tmp_path, monkeypatch):
    database = tmp_path / "new-solo-game.sqlite3"
    app = create_solo_from_ui(open_app(monkeypatch, database), nickname="First Café")
    first = solo_identity(app)
    first_progress = v2_storage.get_player_progress(
        database, first["session_id"], first["player_id"]
    )

    app = next(item for item in app.sidebar.radio if item.label == "GAME SECTION").set_value(
        "Solo Game"
    ).run()
    app = click(app, "Start Another Solo Game")
    app = click(app, "Confirm New Solo Game")
    next(field for field in app.text_input if field.key == "solo_cafe_name").set_value(
        "Second Café"
    )
    app = click(app, "Start Solo Game")

    second = solo_identity(app)
    assert second["session_id"] != first["session_id"]
    assert second["player_id"] != first["player_id"]
    assert v2_storage.get_player_progress(
        database, first["session_id"], first["player_id"]
    ) == first_progress
    assert v2_storage.get_player_progress(
        database, second["session_id"], second["player_id"]
    )["nickname"] == "Second Café"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM game_sessions").fetchone()[0] == 2
