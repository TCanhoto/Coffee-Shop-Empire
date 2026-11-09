"""Storage tests for the V2 multiplayer data foundation."""

import sqlite3

import pytest

from storage import DATABASE_PATH, initialize_database
from v2_storage import (
    create_game_session,
    get_game_session,
    get_player_progress,
    initialize_v2_database,
    join_game_session,
    load_player_trade_history,
    purchase_player_stock,
    resume_player,
    set_player_selling_price,
    start_game_session,
    trade_player_day,
)


def make_session(database, **options):
    return create_game_session(database, **options)


def join(database, session, nickname):
    return join_game_session(database, session["join_code"], nickname)


def test_two_separate_sessions_are_created_with_defaults(tmp_path):
    database = tmp_path / "game-v2.sqlite3"

    first = make_session(database)
    second = make_session(database)

    assert first["session_id"] != second["session_id"]
    assert first["join_code"] != second["join_code"]
    assert first["trading_days"] == second["trading_days"] == 7
    assert first["starting_budget_cents"] == second["starting_budget_cents"] == 200_000
    assert first["status"] == second["status"] == "waiting"
    assert first["created_at"]


def test_session_settings_are_configurable_and_budget_uses_cents(tmp_path):
    session = make_session(
        tmp_path / "game-v2.sqlite3", trading_days=12, starting_budget="1250.75"
    )

    assert session["trading_days"] == 12
    assert session["starting_budget_cents"] == 125_075


@pytest.mark.parametrize(
    ("trading_days", "starting_budget"),
    [(0, "2000.00"), (1.5, "2000.00"), (7, "0"), (7, "bad")],
)
def test_invalid_session_settings_are_rejected(tmp_path, trading_days, starting_budget):
    with pytest.raises(ValueError):
        make_session(
            tmp_path / "game-v2.sqlite3",
            trading_days=trading_days,
            starting_budget=starting_budget,
        )


def test_two_players_can_join_one_session_and_first_player_is_host(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)

    host = join(database, session, "Alex")
    player = join(database, session, "Sam")

    assert host["session_id"] == player["session_id"] == session["session_id"]
    assert host["player_id"] != player["player_id"]
    assert host["is_host"] is True
    assert player["is_host"] is False
    assert host["starting_cash_cents"] == player["starting_cash_cents"] == 200_000


