"""Pure event rules and persistent event-to-trade integration checks."""

import json
import sqlite3

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


def test_all_eight_location_events_have_the_approved_effects_and_names():
    assert {
        key: [(event.polarity, event.name, event.effect, event.percent) for event in events]
        for key, events in EVENTS_BY_LOCATION.items()
    } == {
        "chiado": [
            ("negative", "Protest and vandalism", "inventory_loss", 80),
            ("positive", "Christmas Lights in Chiado", "demand_multiplier", 125),
        ],
        "carcavelos_nova_sbe": [
            ("negative", "Marathon blocks the Marginal", "demand_multiplier", 50),
            ("positive", "NOVA Sunset Festival", "demand_multiplier", 175),
        ],
        "belem": [
            ("negative", "Storm Charles floods the café", "inventory_loss", 60),
            ("positive", "Concert in Belém Gardens", "demand_multiplier", 135),
        ],
        "principe_real": [
            ("negative", "Tuk-tuk crashes into the café", "inventory_loss", 40),
            ("positive", "Príncipe Real Design & Creativity Fair", "demand_multiplier", 155),
        ],
    }


@pytest.mark.parametrize("location_key", tuple(EVENTS_BY_LOCATION))
def test_positive_and_negative_events_each_have_a_fifty_percent_choice(location_key):
    negative = v2_events.choose_location_event(location_key, rng=FixedChoice(0))
    positive = v2_events.choose_location_event(location_key, rng=FixedChoice(1))

    assert negative.polarity == "negative"
    assert positive.polarity == "positive"


def test_session_event_count_is_one_or_two_equally_and_one_when_no_future_day():
    assert v2_events.choose_event_count(False, rng=FixedChoice(1)) == 1
    assert v2_events.choose_event_count(True, rng=FixedChoice(0)) == 1
    assert v2_events.choose_event_count(True, rng=FixedChoice(1)) == 2


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
def test_demand_events_adjust_only_that_days_potential_visitors(
    event_key, visitors_before, visitors_after
):
    event = EVENTS_BY_KEY[event_key]
    location = location_data(event.location_key)
    original_traffic = location["passers_by_per_day"]

    changed_location, products, outcome = apply_event(event, location, [])

    assert outcome["potential_visitors_before"] == visitors_before
    assert outcome["potential_visitors_after"] == visitors_after
    assert changed_location["passers_by_per_day"] == visitors_after * 10
    assert products == []
    assert location["passers_by_per_day"] == original_traffic


@pytest.mark.parametrize(
    ("event_key", "expected_loss"),
    [
        ("chiado_vandalism", 8),
        ("belem_storm_charles", 6),
        ("principe_real_tuk_tuk", 4),
    ],
)
def test_inventory_events_record_loss_per_product_without_mutating_inputs(
    event_key, expected_loss
):
    event = EVENTS_BY_KEY[event_key]
    location = location_data(event.location_key)
    products = [
        {"product_key": "bica", "name": "Bica", "quantity": 10},
        {"product_key": "galao", "name": "Galão", "quantity": 5},
    ]

    changed_location, remaining, outcome = apply_event(event, location, products)

    assert [item["quantity"] for item in remaining] == [
        10 - expected_loss,
        5 - v2_events.round_percentage_half_up(5, event.percent),
    ]
    assert sum(item["quantity"] for item in outcome["destroyed_quantities"]) == (
        expected_loss + v2_events.round_percentage_half_up(5, event.percent)
    )
    assert [item["quantity"] for item in products] == [10, 5]
    assert changed_location == location


def _start_event_game(database, location_key, *, days=1):
    session = v2_storage.create_game_session(database, trading_days=days)
    first = v2_storage.join_game_session(database, session["join_code"], "First")
    second = v2_storage.join_game_session(database, session["join_code"], "Second")
    v2_storage.start_game_session(
        database, session["session_id"], session["host_credential"]
    )
    for player in (first, second):
        v2_storage.select_player_location(
            database, session["session_id"], player["player_id"], location_key
        )
        for product_key in ("bica", "galao", "pastel_de_nata"):
            v2_storage.purchase_player_stock(
                database, session["session_id"], player["player_id"], product_key, 10
            )
    return session, first, second


