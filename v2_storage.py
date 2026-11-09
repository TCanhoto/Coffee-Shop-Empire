"""SQLite storage for V2 sessions and independently managed player cafes.

V2 uses a separate database file so these new tables cannot alter a V1 save.
The functions in this module require both a session ID and player ID for
player-specific actions. Nicknames are for display, never identity.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import uuid

from business_logic import (
    PRODUCTS,
    calculate_purchase,
    calculate_trade,
    price_to_cents,
)


V2_DATABASE_PATH = Path(__file__).resolve().parent / "campus_tycoon_v2.sqlite3"
DEFAULT_TRADING_DAYS = 7
DEFAULT_STARTING_BUDGET_CENTS = 200_000
MIN_TRADING_DAYS = 1
MAX_TRADING_DAYS = 30
MIN_STARTING_BUDGET_CENTS = 100
MAX_STARTING_BUDGET_CENTS = 1_000_000
SESSION_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
SESSION_CODE_LENGTH = 6
MAX_SESSION_CODE_ATTEMPTS = 50


def _path_for(database_path: str | Path) -> Path:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _connect(database_path: str | Path):
    """Open one short-lived connection with foreign-key checks enabled."""

    connection = sqlite3.connect(_path_for(database_path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _positive_whole_number(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive whole number.")
    return value


def _normalize_nickname(nickname: object) -> tuple[str, str]:
    if not isinstance(nickname, str):
        raise ValueError("Nickname must be text.")
    display_name = nickname.strip()
    if not display_name:
        raise ValueError("Nickname cannot be empty.")
    if len(display_name) > 30:
        raise ValueError("Nickname must be 30 characters or fewer.")
    return display_name, display_name.casefold()


def _new_session_code() -> str:
    return "".join(
        secrets.choice(SESSION_CODE_ALPHABET)
        for _ in range(SESSION_CODE_LENGTH)
    )


def _credential_hash(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def initialize_v2_database(database_path: str | Path = V2_DATABASE_PATH) -> None:
    """Create V2 tables and seed the V1 products without touching the V1 file."""

    with _connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purchase_cost_cents INTEGER NOT NULL CHECK (purchase_cost_cents >= 0),
                reference_price_cents INTEGER NOT NULL CHECK (reference_price_cents > 0)
            );

            CREATE TABLE IF NOT EXISTS game_sessions (
                session_id TEXT PRIMARY KEY,
                join_code TEXT NOT NULL UNIQUE CHECK (length(join_code) = 6),
                trading_days INTEGER NOT NULL CHECK (trading_days > 0),
                starting_budget_cents INTEGER NOT NULL CHECK (starting_budget_cents > 0),
                status TEXT NOT NULL CHECK (status IN ('waiting', 'active', 'finished')),
                created_at TEXT NOT NULL,
                host_credential_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES game_sessions(session_id),
                nickname TEXT NOT NULL,
                nickname_key TEXT NOT NULL,
                is_host INTEGER NOT NULL CHECK (is_host IN (0, 1)),
                recovery_credential_hash TEXT NOT NULL,
                starting_cash_cents INTEGER NOT NULL CHECK (starting_cash_cents > 0),
                cash_cents INTEGER NOT NULL CHECK (cash_cents >= 0),
                current_day INTEGER NOT NULL CHECK (current_day > 0),
                created_at TEXT NOT NULL,
                UNIQUE (session_id, nickname_key),
                UNIQUE (session_id, player_id)
            );

            CREATE TABLE IF NOT EXISTS player_inventory (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                product_key TEXT NOT NULL REFERENCES products(product_key),
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                selected_price_cents INTEGER NOT NULL CHECK (selected_price_cents > 0),
                PRIMARY KEY (session_id, player_id, product_key),
                FOREIGN KEY (session_id, player_id)
                    REFERENCES players(session_id, player_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS player_trading_days (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                day_number INTEGER NOT NULL CHECK (day_number > 0),
                cash_cents_after INTEGER NOT NULL CHECK (cash_cents_after >= 0),
                total_demand INTEGER NOT NULL,
                total_units_sold INTEGER NOT NULL,
                total_revenue_cents INTEGER NOT NULL,
                total_cost_of_goods_sold_cents INTEGER NOT NULL,
                total_gross_profit_cents INTEGER NOT NULL,
                PRIMARY KEY (session_id, player_id, day_number),
                FOREIGN KEY (session_id, player_id)
                    REFERENCES players(session_id, player_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS player_daily_results (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                day_number INTEGER NOT NULL,
                product_key TEXT NOT NULL,
                demand INTEGER NOT NULL,
                units_sold INTEGER NOT NULL,
                revenue_cents INTEGER NOT NULL,
                cost_of_goods_sold_cents INTEGER NOT NULL,
                gross_profit_cents INTEGER NOT NULL,
                PRIMARY KEY (session_id, player_id, day_number, product_key),
                FOREIGN KEY (session_id, player_id, day_number)
                    REFERENCES player_trading_days(session_id, player_id, day_number)
                    ON DELETE CASCADE,
                FOREIGN KEY (session_id, player_id, product_key)
                    REFERENCES player_inventory(session_id, player_id, product_key)
            );

            CREATE TRIGGER IF NOT EXISTS players_id_is_immutable
            BEFORE UPDATE OF player_id ON players
            BEGIN
                SELECT RAISE(ABORT, 'player ID cannot be changed');
            END;

            CREATE TRIGGER IF NOT EXISTS players_session_is_immutable
            BEFORE UPDATE OF session_id ON players
            BEGIN
                SELECT RAISE(ABORT, 'player session cannot be changed');
            END;
            """
        )
        # Phase 1A databases may already exist without host authentication.
        # This additive migration preserves all existing sessions and players.
        session_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(game_sessions)")
        }
        if "host_credential_hash" not in session_columns:
            connection.execute(
                "ALTER TABLE game_sessions ADD COLUMN host_credential_hash TEXT"
            )
        with connection:
            for product in PRODUCTS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO products
                        (product_key, name, purchase_cost_cents, reference_price_cents)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        product.key,
                        product.name,
                        product.purchase_cost_cents,
                        product.reference_price_cents,
                    ),
                )


