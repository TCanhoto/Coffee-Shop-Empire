"""SQLite storage for V2 sessions and independently managed player cafes.

V2 uses a separate database file so these new tables cannot alter a V1 save.
The functions in this module require both a session ID and player ID for
player-specific actions. Nicknames are for display, never identity.
"""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import uuid

from content import DEFAULT_MENU_KEYS, MAX_MENU_SIZE, PRODUCT_CATALOGUE
from business_logic import (
    LOCATIONS,
    calculate_purchase,
    calculate_v2_trade,
    price_to_cents,
)
import v2_events


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
    """Create V2 tables and seed catalogues without touching the V1 file."""

    with _connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purchase_cost_cents INTEGER NOT NULL CHECK (purchase_cost_cents >= 0),
                reference_price_cents INTEGER NOT NULL CHECK (reference_price_cents > 0),
                category TEXT NOT NULL DEFAULT 'Legacy',
                is_drink INTEGER NOT NULL DEFAULT 0 CHECK (is_drink IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS locations (
                location_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                passers_by_per_day INTEGER NOT NULL CHECK (passers_by_per_day >= 0),
                rent_per_day_cents INTEGER NOT NULL CHECK (rent_per_day_cents >= 0),
                nomad_percentage INTEGER NOT NULL CHECK (nomad_percentage BETWEEN 0 AND 100),
                healthy_percentage INTEGER NOT NULL CHECK (healthy_percentage BETWEEN 0 AND 100),
                tourist_percentage INTEGER NOT NULL CHECK (tourist_percentage BETWEEN 0 AND 100),
                local_percentage INTEGER NOT NULL CHECK (local_percentage BETWEEN 0 AND 100),
                student_percentage INTEGER NOT NULL CHECK (student_percentage BETWEEN 0 AND 100),
                CHECK (nomad_percentage + healthy_percentage + tourist_percentage +
                       local_percentage + student_percentage = 100)
            );

            CREATE TABLE IF NOT EXISTS game_sessions (
                session_id TEXT PRIMARY KEY,
                join_code TEXT NOT NULL UNIQUE CHECK (length(join_code) = 6),
                trading_days INTEGER NOT NULL CHECK (trading_days > 0),
                starting_budget_cents INTEGER NOT NULL CHECK (starting_budget_cents > 0),
                status TEXT NOT NULL CHECK (status IN ('waiting', 'active', 'finished')),
                created_at TEXT NOT NULL,
                host_credential_hash TEXT,
                mode TEXT NOT NULL DEFAULT 'multiplayer'
                    CHECK (mode IN ('single_player', 'multiplayer'))
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
                is_bankrupt INTEGER NOT NULL DEFAULT 0 CHECK (is_bankrupt IN (0, 1)),
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

            CREATE TABLE IF NOT EXISTS player_menu (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                PRIMARY KEY (session_id, player_id, product_key),
                FOREIGN KEY (session_id, player_id, product_key)
                    REFERENCES player_inventory(session_id, player_id, product_key)
                    ON DELETE CASCADE
            );

            CREATE TRIGGER IF NOT EXISTS player_menu_maximum_size
            BEFORE INSERT ON player_menu
            WHEN (SELECT COUNT(*) FROM player_menu
                  WHERE session_id = NEW.session_id AND player_id = NEW.player_id)
                 >= 5
            BEGIN
                SELECT RAISE(ABORT, 'A menu can contain at most 5 products.');
            END;

            CREATE TABLE IF NOT EXISTS player_locations (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                location_key TEXT NOT NULL REFERENCES locations(location_key),
                rent_per_day_cents INTEGER NOT NULL CHECK (rent_per_day_cents >= 0),
                selected_at TEXT NOT NULL,
                PRIMARY KEY (session_id, player_id),
                FOREIGN KEY (session_id, player_id)
                    REFERENCES players(session_id, player_id) ON DELETE CASCADE
            );

            CREATE TRIGGER IF NOT EXISTS player_location_is_immutable
            BEFORE UPDATE ON player_locations
            BEGIN
                SELECT RAISE(ABORT, 'confirmed player location cannot be changed');
            END;

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
                potential_visitors INTEGER NOT NULL DEFAULT 0,
                customers_served INTEGER NOT NULL DEFAULT 0,
                lost_visitors INTEGER NOT NULL DEFAULT 0,
                food_buyer_slots INTEGER NOT NULL DEFAULT 0,
                food_opportunities_not_fulfilled INTEGER NOT NULL DEFAULT 0,
                rent_due_cents INTEGER NOT NULL DEFAULT 0 CHECK (rent_due_cents >= 0),
                rent_paid_cents INTEGER NOT NULL DEFAULT 0 CHECK (rent_paid_cents >= 0),
                rent_shortfall_cents INTEGER NOT NULL DEFAULT 0 CHECK (rent_shortfall_cents >= 0),
                bankrupt INTEGER NOT NULL DEFAULT 0 CHECK (bankrupt IN (0, 1)),
                served_customers_by_persona_json TEXT,
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

            -- Legacy metadata retained so existing V2 databases need no table
            -- rebuild. Day 3 rules do not read or write session-wide plans.
            CREATE TABLE IF NOT EXISTS session_event_plans (
                session_id TEXT PRIMARY KEY REFERENCES game_sessions(session_id)
                    ON DELETE CASCADE,
                planned_event_count INTEGER NOT NULL
                    CHECK (planned_event_count IN (1, 2)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS player_day_events (
                session_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                day_number INTEGER NOT NULL CHECK (day_number > 0),
                event_key TEXT NOT NULL,
                event_name TEXT NOT NULL,
                polarity TEXT NOT NULL CHECK (polarity IN ('positive', 'negative')),
                location_key TEXT NOT NULL,
                explanation TEXT NOT NULL,
                effect TEXT NOT NULL CHECK (
                    effect IN ('inventory_loss', 'demand_multiplier')
                ),
                effect_percent INTEGER NOT NULL CHECK (effect_percent > 0),
                status TEXT NOT NULL CHECK (status IN ('scheduled', 'occurred')),
                outcome_json TEXT,
                created_at TEXT NOT NULL,
                occurred_at TEXT,
                popup_acknowledged_at TEXT,
                PRIMARY KEY (session_id, player_id, day_number),
                FOREIGN KEY (session_id, player_id)
                    REFERENCES players(session_id, player_id) ON DELETE CASCADE,
                CHECK (
                    (status = 'scheduled' AND outcome_json IS NULL AND occurred_at IS NULL)
                    OR (status = 'occurred' AND outcome_json IS NOT NULL AND occurred_at IS NOT NULL)
                )
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
        if "mode" not in session_columns:
            connection.execute(
                "ALTER TABLE game_sessions ADD COLUMN mode TEXT NOT NULL "
                "DEFAULT 'multiplayer' CHECK (mode IN ('single_player', 'multiplayer'))"
            )
        # Preserve each existing lease's old rent before the shared location
        # catalogue is updated. New leases always store their own rent snapshot.
        player_location_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(player_locations)")
        }
        rent_snapshot_needs_backfill = "rent_per_day_cents" not in player_location_columns
        if rent_snapshot_needs_backfill:
            connection.execute(
                "ALTER TABLE player_locations ADD COLUMN rent_per_day_cents INTEGER "
                "CHECK (rent_per_day_cents IS NULL OR rent_per_day_cents >= 0)"
            )
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS single_player_session_one_player
            BEFORE INSERT ON players
            WHEN (SELECT mode FROM game_sessions
                  WHERE session_id = NEW.session_id) = 'single_player'
              AND EXISTS (
                  SELECT 1 FROM players WHERE session_id = NEW.session_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'a solo game can contain only one player');
            END;
            """
        )
        player_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(players)")
        }
        if "is_bankrupt" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN is_bankrupt INTEGER NOT NULL DEFAULT 0"
            )
        product_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(products)")
        }
        if "category" not in product_columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Legacy'"
            )
        if "is_drink" not in product_columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN is_drink INTEGER NOT NULL DEFAULT 0"
            )
        trading_day_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(player_trading_days)")
        }
        for column in (
            "potential_visitors",
            "customers_served",
            "lost_visitors",
            "food_buyer_slots",
            "food_opportunities_not_fulfilled",
            "rent_due_cents",
            "rent_paid_cents",
            "rent_shortfall_cents",
            "bankrupt",
        ):
            if column not in trading_day_columns:
                connection.execute(
                    f"ALTER TABLE player_trading_days ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                )
        if "served_customers_by_persona_json" not in trading_day_columns:
            connection.execute(
                "ALTER TABLE player_trading_days "
                "ADD COLUMN served_customers_by_persona_json TEXT"
            )
        event_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(player_day_events)")
        }
        added_popup_acknowledgement = "popup_acknowledged_at" not in event_columns
        if added_popup_acknowledgement:
            connection.execute(
                "ALTER TABLE player_day_events ADD COLUMN popup_acknowledged_at TEXT"
            )
        with connection:
            if added_popup_acknowledgement:
                # Existing completed Day 3 records are historical. Do not show
                # the newly introduced popup as if the old trade just happened.
                connection.execute(
                    """UPDATE player_day_events
                       SET popup_acknowledged_at = COALESCE(occurred_at, created_at)
                       WHERE day_number = 3 AND status = 'occurred'"""
                )
            # Earlier event versions could schedule effects on arbitrary days.
            # Discard only unapplied schedules outside Day 3, and schedules for
            # games/players that have already passed Day 3. Saved outcomes and
            # completed trading records are never changed.
            connection.execute(
                """DELETE FROM player_day_events
                   WHERE status = 'scheduled'
                     AND (
                         day_number <> 3
                         OR EXISTS (
                             SELECT 1 FROM game_sessions AS s
                             WHERE s.session_id = player_day_events.session_id
                               AND s.trading_days < 3
                         )
                         OR EXISTS (
                             SELECT 1 FROM player_trading_days AS d
                             WHERE d.session_id = player_day_events.session_id
                               AND d.player_id = player_day_events.player_id
                               AND d.day_number = 3
                         )
                     )"""
            )
            if not rent_snapshot_needs_backfill:
                rent_snapshot_needs_backfill = connection.execute(
                    "SELECT 1 FROM player_locations WHERE rent_per_day_cents IS NULL LIMIT 1"
                ).fetchone() is not None
            if rent_snapshot_needs_backfill:
                # The immutable-lease trigger is briefly suspended in this
                # transaction so the additive migration can fill the snapshot.
                connection.execute(
                    "DROP TRIGGER IF EXISTS player_location_is_immutable"
                )
            for location in LOCATIONS:
                connection.execute(
                    """INSERT OR IGNORE INTO locations
                       (location_key, name, description, passers_by_per_day,
                        rent_per_day_cents, nomad_percentage, healthy_percentage,
                        tourist_percentage, local_percentage, student_percentage)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        location.key,
                        location.name,
                        location.description,
                        location.passers_by_per_day,
                        location.rent_per_day_cents,
                        *location.persona_mix,
                    ),
                )
            # On older databases, the lease had no rent snapshot and the
            # location table still contains its previously agreed rent here.
            connection.execute(
                """UPDATE player_locations
                   SET rent_per_day_cents = (
                       SELECT locations.rent_per_day_cents
                       FROM locations
                       WHERE locations.location_key = player_locations.location_key
                   )
                   WHERE rent_per_day_cents IS NULL"""
            )
            if rent_snapshot_needs_backfill:
                connection.execute(
                    """CREATE TRIGGER player_location_is_immutable
                       BEFORE UPDATE ON player_locations
                       BEGIN
                           SELECT RAISE(ABORT, 'confirmed player location cannot be changed');
                       END"""
                )
            # The catalogue is the authoritative rent for future leases.
            for location in LOCATIONS:
                connection.execute(
                    "UPDATE locations SET rent_per_day_cents = ? WHERE location_key = ?",
                    (location.rent_per_day_cents, location.key),
                )
            for product in PRODUCT_CATALOGUE:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO products
                        (product_key, name, purchase_cost_cents,
                         reference_price_cents, category, is_drink)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product.key,
                        product.name,
                        product.purchase_cost_cents,
                        product.reference_price_cents,
                        product.category,
                        int(product.is_drink),
                    ),
                )
            # Add the new catalog rows and a valid starter menu to players saved
            # by earlier V2 versions. INSERT OR IGNORE preserves their stock.
            existing_players = connection.execute(
                "SELECT session_id, player_id FROM players"
            ).fetchall()
            for player in existing_players:
                for product in PRODUCT_CATALOGUE:
                    connection.execute(
                        """INSERT OR IGNORE INTO player_inventory
                           (session_id, player_id, product_key, quantity,
                            selected_price_cents)
                           VALUES (?, ?, ?, 0, ?)""",
                        (
                            player["session_id"],
                            player["player_id"],
                            product.key,
                            product.reference_price_cents,
                        ),
                    )
                has_menu = connection.execute(
                    """SELECT 1 FROM player_menu
                       WHERE session_id = ? AND player_id = ? LIMIT 1""",
                    (player["session_id"], player["player_id"]),
                ).fetchone()
                if has_menu is None:
                    for product_key in DEFAULT_MENU_KEYS:
                        connection.execute(
                            """INSERT OR IGNORE INTO player_menu
                               (session_id, player_id, product_key)
                               VALUES (?, ?, ?)""",
                            (player["session_id"], player["player_id"], product_key),
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
                             host_credential_hash, mode)
                        VALUES (?, ?, ?, ?, 'waiting', ?, ?, 'multiplayer')
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


