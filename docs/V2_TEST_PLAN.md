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

1. **Host/join UI:** create code, join by code, duplicate/invalid nickname, session full/closed, host permissions, secure rejoin.
2. **Locations and catalogue:** all eight agreed records, selection rules, product menu size up to 10, rejection of item 11 without writes.
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
