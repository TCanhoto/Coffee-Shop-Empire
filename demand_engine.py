"""Pure deterministic demand calculations for Campus Tycoon V2.

This module reads only the location and active-menu values passed to its
functions. It never opens SQLite, mutates its inputs, or updates player state.
All customer allocation uses integers and the approved largest-remainder rule.
"""

from collections.abc import Mapping, Sequence

from content import PERSONAS, PRODUCT_AFFINITIES, PRODUCT_CATALOGUE


PERSONA_KEYS = tuple(persona.key for persona in PERSONAS)

# Each tuple is the exact acceptable-price multiplier as numerator/denominator.
PRICE_LIMITS = {
    "student": (1, 1),
    "local_traditional": (5, 4),
    "digital_nomad": (3, 2),
    "healthy_plant_based": (7, 4),
    "tourist": (2, 1),
}


def allocate_largest_remainder(
    total: int,
    weights: Mapping[str, int],
    tie_order: Sequence[str],
) -> dict[str, int]:
    """Split a whole-number total by integer weights with stable tie-breaking."""

    if type(total) is not int or total < 0:
        raise ValueError("Allocation total must be a non-negative whole number.")
    if not isinstance(weights, Mapping) or not isinstance(tie_order, Sequence):
        raise ValueError("Allocation weights and tie order must be mappings and sequences.")

    keys = tuple(weights)
    if len(set(tie_order)) != len(tie_order) or set(keys) != set(tie_order):
        raise ValueError("Allocation tie order must contain each recipient exactly once.")
    if any(type(weight) is not int or weight < 0 for weight in weights.values()):
        raise ValueError("Allocation weights must be non-negative whole numbers.")

    denominator = sum(weights.values())
    allocations = {key: 0 for key in keys}
    if denominator == 0 or total == 0:
        return allocations

    remainders = {}
    allocated = 0
    for key in keys:
        numerator = total * weights[key]
        allocations[key], remainders[key] = divmod(numerator, denominator)
        allocated += allocations[key]

    order_index = {key: index for index, key in enumerate(tie_order)}
    remainder_order = sorted(
        keys, key=lambda key: (-remainders[key], order_index[key])
    )
    for key in remainder_order[: total - allocated]:
        allocations[key] += 1
    return allocations


def _persona_visitor_counts(location: Mapping[str, object]) -> tuple[int, dict[str, int]]:
    """Convert stored location percentages to canonical persona visitor counts."""

    traffic = location.get("passers_by_per_day")
    mix = location.get("persona_mix")
    if type(traffic) is not int or traffic < 0:
        raise ValueError("Daily foot traffic must be a non-negative whole number.")
    if (
        not isinstance(mix, (list, tuple))
        or len(mix) != 5
        or any(type(value) is not int or value < 0 for value in mix)
        or sum(mix) != 100
    ):
        raise ValueError("Location persona percentages must be five whole numbers totaling 100.")

    # Location tuples are stored in nomad/healthy/tourist/local/student order.
    nomad, healthy, tourist, local, student = mix
    percentages = {
        "student": student,
        "tourist": tourist,
        "digital_nomad": nomad,
        "healthy_plant_based": healthy,
        "local_traditional": local,
    }
    potential_visitors = traffic // 10
    counts = allocate_largest_remainder(
        potential_visitors, percentages, PERSONA_KEYS
    )
    return potential_visitors, counts


def _price_weight(persona_key: str, price_cents: int, reference_cents: int) -> int:
    """Return zero outside the price limit, else the approved price tier weight."""

    if type(price_cents) is not int or price_cents <= 0:
        raise ValueError("Selling price must be a positive amount in cents.")
    if type(reference_cents) is not int or reference_cents <= 0:
        raise ValueError("Reference price must be a positive amount in cents.")
    numerator, denominator = PRICE_LIMITS[persona_key]
    if price_cents * denominator > reference_cents * numerator:
        return 0
    return 2 if price_cents <= reference_cents else 1


