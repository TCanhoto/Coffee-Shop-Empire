# Campus Tycoon V2 scope

## Objective

V2 will let several people join a shared game and independently manage cafés in Lisbon. They will compete on an agreed final profit measure. Keep the project understandable for a programming beginner and keep Python, Streamlit, SQLite, pytest, and uv.

## Planned core features

- Multiplayer sessions with a host, a six-character joining code, and independent players.
- Eight café locations with agreed rent, foot traffic, and customer composition.
- Five customer personas with different product preferences and price sensitivity.
- An expanded product catalogue; each player's menu can contain no more than 10 products.
- Deterministic demand based on agreed location, persona, product, and price rules.
- Improved daily progression, dashboard, leaderboard, final player performance report, and mobile-friendly screens.

Optional later work, only after the core game is accepted: marketing campaigns, market research reports, and café space customisation.

Out of scope: random demand or events, a What-if panel, AI-controlled competitors, advanced financial accounting, paid AI APIs, and unnecessary technologies.

## Intentional changes from V1

V1 has one local run, €100 starting cash, three products, five trading days, price-tier demand, and final value calculated from cash plus remaining stock value. V2 is expected to replace the single-run model and may change starting cash, game length, demand, and final scoring. The group must approve exact values and formulas before those rules are implemented. Preserve V1 code, data, and historical tests; do not silently change old expectations.

## Phase 1A delivered boundary

Phase 1A adds SQLite storage for multiple sessions and players, independent cash/inventory/prices/day/history, and a recovery credential. It uses a separate `campus_tycoon_v2.sqlite3` file. The existing V1 app, V1 database, and V1 business rules remain the live application. No host/join screens, locations, personas, new demand rules, or leaderboard are part of Phase 1A.

## Decisions still needed

Before implementing later rules, agree: exact location data and location-sharing limits; persona names and weights; product catalogue and costs; demand equation and rounding; rent timing; starting budget and game length (Phase 1A defaults to €2,000 and 7 days); number of players per session; how inactive players affect progression; and the final profit formula, including rent and unsold stock. Also define how the host is authenticated and how a player privately rejoins.

## Suggested next stages

1. **Phase 1A — Multiplayer data foundation:** sessions, player records, scoped inventory/prices/results, persistence, and recovery credential. (Implemented in this change.)
2. **Phase 1B — Host and join flow:** create a session, share/join by code, validate host actions, and rejoin a player securely.
3. **Phase 2 — Locations and menu catalogue:** eight locations, expanded products, and the 10-item limit.
4. **Phase 3 — Persona-based demand:** approve and implement deterministic demand with unit tests.
5. **Phase 4 — Daily session progression:** host-controlled shared day resolution, atomic results, and inactive-player rules.
6. **Phase 5 — Leaderboard and final report:** implement agreed profit scoring and session-specific ranking.
7. **Phase 6 — Responsive dashboard and acceptance:** complete desktop/mobile player flows and end-to-end tests.
8. **Optional phases:** research, marketing, or customisation only after separate approval.
