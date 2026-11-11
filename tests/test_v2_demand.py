"""Acceptance tests for the approved deterministic V2 customer demand model."""

from copy import deepcopy

import pytest

from business_logic import LOCATIONS, calculate_v2_trade
from demand_engine import (
    allocate_largest_remainder,
    calculate_v2_demand,
)
from content import PRODUCT_CATALOGUE
from v2_storage import (
    create_game_session,
    get_player_progress,
    join_game_session,
    load_player_trade_history,
    select_player_location,
    start_game_session,
)


def location(key="carcavelos_nova_sbe"):
    item = next(item for item in LOCATIONS if item.key == key)
    # This is the same dictionary shape returned by v2_storage for locations.
    nomad, healthy, tourist, local, student = item.persona_mix
    return {
        "location_key": item.key,
        "passers_by_per_day": item.passers_by_per_day,
        "rent_per_day_cents": item.rent_per_day_cents,
        "persona_mix": (nomad, healthy, tourist, local, student),
    }


def menu(*keys, prices=None, stocks=None):
    prices = prices or {}
    stocks = stocks or {}
    catalog = {item.key: item for item in PRODUCT_CATALOGUE}
    return [
        {
            "product_key": key,
            "name": catalog[key].name,
            "purchase_cost_cents": catalog[key].purchase_cost_cents,
            "reference_price_cents": catalog[key].reference_price_cents,
            "selected_price_cents": prices.get(key, catalog[key].reference_price_cents),
            "quantity": stocks.get(key, 10_000),
            "is_drink": catalog[key].is_drink,
        }
        for key in keys
    ]


@pytest.mark.parametrize(
    ("key", "potential"),
    [
        ("carcavelos_nova_sbe", 120),
        ("chiado", 300),
        ("principe_real", 150),
        ("belem", 250),
    ],
)
def test_potential_visitors_are_ten_percent_of_traffic(key, potential):
    result = calculate_v2_demand(location(key), menu("bica"))
    assert result["potential_visitors"] == potential


@pytest.mark.parametrize("key", [item.key for item in LOCATIONS])
def test_persona_counts_sum_to_potential_visitors(key):
    result = calculate_v2_demand(location(key), menu("bica"))
    assert sum(result["persona_visitors"].values()) == result["potential_visitors"]


def test_persona_largest_remainder_tie_uses_canonical_persona_order():
    allocation = allocate_largest_remainder(
        150,
        {"student": 5, "tourist": 20, "digital_nomad": 30, "healthy_plant_based": 35, "local_traditional": 10},
        ("student", "tourist", "digital_nomad", "healthy_plant_based", "local_traditional"),
    )
    assert allocation == {
        "student": 8,
        "tourist": 30,
        "digital_nomad": 45,
        "healthy_plant_based": 52,
        "local_traditional": 15,
    }


def test_carcavelos_persona_visitors_match_location_mix():
    result = calculate_v2_demand(location(), menu("bica"))
    assert result["persona_visitors"] == {
        "student": 60,
        "tourist": 6,
        "digital_nomad": 24,
        "healthy_plant_based": 18,
        "local_traditional": 12,
    }


def test_zero_affinity_personas_are_not_allocated_to_product():
    result = calculate_v2_demand(location(), menu("matcha_latte"))
    assert result["demand_by_persona"]["matcha_latte"]["student"] == 0
    assert result["demand_by_persona"]["matcha_latte"]["local_traditional"] == 0


def test_affinity_three_has_three_times_weight_of_affinity_one():
    result = calculate_v2_demand(location(), menu("bica", "galao"))
    student = result["demand_by_persona"]
    assert student["bica"]["student"] == 45
    assert student["galao"]["student"] == 15


def test_below_reference_product_gets_double_price_weight():
    products = menu("bica", "galao", prices={"bica": 90, "galao": 151})
    result = calculate_v2_demand(location(), products)
    # For a nomad, equal affinities split 24 visitors in the 2:1 price-weight ratio.
    assert result["demand_by_persona"]["bica"]["digital_nomad"] == 16
    assert result["demand_by_persona"]["galao"]["digital_nomad"] == 8


@pytest.mark.parametrize(
    ("persona", "product", "price", "allowed"),
    [
        ("student", "bica", 90, True), ("student", "bica", 91, False),
        ("local_traditional", "bica", 112, True), ("local_traditional", "bica", 113, False),
        ("digital_nomad", "bica", 135, True), ("digital_nomad", "bica", 136, False),
        ("healthy_plant_based", "fresh_orange_juice", 525, True),
        ("healthy_plant_based", "fresh_orange_juice", 526, False),
        ("tourist", "bica", 180, True), ("tourist", "bica", 181, False),
    ],
)
def test_persona_price_caps_are_exact_and_inclusive(persona, product, price, allowed):
    result = calculate_v2_demand(
        location(), menu(product, prices={product: price})
    )
    assert (result["demand_by_persona"][product][persona] > 0) is allowed


@pytest.mark.parametrize(("price", "expected"), [(90, 102), (120, 30), (140, 6), (180, 6), (181, 0)])
def test_carcavelos_bica_price_series(price, expected):
    result = calculate_v2_demand(location(), menu("bica", prices={"bica": price}))
    assert result["products"]["bica"]["demand"] == expected


def test_affinity_preferences_partition_each_persona_drink_demand():
    result = calculate_v2_demand(location(), menu("bica", "galao", "matcha_latte"))
    for persona, visitors in result["persona_visitors"].items():
        assigned = sum(
            result["demand_by_persona"][key][persona]
            for key in ("bica", "galao", "matcha_latte")
        )
        assert assigned <= visitors


