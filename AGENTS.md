# Project instructions

## Current project

- The current project is **Coffee Shop Empire**, previously known as Campus Tycoon. It uses Python 3.12, Streamlit, and SQLite.
- The visible **Version 1.0 — Single Player** and **Version 2.0 — Multiplayer** modes use the same current café-game implementation. The original V1 requirements and early command-line plan in `docs/BRD.md` and `docs/PLAN.md` are historical, not the current player interface.
- `app.py` selects a mode; `v2_interface.py` renders the shared Streamlit experience; `business_logic.py`, `content.py`, and `demand_engine.py` hold game rules and data; `v2_storage.py` persists current games in SQLite. `storage.py` and parts of `business_logic.py` retain legacy V1 behavior.
- For current behavior, follow the source code, tests, `README.md`, and `docs/V2_ARCHITECTURE.md`. Preserve existing saved-game compatibility unless the user approves a migration.

## Development workflow

- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. Use the locked environment:

  ```bash
  uv sync --locked
  uv run streamlit run app.py
  uv run --locked pytest
  ```

- Keep the interface, business calculations, and SQLite operations separate. Preserve both Single Player and Multiplayer behavior when changing shared gameplay.
- Validate actions before writing. Accepted game updates must be consistent and transactional where required; rejected actions must not change saved data.
- Preserve player/session isolation, authorization checks, duplicate-action protection, and transaction integrity.
- Changes to money, demand, inventory, prices, menus, rents, daily trading, or events require deterministic regression tests. Do not weaken, delete, skip, or rewrite tests to hide failures.
- Tests that use SQLite must use temporary databases and must never modify real saved-game databases.
- Keep the app usable locally without paid services or unnecessary dependencies. SQLite files on Streamlit Community Cloud's local filesystem are not guaranteed to survive restarts or redeployments; do not promise durable cloud saves.

## Security and repository safety

- Never hardcode, print, or commit passwords, recovery credentials, tokens, or other secrets. Keep local secret files and player databases excluded by `.gitignore`.
- Do not delete, reset, migrate, or overwrite real game databases as part of tests or routine development. Use a temporary database for migration checks.
- Do not change Git branches or commit, push, pull, or merge unless the user explicitly instructs you to do so.

## Communication

- Work in small, reviewable steps, explain important decisions in beginner-friendly English, and do not implement future or unrelated features before the user asks.
- Report the exact commands run and their results. Distinguish automated test results from manual browser/device verification.
