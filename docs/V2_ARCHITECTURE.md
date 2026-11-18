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
- **`products`**: the 12 approved V2 products with category, drink flag, purchase cost, and reference price. Existing V1 product rows are retained as legacy rows when upgrading a database with old V2 saves.
- **`player_inventory`**: one row per player and catalogue product, holding stock quantity and selected selling price. Menu removal never deletes this row or its stock.
- **`player_menu`**: one row for each product currently offered by one player. The player and product keys point back to that player's inventory, so each player can have a different menu.
- **`player_trading_days`**: one summary row per player, session, and completed day, including served-customer counts by persona where recorded.
- **`player_daily_results`**: product-level saved results for that player's day.

## Step 2.1 location setup

- **`locations`**: the four agreed fictional Lisbon gameplay locations, including traffic, rent in cents, description, and internal persona percentages. A database check requires the five percentages to total 100.
- **`player_locations`**: at most one confirmed location for each `(session_id, player_id)`. It references both the player's session membership and the fixed location catalogue. A database trigger prevents changing a confirmed lease.

The player first chooses a card in Streamlit session state; that pending choice is not persisted. Pressing **Sign the lease** performs one insert in a `BEGIN IMMEDIATE` transaction. The player progress loader includes the saved location, so reopening or resuming restores it. The UI shows traffic and rent but omits persona percentages. Storage rejects a trade without a saved location.

## Step 2.2 persona and menu data

`content.py` is the single source for the five persona sensitivity labels and descriptions, the 12 products and their categories/prices, and the approved product-affinity matrix. Affinity scores are 0, 1, or 3. SQLite stores product catalogue rows, each player's inventory/price rows, and the active menu rows separately.

New players receive a valid starter menu (Bica, Galão, and Pastel de nata). Menu changes are saved in one transaction after validating 1–5 unique catalogue products and at least one drink. SQLite also rejects an insert that would take a player's menu over five items. Older saves with larger menus are preserved and shown with a warning; the player must reduce the menu before saving again. The UI attaches the upcoming day number to a menu save; stale submissions are rejected if another tab has completed that day. Purchases and price updates require the product to be in the active menu. Trading reads only menu rows. Removing a menu row leaves inventory and prices untouched, so stock survives if the item is re-added. Recorded day results are separate rows and are not rewritten by later menu changes.

The player ID is random and immutable. Every player-specific storage function requires both `session_id` and `player_id`; nickname is display text and never a lookup identity. Nicknames are trimmed and compared with case-folding, so ` Alex ` and `aLeX` conflict only inside the same session.

Phase 1B adds `game_sessions.host_credential_hash` using a safe, additive SQLite column migration. Older sessions keep their saved data; because they have no host secret, they cannot be started through the new host-only action. New sessions receive a separate random host credential and save only its SHA-256 hash. The raw secret is returned once at creation; the host can use it with the session code to restore host controls in another browser session. It is never included in public session summaries.

## Steps 2.3–2.4 deterministic demand engine

`demand_engine.py` contains the pure V2 demand function and deterministic largest-remainder helper. It uses only the passed location and active-menu values; it does not access SQLite or mutate those inputs. V2 estimates 10% of location foot traffic as potential visitors, allocates persona counts, and splits each persona's demand among suitable products by affinity and a two-level price weight. Persona price limits use exact integer comparisons. Inventory is read only to determine drink service and food opportunities. Drink stockouts create lost visitors without substitution; food slots are capped at 60% of customers served, and those customers remain counted once even when they also buy food.

`business_logic.py` consumes demand output separately to calculate stock-limited sales, revenue, and gross profit in integer cents. `v2_storage.py` saves customer counts, product results, rent settlement, updated inventory, cash, and day progression inside one SQLite transaction. An additive schema migration supplies new columns for older V2 databases. The interface shows the model rules, recalculates the current menu estimate when a price is edited, and displays the latest product-level day results.

## Step 2.5 daily gameplay and rent

Each player completes days independently, up to the trading-day count and starting budget chosen by the host (defaults: seven days and €2,000). A completed day sells no more than available stock, adds revenue to cash, and charges that player's location rent once. Purchase costs are paid when stock is purchased and are not deducted again during sales. The daily summary records rent due, rent paid, and any forgiven shortfall alongside customer, product, and cash results.

If post-sales cash is below mandatory rent, the player pays all remaining cash toward rent, ends the day with €0, and becomes bankrupt. The unpaid rent is forgiven; no debt is carried. That player's game ends immediately, while other players continue independently. The final score is final cash minus that player's starting cash; unsold inventory has no recovery value. The game session finishes when every player has either completed the configured days or gone bankrupt.

