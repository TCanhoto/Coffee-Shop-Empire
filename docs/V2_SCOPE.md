# Campus Tycoon V2 scope

## Objective

V2 will let several people join a shared game and independently manage cafés in Lisbon. They will compete on an agreed final profit measure. Keep the project understandable for a programming beginner and keep Python, Streamlit, SQLite, pytest, and uv.

## Planned core features

- Multiplayer sessions with a host, a six-character joining code, and independent players.
- Eight café locations with agreed rent, foot traffic, and customer composition.
- Five customer personas with different product preferences and price sensitivity.
- An expanded product catalogue; each player's menu can contain no more than 5 products.
- Deterministic demand based on agreed location, persona, product, and price rules.
- Improved daily progression, dashboard, leaderboard, final player performance report, and mobile-friendly screens.

Optional later work, only after the core game is accepted: marketing campaigns, market research reports, and café space customisation.

Out of scope: random demand or events, a What-if panel, AI-controlled competitors, advanced financial accounting, paid AI APIs, and unnecessary technologies.

## Intentional changes from V1

V1 has one local run, €100 starting cash, three products, five trading days, price-tier demand, and final value calculated from cash plus remaining stock value. V2 is expected to replace the single-run model and may change starting cash, game length, demand, and final scoring. The group must approve exact values and formulas before those rules are implemented. Preserve V1 code, data, and historical tests; do not silently change old expectations.

## Phase 1A delivered boundary

Phase 1A adds SQLite storage for multiple sessions and players, independent cash/inventory/prices/day/history, and a recovery credential. It uses a separate `campus_tycoon_v2.sqlite3` file. The existing V1 app, V1 database, and V1 business rules remain the live application. No host/join screens, locations, personas, new demand rules, or leaderboard are part of Phase 1A.

## Phase 1B delivered boundary

Phase 1B adds mobile-friendly Host Game, Join Game, and Resume Game screens under the V2 choice in the app's version selector. Hosts choose 1–30 trading days (default 7) and €1–€10,000 starting cash (default €2,000). The limits are intentionally broad for classroom sessions while preventing zero or implausibly large setup values. Creating a game returns a six-character join code and a separate random host credential. The host credential is stored only as a SHA-256 hash and is required by the storage function to start the session.

Players join a waiting session with a non-empty nickname and receive a random recovery credential once; only its hash is saved. A player can resume with the session code, nickname, and recovery credential. A host can restore host controls using the session code and separate host credential. Nicknames are unique within one session, case-insensitively after trimming. Players see a public nickname-only waiting room; the host can start only after at least one player has joined. New joins are rejected after the session leaves `waiting`. Streamlit session state holds the current browser's player identity and the host's private control credential; it is not a substitute for the SQLite records. A host may also join as a normal player using Join Game.

The V1 dashboard and historical behavior remain available in the version selector.

## Phase 1C delivered boundary

Each joined player can manage an independent café after the host starts the session. Players reuse the V1 catalogue, integer-cent money calculations, and deterministic price-tier demand. Cash, stock, prices, day progression, and history stay scoped to the player's session and player IDs. Each player advances independently through the number of days configured by the host. A player who finishes cannot buy or trade more; the shared session finishes once all players finish.

Every day completion submits the day number shown by that browser. Inside a `BEGIN IMMEDIATE` transaction, storage compares that number with the saved current day before calculating or writing. A stale submission from another tab or a repeated click is rejected rather than applied to the next day. The database also has a unique completed-day key for each session, player, and day. Waiting players receive a clear message and cannot buy, change prices, or trade before the host starts.

## Step 2.1 delivered boundary — Lisbon location selection

After the host starts the game, each player sees a Day 0 setup screen with four location cards: Carcavelos / Nova SBE, Chiado, Príncipe Real, and Belém. The cards show a short description, daily foot traffic, and daily rent. Persona percentages are saved as internal location data and are not shown to players. A browser-only pending choice is saved to SQLite only when the player presses **Sign the lease**. The confirmed location is stored against that player's session and player IDs, is locked against replacement, and survives app restarts. Players in the same session may select different locations.

Trading is rejected until that player has confirmed a location. Step 2.4 uses this saved location for deterministic demand. The supplied location values are fictional gameplay values. Step 2.5 charges the selected location's rent once per completed day.

## Step 2.2 delivered boundary — personas, catalogue, and player menus

`content.py` contains the five approved persona descriptions and price-sensitivity labels, the approved 12 products with categories and cent-based costs/reference prices, and the approved 0/1/3 affinity matrix. Step 2.4 uses this affinity data in the approved demand engine.

