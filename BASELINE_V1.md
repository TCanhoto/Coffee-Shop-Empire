# Campus Tycoon — Baseline V1

This document records the current Campus Tycoon version as a comparison point for future group-project changes. It describes the implementation and tests in this repository; the automated test results below were verified with the test command shown.

## Implemented features

- A local Streamlit dashboard showing available cash, current day and five-day progress, and the stock and fixed costs/reference prices for Coffee, Sandwich, and Cookie.
- A purchasing flow for positive whole-number quantities. It shows the total cost, rejects unaffordable or invalid purchases, and saves accepted cash and inventory changes together.
- A price-setting section for each product. It accepts positive prices to two decimal places, previews demand according to the displayed rule, and saves accepted prices immediately.
- A clearly labelled **Trade Day** action that simulates one day for all products. It displays demand, units sold, revenue, cost of goods sold, and gross profit by product and in total.
- Persistent trading history with daily totals and product-level results.
- A final results dashboard after the fifth trading day, showing final cash, remaining inventory value at purchase cost, and overall gain or loss.
- Disabled purchase, price-setting, and trading controls when a run is complete.
- A **New Run** flow requiring confirmation. Cancelling preserves the run; confirming restores starting cash, stock, prices, day, and empty history.
- Local SQLite persistence. Starting or refreshing the application does not reset the saved run or repeat completed sales.
- Automated tests for business rules, persistence, run management, and Streamlit run controls.

## Business rules

1. Demand is deterministic for each product and trading day:
   - Selling price at or below reference price: 10 units.
   - Selling price above reference price and at or below twice reference price: 5 units.
   - Selling price above twice reference price: 0 units.
2. Units sold are the smaller of demand and available inventory. Unsold stock carries forward.
3. Purchases reduce cash by quantity multiplied by purchase cost. Sales add revenue to cash; the purchase cost is not deducted again at sale. Cash and inventory cannot become negative.
4. Daily gross profit is revenue minus the purchase cost of units sold.
5. Overall gain or loss is final cash plus remaining stock valued at purchase cost, minus the starting €100.
6. Euro amounts are validated to at most two decimal places and stored/calculated as integer cents.
7. Each explicit trade action completes exactly one day. Refreshing or reopening the app does not replay it.
8. Cash, inventory, selected prices, current day, and history persist across restarts.
9. Accepted purchases, price changes, and trading results are saved immediately. Purchase and trade state changes use SQLite transactions; rejected actions leave saved state unchanged.
10. There are no running costs, spoilage, borrowing, stock returns, random events, or competing businesses in this version.
11. The app works locally and does not require paid external services.

The products and initial state are:

| Product | Purchase cost | Reference selling price |
| --- | ---: | ---: |
| Coffee | €2.00 | €4.00 |
| Sandwich | €3.00 | €6.00 |
| Cookie | €1.00 | €2.00 |

Each new run starts with €100.00, zero stock, and Day 1 of five.

## Acceptance scenarios and verified results

The following results were verified by the corresponding automated pytest coverage. The complete suite result is **42 passed**.

| Scenario | Verified result | Relevant test |
| --- | --- | --- |
| A1 — Purchase within budget | **PASS** — Buying 10 coffees leaves €80 cash and 10 units. A further €82 purchase is rejected, with cash and stock unchanged. | `test_purchase_within_budget_then_reject_overspend` |
| A2 — Demand boundaries | **PASS** — Coffee prices €4.00, €4.01, €8.00, and €8.01 give demand 10, 5, 5, and 0. Non-positive prices are rejected. | `test_coffee_demand_price_boundaries`, `test_invalid_prices_are_rejected` |
| A3 — Reconcile a trading day | **PASS** — Selling 10 coffees at €4.00 yields €40 revenue, €20 COGS, €20 gross profit, €120 cash, and zero remaining coffee stock. | `test_trade_day_reconciles_coffee_sales_and_cash` |
| A4 — Stock limits sales | **PASS** — Demand 10 with stock 3 sells 3; zero stock sells 0; inventory stays non-negative. | `test_trade_sells_only_available_inventory`, `test_zero_stock_sells_zero_units_and_totals_reconcile` |
| A5 — Resume without replay | **PASS** — Reopening storage and starting the dashboard preserve state and history; a completed trade remains recorded once. | `test_reopening_preserves_run_and_does_not_repeat_a_completed_trade`, `test_reopening_dashboard_does_not_repeat_saved_trade` |
| A6 — Complete and restart | **PASS** — Day 5 completion locks purchase, price, and trade actions. Cancelling preserves the completed run; confirming restores the initial state and clears history. | `test_ui_cancellation_leaves_the_saved_run_unchanged`, `test_ui_confirmation_resets_saved_run_and_history` |

## Setup and run commands

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

From the project directory:

```bash
uv sync
```

Launch the application:

```bash
uv run streamlit run app.py
```

Run all automated tests:

```bash
uv run pytest
```

If the default uv cache location has a permissions problem, the verified test command is:

```bash
UV_CACHE_DIR=/private/tmp/campus-tycoon-uv-cache uv run pytest
```

The application creates `campus_tycoon.sqlite3` in the project directory on first startup. That file contains the local saved run and is excluded from Git.

## Project structure

| File or directory | Responsibility |
| --- | --- |
| `app.py` | Streamlit dashboard and user interactions; calls business and storage functions. |
| `business_logic.py` | Product definitions, money/price validation, purchase and demand calculations, trade calculations, and final valuation. Money is handled in integer cents. |
| `storage.py` | SQLite schema creation, loading and saving the run, purchase/price/trade operations, history, final results, and confirmed reset. |
| `tests/` | Automated tests for storage, purchases, pricing/demand, trading, run management, and UI run controls. |
| `tests/test_storage.py` | Initial state and database initialization/persistence tests. |
| `tests/test_purchases.py` | Purchase acceptance/rejection and persistence tests. |
| `tests/test_pricing.py` | Price validation, demand boundaries, and price persistence tests. |
| `tests/test_trading.py` | One-day calculations, stock constraints, atomic saving, and five-day progression tests. |
| `tests/test_run_management.py` | Reopening, history, final valuation, completion locks, and reset tests. |
| `tests/test_app_run_controls.py` | Streamlit-level checks for reopening and new-run cancel/confirm behavior. |
| `docs/BRD.md` | Business requirements and acceptance criteria. |
| `docs/PLAN.md` | Proposed development stages and file plan. |
| `AGENTS.md` | Project working practices, testing expectations, and hygiene instructions. |
| `README.md` | Basic project overview and run/test instructions. |
| `pyproject.toml` | Python version range, Streamlit runtime dependency, pytest development dependency, and pytest configuration. |
| `uv.lock` | Locked dependency versions for reproducible `uv` environments. |
| `.gitignore` | Excludes local environment, database, temporary files, and secrets from Git. |

## Known limitations

- The game is a single local saved run in one SQLite file; it has no accounts, multi-user support, cloud synchronization, or automatic backup.
- UI tests use Streamlit `AppTest` and persistence tests use temporary SQLite databases. They do not automate a real Safari session or test multiple operating systems.
- The app provides only the defined deterministic demand model and does not model real-world customer behavior.
- `README.md` still contains an earlier, incomplete description of the feature set; this baseline document and `docs/BRD.md` describe the implemented version.

## Explicitly out of scope for V1

- Random events or demand.
- Business upgrades.
- Competing businesses.
- Complex demand models.
- Running costs, spoilage, borrowing, and stock returns.
- Paid services and unnecessary external integrations.
- Optional group-project enhancements not listed in the V1 business requirements.