def create_game_session(
    database_path: str | Path = V2_DATABASE_PATH,
    *,
    trading_days: object = DEFAULT_TRADING_DAYS,
    starting_budget: object = "2000.00",
) -> dict:
    """Create a waiting game and return its internal ID and joining code.

    ``starting_budget`` is supplied in euros and stored as integer cents.
    """

    days = _positive_whole_number(trading_days, "Trading days")
    if not MIN_TRADING_DAYS <= days <= MAX_TRADING_DAYS:
        raise ValueError("Trading days must be between 1 and 30.")
    budget_cents = price_to_cents(starting_budget)
    if not MIN_STARTING_BUDGET_CENTS <= budget_cents <= MAX_STARTING_BUDGET_CENTS:
        raise ValueError("Starting cash must be between €1.00 and €10,000.00.")
    initialize_v2_database(database_path)

    host_credential = secrets.token_urlsafe(32)
    for _ in range(MAX_SESSION_CODE_ATTEMPTS):
        session_id = str(uuid.uuid4())
        join_code = _new_session_code()
        try:
            with _connect(database_path) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        INSERT INTO game_sessions
                            (session_id, join_code, trading_days,
                             starting_budget_cents, status, created_at,
                             host_credential_hash)
                        VALUES (?, ?, ?, ?, 'waiting', ?, ?)
                        """,
                        (
                            session_id,
                            join_code,
                            days,
                            budget_cents,
                            _now_utc(),
                            _credential_hash(host_credential),
                        ),
                    )
        except sqlite3.IntegrityError as error:
            if "join_code" in str(error) or "UNIQUE constraint failed" in str(error):
                continue
            raise
        return {
            **get_game_session(database_path, session_id),
            "host_credential": host_credential,
        }

    raise RuntimeError("Could not generate a unique session code. Please try again.")


def get_game_session(
    database_path: str | Path,
    session_id: str,
) -> dict:
    """Load one session by its internal ID."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT session_id, join_code, trading_days,
                      starting_budget_cents, status, created_at
               FROM game_sessions WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Game session was not found.")
    return dict(row)


