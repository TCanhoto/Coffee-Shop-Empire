# Campus Tycoon V2 test plan

## Test principles

- Use pytest and a fresh temporary SQLite file for each storage test.
- Keep the V1 tests unchanged as historical checks of V1 behavior.
- Test pure business calculations separately from database persistence and Streamlit screens.
- Assert rejected actions leave all related rows and balances unchanged.
- Demand remains deterministic; don't introduce random test outcomes.

## Phase 1A test coverage

`tests/test_v2_storage.py` covers:

- Creating separate sessions, unique session codes, defaults (7 days and €2,000), and configurable settings.
- Joining multiple players, unique nicknames within a session (ignoring case and outer spaces), and reusing a nickname in another session.
- Independent player cash, inventory, current day, and trade history.
- Rejection when a player ID is paired with the wrong session ID.
- Saving and reloading progress and trade history.
- Recovery credential validation and hash-only database storage.
- Transaction rollback when player creation fails after the player row would otherwise have been inserted.
- Rejected unaffordable purchase without partial state changes.
- Proof that initializing V2 does not alter the V1 schema or saved run.

## Phase 1B test coverage

`tests/test_v2_storage.py` and `tests/test_v2_interface.py` cover:

- Session setup limits (1–30 days and €1–€10,000), default values, and six-character code lookup.
- Invalid codes, blank nicknames, and duplicate nicknames being rejected.
- Host credential hashes being stored instead of the secret; only the right host credential can start a session or restore host controls.
- Correct player recovery credentials resuming the right player; incorrect credentials are rejected.
- Lobby output exposing nicknames only, not internal player IDs or credentials.
- AppTest host creation, join validation, resume validation, and a rerun after a successful action leaving exactly one saved session/player.
- Existing V1 app tests continuing to pass through the version selector.

## Phase 1C test coverage

`tests/test_v2_storage.py` and `tests/test_v2_interface.py` cover:

- Player A's purchases and price changes leaving Player B's cash, stock, and prices unchanged.
- A player completing a day without advancing another player's day.
- Waiting players seeing a host-wait message and having no purchase or day-completion controls.
- Reopening/resuming preserving cash, inventory, prices, and trading history without replaying sales.
- Concurrent same-day submissions using the same expected day resulting in one saved result; a stale retry cannot advance the next day.
- Invalid purchases, prices, pre-start actions, and post-final-day actions being rejected without partial updates.
- The final configured day stopping further activity for that player and finishing the session once all players finish.
- A resumed player seeing and continuing only their own café.

## Step 2.1 and 2.2 test coverage

`tests/test_v2_storage.py`, `tests/test_v2_interface.py`, and `tests/test_v2_content.py` cover:

- The four configured Step 2.1 locations, their persona percentages summing to 100, per-player selection/persistence, lease locking, and trading blocked before lease confirmation.
- The 12 approved Step 2.2 catalogue records and all five personas.
- A complete affinity entry for every product/persona pair using only scores 0, 1, or 3.
- Per-player menus surviving resume, independent menus, the 10-product limit, duplicate rejection, and the requirement for at least one drink.
- Purchases and prices restricted to active menu products; invalid prices leave saved state unchanged.
- Removed menu products retaining unsold stock, and later menu changes leaving completed trading history unchanged.
- AppTest showing category and reference price details and actions only for current menu products.

## Step 2.5 daily gameplay test coverage

`tests/test_v2_daily_gameplay.py`, `tests/test_v2_storage.py`, and
`tests/test_v2_interface.py` cover:

- A complete configured game with one saved result per day and no trade after completion.
- Rent paid exactly once after sales, with purchase costs excluded from the sale cash update.
- Rent shortfall setting cash to zero, recording paid and forgiven rent, and ending only the affected player.
- Per-player rent, bankruptcy, balances, inventory, and day progression remaining independent.
- Final result equaling final cash minus starting cash, with no inventory recovery value.
- The interface showing product-level results, totals, and rent after a completed day.

## Step 3.1 leaderboard test coverage

`tests/test_v2_leaderboard.py` covers result ranking, revenue and stable-ID
tie-breaks, finished and playing progress, session isolation, negative results,
one-player and empty sessions, unknown sessions, and read-only refresh behavior.
An AppTest checks that the page shows a negative euro result and that its manual
refresh leaves player progress unchanged.

## Step 3.2 management dashboard test coverage

`tests/test_v2_interface.py` covers dashboard metrics against the player's
saved progress and history, product sales totals, chronological daily history,
player isolation, empty histories, and reruns that leave player progress and
history unchanged. The app uses Streamlit's built-in line and bar charts; AppTest
checks the chart sections and the data tables that accompany them.

