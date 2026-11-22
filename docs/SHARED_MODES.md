# Campus Tycoon shared game modes

## Architecture

Campus Tycoon 1.0 Single Player and Campus Tycoon 2.0 Multiplayer use one player-game implementation.

- `app.py` offers the version selector and passes the selected mode to `v2_interface.render`.
- `v2_interface.py` owns the shared café screens: location setup, menu, prices, purchases, trading, Dashboard, event notices, and final performance report.
- `v2_storage.py` owns persistence and player-scoped SQLite transactions for both modes.
- `business_logic.py`, `content.py`, `demand_engine.py`, `v2_events.py`, and `performance_report.py` hold the shared catalogue, calculations, demand, event and report rules.
- `v2_ui_components.py` supplies the shared sticky player header.

Mode-specific code is intentionally small:

- **Single Player** has a create/resume screen. Creation writes a new active session and its one player in one transaction. It does not create a host credential or waiting room. The interface keeps a separate `solo_player` identity and `solo_main_navigation` key.
- **Multiplayer** retains Host, Join, Resume, waiting-room, host credential, and session leaderboard flows. It uses its own `v2_player` identity and `v2_main_navigation` key.

The page navigation value is also saved separately from Streamlit's radio widget state. This restores the selected page when the user switches versions and Streamlit temporarily removes the hidden version's widget.

Every purchase, menu update, price change, and day completion calls the same validated V2 storage functions in either mode. A solo game has its own random session ID and player ID, and a database trigger prevents a second player from being inserted into a solo session. Session IDs scope every balance, inventory, menu, event, and result. Solo resume requires the six-character solo recovery code, player name, and private recovery credential. Only the credential hash is stored in SQLite.

## Saved data and compatibility

The shared engine continues using `campus_tycoon_v2.sqlite3`. The `game_sessions.mode` column distinguishes `single_player` and `multiplayer`. An additive SQLite migration gives existing V2 sessions the default mode `multiplayer`; it does not rebuild or delete their tables or rows.

The old `campus_tycoon.sqlite3` singleton save is left untouched. Its three legacy products, five-day rules, and stock-value final score do not match the current shared game, so this change does not attempt to convert it. The old `storage.py` APIs and their tests remain for compatibility, but the old V1 interface in `app.py` has been replaced by the shared player interface.

Both database files are local SQLite files. On a single running Streamlit server, separate users get separate sessions in the shared V2 database. Streamlit Community Cloud may not preserve files across app replacement or redeployment; durable cross-deployment saves would require a storage service or persistent volume, which is outside this implementation and was not added.

## Current V2 source-of-truth findings

- The current catalogue has **four** locations, not eight.
- Each menu may contain at most **five** products.
- The Today page shows **demand estimate ranges**; it explicitly says profit is not forecast. There is no expected-profit estimate range to share with Single Player.
- Menu and inventory are not separate Game Section pages. Menu selection is in Café Setup, while purchasing, prices and inventory information are in Today and the Dashboard.
- Multiplayer has a session leaderboard. Solo hides it; the final report shows the player's personal result without a competitor rank.

The implementation follows these actual V2 behaviors and does not create the missing locations or profit forecasts.

## Testing

Run the full suite with:

```bash
UV_CACHE_DIR=/private/tmp/campus-tycoon-uv-cache uv run pytest
```

Solo-mode tests cover immediate one-player session creation, validation, isolated concurrent saves, credentials and mode boundaries, saved-game resume, navigation state, full seven-day progression, one saved Day 3 event, final results, and calculation parity with an equivalent multiplayer player. Existing multiplayer tests continue to cover host/join, waiting, independent players, transactions, events, leaderboard, and reports. Tests use temporary databases; they do not open the project production SQLite files.

## Manual verification

1. Run `uv sync`, then `uv run streamlit run app.py`.
2. Select **Campus Tycoon 1.0 · Single Player**. Enter a name, starting cash, and seven trading days. Click **Start Solo Game**.
3. Save the one-time solo recovery code and credential. Sign a location lease, save a menu, buy stock, set prices, and complete days. Confirm the Dashboard, Day 3 event, Continue button, and final report.
4. Refresh the browser and confirm the current café is still open with the same data. In a private/different browser, use **Solo Game** and the saved code, name, and credential to resume.
5. Create a second solo game. Confirm the prompt before switching and verify the first game remains resumable.
6. Open a second browser at the same time and create another solo game. Verify its cash, stock, location, history, and recovery credentials are distinct.
7. Switch the version selector between Single Player and Multiplayer. Confirm each version restores its own current section and identity.
8. In Multiplayer, create a host session, join with a second browser, start the game, and play both cafés. Confirm the waiting room, host controls, independent data, leaderboard, and resume flow remain available only in Multiplayer.
9. Repeat the player workflows on mobile Safari. Automated tests do not replace browser/device checks.
