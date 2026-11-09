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

## Phase 1B delivered boundary

Phase 1B adds mobile-friendly Host Game, Join Game, and Resume Game screens under the V2 choice in the app's version selector. Hosts choose 1–30 trading days (default 7) and €1–€10,000 starting cash (default €2,000). The limits are intentionally broad for classroom sessions while preventing zero or implausibly large setup values. Creating a game returns a six-character join code and a separate random host credential. The host credential is stored only as a SHA-256 hash and is required by the storage function to start the session.

Players join a waiting session with a non-empty nickname and receive a random recovery credential once; only its hash is saved. A player can resume with the session code, nickname, and recovery credential. A host can restore host controls using the session code and separate host credential. Nicknames are unique within one session, case-insensitively after trimming. Players see a public nickname-only waiting room; the host can start only after at least one player has joined. New joins are rejected after the session leaves `waiting`. Streamlit session state holds the current browser's player identity and the host's private control credential; it is not a substitute for the SQLite records. A host may also join as a normal player using Join Game.

The V1 dashboard and historical behavior remain available in the version selector.

## Phase 1C delivered boundary

Each joined player can manage an independent café after the host starts the session. Players reuse the V1 catalogue, integer-cent money calculations, and deterministic price-tier demand. Cash, stock, prices, day progression, and history stay scoped to the player's session and player IDs. Each player advances independently through the number of days configured by the host. A player who finishes cannot buy or trade more; the shared session finishes once all players finish.

Every day completion submits the day number shown by that browser. Inside a `BEGIN IMMEDIATE` transaction, storage compares that number with the saved current day before calculating or writing. A stale submission from another tab or a repeated click is rejected rather than applied to the next day. The database also has a unique completed-day key for each session, player, and day. Waiting players receive a clear message and cannot buy, change prices, or trade before the host starts.

## Decisions still needed

Before implementing later rules, agree: exact location data and location-sharing limits; persona names and weights; product catalogue and costs; demand equation and rounding; rent timing; number of players per session; how inactive players affect progression; and the final profit formula, including rent and unsold stock. The lobby currently defaults to €2,000 and 7 days but allows hosts to change them within the documented ranges.

## Suggested next stages

1. **Phase 1A — Multiplayer data foundation:** sessions, player records, scoped inventory/prices/results, persistence, and recovery credential. (Implemented.)
2. **Phase 1B — Host and join flow:** create a session, share/join by code, validate host actions, and rejoin a player securely. (Implemented.)
3. **Phase 1C — Independent café gameplay:** player-scoped buying, pricing, daily results, and protected day completion using the V1 rules. (Implemented.)
4. **Phase 2 — Locations and menu catalogue:** eight locations, expanded products, and the 10-item limit.
5. **Phase 3 — Persona-based demand:** approve and implement deterministic demand with unit tests.
6. **Phase 4 — Shared session progression:** host-controlled shared day resolution and inactive-player rules.
7. **Phase 5 — Leaderboard and final report:** implement agreed profit scoring and session-specific ranking.
8. **Phase 6 — Responsive dashboard and acceptance:** complete desktop/mobile player flows and end-to-end tests.

Optional later work: research, marketing, or customisation only after separate approval.
