# Campus Tycoon V2 architecture

## Beginner-friendly overview

The app has three jobs:

1. **Streamlit (`app.py`)** displays pages and collects button/input choices.
2. **Business rules (`business_logic.py`)** checks and calculates game actions without drawing screens or saving files.
3. **SQLite storage (`storage.py`, `v2_storage.py`)** saves accepted changes consistently.

Phase 1A builds the storage foundation only. `v2_storage.py` is separate from V1's `storage.py` so the working V1 game continues using its existing database and functions.

## V2 SQLite file and preservation of V1

V1 uses `campus_tycoon.sqlite3`. V2 uses `campus_tycoon_v2.sqlite3`, which is already covered by the existing `.gitignore` rule for SQLite database files. This avoids trying to convert V1's singleton `game_run` row and global inventory into a multiplayer schema while the rules are still changing. V1 data is neither copied, deleted, nor overwritten. A future migration would require a separate, reviewed, backed-up plan.

## Phase 1A tables

- **`game_sessions`**: internal UUID, unique six-character code, trading-day count, starting budget in cents, waiting/active/finished status, and UTC creation timestamp.
- **`players`**: immutable UUID, session ID, display nickname, normalized nickname key, legacy first-player flag, starting/current cash, current day, creation time, and SHA-256 hash of the recovery credential. The raw credential is shown only once when the player record is created. The legacy flag is informational; it does not grant host permissions.
- **`products`**: the existing three V1 product definitions, seeded into V2 so V1 purchase and trading calculations can be reused. No new catalogue is introduced yet.
- **`player_inventory`**: one row per player and product, holding stock quantity and selected selling price.
- **`player_trading_days`**: one summary row per player, session, and completed day.
- **`player_daily_results`**: product-level saved results for that player's day.

The player ID is random and immutable. Every player-specific storage function requires both `session_id` and `player_id`; nickname is display text and never a lookup identity. Nicknames are trimmed and compared with case-folding, so ` Alex ` and `aLeX` conflict only inside the same session.

Phase 1B adds `game_sessions.host_credential_hash` using a safe, additive SQLite column migration. Older sessions keep their saved data; because they have no host secret, they cannot be started through the new host-only action. New sessions receive a separate random host credential and save only its SHA-256 hash. The raw secret is returned once at creation; the host can use it with the session code to restore host controls in another browser session. It is never included in public session summaries.

## Reused V1 rules

V2 imports and reuses `calculate_purchase`, `calculate_trade`, `calculate_demand`, `format_euros`, and `price_to_cents` from `business_logic.py`. This keeps the known integer-cent math and purchase/trade calculations without duplicating them. Phase 1C uses the same fixed price-tier demand rule as V1; location/persona demand will be introduced in a later approved phase.

## Transactions and simultaneous actions

SQLite transactions group related changes. For a purchase, V2 locks the write transaction, checks the player's latest cash and stock, then updates both together. For a trade, the UI supplies the day number it displayed. Inside the transaction that saves the day summary, product results, updated inventory, cash, and next day, storage checks that the saved current day still matches this expected day. If another tab or click already completed it, the stale request is rejected. A uniqueness constraint on `(session_id, player_id, day_number)` is the database-level duplicate guard. If any database write fails, SQLite rolls back that action instead of saving half of it.

Connections turn on foreign-key checks and use a timeout for short periods when another writer holds the database. All writes use `BEGIN IMMEDIATE`, so simultaneous writers take turns before reading balances. SQLite remains suitable for the expected small local group; a much larger multi-server deployment would need a new capacity review.

## Recovery credential

When a player joins, the storage function returns a long random recovery credential once. Only its SHA-256 hash is saved. Resume accepts the session code, normalized nickname, and credential, then compares hashes safely before returning player state. The interface shows the credential once and keeps it in the current browser session state for convenience. Public waiting-room rows contain nicknames only.

Starting a game requires the host credential at the storage boundary; the UI's button visibility is not the security check. The host can also join as a regular player. Streamlit reruns do not recreate sessions or players because writes occur only after form submission, and authenticated identities are kept in session state after the first successful submission.

## Scope limits

Locations, personas, a larger catalogue, a new demand equation, shared host-driven daily resolution, and the leaderboard remain out of scope. Each player's daily trade resolves independently using the existing V1 rules.
