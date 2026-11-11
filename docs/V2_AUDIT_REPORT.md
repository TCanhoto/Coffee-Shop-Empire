# Campus Tycoon V2 — Step 3.5 Integration Audit

Date: 11 November 2026. Branch: `test/v2-integration-audit`.

The working tree was clean before this audit. No commits, pushes, merges,
dependency installations, optional features, or database resets were performed.
The scope is four locations, five personas, twelve products, and independent
player days. Older roadmap references to eight core locations or host-driven
shared days do not override the latest approved scope.

## 1. Features verified

The following table distinguishes automated checks from physical-device testing.
All automated game writes use temporary SQLite databases.

| Scenario | Evidence and result |
| --- | --- |
| Host creates seven days / €2,000 | Storage integration checks exact defaults; existing AppTest checks host creation and no duplicate session on rerun. |
| Three players join one session | New integration test creates Alice, Bob and Carol in the same game. |
| Different locations, menus and prices | Three-player test selects Carcavelos, Chiado and Belém, with different two-item menus and drink prices. |
| Independent purchases and daily progression | Each player completes seven days independently; players not yet trading remain on Day 1. |
| Deterministic demand and stock limits | Existing demand tests cover approved hand-calculated examples, price boundaries, persona/product rounding, stockouts and food opportunities. Integration reconciles engine output to saved sales and inventory. |
| Revenue, rent and cash | Every integration day checks purchase spending, revenue, location rent and closing cash. Existing tests check COGS is not charged twice and seven rents are applied. |
| Leave and resume | Credentials restore identical saved progress after each integration day. A new Python subprocess also resumes a saved game with one history entry. |
| Refresh without repeating actions | AppTest buys once then reruns without changing balances; existing tests cover reruns, cancellation and no repeated completed sales. Storage rejects stale day submissions. |
| Concurrent actions and isolation | Three threads buy and trade for different players. Two threads compete for the same player's cash; one purchase succeeds and one is rejected. Existing test submits the same trading day concurrently and saves exactly one result. |
| Independent login state | Two AppTest instances verify the second inherits neither the first player's identity nor a host credential; sign-out clears player identity. These are simulated sessions, not real browser connections. |
| Dashboard | Existing AppTests compare displayed money, inventory, customers, history and product sales to saved data and check player isolation. Chart headings/data are covered; physical rendering is not. |
| Leaderboard | Existing tests cover results, revenue tie-breaks, stable ordering, session isolation and provisional status. Integration checks final ordering after all players finish. |
| Final reports | Integration reconciles revenue, customers, cash-only score and provisional/final ranking. Existing tests cover products, stock, personas and recommendations. |
| Persistence after restart | New subprocess verifies persistence across Python processes. Reinitializing storage leaves a completed integration save unchanged. An actual Streamlit stop/start with browser reconnection remains manual. |
| SQLite consistency | The completed three-player save passes `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Fault-injection tests verify full rollback of purchases, menu replacement and trading. |

### Edge cases covered automatically

The full suite includes invalid codes, blank/duplicate nicknames, wrong recovery
credentials, non-positive/malformed prices, invalid quantities (zero, negative,
fractional, text and boolean), menus without drinks, more than ten menu items,
overspending, stock shortages, zero sales, negative results, bankruptcy,
repeated day completion, locked location changes, stale menu submissions,
post-completion actions and cross-session access.

New wrong-session tests cover price changes, menus, trading and final reports;
existing tests cover purchases. Rejected inputs and injected failures are
checked against saved state. This is evidence for the tested cases, not a claim
that every possible malformed input or database failure has been exhausted.

## 2. Tests executed

Environment: Windows, Python 3.12.16, pytest 8.4.2, existing project environment.
Commands ran outside the Windows sandbox because its temporary-directory
permissions previously prevented pytest from creating disposable databases.

Before each command, PowerShell environment variables were set:

```powershell
$env:UV_NO_SYNC='1'
$env:UV_OFFLINE='1'
$env:PYTHONDONTWRITEBYTECODE='1'
```

These prevent uv from syncing/installing packages or using the network and
prevent Python bytecode writes. The requested full-suite command was:

```powershell
uv run pytest
```

Focused commands:

```powershell
uv run pytest tests/test_v2_integration_audit.py::test_price_larger_than_sqlite_integer_is_rejected_without_writes tests/test_v2_performance_report.py::test_unsold_stock_recommendation_preserves_euro_cents -q
uv run pytest tests/test_v2_integration_audit.py tests/test_v2_performance_report.py tests/test_v2_interface.py -q
```

## 3. Exact results

| Run | Result |
| --- | --- |
| First full suite, after initial audit tests | 164 passed, 1 failed in 69.43 seconds. Existing V1 AppTest exceeded its three-second timeout. |
| Two new bug regressions, before fixes | 2 failed in 1.74 seconds: price overflow and recommendation dropping cents. |
| Focused run after application fixes, before timeout adjustment | 30 passed, 1 failed in 34.36 seconds. Existing lease-signing AppTest exceeded its three-second timeout. |
| Focused run after all test additions and harness adjustment | 36 passed in 33.17 seconds. |
| Final full suite: `uv run pytest` | **173 passed in 61.85 seconds.** |

Both existing application SQLite files had identical SHA-256 hashes before and
after the final full-suite run. `git diff --check` also passed.

No existing test assertions were removed, skipped or changed to accept incorrect
game behavior. Three AppTest constructors now allow fifteen seconds rather than
three for a screen run. This addresses observed slow screen initialization in
this environment; it is not evidence of a three-second UI performance guarantee.

## 4. Bugs discovered

1. A valid decimal price above SQLite's signed 64-bit integer capacity reached
   the database and raised an uncaught `OverflowError`.
2. An unsold-stock recommendation formatted €210.10 as €210, losing cents in
   text even though its underlying inventory value was correct.
3. V2 screen tests initially opened V1 with its normal default database path.
   Patching only the V2 path did not isolate them from local V1 saves.
4. Existing three-second UI-test timeouts failed on both initial V1 rendering
   and V2 lease signing in this environment.

## 5. Bugs corrected

- `v2_storage.set_player_selling_price` now rejects a price above SQLite's
  integer capacity with a normal validation message before database writes.
  It does not introduce a new economic price rule.
- The final-report recommendation now prints euros and two cent digits.
- An automatic test fixture redirects V1's database constant and captured
  default function arguments to a temporary save for each test. Explicit
  database arguments still work, and fixtures restore the original defaults.
- AppTest constructors in the V1 controls, V2 interface and leaderboard tests
  now allow fifteen seconds. Business assertions are unchanged.

No demand, rent, bankruptcy, score, catalogue or menu rules were changed.

## 6. Remaining risks and scope questions

- **Real devices remain unverified in this audit.** Automated storage and
  AppTest checks do not establish classroom Wi-Fi reachability or mobile layout.
- **Legacy V2 compatibility:** an old player already beyond Day 1 without a
  location cannot trade, while location selection requires Day 1. This follows
  from the current guards; a populated old-save upgrade was not exercised here.
  No location was silently assigned and no old game was reset. Agree a migration
  policy before promising continuation of such old saves.
- **Read functions can perform initialization writes.** Many storage functions
  seed/check all existing players before their main operation. Tests establish
  unchanged table contents on current-schema saves; they do not establish that
  refreshes never acquire write locks or that migration has no side effects.
- **Long lock contention:** SQLite has a ten-second connection timeout, and UI
  actions mainly catch validation errors. A prolonged lock or disk failure can
  still surface an SQLite exception. The audit tested short simultaneous writes
  and transaction rollback, not disk-full conditions or a ten-second lock hold.
- **Inline demand previews:** the pricing screen estimates demand before saving
  a price. There is no separate What-if page, but whether inline estimates fit
  the no-prediction principle needs product confirmation. Existing documented
  behavior was preserved. Food demand also depends on drink stock, so the
  preview's “before applying stock limits” wording is incomplete for food.
- **Historical reporting limits:** daily prices and product/persona demand are
  not saved. The report identifies unavailable causal conclusions instead of
  inventing them. Unsold stock value is informational and never added to score.
- **Inactive players:** a joined player who never finishes keeps the session
  provisional. No new inactivity policy was introduced.
- **Documentation drift:** README's opening paragraph and the original PLAN
  are outdated; V2 scope/test documents retain earlier roadmap terminology.
  This audit report records the latest approved scope without rewriting it.
- **Capacity:** the checks simulate three writers and one same-player race,
  not a large classroom load or several application servers.

Git inspection found no tracked files matching database, `.env` or secrets-file
patterns. `git check-ignore` confirms both normal SQLite files, `.env` and
`.streamlit/secrets.toml` are ignored. Credential hashes are tested in storage.
This is not a forensic scan of every historical commit for secrets. V1 commit
`734316d` still exists. Dependencies remain Streamlit and development pytest;
no dependency or lockfile changes were made.

## 7. Tests requiring manual verification

- Three physical devices on the same trusted network, including a phone.
- Actual browser login separation, reconnects, refresh and stale tabs.
- Actual Streamlit server stop/start with authenticated player recovery.
- Narrow screens, readable tables/charts and the complete navigation flow.
- Prolonged lock/disk error behavior, if operational acceptance requires it.

No real-browser, Wi-Fi, physical-phone or running-Streamlit restart test was
performed as part of this audit. The subprocess check is storage-only.

## 8. Manual complete-game instructions

Use a new test session. Do not reset or delete existing saves. With the server
stopped, copy the SQLite files somewhere private if a backup is desired.

1. From the project folder with dependencies already installed, run
   `uv run streamlit run app.py --server.address 0.0.0.0 --server.port 8501`.
   Keep the host awake. Connect all devices to the same trusted network.
   Open `http://<host-local-IP>:8501` on the other devices; `localhost` works
   only on the host. Do not use public tunnels or router port forwarding.