def create_solo_game_session(
    database_path: str | Path = V2_DATABASE_PATH,
    *,
    trading_days: object = DEFAULT_TRADING_DAYS,
    starting_budget: object = "2000.00",
    nickname: object = "My Café",
) -> dict:
    """Create and start one persistent solo session and its only player atomically.

    The returned session code and recovery credential are shown once so the
    player can resume the game after losing browser session state.
    """

    days = _positive_whole_number(trading_days, "Trading days")
    if not MIN_TRADING_DAYS <= days <= MAX_TRADING_DAYS:
        raise ValueError("Trading days must be between 1 and 30.")
    budget_cents = price_to_cents(starting_budget)
    if not MIN_STARTING_BUDGET_CENTS <= budget_cents <= MAX_STARTING_BUDGET_CENTS:
        raise ValueError("Starting cash must be between €1.00 and €10,000.00.")
    display_name, nickname_key = _normalize_nickname(nickname)
    initialize_v2_database(database_path)

    player_id = str(uuid.uuid4())
    recovery_credential = secrets.token_urlsafe(32)
    for _ in range(MAX_SESSION_CODE_ATTEMPTS):
        session_id = str(uuid.uuid4())
        join_code = _new_session_code()
        try:
            with _connect(database_path) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """INSERT INTO game_sessions
                           (session_id, join_code, trading_days,
                            starting_budget_cents, status, created_at,
                            host_credential_hash, mode)
                           VALUES (?, ?, ?, ?, 'active', ?, NULL, 'single_player')""",
                        (
                            session_id,
                            join_code,
                            days,
                            budget_cents,
                            _now_utc(),
                        ),
                    )
                    connection.execute(
                        """INSERT INTO players
                           (player_id, session_id, nickname, nickname_key,
                            is_host, recovery_credential_hash,
                            starting_cash_cents, cash_cents, current_day,
                            created_at)
                           VALUES (?, ?, ?, ?, 0, ?, ?, ?, 1, ?)""",
                        (
                            player_id,
                            session_id,
                            display_name,
                            nickname_key,
                            _credential_hash(recovery_credential),
                            budget_cents,
                            budget_cents,
                            _now_utc(),
                        ),
                    )
                    for product in PRODUCT_CATALOGUE:
                        connection.execute(
                            """INSERT INTO player_inventory
                               (session_id, player_id, product_key, quantity,
                                selected_price_cents)
                               VALUES (?, ?, ?, 0, ?)""",
                            (
                                session_id,
                                player_id,
                                product.key,
                                product.reference_price_cents,
                            ),
                        )
                    connection.executemany(
                        """INSERT INTO player_menu
                           (session_id, player_id, product_key)
                           VALUES (?, ?, ?)""",
                        [
                            (session_id, player_id, product_key)
                            for product_key in DEFAULT_MENU_KEYS
                        ],
                    )
        except sqlite3.IntegrityError as error:
            if "join_code" in str(error) or "UNIQUE constraint failed" in str(error):
                continue
            raise
        return {
            **get_game_session(database_path, session_id),
            "player_id": player_id,
            "nickname": display_name,
            "starting_cash_cents": budget_cents,
            "recovery_credential": recovery_credential,
        }

    raise RuntimeError("Could not generate a unique solo game code. Please try again.")


