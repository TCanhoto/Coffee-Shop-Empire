"""Day-three random-event rules and atomic storage/UI integration checks."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from business_logic import LOCATIONS
import v2_events
import v2_storage
from v2_events import EVENTS_BY_KEY, EVENTS_BY_LOCATION, apply_event


def location_data(location_key):
    location = next(item for item in LOCATIONS if item.key == location_key)
    return {
        "location_key": location.key,
        "passers_by_per_day": location.passers_by_per_day,
        "rent_per_day_cents": location.rent_per_day_cents,
        "persona_mix": location.persona_mix,
    }


class FixedChoice:
    def __init__(self, index):
        self.index = index

    def choice(self, values):
        return values[self.index]


def test_all_eight_location_events_have_the_approved_names_and_effects():
    assert {
        key: [(event.polarity, event.name, event.effect, event.percent) for event in events]
        for key, events in EVENTS_BY_LOCATION.items()
    } == {
        "chiado": [
            ("negative", "Protest and Vandalism", "inventory_loss", 80),
            ("positive", "Christmas Lights in Chiado", "demand_multiplier", 125),
        ],
        "carcavelos_nova_sbe": [
            ("negative", "Marathon Blocks the Marginal", "demand_multiplier", 50),
            ("positive", "NOVA Sunset Festival", "demand_multiplier", 175),
        ],
        "belem": [
            ("negative", "Storm Charles", "inventory_loss", 60),
            ("positive", "Concert in Belém Gardens", "demand_multiplier", 135),
        ],
        "principe_real": [
            ("negative", "Tuk-tuk Accident", "inventory_loss", 40),
            ("positive", "Príncipe Real Design & Creativity Fair", "demand_multiplier", 155),
        ],
    }


@pytest.mark.parametrize(
    ("event_key", "outcome", "expected"),
    [
        ("chiado_christmas_lights", {}, "The Christmas lights have brought extra visitors to Chiado! Your café's potential demand increased by 25% today."),
        ("chiado_vandalism", {"total_units_destroyed": 12}, "A protest in Chiado led to vandalism at your café. You lost 12 units of inventory."),
        ("chiado_vandalism", {"total_units_destroyed": 1}, "A protest in Chiado led to vandalism at your café. You lost 1 unit of inventory."),
        ("chiado_vandalism", {"total_units_destroyed": 0}, "A protest in Chiado led to vandalism at your café. Fortunately, you had no stock to lose."),
        ("carcavelos_sunset_festival", {}, "A sunset festival at NOVA SBE has attracted more visitors to Carcavelos! Your café's potential demand increased by 75% today."),
        ("carcavelos_marathon", {}, "A marathon closed the Marginal road, keeping many customers away. Your café's potential demand fell by 50% today."),
        ("belem_concert", {}, "A concert in the gardens of Belém has brought more visitors to the area! Your café's potential demand increased by 35% today."),
        ("belem_storm_charles", {"total_units_destroyed": 7}, "Storm Charles flooded your café in Belém. You lost 7 units of inventory."),
        ("principe_real_design_fair", {}, "A design and creativity fair has attracted more visitors to Príncipe Real! Your café's potential demand increased by 55% today."),
        ("principe_real_tuk_tuk", {"total_units_destroyed": 2}, "A tuk-tuk crashed into your café in Príncipe Real, destroying 2 units of inventory."),
    ],
)
def test_event_messages_use_approved_templates_and_saved_loss_counts(
    event_key, outcome, expected
):
    assert v2_events.format_event_message({"key": event_key, "outcome": outcome}) == expected


@pytest.mark.parametrize(
    ("event_key", "expected"),
    [
        ("chiado_vandalism", "A protest in Chiado led to vandalism at your café. You lost 3 units of inventory."),
        ("belem_storm_charles", "Storm Charles flooded your café in Belém. You lost 3 units of inventory."),
        ("principe_real_tuk_tuk", "A tuk-tuk crashed into your café in Príncipe Real, destroying 3 units of inventory."),
    ],
)
def test_each_inventory_event_uses_actual_saved_destroyed_units(event_key, expected):
    assert v2_events.format_event_message(
        {"key": event_key, "outcome": {"total_units_destroyed": 99}}
    ).find("99 units") >= 0
    assert v2_events.format_event_message({
        "key": event_key,
        "outcome": {"destroyed_quantities": [{"quantity": 1}, {"quantity": 2}]},
    }) == expected


@pytest.mark.parametrize("location_key", tuple(EVENTS_BY_LOCATION))
def test_positive_and_negative_events_each_have_a_fifty_percent_choice(location_key):
    negative = v2_events.choose_location_event(location_key, rng=FixedChoice(0))
    positive = v2_events.choose_location_event(location_key, rng=FixedChoice(1))
    assert negative.polarity == "negative"
    assert positive.polarity == "positive"


@pytest.mark.parametrize(
    ("baseline", "percentage", "expected"),
    [(0, 175, 0), (1, 50, 1), (3, 50, 2), (7, 135, 9), (10, 80, 8)],
)
def test_percentage_effects_round_half_up_for_people_and_inventory(
    baseline, percentage, expected
):
    assert v2_events.round_percentage_half_up(baseline, percentage) == expected


@pytest.mark.parametrize(
    ("event_key", "visitors_before", "visitors_after"),
    [
        ("chiado_christmas_lights", 300, 375),
        ("carcavelos_marathon", 120, 60),
        ("carcavelos_sunset_festival", 120, 210),
        ("belem_concert", 250, 338),
        ("principe_real_design_fair", 150, 233),
    ],
)
def test_demand_event_changes_only_the_day_three_location_input(
    event_key, visitors_before, visitors_after
):
    event = EVENTS_BY_KEY[event_key]
    location = location_data(event.location_key)
    changed_location, products, outcome = apply_event(event, location, [])
    assert outcome["potential_visitors_before"] == visitors_before
    assert outcome["potential_visitors_after"] == visitors_after
    assert changed_location["passers_by_per_day"] == visitors_after * 10
    assert products == []
    assert location["passers_by_per_day"] == visitors_before * 10


@pytest.mark.parametrize(
    ("event_key", "expected_loss"),
    [
        ("chiado_vandalism", 8),
        ("belem_storm_charles", 6),
        ("principe_real_tuk_tuk", 4),
    ],
)
def test_inventory_event_rounds_and_records_each_destroyed_product(
    event_key, expected_loss
):
    event = EVENTS_BY_KEY[event_key]
    location = location_data(event.location_key)
    products = [
        {"product_key": "bica", "name": "Bica", "quantity": 10},
        {"product_key": "off_menu", "name": "Off-menu stock", "quantity": 5},
    ]
    _, remaining, outcome = apply_event(event, location, products)
    assert [item["quantity"] for item in remaining] == [
        10 - expected_loss,
        5 - v2_events.round_percentage_half_up(5, event.percent),
    ]
    assert sum(item["quantity"] for item in outcome["destroyed_quantities"]) == (
        expected_loss + v2_events.round_percentage_half_up(5, event.percent)
    )
    assert [item["quantity"] for item in products] == [10, 5]


def _start_event_game(database, location_key, *, days=4, player_names=("First", "Second")):
    session = v2_storage.create_game_session(database, trading_days=days)
    players = [
        v2_storage.join_game_session(database, session["join_code"], nickname)
        for nickname in player_names
    ]
    v2_storage.start_game_session(database, session["session_id"], session["host_credential"])
    for player in players:
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], location_key
        )
    return session, players


def _trade(database, session, player, day):
    return v2_storage.trade_player_day(
        database, session["session_id"], player["player_id"], expected_day=day
    )


def _advance_to_day_three(database, session, player):
    assert _trade(database, session, player, 1)["event"] is None
    assert _trade(database, session, player, 2)["event"] is None
    assert v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )["current_day"] == 3


@pytest.mark.parametrize("event_key", tuple(EVENTS_BY_KEY))
def test_all_eight_events_apply_only_on_day_three_and_persist(
    tmp_path, monkeypatch, event_key
):
    database = tmp_path / f"{event_key}.sqlite3"
    event = EVENTS_BY_KEY[event_key]
    session, players = _start_event_game(database, event.location_key)
    first, other = players
    _advance_to_day_three(database, session, first)
    _advance_to_day_three(database, session, other)

    # Newly purchased active and off-menu stock must both be available to the
    # event before Day 3 sales are calculated.
    for key in ("bica", "galao", "pastel_de_nata"):
        v2_storage.purchase_player_stock(
            database, session["session_id"], first["player_id"], key, 10
        )
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: EVENTS_BY_KEY[event_key],
    )
    before = v2_storage.get_player_progress(database, session["session_id"], first["player_id"])
    old_stock = {p["product_key"]: p["quantity"] for p in before["products"]}
    result = _trade(database, session, first, 3)
    assert result["event"]["key"] == event_key
    assert result["day"] == 3
    assert result["cash_cents_after"] >= 0
    assert result["totals"]["units_sold"] >= 0

    saved = v2_storage.get_player_progress(database, session["session_id"], first["player_id"])
    destroyed = {
        row["product_key"]: row["quantity"]
        for row in result["event"]["outcome"]["destroyed_quantities"]
    }
    if event.effect == "inventory_loss":
        sold = {row["product_key"]: row["units_sold"] for row in result["products"]}
        for key, quantity in old_stock.items():
            row = next(p for p in saved["products"] if p["product_key"] == key)
            assert row["quantity"] == quantity - destroyed.get(key, 0) - sold.get(key, 0)
        assert result["event"]["outcome"]["total_units_destroyed"] == sum(destroyed.values())
    else:
        assert result["event"]["outcome"]["potential_visitors_after"] == result["potential_visitors"]

    # Same location, different player: independent random choice and result.
    other_event = next(
        choice for choice in EVENTS_BY_LOCATION[event.location_key]
        if choice.key != event.key
    )
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: other_event,
    )
    other_result = _trade(database, session, other, 3)
    assert other_result["event"]["key"] == other_event.key

    history = v2_storage.load_player_trade_history(
        database, session["session_id"], first["player_id"]
    )
    assert [day["day"] for day in history if day["event"]] == [3]
    assert history[2]["event"]["key"] == event_key
    v2_storage.initialize_v2_database(database)
    resumed = v2_storage.resume_player_by_credentials(
        database, session["join_code"], first["nickname"], first["recovery_credential"]
    )
    assert resumed["current_day"] == 4
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], first["player_id"]
    ) == history
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT day_number, status FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], first["player_id"]),
        ).fetchall()
    assert rows == [(3, "occurred")]


@pytest.mark.parametrize("days", [1, 2])
def test_games_shorter_than_three_days_never_create_events(tmp_path, days):
    database = tmp_path / f"short-{days}.sqlite3"
    session, players = _start_event_game(database, "chiado", days=days, player_names=("Only",))
    player = players[0]
    for day in range(1, days + 1):
        assert _trade(database, session, player, day)["event"] is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM player_day_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM session_event_plans").fetchone()[0] == 0


def test_days_one_two_and_four_have_no_event_and_day_three_has_exactly_one(
    tmp_path, monkeypatch
):
    database = tmp_path / "only-day-three.sqlite3"
    session, players = _start_event_game(database, "belem", days=4, player_names=("Solo",))
    player = players[0]
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["belem_concert"],
    )
    _advance_to_day_three(database, session, player)
    assert _trade(database, session, player, 3)["event"]["key"] == "belem_concert"
    assert _trade(database, session, player, 4)["event"] is None
    history = v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])
    assert [day["day"] for day in history if day["event"]] == [3]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        ).fetchone()[0] == 1


def test_concurrent_day_three_submissions_apply_one_event_and_one_trade(tmp_path, monkeypatch):
    database = tmp_path / "concurrent-day-three.sqlite3"
    session, players = _start_event_game(database, "carcavelos_nova_sbe", days=3, player_names=("Solo",))
    player = players[0]
    _advance_to_day_three(database, session, player)
    sid, pid = session["session_id"], player["player_id"]
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["carcavelos_sunset_festival"],
    )
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        try:
            return _trade(database, session, player, 3)
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    history = v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])
    assert len(history) == 3
    assert sum(day["event"] is not None for day in history) == 1
    assert history[2]["event"]["key"] == "carcavelos_sunset_festival"


def test_failed_day_three_trade_rolls_back_event_selection_and_effect(tmp_path, monkeypatch):
    database = tmp_path / "day-three-rollback.sqlite3"
    session, players = _start_event_game(database, "chiado", days=3, player_names=("Solo",))
    player = players[0]
    _advance_to_day_three(database, session, player)
    before = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location: EVENTS_BY_KEY["chiado_christmas_lights"],
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TRIGGER fail_day_three_result BEFORE INSERT ON player_daily_results
               BEGIN SELECT RAISE(ABORT, 'simulated Day 3 write failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="simulated Day 3 write failure"):
        _trade(database, session, player, 3)
    assert v2_storage.get_player_progress(database, session["session_id"], player["player_id"]) == before
    assert v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])[-1]["day"] == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], player["player_id"]),
        ).fetchone()[0] == 0


def test_inventory_event_also_destroys_off_menu_stock(tmp_path, monkeypatch):
    database = tmp_path / "off-menu-event.sqlite3"
    session, players = _start_event_game(database, "chiado", days=3, player_names=("Solo",))
    player = players[0]
    sid, pid = session["session_id"], player["player_id"]
    v2_storage.set_player_menu(database, sid, pid, ["bica", "galao", "pastel_de_nata", "brownie"], expected_day=1)
    v2_storage.purchase_player_stock(database, sid, pid, "brownie", 10)
    v2_storage.set_player_menu(database, sid, pid, ["bica", "galao", "pastel_de_nata"], expected_day=1)
    _advance_to_day_three(database, session, player)
    monkeypatch.setattr(v2_storage.v2_events, "choose_location_event", lambda location_key: EVENTS_BY_KEY["chiado_vandalism"])
    result = _trade(database, session, player, 3)
    assert result["event"]["outcome"]["destroyed_quantities"] == [
        {"product_key": "brownie", "name": "Brownie", "quantity": 8}
    ]
    brownie = next(p for p in v2_storage.get_player_progress(database, sid, pid)["products"] if p["product_key"] == "brownie")
    assert not brownie["is_active"] and brownie["quantity"] == 2


def test_old_unapplied_assignments_are_removed_and_completed_results_are_preserved(
    tmp_path, monkeypatch
):
    database = tmp_path / "legacy-events.sqlite3"
    session, players = _start_event_game(database, "chiado", days=5, player_names=("Legacy",))
    player = players[0]
    # Complete the first three days with the new rules, creating one Day 3 event.
    _advance_to_day_three(database, session, player)
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["chiado_christmas_lights"],
    )
    _trade(database, session, player, 3)
    before_history = v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])
    before_progress = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO session_event_plans VALUES (?, 2, 'legacy-plan')",
            (session["session_id"],),
        )
        connection.execute(
            "INSERT INTO player_day_events (session_id, player_id, day_number, event_key, event_name, polarity, location_key, explanation, effect, effect_percent, status, outcome_json, created_at, occurred_at, popup_acknowledged_at) VALUES (?, ?, 4, 'chiado_vandalism', 'old scheduled', 'negative', 'chiado', 'old', 'inventory_loss', 80, 'scheduled', NULL, 'legacy', NULL, NULL)",
            (session["session_id"], player["player_id"]),
        )
    v2_storage.initialize_v2_database(database)
    assert v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"]) == before_history
    assert v2_storage.get_player_progress(database, session["session_id"], player["player_id"]) == before_progress
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT day_number, status FROM player_day_events WHERE session_id = ? AND player_id = ? ORDER BY day_number",
            (session["session_id"], player["player_id"]),
        ).fetchall() == [(3, "occurred")]


def test_day_three_event_popup_acknowledgement_is_persistent_and_read_only(tmp_path, monkeypatch):
    database = tmp_path / "event-popup.sqlite3"
    session, players = _start_event_game(database, "belem", days=4, player_names=("Solo",))
    player = players[0]
    _advance_to_day_three(database, session, player)
    sid, pid = session["session_id"], player["player_id"]
    v2_storage.set_player_menu(
        database, sid, pid, ["bica", "galao", "pastel_de_nata", "brownie"], expected_day=3
    )
    monkeypatch.setattr(
        v2_storage.v2_events,
        "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["belem_storm_charles"],
    )
    v2_storage.purchase_player_stock(database, sid, pid, "brownie", 10)
    v2_storage.set_player_menu(
        database, sid, pid, ["bica", "galao", "pastel_de_nata"], expected_day=3
    )
    result = _trade(database, session, player, 3)
    assert result["event"]["outcome"]["total_units_destroyed"] > 0
    pending = v2_storage.load_pending_day_three_event_popup(database, session["session_id"], player["player_id"])
    assert pending["key"] == "belem_storm_charles"
    assert sum(row["quantity"] for row in pending["outcome"]["destroyed_quantities"]) == pending["outcome"]["total_units_destroyed"]
    progress_before = v2_storage.get_player_progress(database, session["session_id"], player["player_id"])
    history_before = v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])
    assert v2_storage.acknowledge_day_three_event_popup(database, session["session_id"], player["player_id"])
    assert v2_storage.load_pending_day_three_event_popup(database, session["session_id"], player["player_id"]) is None
    assert v2_storage.get_player_progress(database, session["session_id"], player["player_id"]) == progress_before
    assert v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"]) == history_before
    assert not v2_storage.acknowledge_day_three_event_popup(database, session["session_id"], player["player_id"])


def test_existing_completed_day_three_event_is_not_replayed_or_shown_retroactively(tmp_path):
    database = tmp_path / "legacy-completed-day-three.sqlite3"
    session, players = _start_event_game(database, "chiado", days=3, player_names=("Legacy",))
    player = players[0]
    _advance_to_day_three(database, session, player)
    v2_storage.trade_player_day(database, session["session_id"], player["player_id"], 3)
    before_history = v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"])
    # Emulate an old database before the popup acknowledgement column existed.
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE player_day_events DROP COLUMN popup_acknowledged_at")
    v2_storage.initialize_v2_database(database)
    assert v2_storage.load_player_trade_history(database, session["session_id"], player["player_id"]) == before_history
    assert v2_storage.load_pending_day_three_event_popup(database, session["session_id"], player["player_id"]) is None