def test_nickname_is_unique_ignoring_case_and_outer_spaces_per_session(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    join(database, session, "  Alex  ")

    with pytest.raises(ValueError, match="already used"):
        join(database, session, "aLeX")


def test_same_nickname_is_allowed_in_different_sessions(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    first_session = make_session(database)
    second_session = make_session(database)

    first = join(database, first_session, "Alex")
    second = join(database, second_session, " alex ")

    assert first["player_id"] != second["player_id"]
    assert first["session_id"] != second["session_id"]


def test_players_have_independent_cash_inventory_and_trade_history(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"])

    purchase_player_stock(
        database, session["session_id"], first["player_id"], "coffee", 10
    )
    first_before_trade = get_player_progress(
        database, session["session_id"], first["player_id"]
    )
    second_before_trade = get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    first_coffee_before_trade = next(
        p for p in first_before_trade["products"] if p["product_key"] == "coffee"
    )
    second_coffee_before_trade = next(
        p for p in second_before_trade["products"] if p["product_key"] == "coffee"
    )
    assert first_before_trade["cash_cents"] == 198_000
    assert first_coffee_before_trade["quantity"] == 10
    assert second_before_trade["cash_cents"] == 200_000
    assert second_coffee_before_trade["quantity"] == 0

    trade_player_day(database, session["session_id"], first["player_id"])

    first_progress = get_player_progress(
        database, session["session_id"], first["player_id"]
    )
    second_progress = get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    first_coffee = next(p for p in first_progress["products"] if p["product_key"] == "coffee")
    second_coffee = next(p for p in second_progress["products"] if p["product_key"] == "coffee")

    assert first_progress["cash_cents"] == 202_000
    assert first_progress["current_day"] == 2
    assert first_coffee["quantity"] == 0
    assert second_progress["cash_cents"] == 200_000
    assert second_progress["current_day"] == 1
    assert second_coffee["quantity"] == 0
    assert len(load_player_trade_history(database, session["session_id"], first["player_id"])) == 1
    assert load_player_trade_history(database, session["session_id"], second["player_id"]) == []


def test_player_action_cannot_target_another_session_player(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    first_session = make_session(database)
    second_session = make_session(database)
    player = join(database, second_session, "Alex")
    start_game_session(database, second_session["session_id"])
    before = get_player_progress(database, second_session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="not found"):
        purchase_player_stock(
            database, first_session["session_id"], player["player_id"], "coffee", 1
        )

    after = get_player_progress(database, second_session["session_id"], player["player_id"])
    assert after == before


def test_progress_and_history_survive_reopening_and_recovery_is_verified(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"])
    purchase_player_stock(database, session["session_id"], player["player_id"], "coffee", 3)
    set_player_selling_price(
        database, session["session_id"], player["player_id"], "coffee", "4.25"
    )
    trade_player_day(database, session["session_id"], player["player_id"])

    initialize_v2_database(database)  # a new connection models reopening the file
    resumed = resume_player(
        database,
        session["session_id"],
        player["player_id"],
        player["recovery_credential"],
    )
    history = load_player_trade_history(database, session["session_id"], player["player_id"])
    coffee = next(p for p in resumed["products"] if p["product_key"] == "coffee")

    assert resumed["cash_cents"] == 200_675
    assert resumed["current_day"] == 2
    assert coffee["quantity"] == 0
    assert coffee["selected_price_cents"] == 425
    assert len(history) == 1
    assert history[0]["day"] == 1

    with pytest.raises(ValueError, match="could not be resumed"):
        resume_player(database, session["session_id"], player["player_id"], "wrong-token")


def test_recovery_credential_is_stored_as_a_hash(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")

    with sqlite3.connect(database) as connection:
        stored_hash = connection.execute(
            "SELECT recovery_credential_hash FROM players WHERE player_id = ?",
            (player["player_id"],),
        ).fetchone()[0]

    assert stored_hash != player["recovery_credential"]
    assert len(stored_hash) == 64


def test_session_finishes_after_each_player_completes_and_ids_are_immutable(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database, trading_days=1)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"])

    trade_player_day(database, session["session_id"], first["player_id"])
    assert get_game_session(database, session["session_id"])["status"] == "active"
    trade_player_day(database, session["session_id"], second["player_id"])
    assert get_game_session(database, session["session_id"])["status"] == "finished"

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="player ID cannot be changed"):
            connection.execute(
                "UPDATE players SET player_id = ? WHERE player_id = ?",
                ("replacement-id", first["player_id"]),
            )


def test_failed_player_creation_rolls_back_player_and_inventory_rows(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    initialize_v2_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TRIGGER fail_player_inventory
               BEFORE INSERT ON player_inventory
               BEGIN SELECT RAISE(ABORT, 'simulated inventory failure'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="simulated inventory failure"):
        join(database, session, "Alex")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM player_inventory").fetchone()[0] == 0


def test_rejected_purchase_does_not_partially_change_player_state(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database, starting_budget="10.00")
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"])
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="afford"):
        purchase_player_stock(
            database, session["session_id"], player["player_id"], "coffee", 6
        )

    after = get_player_progress(database, session["session_id"], player["player_id"])
    assert after == before


def test_v2_database_does_not_change_the_existing_v1_database(tmp_path):
    v1_database = tmp_path / "campus_tycoon.sqlite3"
    v2_database = tmp_path / "campus_tycoon_v2.sqlite3"
    initialize_database(v1_database)
    with sqlite3.connect(v1_database) as connection:
        before_schema = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        before_run = connection.execute("SELECT * FROM game_run").fetchall()

    initialize_v2_database(v2_database)

    with sqlite3.connect(v1_database) as connection:
        assert connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall() == before_schema
        assert connection.execute("SELECT * FROM game_run").fetchall() == before_run
    assert DATABASE_PATH.name == "campus_tycoon.sqlite3"