def get_game_session(
    database_path: str | Path,
    session_id: str,
) -> dict:
    """Load one session by its internal ID."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT session_id, join_code, trading_days,
                      starting_budget_cents, status, created_at, mode
               FROM game_sessions WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Game session was not found.")
    return dict(row)


def get_game_session_status(database_path: str | Path, session_id: str) -> str:
    """Check an existing session without initializing or writing the database."""
    database_uri = Path(database_path).resolve().as_uri()
    with closing(sqlite3.connect(f"{database_uri}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT status FROM game_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if row is None:
        raise ValueError("Game session was not found.")
    return row[0]


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
                      starting_budget_cents, status, created_at, mode
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
    if session["mode"] != "multiplayer":
        raise ValueError("Host controls are not available for a solo game.")
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


def get_session_leaderboard(
    database_path: str | Path, session_id: str
) -> dict:
    """Return one session's public standings without exposing player IDs.

    Result descends first, then total recorded revenue descends. The immutable
    player UUID is the final ascending sort key, but is deliberately not
    returned to the caller or shown in the interface.
    """

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        session = connection.execute(
            "SELECT status, trading_days FROM game_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError("Game session was not found.")
        rows = connection.execute(
            """SELECT p.player_id, p.nickname, p.starting_cash_cents,
                      p.cash_cents, p.current_day, p.is_bankrupt,
                      l.name AS location,
                      COUNT(DISTINCT d.day_number) AS completed_days,
                      COALESCE(SUM(d.total_revenue_cents), 0) AS total_revenue_cents
               FROM players AS p
               LEFT JOIN player_locations AS pl
                 ON pl.session_id = p.session_id AND pl.player_id = p.player_id
               LEFT JOIN locations AS l ON l.location_key = pl.location_key
               LEFT JOIN player_trading_days AS d
                 ON d.session_id = p.session_id AND d.player_id = p.player_id
               WHERE p.session_id = ?
               GROUP BY p.player_id, p.nickname, p.starting_cash_cents,
                        p.cash_cents, p.current_day, p.is_bankrupt, l.name""",
            (session_id,),
        ).fetchall()

    standings = []
    for row in rows:
        finished = bool(row["is_bankrupt"]) or row["current_day"] > session[
            "trading_days"
        ]
        standings.append(
            {
                "_stable_id": row["player_id"],
                "nickname": row["nickname"],
                "location": row["location"] or "Not selected",
                "completed_days": row["completed_days"],
                "game_result_cents": row["cash_cents"]
                - row["starting_cash_cents"],
                "total_revenue_cents": row["total_revenue_cents"],
                "status": "Finished" if finished else "Playing",
            }
        )
    standings.sort(
        key=lambda item: (
            -item["game_result_cents"],
            -item["total_revenue_cents"],
            item["_stable_id"],
        )
    )
    public_rows = []
    for rank, item in enumerate(standings, start=1):
        public_rows.append(
            {
                "rank": rank,
                **{key: value for key, value in item.items() if key != "_stable_id"},
            }
        )
    return {
        "is_final": session["status"] == "finished",
        "players": public_rows,
    }


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
                    """SELECT session_id, starting_budget_cents, status, mode
                       FROM game_sessions WHERE join_code = ?""",
                    (code,),
                ).fetchone()
                if session is None:
                    raise ValueError("Game session was not found.")
                if session["status"] != "waiting":
                    raise ValueError("This game session is no longer accepting players.")
                if session["mode"] != "multiplayer":
                    raise ValueError("Solo games do not accept additional players.")

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

                for product in PRODUCT_CATALOGUE:
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
                for product_key in DEFAULT_MENU_KEYS:
                    connection.execute(
                        """INSERT INTO player_menu
                           (session_id, player_id, product_key) VALUES (?, ?, ?)""",
                        (session["session_id"], player_id, product_key),
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
                "SELECT status, host_credential_hash, mode FROM game_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError("Game session was not found.")
            if session["mode"] != "multiplayer":
                raise ValueError("Only multiplayer sessions use host start controls.")
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
                  p.is_bankrupt,
                  s.trading_days, s.status
           FROM players AS p
           JOIN game_sessions AS s ON s.session_id = p.session_id
           WHERE p.session_id = ? AND p.player_id = ?""",
        (session_id, player_id),
    ).fetchone()
    if row is None:
        raise ValueError("Player was not found in this game session.")
    if row["is_bankrupt"]:
        raise ValueError("This player is bankrupt and their game has ended.")
    if row["current_day"] > row["trading_days"]:
        raise ValueError("This player has completed all trading days.")
    if row["status"] != "active":
        raise ValueError("This game session is not active.")
    return row


