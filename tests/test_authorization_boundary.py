"""Security boundary probes using isolated SQLite databases only.

The Streamlit UI authenticates a player once with the recovery credential and
keeps that player's identity in server-side session state. These tests verify
that a player ID paired with the wrong session cannot cross the database
tenant boundary. They do not treat storage functions as public login APIs.
"""

import pytest

import v2_storage as storage


def _started_session(database, first_name, second_name):
    session = storage.create_game_session(database)
    first = storage.join_game_session(database, session["join_code"], first_name)
    second = storage.join_game_session(database, session["join_code"], second_name)
    storage.start_game_session(database, session["session_id"], session["host_credential"])
    return session, first, second


def _snapshot(database, session_id, player_id):
    return (
        storage.get_player_progress(database, session_id, player_id),
        storage.load_player_trade_history(database, session_id, player_id),
    )


@pytest.mark.parametrize(
    "operation",
    ["purchase", "price", "menu", "lease", "trade", "progress", "history", "report"],
)
def test_player_operations_reject_victim_id_paired_with_another_session(
    tmp_path, operation
):
    database = tmp_path / "authorization.sqlite3"
    victim_session, victim, _ = _started_session(database, "Victim", "Teammate")
    attacker_session, attacker, _ = _started_session(database, "Attacker", "Colleague")
    before = _snapshot(database, victim_session["session_id"], victim["player_id"])

    sid = attacker_session["session_id"]
    pid = victim["player_id"]
    if operation == "purchase":
        action = lambda: storage.purchase_player_stock(database, sid, pid, "bica", 1)
    elif operation == "price":
        action = lambda: storage.set_player_selling_price(database, sid, pid, "bica", "1.00")
    elif operation == "menu":
        action = lambda: storage.set_player_menu(database, sid, pid, ["bica"], expected_day=1)
    elif operation == "lease":
        action = lambda: storage.select_player_location(database, sid, pid, "chiado")
    elif operation == "trade":
        action = lambda: storage.trade_player_day(database, sid, pid, expected_day=1)
    elif operation == "progress":
        action = lambda: storage.get_player_progress(database, sid, pid)
    elif operation == "history":
        action = lambda: storage.load_player_trade_history(database, sid, pid)
    else:
        action = lambda: storage.get_player_final_report(database, sid, pid)

    with pytest.raises(ValueError, match="not found"):
        action()

    assert _snapshot(database, victim_session["session_id"], victim["player_id"]) == before
    assert storage.get_player_progress(
        database, attacker_session["session_id"], attacker["player_id"]
    )["cash_cents"] == attacker["starting_cash_cents"]


def test_event_popup_lookup_with_another_sessions_player_id_reveals_nothing(tmp_path):
    database = tmp_path / "event-boundary.sqlite3"
    victim_session, victim, _ = _started_session(database, "Victim", "Teammate")
    attacker_session, _, _ = _started_session(database, "Attacker", "Colleague")

    assert storage.load_pending_day_three_event_popup(
        database, attacker_session["session_id"], victim["player_id"]
    ) is None


def test_storage_calls_trust_the_server_caller_to_supply_the_authenticated_player_id(
    tmp_path, monkeypatch
):
    """Characterize the internal trust boundary; this is not a browser API test."""
    database = tmp_path / "trusted-caller.sqlite3"
    session, target, other = _started_session(database, "Target", "Other")
    monkeypatch.setattr(storage.v2_events, "choose_location_event", lambda *_: None)
    other_before = _snapshot(database, session["session_id"], other["player_id"])
    sid, pid = session["session_id"], target["player_id"]

    # These functions have no caller credential parameter. A trusted Python
    # caller that supplies the target's real identity acts on that player.
    storage.select_player_location(database, sid, pid, "chiado")
    storage.set_player_menu(database, sid, pid, ["bica"], expected_day=1)
    storage.set_player_selling_price(database, sid, pid, "bica", "1.00")
    storage.purchase_player_stock(database, sid, pid, "bica", 1)
    before_trade = storage.get_player_progress(database, sid, pid)
    result = storage.trade_player_day(database, sid, pid, expected_day=1)

    assert before_trade["cash_cents"] == target["starting_cash_cents"] - 20
    assert result["day"] == 1
    assert storage.get_player_progress(database, sid, pid)["current_day"] == 2
    assert _snapshot(database, sid, other["player_id"]) == other_before


def test_host_action_rejects_player_or_other_session_credentials_without_changes(tmp_path):
    database = tmp_path / "host-boundary.sqlite3"
    host_session = storage.create_game_session(database)
    host_player = storage.join_game_session(database, host_session["join_code"], "Host Player")
    storage.join_game_session(database, host_session["join_code"], "Guest")
    other_session = storage.create_game_session(database)
    storage.join_game_session(database, other_session["join_code"], "Other Host")
    before_status = storage.get_game_session(database, other_session["session_id"])["status"]

    with pytest.raises(ValueError, match="Only the host can start"):
        storage.start_game_session(
            database, host_session["session_id"], host_player["recovery_credential"]
        )
    with pytest.raises(ValueError, match="could not be resumed"):
        storage.authenticate_host(database, other_session["join_code"], host_session["host_credential"])

    assert storage.get_game_session(database, other_session["session_id"])["status"] == before_status


def test_wrong_recovery_credential_does_not_resume_or_echo_the_secret(tmp_path):
    database = tmp_path / "recovery-boundary.sqlite3"
    session, player, _ = _started_session(database, "Player", "Guest")
    wrong_secret = "definitely-not-the-player-secret"

    with pytest.raises(ValueError) as error:
        storage.resume_player_by_credentials(
            database, session["join_code"], player["nickname"], wrong_secret
        )

    assert wrong_secret not in str(error.value)
    assert storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )["cash_cents"] == player["starting_cash_cents"]


def test_solo_games_remain_isolated_and_cannot_be_joined_as_multiplayer(tmp_path):
    database = tmp_path / "solo-boundary.sqlite3"
    solo = storage.create_solo_game_session(database, nickname="Solo")
    multiplayer = storage.create_game_session(database)
    storage.join_game_session(database, multiplayer["join_code"], "Player")

    with pytest.raises(ValueError):
        storage.join_game_session(database, solo["join_code"], "Intruder")
    with pytest.raises(ValueError, match="different game mode"):
        storage.resume_player_by_credentials(
            database, solo["join_code"], solo["nickname"], solo["recovery_credential"]
        )

    solo_progress = storage.resume_solo_player_by_credentials(
        database, solo["join_code"], solo["nickname"], solo["recovery_credential"]
    )
    assert solo_progress["cash_cents"] == solo["starting_cash_cents"]
    assert solo_progress["location"] is None
