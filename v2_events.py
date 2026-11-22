"""Random, location-specific events applied only during completed V2 trades."""

from dataclasses import dataclass
import random
from collections.abc import Mapping


@dataclass(frozen=True)
class GameEvent:
    key: str
    location_key: str
    polarity: str
    name: str
    explanation: str
    effect: str
    percent: int


EVENTS_BY_LOCATION = {
    "chiado": (
        GameEvent(
            "chiado_vandalism", "chiado", "negative", "Protest and Vandalism",
            "A protest in Chiado led to vandalism at your café. You lost "
            "{lost_units} units of inventory.",
            "inventory_loss", 80,
        ),
        GameEvent(
            "chiado_christmas_lights", "chiado", "positive",
            "Christmas Lights in Chiado",
            "The Christmas lights have brought extra visitors to Chiado! Your "
            "café's potential demand increased by 25% today.",
            "demand_multiplier", 125,
        ),
    ),
    "carcavelos_nova_sbe": (
        GameEvent(
            "carcavelos_marathon", "carcavelos_nova_sbe", "negative",
            "Marathon Blocks the Marginal",
            "A marathon closed the Marginal road, keeping many customers away. "
            "Your café's potential demand fell by 50% today.",
            "demand_multiplier", 50,
        ),
        GameEvent(
            "carcavelos_sunset_festival", "carcavelos_nova_sbe", "positive",
            "NOVA Sunset Festival",
            "A sunset festival at NOVA SBE has attracted more visitors to "
            "Carcavelos! Your café's potential demand increased by 75% today.",
            "demand_multiplier", 175,
        ),
    ),
    "belem": (
        GameEvent(
            "belem_storm_charles", "belem", "negative",
            "Storm Charles",
            "Storm Charles flooded your café in Belém. You lost {lost_units} "
            "units of inventory.",
            "inventory_loss", 60,
        ),
        GameEvent(
            "belem_concert", "belem", "positive", "Concert in Belém Gardens",
            "A concert in the gardens of Belém has brought more visitors to the "
            "area! Your café's potential demand increased by 35% today.",
            "demand_multiplier", 135,
        ),
    ),
    "principe_real": (
        GameEvent(
            "principe_real_tuk_tuk", "principe_real", "negative",
            "Tuk-tuk Accident",
            "A tuk-tuk crashed into your café in Príncipe Real, destroying "
            "{lost_units} units of inventory.",
            "inventory_loss", 40,
        ),
        GameEvent(
            "principe_real_design_fair", "principe_real", "positive",
            "Príncipe Real Design & Creativity Fair",
            "A design and creativity fair has attracted more visitors to "
            "Príncipe Real! Your café's potential demand increased by 55% today.",
            "demand_multiplier", 155,
        ),
    ),
}

EVENTS_BY_KEY = {
    event.key: event
    for location_events in EVENTS_BY_LOCATION.values()
    for event in location_events
}


def format_event_message(event: Mapping[str, object]) -> str:
    """Format the approved event message using the saved event outcome."""

    key = event.get("key")
    definition = EVENTS_BY_KEY.get(key) if isinstance(key, str) else None
    if definition is None:
        raise ValueError("The saved event is not recognized.")
    if definition.effect != "inventory_loss":
        return definition.explanation

    outcome = event.get("outcome")
    if not isinstance(outcome, Mapping):
        raise ValueError("The saved event outcome is unavailable.")
    lost_units = outcome.get("total_units_destroyed")
    if type(lost_units) is not int or lost_units < 0:
        destroyed = outcome.get("destroyed_quantities", [])
        if not isinstance(destroyed, list):
            raise ValueError("The saved inventory loss is invalid.")
        lost_units = sum(
            item.get("quantity", 0)
            for item in destroyed
            if isinstance(item, Mapping)
            and type(item.get("quantity")) is int
            and item["quantity"] >= 0
        )
    if lost_units == 0:
        return {
            "chiado_vandalism": (
                "A protest in Chiado led to vandalism at your café. "
                "Fortunately, you had no stock to lose."
            ),
            "belem_storm_charles": (
                "Storm Charles flooded your café in Belém. "
                "Fortunately, you had no stock to lose."
            ),
            "principe_real_tuk_tuk": (
                "A tuk-tuk crashed into your café in Príncipe Real. "
                "Fortunately, you had no stock to lose."
            ),
        }[definition.key]
    message = definition.explanation.replace("{lost_units}", f"{lost_units:,}")
    if lost_units == 1:
        message = message.replace("1 units", "1 unit")
    return message


def choose_location_event(location_key: str, rng=random) -> GameEvent:
    """Select a location's positive or negative event with equal probability."""

    try:
        events = EVENTS_BY_LOCATION[location_key]
    except KeyError:
        raise ValueError("Events are not configured for this location.") from None
    return rng.choice(events)


def round_percentage_half_up(value: int, percentage: int) -> int:
    """Apply an integer percentage and round half up to a whole person/unit."""

    if type(value) is not int or value < 0:
        raise ValueError("Event quantities must be non-negative whole numbers.")
    if type(percentage) is not int or percentage < 0:
        raise ValueError("Event percentages must be non-negative whole numbers.")
    return (value * percentage + 50) // 100


def apply_event(
    event: GameEvent, location: Mapping[str, object], products: list[dict]
) -> tuple[dict, list[dict], dict]:
    """Apply an event to copies of one player's current trade inputs."""

    if location.get("location_key") != event.location_key:
        raise ValueError("The event does not match this player's location.")
    updated_location = dict(location)
    updated_products = [dict(product) for product in products]
    outcome = {
        "destroyed_quantities": [],
        "total_units_destroyed": 0,
        "potential_visitors_before": None,
        "potential_visitors_after": None,
        "impact_summary": "",
    }

    if event.effect == "inventory_loss":
        destroyed = []
        for product in updated_products:
            quantity = product["quantity"]
            if type(quantity) is not int or quantity < 0:
                raise ValueError("Inventory must contain non-negative whole numbers.")
            lost = round_percentage_half_up(quantity, event.percent)
            lost = min(quantity, lost)
            if lost:
                destroyed.append(
                    {
                        "product_key": product["product_key"],
                        "name": product["name"],
                        "quantity": lost,
                    }
                )
            product["quantity"] = quantity - lost
        outcome["destroyed_quantities"] = destroyed
        total_lost = sum(item["quantity"] for item in destroyed)
        outcome["total_units_destroyed"] = total_lost
        if total_lost:
            detail = ", ".join(
                f"{item['name']} ({item['quantity']})" for item in destroyed
            )
            outcome["impact_summary"] = (
                f"Destroyed {total_lost} inventory units: {detail}."
            )
        else:
            outcome["impact_summary"] = "No inventory units were available to destroy."
    elif event.effect == "demand_multiplier":
        traffic = updated_location.get("passers_by_per_day")
        if type(traffic) is not int or traffic < 0:
            raise ValueError("Daily foot traffic must be a non-negative whole number.")
        before = traffic // 10
        after = round_percentage_half_up(before, event.percent)
        updated_location["passers_by_per_day"] = after * 10
        outcome["potential_visitors_before"] = before
        outcome["potential_visitors_after"] = after
        change = after - before
        direction = "+" if change > 0 else ""
        outcome["impact_summary"] = (
            f"Potential visitors changed from {before} to {after} ({direction}{change})."
        )
    else:
        raise ValueError("The event effect is not supported.")

    return updated_location, updated_products, outcome
