# Coffee Shop Empire — V2 architecture

Coffee Shop Empire (previously Campus Tycoon) uses Python, Streamlit, and SQLite. The design keeps screen code, game calculations, fixed catalogue data, and persistence in separate modules so each part can be understood and checked independently.

## Current application flow

`app.py` configures the page and presents the two visible modes. Both route to `v2_interface.render`, with a mode value that controls the entry flow and available navigation:

- **Version 1.0 — Single Player** creates or resumes a one-player game using the shared current implementation.
- **Version 2.0 — Multiplayer** adds host creation, joining, a waiting room, player resume, and a session leaderboard. Each player still completes their own daily turns.

The original V1 implementation in `business_logic.py` and `storage.py`, with its separate `campus_tycoon.sqlite3` database and older three-product/five-day rules, is retained for historical compatibility. It is not the current Version 1.0 interface. Current solo and multiplayer saves use `campus_tycoon_v2.sqlite3` and the shared V2 game operations.

## Main modules

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit page setup and selection of Single Player or Multiplayer mode. |
| `v2_interface.py` | Current shared player interface: authentication entry flows, navigation, setup, gameplay, dashboard, leaderboard, and report rendering. |
| `v2_storage.py` | V2 SQLite schema and reads/writes for sessions, players, leases, menus, inventory, prices, daily results, events, rankings, and reports. It validates player/session ownership at storage boundaries. |
| `business_logic.py` | Shared money and gameplay calculations, including integer-cent handling, purchases, sales, and rent settlement. Legacy V1 calculation functions remain here as well. |
| `content.py` | Fixed persona, product, affinity, and location catalogue data used by the current game. |
| `demand_engine.py` | Pure deterministic demand calculation. It receives data as inputs and does not access SQLite or mutate game state. |
| `v2_events.py` | Day 3 location-event definitions, random selection, and event effects. |
| `performance_report.py` | Reusable calculations for the finished-player report and evidence-based recommendations. |
| `v2_ui_components.py` | Shared small interface components, including the compact business header. |
| `tests/` | pytest coverage for calculations, persistence, authorization boundaries, concurrency, and Streamlit AppTest workflows. |
| `docs/` | Requirements, approved demand design, scope, architecture, and test documentation. Some documents explicitly preserve historical V1 context. |

## Catalogue, lease, and menu data

`content.py` defines four fictional Lisbon locations, five personas, twelve products, and each product/persona affinity score. Each player confirms one locked location and chooses a menu of up to five distinct items that includes a drink. Inventory and prices are stored per player and product. Removing an item from a menu does not remove its inventory; stock remains available if that product is added again.

The current default daily rents are:

| Location | Daily rent |
| --- | ---: |
| Carcavelos / NOVA SBE | €30 |
| Príncipe Real | €85 |
| Belém | €125 |
| Chiado | €165 |

When a player signs a lease, `player_locations.rent_per_day_cents` stores a snapshot of that location's rent. Daily gameplay charges this player-specific saved value, not a live lookup of the catalogue default. This keeps an agreed lease unchanged if a future release changes default rents. During migration of older V2 saves, a missing/null lease snapshot is backfilled from the rent value already in that database before the location catalogue is refreshed to current defaults. Existing non-null snapshots and completed historical results are left unchanged; new leases receive the current catalogue value. `tests/test_v2_location_rents.py` covers this preservation behavior.

## Demand, gameplay, and results

`demand_engine.py` calculates potential visitors as 10% of the selected location's daily foot traffic, allocates whole visitors to personas deterministically, and calculates drink and food demand using affinity and persona price sensitivity. It applies no random variation and does not make stock or cash changes. There is no product substitution when a requested item is unavailable.

`business_logic.py` uses demand output and player state to calculate stock-limited sales, revenue, gross profit, cash, and rent settlement. Inventory purchase cost is paid at purchase and is not deducted from cash again when stock sells. Daily rent is charged once. If a player cannot fully pay rent from post-sales cash, available cash is paid, unpaid rent is forgiven, and that player's game ends at zero cash as bankrupt. Final result is final cash minus starting cash; inventory has no end-of-game recovery value.

Every eligible player receives exactly one randomly selected location event while successfully completing Day 3 in a game configured for at least three days. There is no event on other days or in a shorter game. The event is selected from the positive and negative options for that player's location. It may alter that day's potential demand or destroy inventory; demand itself remains deterministic. The selected outcome is persisted and is not replayed on refresh or resume.

## SQLite and write consistency

`v2_storage.py` uses a separate SQLite file for current solo and multiplayer games. Tables separate sessions, players, inventory/prices, active menus, leases, daily summaries, and product-level results. Session and player IDs scope private records. Recovery credentials are stored as hashes rather than raw values. Single Player records use the same schema with a single-player mode marker and a database rule that prevents adding another player to the session.

Gameplay mutations such as lease signing, menu saving, purchasing, price changes, and day completion use explicit write transactions (`BEGIN IMMEDIATE`) so competing writers serialize before checking and updating balances or progress. Day completion groups the event outcome, product results, inventory, cash, rent settlement, and day/session progression into one transaction. An expected-day check plus a unique `(session_id, player_id, day_number)` key prevents stale or duplicate day submissions.

Schema creation, seed data, and compatibility migrations are initialization work with their own SQLite statements and migration logic; they are not all gameplay actions wrapped in the same `BEGIN IMMEDIATE` pattern. Initialization updates current catalogue defaults while retaining lease snapshots and saved historical results as described above. SQLite transaction handling protects a local database from partial operations; it does not provide a shared durable database across separate server instances.

## Dashboard and navigation details

The dashboard in `v2_interface.py` reads only the authenticated player's saved state and history. Its revenue-by-day, cash-balance, and units-sold visualizations are created with Altair and rendered using `st.altair_chart`. Read-only summaries use Streamlit table components, including `st.table` and `st.dataframe` where appropriate. `tests/test_v2_interface.py` checks dashboard metrics, chart sections, history, empty states, and player isolation through AppTest; this does not replace manual browser/device testing.

After a successful day completion, a small `st.iframe` embeds JavaScript that scrolls the main page to the Dashboard heading. It is used for that programmatic post-trade navigation, not as a general dashboard interaction. Browser behavior, especially on mobile Safari, should still be checked manually.

## Authentication boundary

Players resume with a session code, nickname, and recovery credential; only a hash of the credential is stored. Host-only operations check the host credential at the storage boundary. Streamlit session state carries the authenticated identity for that browser session, while storage functions enforce session/player ownership for player-specific reads and writes. The application is designed for the project's classroom use, not as a general internet-scale identity platform.

## Deployment limitation

The app can run locally without paid services. It uses SQLite in the application's filesystem. On Streamlit Community Cloud, local filesystem data is not guaranteed to survive restarts or redeployments, and the durability of the deployed save file has not been verified. A durable multi-instance deployment would need managed shared storage and a separate architecture review. No automatic conversion from the historical V1 SQLite file is performed.