def get_game_session_by_code(
    database_path: str | Path,
    join_code: str,
) -> dict:
    """Load a public session summary by its six-character joining code."""

    if not isinstance(join_code, str) or len(join_code.strip()) != SESSION_CODE_LENGTH:
        raise ValueError("Enter a valid six-character session code.")
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT session_id, join_code, trading_days,
                      starting_budget_cents, status, created_at
               FROM game_sessions WHERE join_code = ?""",
            (join_code.strip().upper(),),
        ).fetchone()
    if row is None:
        raise ValueError("Game session was not found.")
    return dict(row)


def authenticate_host(
    database_path: str | Path,
    join_code: str,
    host_credential: str,
) -> dict:
    """Verify the private host secret before restoring host controls."""

    session = get_game_session_by_code(database_path, join_code)
    with _connect(database_path) as connection:
        row = connection.execute(
            "SELECT host_credential_hash FROM game_sessions WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()
    if (
        row is None
        or not row["host_credential_hash"]
        or not isinstance(host_credential, str)
        or not hmac.compare_digest(
            row["host_credential_hash"], _credential_hash(host_credential)
        )
    ):
        raise ValueError("Host controls could not be resumed with those credentials.")
    return session


def list_session_players(database_path: str | Path, session_id: str) -> list[dict]:
    """Return only public lobby details, never player identifiers or credentials."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        rows = connection.execute(
            """SELECT nickname, created_at FROM players
               WHERE session_id = ? ORDER BY created_at, nickname_key""",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def join_game_session(
    database_path: str | Path,
    join_code: str,
    nickname: str,
) -> dict:
    """Add a player and return their one-time private recovery credential."""

    if not isinstance(join_code, str):
        raise ValueError("Enter a valid six-character session code.")
    code = join_code.strip().upper()
    if len(code) != SESSION_CODE_LENGTH:
        raise ValueError("Enter a valid six-character session code.")
    display_name, nickname_key = _normalize_nickname(nickname)
    initialize_v2_database(database_path)

    player_id = str(uuid.uuid4())
    recovery_credential = secrets.token_urlsafe(32)
    try:
        with _connect(database_path) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                session = connection.execute(
                    """SELECT session_id, starting_budget_cents, status
                       FROM game_sessions WHERE join_code = ?""",
                    (code,),
                ).fetchone()
                if session is None:
                    raise ValueError("Game session was not found.")
                if session["status"] != "waiting":
                    raise ValueError("This game session is no longer accepting players.")

                existing = connection.execute(
                    """SELECT 1 FROM players
                       WHERE session_id = ? AND nickname_key = ?""",
                    (session["session_id"], nickname_key),
                ).fetchone()
                if existing is not None:
                    raise ValueError("That nickname is already used in this session.")

                player_count = connection.execute(
                    "SELECT COUNT(*) FROM players WHERE session_id = ?",
                    (session["session_id"],),
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO players
                        (player_id, session_id, nickname, nickname_key, is_host,
                         recovery_credential_hash, starting_cash_cents, cash_cents,
                         current_day, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                    (
                        player_id,
                        session["session_id"],
                        display_name,
                        nickname_key,
                        1 if player_count == 0 else 0,
                        _credential_hash(recovery_credential),
                        session["starting_budget_cents"],
                        session["starting_budget_cents"],
                        _now_utc(),
                    ),
                )

                for product in PRODUCTS:
                    connection.execute(
                        """INSERT INTO player_inventory
                            (session_id, player_id, product_key, quantity,
                             selected_price_cents)
                           VALUES (?, ?, ?, 0, ?)""",
                        (
                            session["session_id"],
                            player_id,
                            product.key,
                            product.reference_price_cents,
                        ),
                    )
    except sqlite3.IntegrityError as error:
        if "players.session_id, players.nickname_key" in str(error):
            raise ValueError("That nickname is already used in this session.") from None
        raise

    return {
        "session_id": session["session_id"],
        "player_id": player_id,
        "nickname": display_name,
        "is_host": player_count == 0,
        "starting_cash_cents": session["starting_budget_cents"],
        "recovery_credential": recovery_credential,
    }


def start_game_session(
    database_path: str | Path,
    session_id: str,
    host_credential: str,
) -> None:
    """Start a waiting session only after verifying its private host credential."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            session = connection.execute(
                "SELECT status, host_credential_hash FROM game_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError("Game session was not found.")
            if (
                not isinstance(host_credential, str)
                or not session["host_credential_hash"]
                or not hmac.compare_digest(
                    session["host_credential_hash"], _credential_hash(host_credential)
                )
            ):
                raise ValueError("Only the host can start this game.")
            if session["status"] != "waiting":
                raise ValueError("Only a waiting session can be started.")
            player_count = connection.execute(
                "SELECT COUNT(*) FROM players WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if player_count == 0:
                raise ValueError("At least one player must join before the game starts.")
            connection.execute(
                "UPDATE game_sessions SET status = 'active' WHERE session_id = ?",
                (session_id,),
            )


def _require_active_player(
    connection: sqlite3.Connection,
    session_id: str,
    player_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """SELECT p.session_id, p.player_id, p.cash_cents, p.current_day,
                  s.trading_days, s.status
           FROM players AS p
           JOIN game_sessions AS s ON s.session_id = p.session_id
           WHERE p.session_id = ? AND p.player_id = ?""",
        (session_id, player_id),
    ).fetchone()
    if row is None:
        raise ValueError("Player was not found in this game session.")
    if row["status"] != "active":
        raise ValueError("This game session is not active.")
    if row["current_day"] > row["trading_days"]:
        raise ValueError("This player has completed all trading days.")
    return row


def get_player_progress(
    database_path: str | Path,
    session_id: str,
    player_id: str,
) -> dict:
    """Load player progress only when both session and player IDs are supplied."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        player = connection.execute(
            """SELECT player_id, session_id, nickname, is_host,
                      starting_cash_cents, cash_cents, current_day
               FROM players WHERE session_id = ? AND player_id = ?""",
            (session_id, player_id),
        ).fetchone()
        if player is None:
            raise ValueError("Player was not found in this game session.")
        products = connection.execute(
            """SELECT p.product_key, p.name, p.purchase_cost_cents,
                      p.reference_price_cents, i.quantity, i.selected_price_cents
               FROM player_inventory AS i
               JOIN products AS p ON p.product_key = i.product_key
               WHERE i.session_id = ? AND i.player_id = ?
               ORDER BY p.product_key""",
            (session_id, player_id),
        ).fetchall()
    return {**dict(player), "products": [dict(product) for product in products]}