def _location_from_row(row: sqlite3.Row) -> dict:
    """Return one location with its internal persona percentages grouped."""

    location = dict(row)
    location["persona_mix"] = (
        location.pop("nomad_percentage"),
        location.pop("healthy_percentage"),
        location.pop("tourist_percentage"),
        location.pop("local_percentage"),
        location.pop("student_percentage"),
    )
    return location


def _get_or_create_session_event(
    connection: sqlite3.Connection,
    session_id: str,
    player_id: str,
    day_number: int,
    location_key: str,
) -> tuple[sqlite3.Row | None, v2_events.GameEvent | None]:
    """Return or create this player's event, only while trading Day 3.

    Selection happens inside the caller's ``BEGIN IMMEDIATE`` transaction.
    It is therefore committed together with sales and cannot be rerolled by a
    refresh or a competing submission.
    """

    if day_number != 3:
        return None, None
    session = connection.execute(
        "SELECT trading_days FROM game_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if session is None or session["trading_days"] < 3:
        return None, None

    assignment = connection.execute(
        """SELECT * FROM player_day_events
           WHERE session_id = ? AND player_id = ? AND day_number = ?""",
        (session_id, player_id, day_number),
    ).fetchone()
    if assignment is None:
        event = v2_events.choose_location_event(location_key)
        connection.execute(
            """INSERT INTO player_day_events
               (session_id, player_id, day_number, event_key, event_name,
                polarity, location_key, explanation, effect, effect_percent,
                status, outcome_json, created_at, occurred_at)
               VALUES (?, ?, 3, ?, ?, ?, ?, ?, ?, ?, 'scheduled', NULL, ?, NULL)""",
            (
                session_id,
                player_id,
                event.key,
                event.name,
                event.polarity,
                event.location_key,
                event.explanation,
                event.effect,
                event.percent,
                _now_utc(),
            ),
        )
        assignment = connection.execute(
            """SELECT * FROM player_day_events
               WHERE session_id = ? AND player_id = ? AND day_number = 3""",
            (session_id, player_id),
        ).fetchone()
    if assignment["status"] != "scheduled":
        raise ValueError("This day's event has already been processed.")
    try:
        event = v2_events.EVENTS_BY_KEY[assignment["event_key"]]
    except KeyError:
        raise ValueError("The saved event is not recognized.") from None
    return assignment, event


def list_locations(database_path: str | Path = V2_DATABASE_PATH) -> list[dict]:
    """Load the fixed location catalogue, including internal persona data."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        rows = connection.execute(
            """SELECT location_key, name, description, passers_by_per_day,
                      rent_per_day_cents, nomad_percentage, healthy_percentage,
                      tourist_percentage, local_percentage, student_percentage
               FROM locations ORDER BY rowid"""
        ).fetchall()
    return [_location_from_row(row) for row in rows]


def select_player_location(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    location_key: object,
) -> dict:
    """Confirm a player's Day 0 location once; a saved choice cannot be replaced."""

    if not isinstance(location_key, str) or not location_key:
        raise ValueError("Choose a valid café location.")
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            player = _require_active_player(connection, session_id, player_id)
            if player["current_day"] != 1:
                raise ValueError("Location setup is only available before Day 1.")
            existing = connection.execute(
                "SELECT 1 FROM player_locations WHERE session_id = ? AND player_id = ?",
                (session_id, player_id),
            ).fetchone()
            if existing:
                raise ValueError("Your location is already confirmed and locked.")
            location = connection.execute(
                """SELECT location_key, name, description, passers_by_per_day,
                          rent_per_day_cents, nomad_percentage, healthy_percentage,
                          tourist_percentage, local_percentage, student_percentage
                   FROM locations WHERE location_key = ?""",
                (location_key,),
            ).fetchone()
            if location is None:
                raise ValueError("Choose a valid café location.")
            connection.execute(
                """INSERT INTO player_locations
                   (session_id, player_id, location_key, rent_per_day_cents, selected_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session_id,
                    player_id,
                    location_key,
                    location["rent_per_day_cents"],
                    _now_utc(),
                ),
            )
    return _location_from_row(location)


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
                      starting_cash_cents, cash_cents, current_day, is_bankrupt
               FROM players WHERE session_id = ? AND player_id = ?""",
            (session_id, player_id),
        ).fetchone()
        if player is None:
            raise ValueError("Player was not found in this game session.")
        products = connection.execute(
            """SELECT p.product_key, p.name, p.purchase_cost_cents,
                      p.reference_price_cents, p.category, p.is_drink,
                      i.quantity, i.selected_price_cents,
                      EXISTS (
                          SELECT 1 FROM player_menu AS m
                          WHERE m.session_id = i.session_id
                            AND m.player_id = i.player_id
                            AND m.product_key = i.product_key
                      ) AS is_active
               FROM player_inventory AS i
               JOIN products AS p ON p.product_key = i.product_key
               WHERE i.session_id = ? AND i.player_id = ?
               ORDER BY p.product_key""",
            (session_id, player_id),
        ).fetchall()
        location_row = connection.execute(
            """SELECT l.location_key, l.name, l.description, l.passers_by_per_day,
                      pl.rent_per_day_cents, l.nomad_percentage, l.healthy_percentage,
                      l.tourist_percentage, l.local_percentage, l.student_percentage
               FROM player_locations AS pl
               JOIN locations AS l ON l.location_key = pl.location_key
               WHERE pl.session_id = ? AND pl.player_id = ?""",
            (session_id, player_id),
        ).fetchone()
    location = _location_from_row(location_row) if location_row else None
    product_data = [dict(product) for product in products]
    for product in product_data:
        product["is_drink"] = bool(product["is_drink"])
        product["is_active"] = bool(product["is_active"])
    progress = {
        **dict(player),
        "products": product_data,
        "location": location,
    }
    progress["is_bankrupt"] = bool(progress["is_bankrupt"])
    progress["final_game_result_cents"] = (
        progress["cash_cents"] - progress["starting_cash_cents"]
    )
    return progress


def set_player_menu(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    product_keys: object,
    *,
    expected_day: object,
) -> list[str]:
    """Replace a player's active menu for the upcoming day, atomically."""

    if not isinstance(product_keys, (list, tuple)):
        raise ValueError("Menu selections must be a list of products.")
    selected = list(product_keys)
    if not selected:
        raise ValueError("Your active menu must include at least one product.")
    if len(selected) > MAX_MENU_SIZE:
        raise ValueError(f"A menu can contain at most {MAX_MENU_SIZE} products.")
    if any(not isinstance(key, str) for key in selected):
        raise ValueError("Menu selections must be valid product names.")
    if len(set(selected)) != len(selected):
        raise ValueError("A product cannot be selected more than once.")
    catalog = {product.key: product for product in PRODUCT_CATALOGUE}
    if any(key not in catalog for key in selected):
        raise ValueError("The menu contains a product that is not in the catalogue.")
    if not any(catalog[key].is_drink for key in selected):
        raise ValueError("Your active menu must include at least one drink.")

    requested_day = _positive_whole_number(expected_day, "Expected day")
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            player = _require_active_player(connection, session_id, player_id)
            if player["current_day"] != requested_day:
                raise ValueError(
                    "The trading day changed before the menu was saved. Refresh and try again."
                )
            connection.execute(
                "DELETE FROM player_menu WHERE session_id = ? AND player_id = ?",
                (session_id, player_id),
            )
            connection.executemany(
                """INSERT INTO player_menu (session_id, player_id, product_key)
                   VALUES (?, ?, ?)""",
                [(session_id, player_id, key) for key in selected],
            )
    return selected


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
    *,
    expected_mode: str = "multiplayer",
) -> dict:
    """Resume by session code, nickname, secret, and the caller's game mode."""

    session = get_game_session_by_code(database_path, join_code)
    if expected_mode not in {"single_player", "multiplayer"}:
        raise ValueError("The requested game mode is invalid.")
    if session["mode"] != expected_mode:
        raise ValueError("The saved game belongs to a different game mode.")
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


