"""Acceptance tests for the read-only V2 multiplayer leaderboard."""

import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import v2_storage


def make_session(database, *, days=3, names=("Ada", "Bo", "Cy")):
    session = v2_storage.create_game_session(database, trading_days=days)
    players = [
        v2_storage.join_game_session(database, session["join_code"], name)
        for name in names
    ]
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    for player in players:
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], "carcavelos_nova_sbe"
        )
    return session, players


def seed_leaderboard_rows(database, session, players, rows):
    """Set a compact, hand-calculated snapshot for ordering tests."""

    with sqlite3.connect(database) as connection:
        for player, (cash_cents, revenue_cents, day_count) in zip(players, rows):
            connection.execute(
                "UPDATE players SET cash_cents = ?, current_day = ? WHERE player_id = ?",
                (cash_cents, day_count + 1, player["player_id"]),
            )
            for day in range(1, day_count + 1):
                connection.execute(
                    """INSERT INTO player_trading_days
                       (session_id, player_id, day_number, cash_cents_after,
                        total_demand, total_units_sold, total_revenue_cents,
                        total_cost_of_goods_sold_cents, total_gross_profit_cents)
                       VALUES (?, ?, ?, ?, 0, 0, ?, 0, 0)""",
                    (
                        session["session_id"], player["player_id"], day,
                        cash_cents, revenue_cents if day == 1 else 0,
                    ),
                )


def test_players_rank_by_result_then_revenue_then_stable_id(tmp_path):
    database = tmp_path / "leaderboard.sqlite3"
    session, players = make_session(database, names=("Ada", "Bo", "Cy", "Dee"))
    # Ada and Bo tie on result; Bo wins on revenue. Ada and Dee tie on both,
    # so their immutable player IDs provide a stable final ordering.
    seed_leaderboard_rows(
        database,
        session,
        players,
        [
            (200_500, 1_000, 1),
            (200_500, 2_000, 1),
            (200_400, 5_000, 1),
            (200_500, 1_000, 1),
        ],
    )

    result = v2_storage.get_session_leaderboard(database, session["session_id"])

    assert [row["nickname"] for row in result["players"]] == [
        "Bo", *sorted(("Ada", "Dee"), key=lambda name: next(
            player["player_id"] for player in players if player["nickname"] == name
        )), "Cy",
    ]
    assert [row["rank"] for row in result["players"]] == [1, 2, 3, 4]
    assert result["is_final"] is False
    assert result["players"][0]["game_result_cents"] == 500
    assert result["players"][0]["total_revenue_cents"] == 2_000


def test_incomplete_player_progress_and_finished_status_are_visible(tmp_path):
    database = tmp_path / "progress.sqlite3"
    session, (finished, playing) = make_session(
        database, days=1, names=("Finished", "Playing")
    )
    v2_storage.trade_player_day(
        database, session["session_id"], finished["player_id"], expected_day=1
    )

    result = v2_storage.get_session_leaderboard(database, session["session_id"])
    by_name = {row["nickname"]: row for row in result["players"]}

    assert result["is_final"] is False
    assert by_name["Finished"]["completed_days"] == 1
    assert by_name["Finished"]["status"] == "Finished"
    assert by_name["Playing"]["completed_days"] == 0
    assert by_name["Playing"]["status"] == "Playing"

    v2_storage.trade_player_day(
        database, session["session_id"], playing["player_id"], expected_day=1
    )
    final_result = v2_storage.get_session_leaderboard(
        database, session["session_id"]
    )
    assert final_result["is_final"] is True
    assert all(row["status"] == "Finished" for row in final_result["players"])


def test_leaderboard_is_scoped_to_one_session(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    first, first_players = make_session(database, names=("First Session Player",))
    second, _ = make_session(database, names=("Other Session Player",))

    result = v2_storage.get_session_leaderboard(database, first["session_id"])

    assert [row["nickname"] for row in result["players"]] == ["First Session Player"]
    assert all(row["nickname"] != "Other Session Player" for row in result["players"])
    assert first_players[0]["nickname"] == result["players"][0]["nickname"]


def test_negative_results_one_player_and_empty_session(tmp_path):
    database = tmp_path / "negative.sqlite3"
    session, (player,) = make_session(database, names=("Solo",))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET cash_cents = 199_950 WHERE player_id = ?",
            (player["player_id"],),
        )

    result = v2_storage.get_session_leaderboard(database, session["session_id"])
    assert len(result["players"]) == 1
    assert result["players"][0]["game_result_cents"] == -50
    assert result["players"][0]["location"] == "Carcavelos / Nova SBE"

    empty = v2_storage.create_game_session(database)
    empty_result = v2_storage.get_session_leaderboard(database, empty["session_id"])
    assert empty_result["players"] == []
    assert empty_result["is_final"] is False


def test_refreshing_leaderboard_does_not_change_game_data(tmp_path):
    database = tmp_path / "refresh.sqlite3"
    session, players = make_session(database)
    before = v2_storage.get_player_progress(
        database, session["session_id"], players[0]["player_id"]
    )

    v2_storage.get_session_leaderboard(database, session["session_id"])
    v2_storage.get_session_leaderboard(database, session["session_id"])

    after = v2_storage.get_player_progress(
        database, session["session_id"], players[0]["player_id"]
    )
    assert after == before
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], players[0]["player_id"]
    ) == []


def test_leaderboard_rejects_unknown_session(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        v2_storage.get_session_leaderboard(tmp_path / "missing.sqlite3", "missing")


def test_leaderboard_page_shows_negative_result_and_manual_refresh_is_read_only(
    tmp_path, monkeypatch
):
    database = tmp_path / "ui.sqlite3"
    session, (player,) = make_session(database, names=("Solo",))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE players SET cash_cents = 199_950 WHERE player_id = ?",
            (player["player_id"],),
        )
    monkeypatch.setattr(v2_storage, "V2_DATABASE_PATH", database)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=15).run()
    app.radio[0].set_value("Campus Tycoon 2.0 · Multiplayer").run()
    app.radio[0].set_value("Resume Game").run()
    app.text_input[0].set_value(session["join_code"])
    app.text_input[1].set_value(player["nickname"])
    app.text_input[2].set_value(player["recovery_credential"])
    app.button[0].click().run()
    app.selectbox[0].set_value("Leaderboard").run()

    assert not app.exception
    assert any("Provisional leaderboard" in item.value for item in app.info)
    assert "-€0.50" in str(app.dataframe[0].value)
    before = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    next(button for button in app.button if button.label == "Refresh leaderboard").click().run()
    after = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    assert after == before
