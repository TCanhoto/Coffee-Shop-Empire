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

To open the multiplayer game, choose **Campus Tycoon 2.0 · Multiplayer** in the left version selector. The host creates a game and shares its six-character code. The host must also save the private host credential to start the session. Each player should save their one-time recovery credential to resume later. Once the host starts, each player can buy stock, set prices, and complete trading days independently using the V1 catalogue and demand rules.

## Run the tests

```bash
uv run pytest
```