def resume_solo_player_by_credentials(
    database_path: str | Path,
    join_code: str,
    nickname: str,
    recovery_credential: str,
) -> dict:
    """Resume only a solo-mode player using their private recovery details."""

    return resume_player_by_credentials(
        database_path,
        join_code,
        nickname,
        recovery_credential,
        expected_mode="single_player",
    )


def purchase_player_stock(
    database_path: str | Path,
    session_id: str,
    player_id: str,
    product_key: str,
    quantity: object,
    *,
    expected_day: int | None = None,
    expected_stock: int | None = None,
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
                   JOIN player_menu AS m
                     ON m.session_id = i.session_id AND m.player_id = i.player_id
                    AND m.product_key = i.product_key
                   WHERE p.product_key = ? AND i.session_id = ? AND i.player_id = ?""",
                (product_key, session_id, player_id),
            ).fetchone()
            if product is None:
                raise ValueError("That product is not in this player's active menu.")
            # Two submits of the same displayed purchase cannot both succeed.
            if (
                (expected_day is not None and player["current_day"] != expected_day)
                or (expected_stock is not None and product["quantity"] != expected_stock)
            ):
                raise ValueError("The day or stock changed. Refresh before buying again.")
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
    # SQLite INTEGER is signed 64-bit. Reject unsupported input before writes.
    if price_cents > 2**63 - 1:
        raise ValueError("Selling price is too large to save.")
    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_active_player(connection, session_id, player_id)
            result = connection.execute(
                """UPDATE player_inventory SET selected_price_cents = ?
                   WHERE session_id = ? AND player_id = ? AND product_key = ?
                     AND EXISTS (
                         SELECT 1 FROM player_menu AS m
                         WHERE m.session_id = player_inventory.session_id
                           AND m.player_id = player_inventory.player_id
                           AND m.product_key = player_inventory.product_key
                     )""",
                (price_cents, session_id, player_id, product_key),
            )
            if result.rowcount != 1:
                raise ValueError("That product is not in this player's active menu.")
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
            location_row = connection.execute(
                """SELECT l.location_key, l.passers_by_per_day,
                          pl.rent_per_day_cents,
                          l.nomad_percentage, l.healthy_percentage,
                          l.tourist_percentage, l.local_percentage, l.student_percentage
                   FROM player_locations AS pl
                   JOIN locations AS l ON l.location_key = pl.location_key
                   WHERE pl.session_id = ? AND pl.player_id = ?""",
                (session_id, player_id),
            ).fetchone()
            if location_row is None:
                raise ValueError("Confirm a café location before trading.")
            location = _location_from_row(location_row)
            product_rows = connection.execute(
                """SELECT p.product_key, p.name, p.purchase_cost_cents,
                          p.reference_price_cents, i.quantity, i.selected_price_cents,
                          p.is_drink,
                          CASE WHEN m.product_key IS NULL THEN 0 ELSE 1 END AS is_active
                   FROM player_inventory AS i
                   JOIN products AS p ON p.product_key = i.product_key
                   LEFT JOIN player_menu AS m
                     ON m.session_id = i.session_id AND m.player_id = i.player_id
                    AND m.product_key = i.product_key
                   WHERE i.session_id = ? AND i.player_id = ?
                   ORDER BY p.rowid""",
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
                    "is_drink": bool(row["is_drink"]),
                    "is_active": bool(row["is_active"]),
                }
                for row in product_rows
            ]
            _, event = _get_or_create_session_event(
                connection, session_id, player_id, requested_day,
                location["location_key"],
            )
            event_record = None
            event_outcome = None
            trade_location = location
            trade_products = [product for product in products if product["is_active"]]
            event_adjusted_products = products
            if event is not None:
                trade_location, event_adjusted_products, event_outcome = v2_events.apply_event(
                    event, location, products
                )
                trade_products = [
                    product for product in event_adjusted_products
                    if product["is_active"]
                ]
            result = calculate_v2_trade(
                player["cash_cents"], trade_location, trade_products
            )
            totals = result["totals"]
            day_number = player["current_day"]
            if event is not None:
                event_outcome["actual_total_demand"] = totals["demand"]
                event_outcome["actual_units_sold"] = totals["units_sold"]
                event_outcome["customers_served"] = result["customers_served"]
                event_update = connection.execute(
                    """UPDATE player_day_events
                       SET status = 'occurred', outcome_json = ?, occurred_at = ?
                       WHERE session_id = ? AND player_id = ? AND day_number = ?
                         AND status = 'scheduled'""",
                    (
                        json.dumps(event_outcome, sort_keys=True),
                        _now_utc(),
                        session_id,
                        player_id,
                        day_number,
                    ),
                )
                if event_update.rowcount != 1:
                    raise ValueError("This day's event could not be recorded.")
                event_record = {
                    "key": event.key,
                    "name": event.name,
                    "polarity": event.polarity,
                    "location_key": event.location_key,
                    "explanation": event.explanation,
                    "effect": event.effect,
                    "effect_percent": event.percent,
                    "outcome": event_outcome,
                }
            connection.execute(
                """INSERT INTO player_trading_days
                    (session_id, player_id, day_number, cash_cents_after,
                     total_demand, total_units_sold, total_revenue_cents,
                     total_cost_of_goods_sold_cents, total_gross_profit_cents,
                     potential_visitors, customers_served, lost_visitors,
                     food_buyer_slots, food_opportunities_not_fulfilled,
                     rent_due_cents, rent_paid_cents, rent_shortfall_cents, bankrupt,
                     served_customers_by_persona_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    result["potential_visitors"],
                    result["customers_served"],
                    result["lost_visitors"],
                    result["food_buyer_slots"],
                    result["food_opportunities_not_fulfilled"],
                    result["rent_due_cents"],
                    result["rent_paid_cents"],
                    result["rent_shortfall_cents"],
                    int(result["bankrupt"]),
                    json.dumps(
                        result["served_customers_by_persona"], sort_keys=True
                    ),
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

            if event is not None and event.effect == "inventory_loss":
                # Event effects apply to all owned stock, including products
                # temporarily removed from the active menu. Sales only use the
                # active menu, so persist loss for off-menu rows separately.
                for product in event_adjusted_products:
                    if product["is_active"]:
                        continue
                    connection.execute(
                        """UPDATE player_inventory SET quantity = ?
                           WHERE session_id = ? AND player_id = ? AND product_key = ?""",
                        (
                            product["quantity"],
                            session_id,
                            player_id,
                            product["product_key"],
                        ),
                    )

            new_day = day_number + 1
            connection.execute(
                """UPDATE players SET cash_cents = ?, current_day = ?, is_bankrupt = ?
                   WHERE session_id = ? AND player_id = ?""",
                (
                    result["cash_cents_after"],
                    new_day,
                    int(result["bankrupt"]),
                    session_id,
                    player_id,
                ),
            )
            remaining = connection.execute(
                """SELECT COUNT(*) FROM players AS p
                   JOIN game_sessions AS s ON s.session_id = p.session_id
                   WHERE p.session_id = ? AND p.current_day <= s.trading_days
                     AND p.is_bankrupt = 0""",
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
        "rent_due_cents": result["rent_due_cents"],
        "rent_paid_cents": result["rent_paid_cents"],
        "rent_shortfall_cents": result["rent_shortfall_cents"],
        "bankrupt": result["bankrupt"],
        "potential_visitors": result["potential_visitors"],
        "customers_served": result["customers_served"],
        "lost_visitors": result["lost_visitors"],
        "food_buyer_slots": result["food_buyer_slots"],
        "food_opportunities_not_fulfilled": result[
            "food_opportunities_not_fulfilled"
        ],
        "served_customers_by_persona": result["served_customers_by_persona"],
        "event": event_record,
    }


def load_pending_day_three_event_popup(
    database_path: str | Path, session_id: str, player_id: str
) -> dict | None:
    """Load this player's saved Day 3 event until its popup is acknowledged."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            """SELECT event_key, event_name, polarity, location_key, explanation,
                      effect, effect_percent, outcome_json
               FROM player_day_events
               WHERE session_id = ? AND player_id = ? AND day_number = 3
                 AND status = 'occurred' AND popup_acknowledged_at IS NULL""",
            (session_id, player_id),
        ).fetchone()
    if row is None:
        return None
    outcome = json.loads(row["outcome_json"])
    return {
        "key": row["event_key"],
        "name": row["event_name"],
        "polarity": row["polarity"],
        "location_key": row["location_key"],
        "explanation": row["explanation"],
        "effect": row["effect"],
        "effect_percent": row["effect_percent"],
        "outcome": outcome,
        "impact_summary": outcome["impact_summary"],
    }


def acknowledge_day_three_event_popup(
    database_path: str | Path, session_id: str, player_id: str
) -> bool:
    """Acknowledge the saved Day 3 popup without changing game balances."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """UPDATE player_day_events
                   SET popup_acknowledged_at = ?
                   WHERE session_id = ? AND player_id = ? AND day_number = 3
                     AND status = 'occurred' AND popup_acknowledged_at IS NULL""",
                (_now_utc(), session_id, player_id),
            )
            return updated.rowcount == 1


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
                      total_cost_of_goods_sold_cents, total_gross_profit_cents,
                      potential_visitors, customers_served, lost_visitors,
                      food_buyer_slots, food_opportunities_not_fulfilled,
                      rent_due_cents, rent_paid_cents, rent_shortfall_cents,
                      bankrupt, served_customers_by_persona_json
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
            event_row = connection.execute(
                """SELECT event_key, event_name, polarity, location_key,
                          explanation, effect, effect_percent, outcome_json
                   FROM player_day_events
                   WHERE session_id = ? AND player_id = ? AND day_number = ?
                     AND status = 'occurred'""",
                (session_id, player_id, day["day_number"]),
            ).fetchone()
            event = None
            if event_row is not None:
                event = {
                    "key": event_row["event_key"],
                    "name": event_row["event_name"],
                    "polarity": event_row["polarity"],
                    "location_key": event_row["location_key"],
                    "explanation": event_row["explanation"],
                    "effect": event_row["effect"],
                    "effect_percent": event_row["effect_percent"],
                    "outcome": json.loads(event_row["outcome_json"]),
                }
                event["impact_summary"] = event["outcome"]["impact_summary"]
            history.append(
                {
                    "day": day["day_number"],
                    "event": event,
                    "cash_cents_after": day["cash_cents_after"],
                    "potential_visitors": day["potential_visitors"],
                    "customers_served": day["customers_served"],
                    "lost_visitors": day["lost_visitors"],
                    "food_buyer_slots": day["food_buyer_slots"],
                    "food_opportunities_not_fulfilled": day[
                        "food_opportunities_not_fulfilled"
                    ],
                    "rent_due_cents": day["rent_due_cents"],
                    "rent_paid_cents": day["rent_paid_cents"],
                    "rent_shortfall_cents": day["rent_shortfall_cents"],
                    "bankrupt": bool(day["bankrupt"]),
                    "served_customers_by_persona": (
                        json.loads(day["served_customers_by_persona_json"])
                        if day["served_customers_by_persona_json"] is not None
                        else None
                    ),
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


def get_player_final_report(
    database_path: str | Path, session_id: str, player_id: str
) -> dict:
    """Load a final report only after this player has finished their game."""

    initialize_v2_database(database_path)
    with _connect(database_path) as connection:
        player = connection.execute(
            """SELECT p.current_day, p.is_bankrupt, s.trading_days
               FROM players AS p
               JOIN game_sessions AS s ON s.session_id = p.session_id
               WHERE p.session_id = ? AND p.player_id = ?""",
            (session_id, player_id),
        ).fetchone()
    if player is None:
        raise ValueError("Player was not found in this game session.")
    if not player["is_bankrupt"] and player["current_day"] <= player["trading_days"]:
        raise ValueError(
            "This player has not finished; the final report is available after the game ends."
        )

    progress = get_player_progress(database_path, session_id, player_id)
    history = load_player_trade_history(database_path, session_id, player_id)
    leaderboard = get_session_leaderboard(database_path, session_id)
    player_rank = next(
        (
            row["rank"]
            for row in leaderboard["players"]
            if row["nickname"] == progress["nickname"]
        ),
        None,
    )
    from performance_report import build_final_report

    return build_final_report(
        progress,
        history,
        ranking_position=player_rank,
        ranking_is_final=leaderboard["is_final"],
    )