V2 continues to reuse `calculate_purchase`, `format_euros`, and `price_to_cents` from `business_logic.py` for purchases and money handling. The V1 `calculate_trade` and `calculate_demand` functions remain unchanged for V1.

## Transactions and simultaneous actions

SQLite transactions group related changes. For a purchase, V2 locks the write transaction, checks the player's latest cash and stock, then updates both together. For a trade, the UI supplies the day number it displayed. Inside the transaction that saves the day summary, product results, updated inventory, cash, and next day, storage checks that the saved current day still matches this expected day. If another tab or click already completed it, the stale request is rejected. A uniqueness constraint on `(session_id, player_id, day_number)` is the database-level duplicate guard. If any database write fails, SQLite rolls back that action instead of saving half of it.

Connections turn on foreign-key checks and use a timeout for short periods when another writer holds the database. All writes use `BEGIN IMMEDIATE`, so simultaneous writers take turns before reading balances. SQLite remains suitable for the expected small local group; a much larger multi-server deployment would need a new capacity review.

## Recovery credential

When a player joins, the storage function returns a long random recovery credential once. Only its SHA-256 hash is saved. Resume accepts the session code, normalized nickname, and credential, then compares hashes safely before returning player state. The interface shows the credential once and keeps it in the current browser session state for convenience. Public waiting-room rows contain nicknames only.

Starting a game requires the host credential at the storage boundary; the UI's button visibility is not the security check. The host can also join as a regular player. Streamlit reruns do not recreate sessions or players because writes occur only after form submission, and authenticated identities are kept in session state after the first successful submission.

## Step 3.1 session leaderboard

`get_session_leaderboard` reads one session's players and completed-day revenue. It calculates each current result as cash minus starting cash and orders players by result descending, total revenue descending, then immutable player ID ascending. The ID is only an internal stable tie-breaker and is not returned. A player is **Finished** after completing the configured days or going bankrupt; otherwise the player is **Playing**. The overall leaderboard is provisional until the session is finished. The Streamlit page uses the currently joined/resumed player's session or the host's session and refreshes only when the user presses the button. The query does not change player/game records.

## Step 3.2 player management dashboard

The signed-in player's dashboard uses their own progress and trade-history queries. Available cash and current inventory come from the player's current saved state. Accumulated revenue and customers served are summed from their completed-day history. Accumulated game result is current cash minus starting cash. Revenue, closing cash, and product sales charts use only completed-day records; the cash chart starts with Day 0 starting cash and then shows saved end-of-day balances. Inventory, best-selling products, and daily history are shown in responsive full-width components. If no day has been completed, the dashboard shows current inventory and guidance instead of empty charts. No forecast or What-if calculation is used.

## Step 3.3 final performance report

`performance_report.py` is a pure summarizer for a finished player's saved progress and daily history. `v2_storage.get_player_final_report` checks that the player has finished (by completing the configured days or ending through bankruptcy), then loads only that player's report data and their session ranking. Revenue and customers are summed from saved days; product performance is ranked by gross profit; stock-limited lost units are demand minus sales; remaining inventory value uses purchase cost and is not added to the game result. Recommendations use explicit evidence rules: unsold stock value at least 10% of starting cash, the same product stock-limited on at least two days, or an offered product with zero demand on at least two days. A best-seller suggestion is used when fewer than two other rules apply and product sales exist. The report identifies missing historical prices and product-persona demand rather than estimating them. A nullable additive migration saves served-customer counts by persona for new day results; prior rows remain NULL and are reported as unavailable.

## Step 3.4 navigation and mobile UI

`v2_interface.render` provides six main sections using built-in Streamlit navigation. Host, join, and resume forms share the entry section; each player's Café Setup holds their lease and editable menu; Today holds pricing, stock purchases, daily progress, results, and a two-step day-completion confirmation. Dashboard, leaderboard, and final report are separate views. Existing per-player widget keys and SQLite records preserve selected choices when a player navigates. A small inline CSS theme uses cream backgrounds, coffee text, terracotta buttons, bordered cards, and narrower-screen spacing. No frontend framework, JavaScript, or dependency was added. The database's expected-day guard remains the final protection against duplicate trades.

## Scope limits

Shared host-driven daily resolution remains out of scope. Each player's daily trade uses the deterministic V2 demand engine independently.
