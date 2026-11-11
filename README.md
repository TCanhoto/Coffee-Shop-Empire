# Campus Tycoon

A local campus café simulation built with Python, Streamlit, and SQLite. The app keeps the original V1 game available and adds V2 multiplayer session creation, joining, waiting rooms, and secure resume. V2 trading rules and gameplay screens are still planned for later phases.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Run the application

From the project folder, run:

```bash
uv sync
uv run streamlit run app.py
```

The local V1 database (`campus_tycoon.sqlite3`) and separate V2 multiplayer database (`campus_tycoon_v2.sqlite3`) are created automatically in the project folder. Both are ignored by Git and kept when the application is restarted.

To open the multiplayer game, choose **Campus Tycoon 2.0 · Multiplayer** in the left version selector. The host creates a game and shares its six-character code. The host must also save the private host credential to start the session. Each player should save their one-time recovery credential to resume later. Once the host starts, each player chooses a location, edits their own menu from the 12-product V2 catalogue, then buys stock, sets prices, and completes trading days independently. Daily demand uses the approved deterministic persona model. Rent is charged once after daily sales; if cash cannot cover rent, the remaining cash is applied, the shortfall is forgiven, and that player's game ends at €0. The final score is final cash minus starting cash, with no recovery value for unsold stock. The management dashboard summarizes each player's own results, inventory, and completed days. Finished players receive a saved-data performance report. Open **Leaderboard** to compare players in the current session; its ranking stays provisional until everyone finishes.

## Run the tests

```bash
uv run pytest
```
