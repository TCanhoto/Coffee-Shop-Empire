# Coffee Shop Empire

Coffee Shop Empire is a café management simulation set in Lisbon. Players choose a neighbourhood, build a menu, buy stock, set prices, and manage a café using customer demand and daily results.

**Course:** Introduction to Programming, Nova SBE

### Playing Online vs. Running Locally

**Deployed application (recommended for multiplayer across devices):** [ctnovasbe.streamlit.app](https://ctnovasbe.streamlit.app/)

This is the recommended way to play Coffee Shop Empire, especially in Multiplayer mode. The application is hosted on Streamlit Community Cloud and is accessible over the internet, allowing players on different computers, smartphones, and networks to join the same multiplayer session using a shared session code.

**Local execution:** When running the application locally, Streamlit starts a server on your own computer (typically at `http://localhost:8501`). Multiplayer functionality is still available, but the `localhost` address is accessible only from the computer running the application. Connecting from other devices requires additional network configuration.

**For the easiest multiplayer experience across multiple devices or different networks, use the deployed application link above.**

## Team

- Margarida Tavares
- Rodrigo Trindade
- Tomás Canhoto

## Game modes

- **Version 1.0 — Single Player:** create or resume a solo café and play at your own pace.
- **Version 2.0 — Multiplayer:** host or join a game, manage an independent café, and compare results on the session leaderboard.

Both modes use the same café screens, business rules, demand calculations, and SQLite storage. The mode changes how a game is created and accessed.

## Gameplay

Choose a Lisbon location, select products for a menu of up to five items, purchase inventory, and set selling prices. Deterministic demand is based on location, customer personas, product preferences, and prices. In games lasting at least three days, each player receives one random location event on Day 3. Dashboards and final reports summarize performance; Multiplayer also includes a leaderboard.

## Run locally

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

From the repository folder, install the locked dependencies and launch the application:

```bash
uv sync --locked
uv run streamlit run app.py
```

Run the automated tests:

```bash
uv run pytest
```

## Repository structure

| File or folder | Responsibility |
| --- | --- |
| `app.py` | Shows the version selector and routes to the selected mode. |
| `v2_interface.py` | Renders the shared Streamlit interface and Solo/Multiplayer entry flows. |
| `v2_storage.py` | Creates and loads game records and saves player-scoped SQLite transactions. |
| `business_logic.py` | Validates and calculates purchases, sales, cash, and rent. |
| `content.py` | Defines the product catalogue, customer personas, and product affinities. |
| `demand_engine.py` | Calculates deterministic customer and product demand. |
| `v2_events.py` | Defines Day 3 location events and their effects. |
| `performance_report.py` | Builds the final player performance report. |
| `tests/` | Automated tests for business rules, storage, and Streamlit workflows. |
| `docs/` | Requirements, architecture, demand model, test plan, and project notes. |
| `pyproject.toml`, `uv.lock` | Declare project dependencies and lock their resolved versions. |

## Data storage and deployment

The application uses SQLite. Locally, it creates `campus_tycoon_v2.sqlite3` in the project folder and uses it to save games across local application restarts. The database is excluded from Git.

On Streamlit Community Cloud, data in the app's local filesystem is **not guaranteed to survive application restarts or redeployments**. Persistence across those events has not been verified for this deployment; do not rely on the local SQLite file as durable hosted storage.

## Historical V1

The project was previously named Campus Tycoon. Historical V1 requirements, baseline documentation, and the original `campus_tycoon.sqlite3` database are retained for reference and compatibility. They describe an earlier three-product game; they are not the current Version 1.0 Single Player mode. Current Single Player and Multiplayer both use the shared implementation described above.
