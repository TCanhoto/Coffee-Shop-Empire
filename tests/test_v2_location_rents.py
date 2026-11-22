"""Approved location rent values and backward-compatible lease snapshots."""

import sqlite3

import pytest

import v2_storage
from business_logic import LOCATIONS
from v2_storage import (
    create_game_session,
    create_solo_game_session,
    get_player_progress,
    join_game_session,
    list_locations,
    load_player_trade_history,
    resume_player,
    select_player_location,
    start_game_session,
    trade_player_day,
)


APPROVED_RENTS = {
    "carcavelos_nova_sbe": 3_000,
    "principe_real": 8_500,
    "belem": 12_500,
    "chiado": 16_500,
}


def start_multiplayer(database, names=("Alex",)):
    session = create_game_session(database)
    players = [join_game_session(database, session["join_code"], name) for name in names]
    start_game_session(database, session["session_id"], session["host_credential"])
    return session, players


def test_catalogue_and_all_new_game_modes_use_approved_rents(tmp_path):
    database = tmp_path / "new-rents.sqlite3"
    assert {location.key: location.rent_per_day_cents for location in LOCATIONS} == APPROVED_RENTS
    assert {
        location["location_key"]: location["rent_per_day_cents"]
        for location in list_locations(database)
    } == APPROVED_RENTS

    session, players = start_multiplayer(database, ("Alex", "Blair"))
    select_player_location(database, session["session_id"], players[0]["player_id"], "chiado")
    select_player_location(database, session["session_id"], players[1]["player_id"], "belem")
    alex = get_player_progress(database, session["session_id"], players[0]["player_id"])
    blair = get_player_progress(database, session["session_id"], players[1]["player_id"])
    assert alex["location"]["rent_per_day_cents"] == APPROVED_RENTS["chiado"]
    assert blair["location"]["rent_per_day_cents"] == APPROVED_RENTS["belem"]

    solo = create_solo_game_session(database)
    select_player_location(database, solo["session_id"], solo["player_id"], "principe_real")
    progress = get_player_progress(database, solo["session_id"], solo["player_id"])
    assert progress["location"]["rent_per_day_cents"] == APPROVED_RENTS["principe_real"]


@pytest.mark.parametrize("location_key,rent_cents", APPROVED_RENTS.items())
def test_each_location_charges_its_exact_daily_rent_once_for_seven_days(
    tmp_path, monkeypatch, location_key, rent_cents
):
    database = tmp_path / f"seven-days-{location_key}.sqlite3"
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    session, players = start_multiplayer(database)
    player = players[0]
    select_player_location(database, session["session_id"], player["player_id"], location_key)

    # Resume reads the saved lease and must not charge rent or advance time.
    before = get_player_progress(database, session["session_id"], player["player_id"])
    resumed = resume_player(
        database, session["session_id"], player["player_id"], player["recovery_credential"]
    )
    assert resumed == before

    results = []
    for day in range(1, 8):
        results.append(
            trade_player_day(database, session["session_id"], player["player_id"], day)
        )
        if day == 3:
            after_trade = get_player_progress(
                database, session["session_id"], player["player_id"]
            )
            reopened = resume_player(
                database,
                session["session_id"],
                player["player_id"],
                player["recovery_credential"],
            )
            assert reopened == after_trade
            assert len(load_player_trade_history(
                database, session["session_id"], player["player_id"]
            )) == 3
    assert [result["rent_due_cents"] for result in results] == [rent_cents] * 7
    assert [result["rent_paid_cents"] for result in results] == [rent_cents] * 7
    history = load_player_trade_history(database, session["session_id"], player["player_id"])
    assert [day["day"] for day in history] == list(range(1, 8))
    assert [day["rent_due_cents"] for day in history] == [rent_cents] * 7
    progress = get_player_progress(database, session["session_id"], player["player_id"])
    expected_cash = 200_000 - 7 * rent_cents
    assert progress["cash_cents"] == expected_cash
    assert progress["final_game_result_cents"] == -7 * rent_cents
    with pytest.raises(ValueError, match="completed all trading days"):
        trade_player_day(database, session["session_id"], player["player_id"], 8)
    assert get_player_progress(database, session["session_id"], player["player_id"])["cash_cents"] == expected_cash


def test_players_pay_only_their_own_lease_rent(tmp_path, monkeypatch):
    database = tmp_path / "separate-rents.sqlite3"
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    session, players = start_multiplayer(database, ("Alex", "Blair"))
    select_player_location(database, session["session_id"], players[0]["player_id"], "carcavelos_nova_sbe")
    select_player_location(database, session["session_id"], players[1]["player_id"], "chiado")

    alex_day = trade_player_day(database, session["session_id"], players[0]["player_id"], 1)
    blair_day = trade_player_day(database, session["session_id"], players[1]["player_id"], 1)
    assert alex_day["rent_paid_cents"] == APPROVED_RENTS["carcavelos_nova_sbe"]
    assert blair_day["rent_paid_cents"] == APPROVED_RENTS["chiado"]
    assert get_player_progress(database, session["session_id"], players[0]["player_id"])["cash_cents"] == 200_000 - 3_000
    assert get_player_progress(database, session["session_id"], players[1]["player_id"])["cash_cents"] == 200_000 - 16_500


def test_old_leases_keep_their_rent_and_history_while_new_leases_get_updated_rent(
    tmp_path, monkeypatch
):
    database = tmp_path / "old-lease-migration.sqlite3"
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    session, players = start_multiplayer(database)
    player = players[0]
    select_player_location(database, session["session_id"], player["player_id"], "chiado")

    # Recreate a pre-snapshot save: the old lease read €80 from locations.
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER player_location_is_immutable")
        connection.execute("UPDATE locations SET rent_per_day_cents = 8000 WHERE location_key = 'chiado'")
        connection.execute("UPDATE player_locations SET rent_per_day_cents = 8000 WHERE player_id = ?", (player["player_id"],))
    day_one = trade_player_day(database, session["session_id"], player["player_id"], 1)
    assert day_one["rent_due_cents"] == 8_000
    history_before = load_player_trade_history(database, session["session_id"], player["player_id"])

    # Older schema had no player_locations rent column. Initialization must
    # snapshot the old global value before refreshing the catalogue to new rents.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE locations SET rent_per_day_cents = 8000 WHERE location_key = 'chiado'")
        connection.execute("ALTER TABLE player_locations DROP COLUMN rent_per_day_cents")

    v2_storage.initialize_v2_database(database)
    migrated = get_player_progress(database, session["session_id"], player["player_id"])
    assert migrated["location"]["rent_per_day_cents"] == 8_000
    assert {row["location_key"]: row["rent_per_day_cents"] for row in list_locations(database)}["chiado"] == 16_500
    history_after = load_player_trade_history(database, session["session_id"], player["player_id"])
    assert history_after == history_before
    assert history_after[0]["rent_due_cents"] == 8_000

    # Resume and later trading keep the signed €80 rate; a new game gets €165.
    resumed = resume_player(
        database, session["session_id"], player["player_id"], player["recovery_credential"]
    )
    assert resumed["location"]["rent_per_day_cents"] == 8_000
    day_two = trade_player_day(database, session["session_id"], player["player_id"], 2)
    assert day_two["rent_due_cents"] == 8_000

    new_session, new_players = start_multiplayer(database, ("New Player",))
    new_lease = v2_storage.select_player_location(
        database, new_session["session_id"], new_players[0]["player_id"], "chiado"
    )
    assert new_lease["rent_per_day_cents"] == 16_500
