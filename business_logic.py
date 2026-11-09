"""Product definitions and small, pure business-rule helpers.

Money is stored as whole euro cents (for example, €2.00 is 200 cents). This
avoids tiny rounding errors that can happen with ordinary decimal fractions.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


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


def format_euros(amount_cents: int) -> str:
    """Turn integer cents into a readable euro amount."""

    euros, cents = divmod(amount_cents, 100)
    return f"€{euros:,}.{cents:02d}"