2. Select **Campus Tycoon 2.0 · Multiplayer**. Under **Host / Join Game**, create
   seven days and €2,000. Save the six-character code and private host credential.
3. Join as Alice, Bob and Carol on three devices. If the host also plays, join
   before starting. Save each player's private recovery credential separately.
   A fresh device should not already be logged in. Try a wrong game code,
   duplicate nickname and wrong recovery credential without revealing secrets.
4. Refresh the waiting room, verify all three players, and start as host.
   Confirm a new player cannot join after start.
5. In **Café Setup**, sign different locations: Carcavelos, Chiado and Belém.
   Their daily rents are €30, €80 and €55. Confirm leases cannot be replaced.
6. Save different menus with at least one drink. Reject a menu without drinks
   and an eleventh product. Remove/re-add an item with stock and confirm stock
   is retained. Set different prices and reject zero, negative or overly
   precise prices. Unsaved price previews are not saved prices.
7. Have Alice use only Bica at €0.90 and buy ten units: cash becomes €1,998.
   Complete Day 1 with confirmation: ten sales yield €9, rent is €30, closing
   cash is €1,977, stock is zero, and day becomes 2. Bob and Carol stay on Day 1.
8. On all devices, record cash, prices, stock and day before and after actions.
   Refresh after buying and after trading. History must contain each completed
   day once. Use another session resumed as the same player to try stale-day
   confirmations; no completed day may be replayed.