def resume_player(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    recovery_credential: str,
) -> dict:
    """Verify a private recovery credential before returning player progress."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT recovery_credential_hash FROM players
               WHERE session_id = ? AND player_id = ?""",
            (session_id, player_id),
        ).fetchone()
    if row is None or not isinstance(recovery_credential, str):
        raise ValueError("Player could not be resumed with those credentials.")
    actual_hash = _credential_hash(recovery_credential)
    if not hmac.compare_digest(row["recovery_credential_hash"], actual_hash):
        raise ValueError("Player could not be resumed with those credentials.")
    return get_player_progress(database_path, session_id, player_id)


def resume_player_by_credentials(
    database_path: str | Path,
    join_code: str,
    nickname: str,
    recovery_credential: str,
) -> dict:
    """Resume by public session code, normalized nickname, and private secret."""

    session = get_game_session_by_code(database_path, join_code)
    _, nickname_key = _normalize_nickname(nickname)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT player_id, recovery_credential_hash FROM players
               WHERE session_id = ? AND nickname_key = ?""",
            (session["session_id"], nickname_key),
        ).fetchone()
    if (
        row is None
        or not isinstance(recovery_credential, str)
        or not hmac.compare_digest(
            row["recovery_credential_hash"], _credential_hash(recovery_credential)
        )
    ):
        raise ValueError("Player could not be resumed with those credentials.")
    progress = get_player_progress(database_path, session["session_id"], row["player_id"])
    return progress


def purchase_player_stock(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    product_key: str,
    quantity: object,
) -> int:
    """Purchase stock for exactly one player, atomically reducing cash."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            player = _require_active_player(connection, session_id, player_id)
            product = connection.execute(
                """SELECT p.purchase_cost_cents, i.quantity
                   FROM products AS p
                   JOIN player_inventory AS i ON i.product_key = p.product_key
                   WHERE p.product_key = ? AND i.session_id = ? AND i.player_id = ?""",
                (product_key, session_id, player_id),
            ).fetchone()
            if product is None:
                raise ValueError("That product is not in this player's inventory.")
            result = calculate_purchase(
                player["cash_cents"],
                product["quantity"],
                product["purchase_cost_cents"],
                quantity,
            )
            connection.execute(
                "UPDATE players SET cash_cents = ? WHERE session_id = ? AND player_id = ?",
                (result.cash_cents, session_id, player_id),
            )
            connection.execute(
                """UPDATE player_inventory SET quantity = ?
                   WHERE session_id = ? AND player_id = ? AND product_key = ?""",
                (result.quantity, session_id, player_id, product_key),
            )
    return result.total_cost_cents