Each player begins with a valid starter menu of Bica, Galão, and Pastel de nata, and can edit it for the current upcoming day. A saved menu can contain between 1 and 5 distinct products and must include a drink. Menu records are scoped to the player's session and player IDs. Purchasing, setting prices, and trading apply only to active menu products. Removing a product leaves its inventory untouched; its stock is shown as off-menu stock and can be sold again if the product is re-added. Menu submissions include the displayed upcoming day so a stale page cannot change the menu after that day has been completed. Legacy saves with larger menus remain intact until the player reduces and saves them.

## Step 2.4 delivered boundary — deterministic demand engine

`demand_engine.py` contains a pure V2 demand function. It uses location traffic and persona mix, the approved affinity matrix and sensitivity tiers, the active menu and read-only stock quantities. It has no database or randomness dependency and does not mutate player state. `business_logic.py` separately calculates sales, cash and rent settlement; `v2_storage.py` commits those results with day progression in one transaction. The rules and rounding examples are documented in `docs/V2_DEMAND_MODEL.md` and covered by automated tests.

## Daily gameplay and financial outcomes

The lobby defaults to €2,000 and 7 days, while respecting host-selected settings. Each completed day charges the player's selected location rent once after sales. Purchases already deduct inventory cost, so COGS is reported but not charged a second time at sale. If cash after sales is below rent, all remaining cash is paid toward rent, the player ends at €0 and bankrupt; unpaid rent is forgiven with no debt. Other players continue. Final score is final cash minus starting cash; unsold inventory has no recovery value. The shared session finishes when every player has completed all configured days or gone bankrupt.

## Step 3.1 delivered boundary — multiplayer leaderboard

The Leaderboard page shows only players from the current host/player session. It orders by current game result (cash minus starting cash), then total revenue, then a stable internal player identifier. The identifier is not displayed. Each row shows rank, nickname, café location, completed days, result, and Playing/Finished status. Results remain labelled provisional until the session has finished. Refresh is manual and does not modify game data.

## Step 3.2 delivered boundary — management dashboard

Each player sees a dashboard built from their own current progress and saved daily history. It shows available cash, day progress, accumulated revenue, current game result (current cash minus starting cash), customers served, and inventory. Charts show completed-day revenue, closing cash from Day 0 through completed days, and units sold by product. Best-selling products and chronological daily results are listed. Empty histories show guidance and current inventory without empty charts. Dashboard data is retrospective/current. The pre-trading Today screen can show broad demand estimate ranges; it does not forecast profit or provide What-if tools.

## Step 3.3 delivered boundary — final performance report

Finished players (including players whose game ended through bankruptcy) receive a report based on their own saved results. It shows final result, current/final rank and whether that rank is provisional, revenue, customers, best and worst offered products by gross profit, remaining stock at purchase cost, stock-limited lost product units, and the best-served persona when every completed day has saved persona counts. Recommendations are generated only from saved sales and inventory evidence. The unsold-stock threshold is 10% of starting cash; repeated stockout and zero-demand recommendations require evidence on at least two days. Old records without saved persona service counts remain marked unavailable. Daily prices and product-level demand by persona are not stored, so pricing-causality and low-affinity claims are explicitly unavailable.

## Step 3.4 delivered boundary — UI and mobile experience

The multiplayer interface is organized into Host / Join Game, Café Setup, Today, Dashboard, Leaderboard, and Final Report. Host, join, and resume are choices inside the entry section. Café Setup contains location selection and saved menu editing; Today contains pricing, purchasing, progress, and daily results. Dashboard, leaderboard, and final report are separate views. A warm coffee-and-cream theme with terracotta actions, product/location emojis, compact metrics, and mobile spacing is applied with Streamlit CSS only. Completing a day now requires a second explicit confirmation; cancelling leaves game data unchanged. Existing session and player storage remain authoritative, so navigation does not discard accepted choices.

## Suggested next stages

1. **Phase 1A — Multiplayer data foundation:** sessions, player records, scoped inventory/prices/results, persistence, and recovery credential. (Implemented.)
2. **Phase 1B — Host and join flow:** create a session, share/join by code, validate host actions, and rejoin a player securely. (Implemented.)
3. **Phase 1C — Independent café gameplay:** player-scoped buying, pricing, daily results, and protected day completion using the V1 rules. (Implemented.)
4. **Phase 2 — Locations and menu catalogue:** eight locations, expanded products, and the 5-item limit.
5. **Phase 3 — Persona-based demand:** deterministic demand engine (approved and implemented).
6. **Phase 4 — Shared session progression:** host-controlled shared day resolution and inactive-player rules.
7. **Phase 5 — Leaderboard and final report:** session-specific leaderboard and per-player final report implemented.
8. **Phase 6 — Responsive dashboard and acceptance:** management dashboard implemented; continue with manual mobile review and end-to-end acceptance.

Optional later work: research, marketing, or customisation only after separate approval.
