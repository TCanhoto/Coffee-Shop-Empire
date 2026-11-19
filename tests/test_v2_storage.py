"""Storage tests for the V2 multiplayer data foundation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from storage import DATABASE_PATH, initialize_database
from content import DEFAULT_MENU_KEYS, MAX_MENU_SIZE, PRODUCT_CATALOGUE
import v2_storage
from v2_storage import (
    authenticate_host,
    create_game_session,
    get_game_session,
    get_game_session_by_code,
    get_player_progress,
    initialize_v2_database,
    join_game_session,
    list_session_players,
    load_player_trade_history,
    list_locations,
    purchase_player_stock,
    resume_player,
    resume_player_by_credentials,
    set_player_selling_price,
    set_player_menu,
    select_player_location,
    start_game_session,
    trade_player_day,
)


def make_session(database, **options):
    return create_game_session(database, **options)


def join(database, session, nickname):
    return join_game_session(database, session["join_code"], nickname)


def confirm_location(database, session, player, location="carcavelos_nova_sbe"):
    return select_player_location(
        database, session["session_id"], player["player_id"], location
    )


def active_menu(progress):
    return {product["product_key"] for product in progress["products"] if product["is_active"]}


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


def test_player_menu_is_saved_and_restored_on_resume(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player)
    selected = ["bica", "matcha_latte", "brownie", "granola_bowl"]

    assert set_player_menu(
        database, session["session_id"], player["player_id"], selected, expected_day=1
    ) == selected
    initialize_v2_database(database)
    resumed = resume_player(
        database,
        session["session_id"],
        player["player_id"],
        player["recovery_credential"],
    )

    assert active_menu(resumed) == set(selected)
    assert len(active_menu(resumed)) == 4


def test_invalid_menus_are_rejected_without_changing_saved_menu(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])
    product_keys = [product.key for product in PRODUCT_CATALOGUE]

    invalid_menus = [
        ([], "at least one product"),
        (product_keys[:6], f"at most {MAX_MENU_SIZE}"),
        (["bica", "bica"], "more than once"),
        (["pastel_de_nata", "brownie"], "at least one drink"),
    ]
    for choices, message in invalid_menus:
        with pytest.raises(ValueError, match=message):
            set_player_menu(
                database,
                session["session_id"],
                player["player_id"],
                choices,
                expected_day=1,
            )
        assert get_player_progress(
            database, session["session_id"], player["player_id"]
        ) == before

    set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        product_keys[:MAX_MENU_SIZE],
        expected_day=1,
    )
    assert len(
        active_menu(get_player_progress(database, session["session_id"], player["player_id"]))
    ) == MAX_MENU_SIZE


def test_sqlite_enforces_menu_cap_without_affecting_other_players(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"], session["host_credential"])
    five_products = [product.key for product in PRODUCT_CATALOGUE[:5]]
    set_player_menu(database, session["session_id"], first["player_id"], five_products,
                    expected_day=1)

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="at most 5"):
            connection.execute(
                "INSERT INTO player_menu (session_id, player_id, product_key) VALUES (?, ?, ?)",
                (session["session_id"], first["player_id"], "brownie"),
            )

    assert active_menu(
        get_player_progress(database, session["session_id"], second["player_id"])
    ) == set(DEFAULT_MENU_KEYS)


def test_legacy_menu_is_preserved_and_can_be_reduced_before_next_save(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Legacy")
    start_game_session(database, session["session_id"], session["host_credential"])
    legacy_keys = [product.key for product in PRODUCT_CATALOGUE[:6]]
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER player_menu_maximum_size")
        connection.execute(
            "DELETE FROM player_menu WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        )
        connection.executemany(
            "INSERT INTO player_menu (session_id, player_id, product_key) VALUES (?, ?, ?)",
            [(session["session_id"], player["player_id"], key) for key in legacy_keys],
        )
        connection.execute(
            "UPDATE player_inventory SET quantity = 7 "
            "WHERE session_id = ? AND player_id = ? AND product_key = 'brownie'",
            (session["session_id"], player["player_id"]),
        )
    initialize_v2_database(database)

    assert active_menu(
        get_player_progress(database, session["session_id"], player["player_id"])
    ) == set(legacy_keys)
    with pytest.raises(ValueError, match="at most 5"):
        set_player_menu(database, session["session_id"], player["player_id"], legacy_keys,
                        expected_day=1)
    assert active_menu(
        get_player_progress(database, session["session_id"], player["player_id"])
    ) == set(legacy_keys)

    reduced = legacy_keys[:5]
    set_player_menu(database, session["session_id"], player["player_id"], reduced,
                    expected_day=1)
    progress = get_player_progress(database, session["session_id"], player["player_id"])
    assert active_menu(progress) == set(reduced)
    assert next(item["quantity"] for item in progress["products"]
                if item["product_key"] == "brownie") == 7


def test_menus_are_independent_between_players(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"], session["host_credential"])
    first_menu = ["oat_flat_white", "plant_based_toastie"]
    set_player_menu(
        database, session["session_id"], first["player_id"], first_menu, expected_day=1
    )

    assert active_menu(
        get_player_progress(database, session["session_id"], first["player_id"])
    ) == set(first_menu)
    assert active_menu(
        get_player_progress(database, session["session_id"], second["player_id"])
    ) == set(DEFAULT_MENU_KEYS)


def test_removing_menu_item_preserves_its_stock_and_does_not_rewrite_history(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database, trading_days=3)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player)
    set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        ["bica", "brownie"],
        expected_day=1,
    )
    purchase_player_stock(database, session["session_id"], player["player_id"], "brownie", 2)
    purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 3)
    set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        ["bica"],
        expected_day=1,
    )
    with pytest.raises(ValueError, match="not in this player's active menu"):
        purchase_player_stock(
            database, session["session_id"], player["player_id"], "brownie", 1
        )
    with pytest.raises(ValueError, match="not in this player's active menu"):
        set_player_selling_price(
            database, session["session_id"], player["player_id"], "brownie", "2.75"
        )

    first_day = trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )
    assert [row["product_key"] for row in first_day["products"]] == ["bica"]
    progress_after_trade = get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    brownie = next(row for row in progress_after_trade["products"] if row["product_key"] == "brownie")
    assert brownie["quantity"] == 2
    assert brownie["is_active"] is False
    history_before_menu_edit = load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    with pytest.raises(ValueError, match="trading day changed"):
        set_player_menu(
            database,
            session["session_id"],
            player["player_id"],
            ["bica"],
            expected_day=1,
        )
    assert active_menu(
        get_player_progress(database, session["session_id"], player["player_id"])
    ) == {"bica"}

    set_player_menu(
        database,
        session["session_id"],
        player["player_id"],
        ["bica", "brownie"],
        expected_day=2,
    )
    assert load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == history_before_menu_edit


@pytest.mark.parametrize("invalid_price", ["0", "-0.01", "1.234", "invalid"])
def test_invalid_prices_are_rejected_without_state_changes(tmp_path, invalid_price):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError):
        set_player_selling_price(
            database, session["session_id"], player["player_id"], "bica", invalid_price
        )

    assert get_player_progress(database, session["session_id"], player["player_id"]) == before


def test_fixed_lisbon_location_data_and_persona_mix_totals(tmp_path):
    locations = list_locations(tmp_path / "game-v2.sqlite3")

    assert [
        (
            location["name"],
            location["passers_by_per_day"],
            location["rent_per_day_cents"],
            location["persona_mix"],
        )
        for location in locations
    ] == [
        ("Carcavelos / Nova SBE", 1200, 3000, (20, 15, 5, 10, 50)),
        ("Chiado", 3000, 8000, (15, 15, 45, 15, 10)),
        ("Príncipe Real", 1500, 6000, (30, 35, 20, 10, 5)),
        ("Belém", 2500, 5500, (5, 10, 60, 25, 0)),
    ]
    assert all(sum(location["persona_mix"]) == 100 for location in locations)


def test_players_select_independent_locations_and_choice_persists(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"], session["host_credential"])

    confirm_location(database, session, first, "chiado")
    assert get_player_progress(
        database, session["session_id"], second["player_id"]
    )["location"] is None
    confirm_location(database, session, second, "belem")

    first_after_reopen = resume_player(
        database,
        session["session_id"],
        first["player_id"],
        first["recovery_credential"],
    )
    second_after_reopen = get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    assert first_after_reopen["location"]["name"] == "Chiado"
    assert second_after_reopen["location"]["name"] == "Belém"
    assert first_after_reopen["cash_cents"] == second_after_reopen["cash_cents"]
    assert first_after_reopen["products"] == second_after_reopen["products"]


def test_confirmed_location_cannot_be_changed_or_overwritten(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player, "chiado")
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="already confirmed"):
        confirm_location(database, session, player, "belem")

    assert get_player_progress(database, session["session_id"], player["player_id"]) == before
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
            connection.execute(
                "UPDATE player_locations SET location_key = 'belem' WHERE player_id = ?",
                (player["player_id"],),
            )


def test_invalid_location_confirmation_is_rejected_without_saving(tmp_path):
    database = tmp_path / "invalid-location.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="valid café location"):
        confirm_location(database, session, player, "not-a-real-location")

    assert get_player_progress(database, session["session_id"], player["player_id"]) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM player_locations WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        ).fetchone()[0] == 0


def test_trade_is_rejected_before_location_confirmation_without_changes(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="location before trading"):
        trade_player_day(database, session["session_id"], player["player_id"], expected_day=1)

    assert get_player_progress(database, session["session_id"], player["player_id"]) == before
    assert load_player_trade_history(database, session["session_id"], player["player_id"]) == []


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


@pytest.mark.parametrize(
    ("trading_days", "starting_budget"),
    [(31, "2000.00"), (7, "0.99"), (7, "10000.01")],
)
def test_host_game_settings_reject_values_outside_documented_ranges(
    tmp_path, trading_days, starting_budget
):
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


def test_session_host_secret_is_private_and_required_to_start(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    assert "host_credential_hash" not in get_game_session(database, session["session_id"])
    with pytest.raises(ValueError, match="Only the host"):
        start_game_session(database, session["session_id"], player["recovery_credential"])
    with pytest.raises(ValueError, match="Only the host"):
        start_game_session(database, session["session_id"], "wrong-host-secret")
    start_game_session(database, session["session_id"], session["host_credential"])
    assert get_game_session(database, session["session_id"])["status"] == "active"


def test_host_credential_is_hashed_and_lobby_only_exposes_nicknames(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    join(database, session, "Alex")
    with sqlite3.connect(database) as connection:
        host_hash = connection.execute(
            "SELECT host_credential_hash FROM game_sessions WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()[0]
    assert host_hash != session["host_credential"]
    assert [row["nickname"] for row in list_session_players(database, session["session_id"])] == ["Alex"]
    assert authenticate_host(database, session["join_code"], session["host_credential"])["session_id"] == session["session_id"]
    with pytest.raises(ValueError, match="Host controls could not be resumed"):
        authenticate_host(database, session["join_code"], "wrong-secret")


def test_phase_1a_database_gets_additive_host_column_without_losing_sessions(tmp_path):
    database = tmp_path / "old-v2.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE game_sessions (
                session_id TEXT PRIMARY KEY,
                join_code TEXT NOT NULL UNIQUE,
                trading_days INTEGER NOT NULL,
                starting_budget_cents INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO game_sessions VALUES
               ('existing-session', 'ABC234', 7, 200000, 'waiting', '2026-01-01T00:00:00+00:00')"""
        )

    initialize_v2_database(database)
    with sqlite3.connect(database) as connection:
        session = connection.execute(
            "SELECT join_code, status, host_credential_hash FROM game_sessions WHERE session_id = ?",
            ("existing-session",),
        ).fetchone()
    assert session == ("ABC234", "waiting", None)