def set_player_selling_price(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    product_key: str,
    price: object,
) -> int:
    """Set one player's price for one product, in integer euro cents."""

    price_cents = price_to_cents(price)
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_active_player(connection, session_id, player_id)
            result = connection.execute(
                """UPDATE player_inventory SET selected_price_cents = ?
                   WHERE session_id = ? AND player_id = ? AND product_key = ?""",
                (price_cents, session_id, player_id, product_key),
            )
            if result.rowcount != 1:
                raise ValueError("That product is not in this player's inventory.")
    return price_cents


def trade_player_day(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    expected_day: object,
) -> dict:
    """Resolve one specific player day, rejecting stale or repeated submissions.

    The caller sends the day number shown when the player pressed Complete Day.
    A second tab with the same old day cannot accidentally trade the next day.
    """

    requested_day = _positive_whole_number(expected_day, "Expected day")
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            player = _require_active_player(connection, session_id, player_id)
            if player["current_day"] != requested_day:
                raise ValueError(
                    "This day was already completed or is no longer current. "
                    "Refresh to see the latest progress."
                )
            product_rows = connection.execute(
                """SELECT p.product_key, p.name, p.purchase_cost_cents,
                          p.reference_price_cents, i.quantity, i.selected_price_cents
                   FROM player_inventory AS i
                   JOIN products AS p ON p.product_key = i.product_key
                   WHERE i.session_id = ? AND i.player_id = ?
                   ORDER BY p.product_key""",
                (session_id, player_id),
            ).fetchall()
            products = [
                {
                    "product_key": row["product_key"],
                    "name": row["name"],
                    "purchase_cost_cents": row["purchase_cost_cents"],
                    "reference_price_cents": row["reference_price_cents"],
                    "quantity": row["quantity"],
                    "selected_price_cents": row["selected_price_cents"],
                }
                for row in product_rows
            ]
            result = calculate_trade(player["cash_cents"], products)
            totals = result["totals"]
            day_number = player["current_day"]
            connection.execute(
                """INSERT INTO player_trading_days
                    (session_id, player_id, day_number, cash_cents_after,
                     total_demand, total_units_sold, total_revenue_cents,
                     total_cost_of_goods_sold_cents, total_gross_profit_cents)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    player_id,
                    day_number,
                    result["cash_cents_after"],
                    totals["demand"],
                    totals["units_sold"],
                    totals["revenue_cents"],
                    totals["cost_of_goods_sold_cents"],
                    totals["gross_profit_cents"],
                ),
            )
            for product_result in result["products"]:
                connection.execute(
                    """INSERT INTO player_daily_results
                        (session_id, player_id, day_number, product_key, demand,
                         units_sold, revenue_cents, cost_of_goods_sold_cents,
                         gross_profit_cents)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        player_id,
                        day_number,
                        product_result["product_key"],
                        product_result["demand"],
                        product_result["units_sold"],
                        product_result["revenue_cents"],
                        product_result["cost_of_goods_sold_cents"],
                        product_result["gross_profit_cents"],
                    ),
                )
                connection.execute(
                    """UPDATE player_inventory SET quantity = ?
                       WHERE session_id = ? AND player_id = ? AND product_key = ?""",
                    (
                        product_result["remaining_quantity"],
                        session_id,
                        player_id,
                        product_result["product_key"],
                    ),
                )

            new_day = day_number + 1
            connection.execute(
                """UPDATE players SET cash_cents = ?, current_day = ?
                   WHERE session_id = ? AND player_id = ?""",
                (result["cash_cents_after"], new_day, session_id, player_id),
            )
            remaining = connection.execute(
                """SELECT COUNT(*) FROM players AS p
                   JOIN game_sessions AS s ON s.session_id = p.session_id
                   WHERE p.session_id = ? AND p.current_day <= s.trading_days""",
                (session_id,),
            ).fetchone()[0]
            if remaining == 0:
                connection.execute(
                    "UPDATE game_sessions SET status = 'finished' WHERE session_id = ?",
                    (session_id,),
                )

    return {
        "day": day_number,
        "products": [
            {key: value for key, value in item.items() if key != "remaining_quantity"}
            for item in result["products"]
        ],
        "totals": totals,
        "cash_cents_after": result["cash_cents_after"],
    }


