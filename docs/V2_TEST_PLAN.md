# Coffee Shop Empire — V2 test plan and coverage

This document records the current automated test coverage and provides a manual verification checklist. The presence of a manual checklist is not evidence that a browser or physical-device test has been performed. Automated Streamlit AppTests do not emulate all desktop-browser or mobile-Safari behavior.

## Test principles

- Run the suite with `uv run pytest`.
- Storage tests use temporary SQLite databases so that test actions do not alter a player's saved game.
- Test pure calculations separately from persistence and Streamlit rendering.
- Check that rejected operations leave saved state unchanged and that repeated submissions cannot duplicate a completed day.
- Demand is deterministic. Randomness is limited to the approved Day 3 event choice and is controlled or asserted appropriately in tests.

## Current automated coverage

The following coverage is implemented in the named test modules. These descriptions identify tested behavior, not proof of manual browser acceptance.

| Area | Automated coverage |
| --- | --- |
| Shared game storage and access | `tests/test_v2_storage.py`, `tests/test_authorization_boundary.py`, and `tests/test_v2_integration_audit.py` cover session/player creation, host and recovery credentials, invalid access, player/session isolation, persistence, rollback, concurrent actions, and protection of legacy V1 data. |
| Single Player mode | `tests/test_solo_mode.py` covers solo creation, resume, isolation, workflow and parity with the shared player-game rules. Version 1.0 Single Player uses the shared current game engine; it is not the original V1 UI. |
| Locations, catalogue, and menus | `tests/test_v2_content.py`, `tests/test_v2_location_rents.py`, `tests/test_v2_storage.py`, and `tests/test_v2_interface.py` cover four location records and persona mixes, approved rents, lease locking and persistence, the 12-product catalogue, affinity matrix, menu limit of five, drink requirement, menu persistence, and preserved off-menu inventory. |
| Demand engine | `tests/test_v2_demand.py` covers 10% potential visitors, persona allocation and rounding, affinity and price sensitivity, stock limits, lost sales, food opportunities, no substitution, deterministic output, examples, and the absence of database/state mutation. |
| Day completion and finances | `tests/test_v2_daily_gameplay.py` and `tests/test_v2_storage.py` cover revenue, purchase costs not charged twice, per-player rent charged once, rent shortfall/bankruptcy, seven-day completion, final score, persistence, duplicate/stale submissions, and player isolation. |
| Day 3 events | `tests/test_v2_events.py`, `tests/test_v2_storage.py`, and `tests/test_v2_interface.py` cover event definitions and effects, saved loss counts, Day 3 timing, one event per eligible player, no events on other days or in games shorter than three days, no duplicate application, transaction rollback, independent player records, popup acknowledgment, and historical display. |
| Streamlit workflows and UI | `tests/test_v2_interface.py` and `tests/test_v2_ui_components.py` use Streamlit AppTest to cover host/join/resume, routing and sidebar navigation, setup, menus, prices, purchases, trade confirmation and results, dashboard, leaderboard, final report, event dialog, and selected layout behaviors. AppTest does not establish successful testing on physical phones or every browser. |
| Dashboard, leaderboard, and final report calculations | `tests/test_v2_leaderboard.py`, `tests/test_v2_performance_report.py`, and dashboard cases in `tests/test_v2_interface.py` cover session-scoped ranking and tie breaks, player-specific metrics/history, empty histories, report evidence and recommendations, and read-only refresh/rerun behavior. Dashboard visualizations are Altair charts; small tables and data tables use Streamlit table components. |

## Day 3 event rule (current implementation)

For each player who successfully completes Day 3 in a game configured for at least three days, the application selects exactly one event from the positive and negative possibilities for that player's confirmed location. The choice is saved with that player's Day 3 result in the trading transaction. Day 1, Day 2, Day 4, and later days have no event. Games shorter than three days have no event. A completed event is not selected or applied again on rerun, refresh, resume, or duplicate submission. The selected event may affect that day's potential demand or inventory, as defined by the event catalogue.

`tests/test_v2_events.py` includes, among others, `test_all_eight_events_apply_only_on_day_three_and_persist`, `test_games_shorter_than_three_days_never_create_events`, and `test_days_one_two_and_four_have_no_event_and_day_three_has_exactly_one`. It also covers concurrent submissions and rollback. The former plans for events on additional days, one-or-two events, and a Day 3 event in a one-day game are superseded and are not current requirements.

## Historical V1 tests

The original V1 tests remain useful regression checks for the legacy `business_logic.py` and `storage.py` behavior and data model. They do not mean that the original V1 interface remains available through the current version selector. Current Version 1.0 is the shared-engine Single Player mode; the legacy V1 database and code are kept separate from current V2 saves.

## Manual verification checklist — not a test record

Use disposable sessions and separate browser profiles. Do not use real player recovery credentials in screenshots or shared notes.

1. Start the app with `uv run streamlit run app.py`. Select **Coffee Shop Empire 2.0 · Multiplayer**, create a session, then join from a separate browser using the session code. Verify the host waiting room and player-specific resume.
2. Start the session. In each player browser, select and sign a location, save a menu with at least one drink and no more than five products, purchase stock, and set prices. Confirm each player's cash, stock, menu, and location remain independent.
3. Complete Day 1 and Day 2 for one player. Verify each result appears once and that no event is assigned. On Day 3, complete the day once and verify one saved event for that player; refresh and resume, and verify neither sales nor the event is applied again. Repeat with another location/player if checking location-specific event choices.
4. Configure a game shorter than three days and verify it completes without a Day 3 event. Do not infer physical-device coverage from AppTest.
5. Complete a seven-day game and verify rent is charged once per completed day, bankruptcy ends only the affected player's game, the dashboard shows historical results, and the final report/leaderboard use the correct player/session.
6. Repeat key screens in a narrow browser viewport and on a physical phone, including mobile Safari if available. Check sidebar navigation, cards, forms, charts, dialogs, page scrolling, and the dashboard scroll-to-top after trade. Record the browser/device and actual outcome separately if this manual verification is performed.

## Commands

Run the complete automated suite:

```bash
uv run pytest
```

Run focused tests, for example:

```bash
uv run pytest tests/test_v2_demand.py tests/test_v2_events.py
uv run pytest tests/test_v2_storage.py tests/test_v2_daily_gameplay.py
uv run pytest tests/test_v2_interface.py tests/test_solo_mode.py
```

Launch the application for manual checks:

```bash
uv run streamlit run app.py
```

## Historical roadmap status

Older phase labels in planning materials recorded the order in which work was proposed. They are not a list of pending tasks. In particular, eight locations, the original V1 interface as the current Single Player mode, additional event days, and host-controlled shared-day resolution are not implemented scope. The current implementation and current tests, rather than those superseded plans, define behavior.
