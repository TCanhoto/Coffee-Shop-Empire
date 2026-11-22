# Campus Tycoon

A campus café simulation built with Python 3.12, Streamlit, and SQLite. Single Player and Multiplayer now use the same café gameplay, business rules, player screens, and database engine. Only the way a game is created and accessed differs.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Run the application

From the project folder, run:

```bash
uv sync
uv run streamlit run app.py
```

The new shared game database (`campus_tycoon_v2.sqlite3`) is created automatically in the project folder and kept when the application is restarted. It stores each game in a separate session and player identity. Single-player sessions start immediately with one player. Multiplayer sessions use a host, join code, waiting room, and independent players.

To play alone, choose **Campus Tycoon 1.0 · Single Player**, enter the game length and starting cash, and start. The game opens directly at Day 0 location setup. Save the one-time solo recovery code and private credential so you can resume in another browser.

To play with others, choose **Campus Tycoon 2.0 · Multiplayer**. The host creates a game and shares its six-character code and private host credential. Each player saves their one-time recovery credential. Once the host starts, players choose locations and manage their own cafés independently.

Both modes use the same 12-product catalogue, five-product menu limit, deterministic persona demand, rent, events, dashboard, and final report. Daily rent is charged once after sales; if cash cannot cover it, the remaining cash is applied, the shortfall is forgiven, and that player's game ends at €0. The final score is final cash minus starting cash, with no recovery value for unsold stock. The Multiplayer mode also has a session leaderboard.

The original singleton V1 database (`campus_tycoon.sqlite3`) and its storage code are retained and never reset or automatically migrated. Because that save uses the older three-product game and different scoring rules, it cannot be resumed as a new shared-engine game.

## Run the tests

```bash
uv run pytest
```

See [docs/SHARED_MODES.md](docs/SHARED_MODES.md) for the shared architecture, data compatibility, manual test steps, and known gaps.