def load_player_trade_history(
    database_path: str | Path,
    session_id: str,
    player_id: str,
) -> list[dict]:
    """Load one player's daily results, never using nickname as identity."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        player_exists = connection.execute(
            "SELECT 1 FROM players WHERE session_id = ? AND player_id = ?",
            (session_id, player_id),
        ).fetchone()
        if player_exists is None:
            raise ValueError("Player was not found in this game session.")
        days = connection.execute(
            """SELECT day_number, cash_cents_after, total_demand,
                      total_units_sold, total_revenue_cents,
                      total_cost_of_goods_sold_cents, total_gross_profit_cents
               FROM player_trading_days
               WHERE session_id = ? AND player_id = ? ORDER BY day_number""",
            (session_id, player_id),
        ).fetchall()
        history = []
        for day in days:
            products = connection.execute(
                """SELECT r.product_key, p.name, r.demand, r.units_sold,
                          r.revenue_cents, r.cost_of_goods_sold_cents,
                          r.gross_profit_cents
                   FROM player_daily_results AS r
                   JOIN products AS p ON p.product_key = r.product_key
                   WHERE r.session_id = ? AND r.player_id = ? AND r.day_number = ?
                   ORDER BY p.product_key""",
                (session_id, player_id, day["day_number"]),
            ).fetchall()
            history.append(
                {
                    "day": day["day_number"],
                    "cash_cents_after": day["cash_cents_after"],
                    "products": [dict(product) for product in products],
                    "totals": {
                        "demand": day["total_demand"],
                        "units_sold": day["total_units_sold"],
                        "revenue_cents": day["total_revenue_cents"],
                        "cost_of_goods_sold_cents": day[
                            "total_cost_of_goods_sold_cents"
                        ],
                        "gross_profit_cents": day["total_gross_profit_cents"],
                    },
                }
            )
    return history