@pytest.mark.parametrize("event_key", tuple(EVENTS_BY_KEY))
def test_each_location_event_is_applied_saved_and_never_replayed(
    tmp_path, monkeypatch, event_key
):
    database = tmp_path / f"{event_key}.sqlite3"
    event = EVENTS_BY_KEY[event_key]
    session, first, second = _start_event_game(database, event.location_key)
    monkeypatch.setattr(v2_storage.v2_events, "choose_event_count", lambda _: 1)
    monkeypatch.setattr(
        v2_storage.v2_events, "choose_location_event",
        lambda location_key: EVENTS_BY_KEY[event_key],
    )
    before = v2_storage.get_player_progress(database, session["session_id"], first["player_id"])
    second_before = v2_storage.get_player_progress(
        database, session["session_id"], second["player_id"]
    )
    first_cash_before = before["cash_cents"]
    quantities_before = {
        item["product_key"]: item["quantity"]
        for item in before["products"] if item["is_active"]
    }

    result = v2_storage.trade_player_day(
        database, session["session_id"], first["player_id"], expected_day=1
    )

    assert result["event"]["key"] == event_key
    assert result["event"]["polarity"] == event.polarity
    assert result["cash_cents_after"] >= 0
    assert result["totals"]["units_sold"] >= 0
    assert result["customers_served"] >= 0
    if event.effect == "demand_multiplier":
        before_visitors = before["location"]["passers_by_per_day"] // 10
        expected_visitors = v2_events.round_percentage_half_up(
            before_visitors, event.percent
        )
        assert result["potential_visitors"] == expected_visitors
        assert result["event"]["outcome"]["potential_visitors_before"] == before_visitors
        assert result["event"]["outcome"]["potential_visitors_after"] == expected_visitors
        assert v2_storage.get_player_progress(
            database, session["session_id"], first["player_id"]
        )["location"]["passers_by_per_day"] == before["location"]["passers_by_per_day"]
    else:
        destroyed = {
            item["product_key"]: item["quantity"]
            for item in result["event"]["outcome"]["destroyed_quantities"]
        }
        assert set(destroyed) == set(quantities_before)
        saved = v2_storage.get_player_progress(
            database, session["session_id"], first["player_id"]
        )
        sold = {item["product_key"]: item["units_sold"] for item in result["products"]}
        for product_key, quantity_before in quantities_before.items():
            remaining = next(
                item["quantity"] for item in saved["products"]
                if item["product_key"] == product_key
            )
            assert remaining == quantity_before - destroyed[product_key] - sold[product_key]
    assert result["cash_cents_after"] == (
        first_cash_before + result["totals"]["revenue_cents"] - result["rent_paid_cents"]
    )
    assert v2_storage.get_player_progress(
        database, session["session_id"], second["player_id"]
    ) == second_before
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], second["player_id"]
    ) == []

    history_before_restart = v2_storage.load_player_trade_history(
        database, session["session_id"], first["player_id"]
    )
    assert history_before_restart[0]["event"]["key"] == event_key
    v2_storage.initialize_v2_database(database)
    resumed = v2_storage.resume_player(
        database, session["session_id"], first["player_id"], first["recovery_credential"]
    )
    assert resumed["current_day"] == 2
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], first["player_id"]
    ) == history_before_restart
    with pytest.raises(ValueError, match="completed all trading days"):
        v2_storage.trade_player_day(
            database, session["session_id"], first["player_id"], expected_day=1
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM player_day_events WHERE session_id = ? AND player_id = ?",
            (session["session_id"], first["player_id"]),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM player_day_events WHERE session_id = ? AND status = 'occurred'",
            (session["session_id"],),
        ).fetchone()[0] == 1


def test_second_event_is_assigned_once_to_a_random_future_player_day(tmp_path, monkeypatch):
    database = tmp_path / "second-event.sqlite3"
    session, first, second = _start_event_game(database, "chiado", days=2)
    monkeypatch.setattr(v2_storage.v2_events, "choose_event_count", lambda _: 2)
    monkeypatch.setattr(
        v2_storage.v2_events, "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["chiado_christmas_lights"],
    )
    original_choice = v2_storage.random.choice

    def choose_second_player(slots):
        if slots and isinstance(slots[0], dict):
            return next(slot for slot in slots if slot["player_id"] == second["player_id"])
        return original_choice(slots)

    monkeypatch.setattr(v2_storage.random, "choice", choose_second_player)

    first_result = v2_storage.trade_player_day(
        database, session["session_id"], first["player_id"], expected_day=1
    )
    assert first_result["event"]["key"] == "chiado_christmas_lights"
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], second["player_id"]
    ) == []
    with sqlite3.connect(database) as connection:
        assignments = connection.execute(
            """SELECT player_id, day_number, status FROM player_day_events
               WHERE session_id = ? ORDER BY player_id, day_number""",
            (session["session_id"],),
        ).fetchall()
        assert connection.execute(
            "SELECT planned_event_count FROM session_event_plans WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone() == (2,)
    assert len(assignments) == 2
    assert sum(row[2] == "occurred" for row in assignments) == 1
    assert sum(row[2] == "scheduled" for row in assignments) == 1

    v2_storage.initialize_v2_database(database)
    second_result = v2_storage.trade_player_day(
        database, session["session_id"], second["player_id"], expected_day=1
    )
    assert second_result["event"]["key"] == "chiado_christmas_lights"
    assert v2_storage.load_player_trade_history(
        database, session["session_id"], second["player_id"]
    )[0]["event"]["name"] == "Christmas Lights in Chiado"


def test_event_plans_and_history_are_isolated_between_sessions(tmp_path, monkeypatch):
    database = tmp_path / "two-sessions.sqlite3"
    first_session, first, _ = _start_event_game(database, "belem")
    second_session = v2_storage.create_game_session(database, trading_days=1)
    other = v2_storage.join_game_session(database, second_session["join_code"], "Other")
    v2_storage.start_game_session(
        database, second_session["session_id"], second_session["host_credential"]
    )
    v2_storage.select_player_location(
        database, second_session["session_id"], other["player_id"], "belem"
    )
    monkeypatch.setattr(v2_storage.v2_events, "choose_event_count", lambda _: 1)
    monkeypatch.setattr(
        v2_storage.v2_events, "choose_location_event",
        lambda location_key: EVENTS_BY_KEY["belem_storm_charles"],
    )

    v2_storage.trade_player_day(
        database, first_session["session_id"], first["player_id"], expected_day=1
    )
    assert v2_storage.load_player_trade_history(
        database, second_session["session_id"], other["player_id"]
    ) == []
    v2_storage.trade_player_day(
        database, second_session["session_id"], other["player_id"], expected_day=1
    )
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT session_id, COUNT(*) FROM player_day_events GROUP BY session_id ORDER BY session_id"
        ).fetchall()
    assert dict(rows) == {first_session["session_id"]: 1, second_session["session_id"]: 1}