def test_code_lookup_and_resume_with_nickname_and_recovery_secret(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    assert get_game_session_by_code(database, session["join_code"].lower())["session_id"] == session["session_id"]
    resumed = resume_player_by_credentials(
        database, session["join_code"].lower(), " alex ", player["recovery_credential"]
    )
    assert resumed["player_id"] == player["player_id"]
    with pytest.raises(ValueError, match="could not be resumed"):
        resume_player_by_credentials(database, session["join_code"], "Alex", "wrong")


def test_invalid_code_and_empty_nickname_are_rejected(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    with pytest.raises(ValueError, match="six-character"):
        join_game_session(database, "bad", "Alex")
    with pytest.raises(ValueError, match="not found"):
        join_game_session(database, "ZZZZZZ", "Alex")
    with pytest.raises(ValueError, match="cannot be empty"):
        join_game_session(database, session["join_code"], "   ")


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


def test_players_have_independent_cash_inventory_and_trade_history(tmp_path, monkeypatch):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, first)
    confirm_location(database, session, second)

    purchase_player_stock(
        database, session["session_id"], first["player_id"], "bica", 10
    )
    first_before_trade = get_player_progress(
        database, session["session_id"], first["player_id"]
    )
    second_before_trade = get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    first_coffee_before_trade = next(
        p for p in first_before_trade["products"] if p["product_key"] == "bica"
    )
    second_coffee_before_trade = next(
        p for p in second_before_trade["products"] if p["product_key"] == "bica"
    )
    assert first_before_trade["cash_cents"] == 199_800
    assert first_coffee_before_trade["quantity"] == 10
    assert second_before_trade["cash_cents"] == 200_000
    assert second_coffee_before_trade["quantity"] == 0

    first_trade = trade_player_day(
        database, session["session_id"], first["player_id"], expected_day=1
    )

    first_progress = get_player_progress(
        database, session["session_id"], first["player_id"]
    )
    second_progress = get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    first_coffee = next(p for p in first_progress["products"] if p["product_key"] == "bica")
    second_coffee = next(p for p in second_progress["products"] if p["product_key"] == "bica")

    assert first_progress["cash_cents"] == (
        first_before_trade["cash_cents"]
        + first_trade["totals"]["revenue_cents"]
        - first_trade["rent_paid_cents"]
    )
    assert first_progress["current_day"] == 2
    assert first_coffee["quantity"] == 0
    assert second_progress["cash_cents"] == 200_000
    assert second_progress["current_day"] == 1
    assert second_coffee["quantity"] == 0
    assert len(load_player_trade_history(database, session["session_id"], first["player_id"])) == 1
    assert load_player_trade_history(database, session["session_id"], second["player_id"]) == []


def test_price_changes_are_isolated_between_players(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    first = join(database, session, "First")
    second = join(database, session, "Second")
    start_game_session(database, session["session_id"], session["host_credential"])

    set_player_selling_price(
        database, session["session_id"], first["player_id"], "bica", "5.25"
    )
    first_coffee = next(
        row for row in get_player_progress(database, session["session_id"], first["player_id"])["products"]
        if row["product_key"] == "bica"
    )
    second_coffee = next(
        row for row in get_player_progress(database, session["session_id"], second["player_id"])["products"]
        if row["product_key"] == "bica"
    )
    assert first_coffee["selected_price_cents"] == 525
    assert second_coffee["selected_price_cents"] == 90


def test_player_action_cannot_target_another_session_player(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    first_session = make_session(database)
    second_session = make_session(database)
    player = join(database, second_session, "Alex")
    start_game_session(
        database, second_session["session_id"], second_session["host_credential"]
    )
    before = get_player_progress(database, second_session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="not found"):
        purchase_player_stock(
            database, first_session["session_id"], player["player_id"], "bica", 1
        )

    after = get_player_progress(database, second_session["session_id"], player["player_id"])
    assert after == before


def test_progress_and_history_survive_reopening_and_recovery_is_verified(tmp_path, monkeypatch):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player)
    purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 3)
    set_player_selling_price(
        database, session["session_id"], player["player_id"], "bica", "1.20"
    )
    trade_player_day(database, session["session_id"], player["player_id"], expected_day=1)

    initialize_v2_database(database)  # a new connection models reopening the file
    resumed = resume_player(
        database,
        session["session_id"],
        player["player_id"],
        player["recovery_credential"],
    )
    history = load_player_trade_history(database, session["session_id"], player["player_id"])
    coffee = next(p for p in resumed["products"] if p["product_key"] == "bica")

    assert resumed["cash_cents"] == 197_300
    assert resumed["current_day"] == 2
    assert coffee["quantity"] == 0
    assert coffee["selected_price_cents"] == 120
    assert len(history) == 1
    assert history[0]["day"] == 1

    with pytest.raises(ValueError, match="could not be resumed"):
        resume_player(database, session["session_id"], player["player_id"], "wrong-token")


def test_approved_demand_example_is_traded_and_customer_counts_are_saved(tmp_path, monkeypatch):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    monkeypatch.setattr(v2_storage, "_get_or_create_session_event", lambda *args: (None, None))
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player, "carcavelos_nova_sbe")
    keys = ["bica", "galao", "pastel_de_nata", "brownie"]
    set_player_menu(
        database, session["session_id"], player["player_id"], keys, expected_day=1
    )
    for product_key, units in zip(keys, (66, 36, 35, 26), strict=True):
        purchase_player_stock(
            database, session["session_id"], player["player_id"], product_key, units
        )

    trade = trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )
    rows = {item["product_key"]: item for item in trade["products"]}
    assert {key: rows[key]["demand"] for key in keys} == {
        "bica": 66,
        "galao": 36,
        "pastel_de_nata": 35,
        "brownie": 26,
    }
    assert trade["potential_visitors"] == 120
    assert trade["customers_served"] == 102
    assert trade["lost_visitors"] == 18
    assert trade["food_buyer_slots"] == 61
    assert trade["food_opportunities_not_fulfilled"] == 0

    initialize_v2_database(database)
    history = load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    assert len(history) == 1
    assert history[0]["potential_visitors"] == 120
    assert history[0]["customers_served"] == 102
    assert history[0]["lost_visitors"] == 18
    assert history[0]["food_buyer_slots"] == 61


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
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, first)
    confirm_location(database, session, second)

    trade_player_day(database, session["session_id"], first["player_id"], expected_day=1)
    assert get_game_session(database, session["session_id"])["status"] == "active"
    with pytest.raises(ValueError, match="completed all trading days"):
        purchase_player_stock(
            database, session["session_id"], first["player_id"], "bica", 1
        )
    with pytest.raises(ValueError, match="completed all trading days"):
        trade_player_day(
            database, session["session_id"], first["player_id"], expected_day=2
        )
    trade_player_day(database, session["session_id"], second["player_id"], expected_day=1)
    assert get_game_session(database, session["session_id"])["status"] == "finished"
    first_progress = get_player_progress(database, session["session_id"], first["player_id"])
    assert first_progress["current_day"] == 2
    with pytest.raises(ValueError, match="completed all trading days"):
        purchase_player_stock(database, session["session_id"], first["player_id"], "bica", 1)
    with pytest.raises(ValueError, match="completed all trading days"):
        trade_player_day(database, session["session_id"], first["player_id"], expected_day=2)

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="player ID cannot be changed"):
            connection.execute(
                "UPDATE players SET player_id = ? WHERE player_id = ?",
                ("replacement-id", first["player_id"]),
            )


