# Campus Tycoon

A local campus café simulation built with Python, Streamlit, and SQLite. The current foundation creates and remembers the starting run and displays its dashboard. Buying, changing prices, and trading are planned for later steps.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Run the application

From the project folder, run:

```bash
uv sync
uv run streamlit run app.py
```

The local database is created automatically as `campus_tycoon.sqlite3` in the project folder. It is ignored by Git and is kept when the application is restarted.

## Run the tests

```bash
uv run pytest
```