## Step 3.3 final performance report test coverage

`tests/test_v2_performance_report.py` covers final result, ranking/provisional
status, best and worst products, unsold inventory valuation, stock-limited lost
sales, saved persona totals, evidence-based recommendation triggers, empty
sales, missing legacy persona records, per-player access/isolation, and repeat
report reads that do not change game state. `tests/test_v2_interface.py` checks
that a finished player's report appears and an unfinished player's report does
not.

## Step 3.4 UI and mobile experience test coverage

`tests/test_v2_interface.py` exercises the Host / Join Game entry flow,
location and menu setup, price saving, purchases, daily trading, dashboard, and
final report. The leaderboard UI and refresh are covered in
`tests/test_v2_leaderboard.py`. The day-completion test checks that the first
button press does not trade, confirmation trades once, and cancellation leaves
the day and history unchanged. AppTest verifies navigation and persistence
behavior; it does not emulate a physical phone, so narrow-screen layout still
needs the manual mobile checklist.

## V1 tests affected by future V2 rules

Do not delete or weaken these tests. Their current expectations continue to test the preserved V1 app. If V2 later changes behavior, add V2 tests alongside them and explain the changed requirement.

| V1 tests | Future incompatibility | V2 replacement coverage to add when that phase is approved |
|---|---|---|
| Initial/reset cash expectations in `test_storage.py` and `test_run_management.py` | V2 uses per-player starting/current cash and may change the starting budget. | Each player receives the approved session budget; players/sessions remain independent. |
| Five-day progression in `test_trading.py` and `test_run_management.py` | V2 defaults to seven days and future game length is configurable. | Configured days advance once, stop at completion, and preserve history. |
| Three V1 products and fixed tier boundaries in `test_storage.py`, `test_pricing.py`, and `test_trading.py` | Later phases add a catalogue and replace price-only demand. | Catalogue/menu cap and deterministic location/persona/product/price cases. |
| V1 final stock-value score in `test_run_management.py` | V2 plans a multiplayer profit leaderboard and may use another final formula. | Hand-calculated revenue minus approved spending, tie handling, and report reconciliation. |
| Single-run persistence/reset and UI tests in `test_run_management.py` and `test_app_run_controls.py` | V2 creates sessions and independent players rather than resetting one shared run. | Session/player isolation, host/join/rejoin flows, and no duplicate day resolution. |

Purchase validation, cents arithmetic, atomic writes, and no replay remain valuable concepts. Phase 1A keeps V1 behavior intact while adding equivalent player-scoped tests.

## Later stage test outline

1. **Host/join UI and independent V1-rule gameplay (implemented):** host/join/resume, player-scoped purchases and prices, day completion, and duplicate-submission protection.
2. **Locations and catalogue:** four supplied location records and Step 2.2 product/menu acceptance are implemented; remaining location records, if still required, and final catalogue expansion are tracked separately.
3. **Demand:** each persona/location/product/price factor separately, hand-calculated combinations, boundaries, repeatability, and stock limits.
4. **Shared progression:** host advances once; all player results persist atomically; failed resolution rolls back; inactive-player policy is enforced.
5. **Leaderboard/report:** profit matches approved formula, includes all agreed costs, handles negative/tied outcomes, and is session-scoped.
6. **Mobile dashboard:** AppTest for actions and re-runs; manual narrow viewport check for layout because AppTest does not fully emulate a phone screen.

## Run commands

Run the entire test suite with:

```bash
uv run pytest
```

Run just the Phase 1A storage tests with:

```bash
uv run pytest tests/test_v2_storage.py
```

## Manual Phase 1B walkthrough

1. Launch with `uv run streamlit run app.py` and choose **Campus Tycoon 2.0 · Multiplayer** in the left version selector.
2. Under **Host Game**, create a session using defaults or values from the allowed ranges. Save both the six-character code and the private host credential.
3. In another browser or private window, choose **Join Game**, enter the code and a nickname, and save the one-time recovery credential.
4. Confirm the nickname appears in the host waiting room. The host selects **Start Game**; the player can refresh their waiting room to see the active status.
5. Test resume in a fresh browser session using the code, nickname, and recovery credential. Try an incorrect credential and confirm access is denied.
6. Confirm an ordinary player cannot start the session and a new player cannot join after the host starts it.
7. After start, resume each player in a separate browser. Buy stock and save a different price for Player A; confirm Player B's cash, stock, and price do not change.
8. Complete a day for Player A and refresh both browsers. Confirm only Player A advanced and their day appears once in history. Submit the same old day from a second tab and confirm it is rejected.
