# Coffee Shop Empire — current V2 scope

Coffee Shop Empire (previously Campus Tycoon) is a Lisbon café-management simulation built with Python, Streamlit, and SQLite. This document describes the implemented application, rather than the original V2 roadmap.

## Current game modes

The version selector offers two modes, and both use the current shared café-game implementation in `v2_interface.py`, `business_logic.py`, `demand_engine.py`, and `v2_storage.py`:

- **Version 1.0 — Single Player:** creates or resumes one player's saved café without host/join steps or a multiplayer lobby.
- **Version 2.0 — Multiplayer:** a host creates a session, players join or resume with credentials, and each player manages an independent café. Players share a session leaderboard.

The original V1 application and its storage/business rules remain in the repository for historical and compatibility purposes. They are not the implementation selected by the current Version 1.0 menu option.

## Implemented gameplay

- **Four fictional Lisbon locations:** Carcavelos / NOVA SBE (€30 rent/day; 1,200 passers-by), Príncipe Real (€85; 1,500), Belém (€125; 2,500), and Chiado (€165; 3,000). Each location has a fixed persona mix. A confirmed lease is locked for that player's game.
- **Five customer personas and 12 products:** the catalogue and approved product-persona affinity scores are defined in `content.py`. Each player's active menu has at most five distinct products and must include a drink. Removing an item from the menu preserves its stock.
- **Purchasing and prices:** purchases and price changes are player-specific, validated, and saved. Money is represented in integer cents.
- **Deterministic demand:** 10% of location foot traffic becomes potential visitors. Persona mix, affinity, price sensitivity, menu availability, and stock determine demand and service. There is no substitution when a preferred product is unavailable. Demand calculations themselves have no randomness.
- **Daily play:** hosts configure a game length and starting cash (defaults: seven days and €2,000). Each player completes days independently. Revenue is added to cash, stock is reduced by units sold, and that player's saved lease rent is charged once per completed day. If cash cannot cover rent, available cash is paid, the unpaid balance is forgiven, cash becomes €0, and that player's game ends as bankrupt.
- **Day 3 location events:** exactly one positive or negative event is selected for each player who completes Day 3 in a game configured for at least three days. No event is applied on another day, and a saved event cannot be applied twice. Events adjust potential demand or destroy inventory according to the event definition.
- **Review and competition:** players have a personal dashboard and final report. Multiplayer players can view a session-specific leaderboard. The final game result is final cash minus that player's starting cash; remaining inventory has no recovery value.
- **Persistence and navigation:** accepted game actions are stored in SQLite. The interface supports host, join, resume, setup, daily play, dashboard, leaderboard, and final report flows as applicable to the mode.

## Storage and deployment boundary

The current game uses the local SQLite database `campus_tycoon_v2.sqlite3`. Local SQLite files are suitable for the project's small-group use. On Streamlit Community Cloud, files on the app's local filesystem are not guaranteed to survive restarts or redeployments; durable cloud persistence has not been verified. The V1 database is separate and is not automatically converted into a V2 save.

## Exclusions

The current game has no marketing or research systems, upgrades, competing café simulations, demand forecasting, What-if panel, borrowing, or advanced accounting. The game does not use paid external services. Shared host-controlled resolution of every player's daily turn is also not implemented; each player's day is completed independently.

## Historical planning note

Earlier V2 planning documents considered eight locations, retaining the old V1 interface as the active Version 1.0 experience, and having the host resolve a shared day. Those were plans, not the current application scope. The implemented game has four locations, both visible modes use the shared current gameplay engine, and player day progression is independent.