def test_no_suitable_drink_means_no_customers_or_food_slots():
    result = calculate_v2_demand(location(), menu("matcha_latte"))
    # Student and local affinity for matcha is zero, but other personas can buy.
    assert result["demand_by_persona"]["matcha_latte"]["student"] == 0
    assert result["served_customers_by_persona"]["student"] == 0
    assert result["served_customers_by_persona"]["local_traditional"] == 0
    assert result["food_slots_by_persona"]["student"] == 0
    assert result["food_slots_by_persona"]["local_traditional"] == 0
    none_suitable = calculate_v2_demand(location(), menu("bica", prices={"bica": 181}))
    assert none_suitable["customers_served"] == 0
    assert none_suitable["food_buyer_slots"] == 0


def test_stockouts_cap_sales_without_substitution_and_count_lost_visitors():
    products = menu("bica", "galao", stocks={"bica": 3, "galao": 0})
    result = calculate_v2_trade(100_000, location(), products)
    assert result["products"][0]["demand"] > 3
    assert result["products"][0]["units_sold"] == 3
    assert result["products"][1]["units_sold"] == 0
    assert result["customers_served"] == result["totals"]["units_sold"]
    assert result["lost_visitors"] == result["potential_visitors"] - result["customers_served"]
    assert result["lost_visitors"] == 117


def test_food_slots_and_sales_are_a_subset_of_drink_customers():
    result = calculate_v2_trade(
        100_000,
        location(),
        menu("bica", "pastel_de_nata", "brownie"),
    )
    assert result["food_buyer_slots"] == (result["customers_served"] * 3) // 5
    food_sold = sum(
        item["units_sold"] for item in result["products"]
        if not item["is_drink"]
    )
    assert food_sold <= result["food_buyer_slots"] <= result["customers_served"]


def test_complete_carcavelos_example_has_proposed_drink_and_food_totals():
    result = calculate_v2_trade(
        100_000,
        location(),
        menu("bica", "galao", "pastel_de_nata", "brownie"),
    )
    by_key = {item["product_key"]: item for item in result["products"]}
    assert (by_key["bica"]["demand"], by_key["galao"]["demand"]) == (66, 36)
    assert (by_key["pastel_de_nata"]["demand"], by_key["brownie"]["demand"]) == (35, 26)
    assert result["customers_served"] == 102
    assert result["lost_visitors"] == 18
    assert result["food_buyer_slots"] == 61
    drink_sold = sum(item["units_sold"] for item in result["products"] if item["is_drink"])
    food_sold = sum(item["units_sold"] for item in result["products"] if not item["is_drink"])
    assert drink_sold == result["customers_served"]
    assert food_sold == 61
    assert result["totals"]["units_sold"] == drink_sold + food_sold


def test_product_remainder_tie_uses_catalogue_order():
    allocation = allocate_largest_remainder(1, {"bica": 1, "galao": 1}, ("bica", "galao"))
    assert allocation == {"bica": 1, "galao": 0}


def test_same_inputs_are_deterministic_and_location_changes_demand():
    products = menu("bica")
    first = calculate_v2_demand(location(), products)
    second = calculate_v2_demand(location(), deepcopy(products))
    chiado = calculate_v2_demand(location("chiado"), products)
    assert first == second
    assert first["products"]["bica"]["demand"] == 102
    assert chiado["products"]["bica"]["demand"] == 255


def test_demand_function_is_pure_and_does_not_mutate_input_data():
    input_location = location()
    input_products = menu("bica", "galao", "pastel_de_nata", "brownie")
    original_location = deepcopy(input_location)
    original_products = deepcopy(input_products)

    first = calculate_v2_demand(input_location, input_products)
    second = calculate_v2_demand(input_location, input_products)

    assert first == second
    assert input_location == original_location
    assert input_products == original_products


def test_calculating_demand_does_not_change_saved_player_data(tmp_path):
    database = tmp_path / "demand-read-only.sqlite3"
    session = create_game_session(database)
    player = join_game_session(database, session["join_code"], "Alex")
    start_game_session(database, session["session_id"], session["host_credential"])
    select_player_location(
        database,
        session["session_id"],
        player["player_id"],
        "carcavelos_nova_sbe",
    )
    before = get_player_progress(database, session["session_id"], player["player_id"])
    history_before = load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    active_products = [item for item in before["products"] if item["is_active"]]

    calculate_v2_demand(before["location"], active_products)

    assert get_player_progress(database, session["session_id"], player["player_id"]) == before
    assert load_player_trade_history(
        database, session["session_id"], player["player_id"]
    ) == history_before


def test_invalid_location_mix_and_negative_stock_are_rejected():
    bad_location = location()
    bad_location["persona_mix"] = (20, 15, 5, 10, 40)
    with pytest.raises(ValueError):
        calculate_v2_demand(bad_location, menu("bica"))
    bad_products = menu("bica", stocks={"bica": -1})
    with pytest.raises(ValueError):
        calculate_v2_trade(100_000, location(), bad_products)


def test_demand_sales_and_lost_visitors_are_non_negative_whole_numbers():
    products = menu(
        "bica", "galao", "pastel_de_nata", "brownie",
        stocks={"bica": 4, "galao": 0, "pastel_de_nata": 2, "brownie": 0},
    )
    demand = calculate_v2_demand(location(), products)
    trade = calculate_v2_trade(100_000, location(), products)
    assert all(type(row["demand"]) is int and row["demand"] >= 0
               for row in demand["products"].values())
    assert type(trade["lost_visitors"]) is int and trade["lost_visitors"] >= 0
    for row, original in zip(trade["products"], products, strict=True):
        assert type(row["units_sold"]) is int and row["units_sold"] >= 0
        assert row["units_sold"] <= original["quantity"]
