"""SQLite helpers for creating and loading the saved game."""

from pathlib import Path
import sqlite3

from business_logic import (
    PRODUCTS,
    STARTING_CASH_CENTS,
    TOTAL_TRADING_DAYS,
    calculate_trade,
    calculate_purchase,
    price_to_cents,
)


# This path is based on this source file, so the database stays in the project
# folder even if the player launches Streamlit from a different directory.
DATABASE_PATH = Path(__file__).resolve().parent / "campus_tycoon.sqlite3"


def initialize_database(database_path: str | Path = DATABASE_PATH) -> None:
    """Create the database and first run only when they do not already exist."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purchase_cost_cents INTEGER NOT NULL,
                reference_price_cents INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS game_run (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash_cents INTEGER NOT NULL,
                current_day INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory (
                product_key TEXT PRIMARY KEY REFERENCES products(product_key),
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                selected_price_cents INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trading_days (
                day INTEGER PRIMARY KEY,
                cash_cents_after INTEGER NOT NULL,
                total_demand INTEGER NOT NULL,
                total_units_sold INTEGER NOT NULL,
                total_revenue_cents INTEGER NOT NULL,
                total_cost_of_goods_sold_cents INTEGER NOT NULL,
                total_gross_profit_cents INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_results (
                day INTEGER NOT NULL REFERENCES trading_days(day),
                product_key TEXT NOT NULL REFERENCES products(product_key),
                demand INTEGER NOT NULL,
                units_sold INTEGER NOT NULL,
                revenue_cents INTEGER NOT NULL,
                cost_of_goods_sold_cents INTEGER NOT NULL,
                gross_profit_cents INTEGER NOT NULL,
                PRIMARY KEY (day, product_key)
            );
            """
        )

        # A transaction makes sure the initial run and its product rows appear
        # together. If the app starts again, the existing run is left alone.
        with connection:
            for product in PRODUCTS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO products
                        (product_key, name, purchase_cost_cents,
                         reference_price_cents)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        product.key,
                        product.name,
                        product.purchase_cost_cents,
                        product.reference_price_cents,
                    ),
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO game_run (id, cash_cents, current_day)
                VALUES (1, ?, 1)
                """,
                (STARTING_CASH_CENTS,),
            )

            for product in PRODUCTS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO inventory
                        (product_key, quantity, selected_price_cents)
                    VALUES (?, 0, ?)
                    """,
                    (product.key, product.reference_price_cents),
                )


def load_run(database_path: str | Path = DATABASE_PATH) -> dict:
    """Return the saved run and product rows in a simple dictionary."""

    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            "SELECT cash_cents, current_day FROM game_run WHERE id = 1"
        ).fetchone()
        rows = connection.execute(
            """
            SELECT p.product_key, p.name, p.purchase_cost_cents,
                   p.reference_price_cents, i.quantity,
                   i.selected_price_cents
            FROM products AS p
            JOIN inventory AS i ON i.product_key = p.product_key
            ORDER BY CASE p.product_key
                WHEN 'coffee' THEN 1 WHEN 'sandwich' THEN 2 WHEN 'cookie' THEN 3
            END
            """
        ).fetchall()

    return {
        "cash_cents": run["cash_cents"],
        "current_day": run["current_day"],
        "products": [dict(row) for row in rows],
    }


def purchase_stock(
    database_path: str | Path,
    product_key: str,
    quantity: object,
) -> int:
    """Buy stock and save the cash and inventory changes as one transaction.

    Returns the total cost in cents. Invalid or unaffordable purchases raise
    ``ValueError`` before either balance is changed.
    """

    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        # Lock the run before reading balances so concurrent clicks cannot use
        # the same old cash balance to approve two purchases.
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT g.cash_cents, g.current_day, i.quantity, p.purchase_cost_cents
            FROM game_run AS g
            JOIN inventory AS i ON i.product_key = ?
            JOIN products AS p ON p.product_key = i.product_key
            WHERE g.id = 1
            """,
            (product_key,),
        ).fetchone()

        if row is None:
            raise ValueError("That product does not exist.")

        if row[1] > TOTAL_TRADING_DAYS:
            raise ValueError("This run is complete; no more purchases are allowed.")

        result = calculate_purchase(
            cash_cents=row[0],
            current_quantity=row[2],
            unit_cost_cents=row[3],
            quantity=quantity,
        )

        connection.execute(
            "UPDATE game_run SET cash_cents = ? WHERE id = 1",
            (result.cash_cents,),
        )
        connection.execute(
            "UPDATE inventory SET quantity = ? WHERE product_key = ?",
            (result.quantity, product_key),
        )

    return result.total_cost_cents


def set_selling_price(
    database_path: str | Path,
    product_key: str,
    price: object,
) -> int:
    """Validate and immediately save one product's selling price in cents."""

    price_cents = price_to_cents(price)
    if product_key not in {product.key for product in PRODUCTS}:
        raise ValueError("That product does not exist.")

    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "UPDATE inventory SET selected_price_cents = ? WHERE product_key = ?",
            (price_cents, product_key),
        )
        if cursor.rowcount != 1:
            raise ValueError("That product does not exist.")

    return price_cents