def test_repeated_stale_day_submission_does_not_complete_the_next_day(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database, trading_days=3)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player)
    first = trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=1
    )
    assert first["day"] == 1

    with pytest.raises(ValueError, match="already completed"):
        trade_player_day(
            database, session["session_id"], player["player_id"], expected_day=1
        )

    progress = get_player_progress(database, session["session_id"], player["player_id"])
    history = load_player_trade_history(database, session["session_id"], player["player_id"])
    assert progress["current_day"] == 2
    assert [item["day"] for item in history] == [1]
    with sqlite3.connect(database) as connection:
        event_rows = connection.execute(
            "SELECT status FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        ).fetchall()
        assert connection.execute(
            "SELECT COUNT(*) FROM session_event_plans WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()[0] == 1
    assert sum(status == "occurred" for (status,) in event_rows) == 1
    assert len(event_rows) in {1, 2}


def test_two_simultaneous_day_submissions_commit_exactly_one_result(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database, trading_days=3)
    player = join(database, session, "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    confirm_location(database, session, player)
    initialize_v2_database(database)
    barrier = Barrier(2)

    def submit_same_day():
        barrier.wait(timeout=3)
        try:
            return trade_player_day(
                database,
                session["session_id"],
                player["player_id"],
                expected_day=1,
            )
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit_same_day(), range(2)))

    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, ValueError) for item in results) == 1
    progress = get_player_progress(database, session["session_id"], player["player_id"])
    history = load_player_trade_history(database, session["session_id"], player["player_id"])
    assert progress["current_day"] == 2
    assert [item["day"] for item in history] == [1]
    with sqlite3.connect(database) as connection:
        event_rows = connection.execute(
            "SELECT status FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        ).fetchall()
        assert connection.execute(
            "SELECT COUNT(*) FROM session_event_plans WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()[0] == 1
    assert sum(status == "occurred" for (status,) in event_rows) == 1
    assert len(event_rows) in {1, 2}


def test_invalid_waiting_and_price_actions_leave_player_data_unchanged(tmp_path):
    database = tmp_path / "game-v2.sqlite3"
    session = make_session(database)
    player = join(database, session, "Alex")
    before = get_player_progress(database, session["session_id"], player["player_id"])
    with pytest.raises(ValueError, match="not active"):
        purchase_player_stock(database, session["session_id"], player["player_id"], "bica", 1)
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])
    with pytest.raises(ValueError):
        set_player_selling_price(
            database, session["session_id"], player["player_id"], "bica", "not a price"
        )
    assert get_player_progress(database, session["session_id"], player["player_id"]) == before


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
    start_game_session(database, session["session_id"], session["host_credential"])
    before = get_player_progress(database, session["session_id"], player["player_id"])

    with pytest.raises(ValueError, match="afford"):
        purchase_player_stock(
            database, session["session_id"], player["player_id"], "bica", 51
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


def test_repeated_purchase_for_same_day_and_stock_is_rejected(tmp_path):
    database = tmp_path / "purchase-retry.sqlite3"
    session = create_game_session(database)
    player = join_game_session(database, session["join_code"], "Alex")
    session_id, player_id = session["session_id"], player["player_id"]
    start_game_session(database, session_id, session["host_credential"])
    purchase_player_stock(
        database, session_id, player_id, "bica", 3, expected_day=1, expected_stock=0
    )
    after_first = get_player_progress(database, session_id, player_id)
    with pytest.raises(ValueError, match="day or stock changed"):
        purchase_player_stock(
            database, session_id, player_id, "bica", 3, expected_day=1, expected_stock=0
        )
    assert get_player_progress(database, session_id, player_id) == after_first

    purchase_player_stock(
        database, session_id, player_id, "bica", 3, expected_day=1, expected_stock=3
    )
    after_second = get_player_progress(database, session_id, player_id)
    bica = next(product for product in after_second["products"] if product["product_key"] == "bica")
    assert bica["quantity"] == 6
