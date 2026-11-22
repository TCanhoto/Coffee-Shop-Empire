"""Product definitions and small, pure business-rule helpers.

Money is stored as whole euro cents (for example, €2.00 is 200 cents). This
avoids tiny rounding errors that can happen with ordinary decimal fractions.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping

from demand_engine import calculate_v2_demand


@dataclass(frozen=True)
class Product:
    """The fixed details of one product in the cafe."""

    key: str
    name: str
    purchase_cost_cents: int
    reference_price_cents: int


PRODUCTS = (
    Product("coffee", "Coffee", 200, 400),
    Product("sandwich", "Sandwich", 300, 600),
    Product("cookie", "Cookie", 100, 200),
)


@dataclass(frozen=True)
class Location:
    """A fictional V2 café location and its planned customer composition."""

    key: str
    name: str
    description: str
    passers_by_per_day: int
    rent_per_day_cents: int
    persona_mix: tuple[int, int, int, int, int]


# Persona percentages are stored as game data for later demand work. The player
# interface deliberately shows only the location's traffic and rent.
LOCATIONS = (
    Location("carcavelos_nova_sbe", "Carcavelos / Nova SBE", "A campus location with a strong student presence.", 1200, 3000, (20, 15, 5, 10, 50)),
    Location("chiado", "Chiado", "A busy central district popular with shoppers and visitors.", 3000, 16500, (15, 15, 45, 15, 10)),
    Location("principe_real", "Príncipe Real", "A lively neighbourhood with residents and café visitors.", 1500, 8500, (30, 35, 20, 10, 5)),
    Location("belem", "Belém", "A historic riverside area that attracts many visitors.", 2500, 12500, (5, 10, 60, 25, 0)),
)

STARTING_CASH_CENTS = 10_000
TOTAL_TRADING_DAYS = 5


@dataclass(frozen=True)
class PurchaseResult:
    """The balances that should result from one accepted stock purchase."""

    cash_cents: int
    quantity: int
    total_cost_cents: int


def calculate_purchase(
    cash_cents: int,
    current_quantity: int,
    unit_cost_cents: int,
    quantity: object,
) -> PurchaseResult:
    """Check a purchase and calculate its new balances without changing data."""

    # bool is a subclass of int in Python, so use an exact type check here.
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("Purchase quantity must be a positive whole number.")

    total_cost_cents = quantity * unit_cost_cents
    if total_cost_cents > cash_cents:
        raise ValueError("You do not have enough cash to afford this purchase.")

    return PurchaseResult(
        cash_cents=cash_cents - total_cost_cents,
        quantity=current_quantity + quantity,
        total_cost_cents=total_cost_cents,
    )


def price_to_cents(price: object) -> int:
    """Validate a euro price and convert it to integer cents."""

    if isinstance(price, bool):
        raise ValueError("Selling price must be a positive amount with at most two decimal places.")

    try:
        amount = Decimal(str(price).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid selling price, such as 4.00.") from None

    if not amount.is_finite():
        raise ValueError("Selling price must be a finite amount.")
    if amount.as_tuple().exponent < -2:
        raise ValueError("Selling price can have at most two decimal places.")
    if amount <= 0:
        raise ValueError("Selling price must be greater than zero.")

    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError("Selling price can have at most two decimal places.")
    return int(cents)


def calculate_demand(selling_price_cents: int, reference_price_cents: int) -> int:
    """Return deterministic daily demand for a product, in units."""

    if type(selling_price_cents) is not int or selling_price_cents <= 0:
        raise ValueError("Selling price must be a positive amount in cents.")
    if type(reference_price_cents) is not int or reference_price_cents <= 0:
        raise ValueError("Reference price must be a positive amount in cents.")

    if selling_price_cents <= reference_price_cents:
        return 10
    if selling_price_cents <= 2 * reference_price_cents:
        return 5
    return 0


def calculate_v2_trade(
    cash_cents: int,
    location: Mapping[str, object],
    products: list[dict],
) -> dict:
    """Calculate V2 sales, rent settlement, and cash without changing state."""

    if type(cash_cents) is not int or cash_cents < 0:
        raise ValueError("Cash cannot be negative.")
    rent_due_cents = location.get("rent_per_day_cents")
    if type(rent_due_cents) is not int or rent_due_cents < 0:
        raise ValueError("Daily rent must be a non-negative whole amount in cents.")
    demand = calculate_v2_demand(location, products)
    by_key = {product["product_key"]: product for product in products}
    results = []
    totals = {
        "demand": 0,
        "units_sold": 0,
        "revenue_cents": 0,
        "cost_of_goods_sold_cents": 0,
        "gross_profit_cents": 0,
    }
    for key, demand_row in demand["products"].items():
        product = by_key[key]
        sold = min(demand_row["demand"], product["quantity"])
        revenue = sold * product["selected_price_cents"]
        cost = sold * product["purchase_cost_cents"]
        item = {
            "product_key": key,
            "name": product.get("name", key),
            "is_drink": product["is_drink"],
            "demand": demand_row["demand"],
            "units_sold": sold,
            "revenue_cents": revenue,
            "cost_of_goods_sold_cents": cost,
            "gross_profit_cents": revenue - cost,
            "remaining_quantity": product["quantity"] - sold,
        }
        results.append(item)
        for total_key in totals:
            totals[total_key] += item[total_key]

    food_sold = sum(
        item["units_sold"] for item in results if not item["is_drink"]
    )
    cash_after_sales_cents = cash_cents + totals["revenue_cents"]
    rent_paid_cents = min(cash_after_sales_cents, rent_due_cents)
    rent_shortfall_cents = rent_due_cents - rent_paid_cents
    return {
        "products": results,
        "totals": totals,
        "cash_cents_after": cash_after_sales_cents - rent_paid_cents,
        "rent_due_cents": rent_due_cents,
        "rent_paid_cents": rent_paid_cents,
        "rent_shortfall_cents": rent_shortfall_cents,
        "bankrupt": rent_shortfall_cents > 0,
        "potential_visitors": demand["potential_visitors"],
        "persona_visitors": demand["persona_visitors"],
        "customers_served": demand["customers_served"],
        "lost_visitors": demand["lost_visitors"],
        "food_buyer_slots": demand["food_buyer_slots"],
        "food_opportunities_not_fulfilled": demand["food_buyer_slots"] - food_sold,
        "demand_by_persona": demand["demand_by_persona"],
        "served_customers_by_persona": demand["served_customers_by_persona"],
    }


def calculate_trade(cash_cents: int, products: list[dict]) -> dict:
    """Calculate one day's sales without changing cash, inventory, or storage."""

    if type(cash_cents) is not int or cash_cents < 0:
        raise ValueError("Cash cannot be negative.")

    results = []
    totals = {
        "demand": 0,
        "units_sold": 0,
        "revenue_cents": 0,
        "cost_of_goods_sold_cents": 0,
        "gross_profit_cents": 0,
    }
    total_revenue_cents = 0

    for product in products:
        quantity = product["quantity"]
        unit_cost_cents = product["purchase_cost_cents"]
        selling_price_cents = product["selected_price_cents"]
        demand = calculate_demand(
            selling_price_cents, product["reference_price_cents"]
        )

        if type(quantity) is not int or quantity < 0:
            raise ValueError("Inventory cannot be negative.")
        if type(unit_cost_cents) is not int or unit_cost_cents < 0:
            raise ValueError("Purchase cost cannot be negative.")

        units_sold = min(demand, quantity)
        revenue_cents = units_sold * selling_price_cents
        cost_of_goods_sold_cents = units_sold * unit_cost_cents
        gross_profit_cents = revenue_cents - cost_of_goods_sold_cents

        result = {
            "product_key": product["product_key"],
            "name": product["name"],
            "demand": demand,
            "units_sold": units_sold,
            "revenue_cents": revenue_cents,
            "cost_of_goods_sold_cents": cost_of_goods_sold_cents,
            "gross_profit_cents": gross_profit_cents,
            "remaining_quantity": quantity - units_sold,
        }
        results.append(result)

        for key in totals:
            totals[key] += result[key]
        total_revenue_cents += revenue_cents

    return {
        "products": results,
        "totals": totals,
        # Sales add revenue to cash. The purchase cost is not deducted again.
        "cash_cents_after": cash_cents + total_revenue_cents,
    }


def calculate_final_results(cash_cents: int, products: list[dict]) -> dict:
    """Value remaining inventory and calculate the overall gain or loss."""

    if type(cash_cents) is not int or cash_cents < 0:
        raise ValueError("Cash cannot be negative.")

    inventory_value_cents = 0
    for product in products:
        quantity = product["quantity"]
        unit_cost_cents = product["purchase_cost_cents"]
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Inventory cannot be negative.")
        if type(unit_cost_cents) is not int or unit_cost_cents < 0:
            raise ValueError("Purchase cost cannot be negative.")
        inventory_value_cents += quantity * unit_cost_cents

    return {
        "cash_cents": cash_cents,
        "remaining_stock_value_cents": inventory_value_cents,
        "overall_gain_loss_cents": (
            cash_cents + inventory_value_cents - STARTING_CASH_CENTS
        ),
    }


def format_euros(amount_cents: int) -> str:
    """Turn integer cents into a readable euro amount."""

    sign = "-" if amount_cents < 0 else ""
    euros, cents = divmod(abs(amount_cents), 100)
    return f"{sign}€{euros:,}.{cents:02d}"
