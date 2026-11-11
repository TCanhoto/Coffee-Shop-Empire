"""Keep all screen tests away from the normal V1 save file."""

import pytest

import storage


@pytest.fixture(autouse=True)
def isolate_default_v1_database(tmp_path, monkeypatch):
    database = tmp_path / "default-v1.sqlite3"
    monkeypatch.setattr(storage, "DATABASE_PATH", database)
    # Python captures default arguments when a function is defined. Updating
    # DATABASE_PATH alone would not redirect load_run() and similar calls.
    for name in (
        "initialize_database", "load_run", "trade_day", "load_latest_trade",
        "load_trade_history", "get_final_results", "reset_run",
    ):
        monkeypatch.setattr(getattr(storage, name), "__defaults__", (database,))