9. Have all three buy/trade at roughly the same time. Each balance must satisfy
   `previous cash - purchases + sales - rent paid`. Inventory decreases only by
   units actually sold. Compare each dashboard to that player's own history.
10. Close/reopen one browser and resume with the saved code, nickname and
    credential. Stop Streamlit with Ctrl+C, restart with the same command and
    project folder, and resume all players. Confirm no repeated transactions.
11. Continue through Day 7 independently. Compare leaderboard results and
    provisional labels while anyone is playing. At completion, purchases and
    trading must be blocked, and ranking must be final once everyone finishes.
    Final score must equal final cash minus €2,000, excluding unsold stock.
12. Reconcile every report's revenue, customers, products and remaining stock
    with saved dashboard results. Test a separate €10 session with Chiado and
    no sales: €10 rent paid, €70 forgiven, €0 closing cash, and that player's
    game ends immediately. Other players in that session must remain unaffected.

Record browser/device, expected value, actual value and pass/fail for each step.
If classroom Wi-Fi blocks peer connections, demonstrate separate local browser
sessions and explicitly leave cross-device acceptance open.

## Acceptance conclusion

The final full suite passed all 173 tests. Automated checks found no failing
game assertions after the corrections above.
Physical-device, real-server restart and mobile acceptance remain open.
Step 3.6 can prepare explanations, but optional Phase 4 should wait for core
acceptance and resolution of the recorded scope questions.