def calculate_v2_demand(
    location: Mapping[str, object],
    active_products: list[dict],
) -> dict:
    """Return deterministic product demand and customer counts for one day.

    Inventory is read as input only: drink stock determines how many visitors
    can be served and therefore how many food opportunities exist. This
    function does not sell stock, calculate money, mutate inputs, or persist
    results. Product demand is returned in catalogue order.
    """

    if not isinstance(location, Mapping) or not isinstance(active_products, list):
        raise ValueError("A location and active product list are required for demand.")

    potential_visitors, persona_visitors = _persona_visitor_counts(location)
    product_by_key = {}
    for product in active_products:
        if not isinstance(product, Mapping):
            raise ValueError("Each demand product must be a mapping.")
        key = product.get("product_key")
        if not isinstance(key, str) or key in product_by_key:
            raise ValueError("Demand products must have unique catalogue keys.")
        if key not in PRODUCT_AFFINITIES:
            raise ValueError("Demand product is not in the approved catalogue.")
        for field, minimum in (
            ("selected_price_cents", 1),
            ("reference_price_cents", 1),
            ("quantity", 0),
        ):
            value = product.get(field)
            if type(value) is not int or value < minimum:
                raise ValueError(f"Product {field} is invalid.")
        if type(product.get("is_drink")) is not bool:
            raise ValueError("Each demand product must identify whether it is a drink.")
        product_by_key[key] = product

    product_order = tuple(
        product.key for product in PRODUCT_CATALOGUE
        if product.key in product_by_key
    )
    demands = {key: 0 for key in product_order}
    demand_by_persona = {
        key: {persona_key: 0 for persona_key in PERSONA_KEYS}
        for key in product_order
    }
    drink_keys = tuple(
        key for key in product_order if product_by_key[key]["is_drink"]
    )
    food_keys = tuple(
        key for key in product_order if not product_by_key[key]["is_drink"]
    )
    persona_indexes = {key: index for index, key in enumerate(PERSONA_KEYS)}

    def allocate_category(
        persona_key: str,
        customer_count: int,
        candidate_keys: tuple[str, ...],
    ) -> dict[str, int]:
        weights = {}
        for product_key in candidate_keys:
            product = product_by_key[product_key]
            affinity = PRODUCT_AFFINITIES[product_key][persona_indexes[persona_key]]
            price_weight = _price_weight(
                persona_key,
                product["selected_price_cents"],
                product["reference_price_cents"],
            )
            weights[product_key] = affinity * price_weight
        return allocate_largest_remainder(customer_count, weights, candidate_keys)

    # Each persona's drink requests are divided across suitable menu drinks.
    for persona_key in PERSONA_KEYS:
        requests = allocate_category(
            persona_key, persona_visitors[persona_key], drink_keys
        )
        for product_key, count in requests.items():
            demand_by_persona[product_key][persona_key] += count
            demands[product_key] += count

    # Only visitors who can buy an in-stock drink may receive food opportunities.
    served_by_persona = {key: 0 for key in PERSONA_KEYS}
    customers_served = 0
    for product_key in drink_keys:
        product = product_by_key[product_key]
        product_sales = min(demands[product_key], product["quantity"])
        customers_served += product_sales
        served_personas = allocate_largest_remainder(
            product_sales, demand_by_persona[product_key], PERSONA_KEYS
        )
        for persona_key, count in served_personas.items():
            served_by_persona[persona_key] += count

    food_buyer_slots = customers_served * 3 // 5
    food_slots_by_persona = allocate_largest_remainder(
        food_buyer_slots, served_by_persona, PERSONA_KEYS
    )
    for persona_key in PERSONA_KEYS:
        requests = allocate_category(
            persona_key, food_slots_by_persona[persona_key], food_keys
        )
        for product_key, count in requests.items():
            demand_by_persona[product_key][persona_key] += count
            demands[product_key] += count

    return {
        "potential_visitors": potential_visitors,
        "persona_visitors": persona_visitors,
        "customers_served": customers_served,
        "lost_visitors": potential_visitors - customers_served,
        "food_buyer_slots": food_buyer_slots,
        "food_slots_by_persona": food_slots_by_persona,
        "served_customers_by_persona": served_by_persona,
        "demand_by_persona": demand_by_persona,
        "products": {
            key: {
                "product_key": key,
                "demand": demands[key],
                "is_drink": product_by_key[key]["is_drink"],
            }
            for key in product_order
        },
    }