def trade_day(database_path: str | Path = DATABASE_PATH) -> dict:
    """Trade one day and atomically save its results and updated run state."""

    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        run = connection.execute(
            "SELECT cash_cents, current_day FROM game_run WHERE id = 1"
        ).fetchone()
        if run is None:
            raise ValueError("There is no active run to trade.")

        day = run[1]
        if day > TOTAL_TRADING_DAYS:
            raise ValueError("This run is complete; there are no more trading days.")

        products = connection.execute(
            """
            SELECT p.product_key, p.name, p.purchase_cost_cents,
                   p.reference_price_cents, i.quantity, i.selected_price_cents
            FROM products AS p
            JOIN inventory AS i ON i.product_key = p.product_key
            ORDER BY CASE p.product_key
                WHEN 'coffee' THEN 1 WHEN 'sandwich' THEN 2 WHEN 'cookie' THEN 3
            END
            """
        ).fetchall()
        product_rows = [
            {
                "product_key": row[0],
                "name": row[1],
                "purchase_cost_cents": row[2],
                "reference_price_cents": row[3],
                "quantity": row[4],
                "selected_price_cents": row[5],
            }
            for row in products
        ]
        calculation = calculate_trade(run[0], product_rows)
        totals = calculation["totals"]

        # Everything from this point through the balance update is one SQLite
        # transaction. Any failure rolls back the whole day's trade.
        connection.execute(
            """
            INSERT INTO trading_days
                (day, cash_cents_after, total_demand, total_units_sold,
                 total_revenue_cents, total_cost_of_goods_sold_cents,
                 total_gross_profit_cents)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day,
                calculation["cash_cents_after"],
                totals["demand"],
                totals["units_sold"],
                totals["revenue_cents"],
                totals["cost_of_goods_sold_cents"],
                totals["gross_profit_cents"],
            ),
        )

        for result in calculation["products"]:
            connection.execute(
                """
                INSERT INTO daily_results
                    (day, product_key, demand, units_sold, revenue_cents,
                     cost_of_goods_sold_cents, gross_profit_cents)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    day,
                    result["product_key"],
                    result["demand"],
                    result["units_sold"],
                    result["revenue_cents"],
                    result["cost_of_goods_sold_cents"],
                    result["gross_profit_cents"],
                ),
            )
            connection.execute(
                "UPDATE inventory SET quantity = ? WHERE product_key = ?",
                (result["remaining_quantity"], result["product_key"]),
            )

        connection.execute(
            "UPDATE game_run SET cash_cents = ?, current_day = ? WHERE id = 1",
            (calculation["cash_cents_after"], day + 1),
        )

    saved_products = [
        {key: value for key, value in result.items() if key != "remaining_quantity"}
        for result in calculation["products"]
    ]
    return {
        "day": day,
        "products": saved_products,
        "totals": calculation["totals"],
        "cash_cents_after": calculation["cash_cents_after"],
    }


def load_latest_trade(database_path: str | Path = DATABASE_PATH) -> dict | None:
    """Load the most recently completed day's saved results, if one exists."""

    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        day_row = connection.execute(
            """
            SELECT day, cash_cents_after, total_demand, total_units_sold,
                   total_revenue_cents, total_cost_of_goods_sold_cents,
                   total_gross_profit_cents
            FROM trading_days ORDER BY day DESC LIMIT 1
            """
        ).fetchone()
        if day_row is None:
            return None
        result_rows = connection.execute(
            """
            SELECT r.product_key, p.name, r.demand, r.units_sold,
                   r.revenue_cents, r.cost_of_goods_sold_cents,
                   r.gross_profit_cents
            FROM daily_results AS r
            JOIN products AS p ON p.product_key = r.product_key
            WHERE r.day = ?
            ORDER BY CASE r.product_key
                WHEN 'coffee' THEN 1 WHEN 'sandwich' THEN 2 WHEN 'cookie' THEN 3
            END
            """,
            (day_row["day"],),
        ).fetchall()

    return {
        "day": day_row["day"],
        "products": [dict(row) for row in result_rows],
        "totals": {
            "demand": day_row["total_demand"],
            "units_sold": day_row["total_units_sold"],
            "revenue_cents": day_row["total_revenue_cents"],
            "cost_of_goods_sold_cents": day_row["total_cost_of_goods_sold_cents"],
            "gross_profit_cents": day_row["total_gross_profit_cents"],
        },
        "cash_cents_after": day_row["cash_cents_after"],
    }
