# Historical document — original Campus Tycoon V1

> This document records the original Campus Tycoon V1 requirements and is not the specification for the current Coffee Shop Empire application. Current Version 1.0 Single Player and Version 2.0 Multiplayer use the shared current game implementation. For the current project, see [README.md](../README.md) and [V2_ARCHITECTURE.md](V2_ARCHITECTURE.md).

# Campus Tycoon — Business Requirements

**Version:** 1.0  
**Product:** Campus Café simulation  
**Course:** Introduction to Programming, Nova SBE

## 1. Purpose

Campus Tycoon is a small, local business simulation for learning programming. The player runs a campus café for five trading days, buying stock and setting prices for three products. The application must be understandable, reliable, and usable without paid external services.

## 2. Products and starting state

| Product | Unit purchase cost | Reference selling price |
| --- | ---: | ---: |
| Coffee | €2.00 | €4.00 |
| Sandwich | €3.00 | €6.00 |
| Cookie | €1.00 | €2.00 |

Each new run starts with €100.00 cash, no inventory, and a five-day trading period. The application must retain the current run when closed and reopened.

## 3. Required features

### CT01 — Manage a run

- Display the current day, available cash, and inventory of each product.
- Support progress through five trading days.
- Require confirmation before a new run replaces the existing run. Cancelling preserves it.

### CT02 — Purchase stock

- Accept positive whole-number quantities.
- Calculate purchase cost from quantity and unit purchase cost.
- Reject purchases the player cannot afford.
- Apply accepted cash and stock changes together. A rejected purchase changes no saved data.

### CT03 — Set prices

- Accept positive selling prices with at most two decimal places.
- Show the demand calculation rules to the player.
- Save accepted price changes.

### CT04 — Trade one day

- Simulate demand using the current prices and available stock.
- Show units sold, revenue, cost of goods sold, and gross profit for each product and in total.
- One explicit trade action completes exactly one day.

### CT05 — Review progress

- Record and display the history of daily results.
- After Day 5, show final cash, remaining inventory valued at purchase cost, and overall gain or loss.
- Disable purchases and trading after completion.

## 4. Business rules

1. Demand for each product on each day is deterministic:
   - Selling price at or below reference price: 10 units.
   - Selling price above reference price and at or below twice reference price: 5 units.
   - Selling price above twice reference price: 0 units.
2. Units sold equal the smaller of demand and available inventory. Unsold inventory carries forward.
3. Purchases reduce cash by quantity × unit cost. Sales increase cash by units sold × selling price. Cash and inventory must never be negative.
4. Daily gross profit equals revenue minus purchase cost of units sold.
5. Overall gain or loss equals final cash + remaining stock valued at purchase cost − starting cash (€100).
6. Euro monetary inputs allow at most two decimal places. Use integer cents or precise decimal arithmetic internally; do not rely on binary floating-point for money.
7. Each explicit trade action completes exactly one day. Refreshing or reopening the application must never replay a completed day's trade.
8. Closing and reopening must preserve cash, inventory, selected prices, current day, and history.
9. Accepted purchases, price changes, and trading-day results must be saved immediately and consistently.
10. Version 1.0 has no running costs, spoilage, borrowing, stock returns, random events, or competing businesses.
11. The application works locally without paid external services.

## 5. Acceptance scenarios

### A1 — Purchase within budget

Start with €100 and zero stock. Buy 10 units costing €2 each. Cash becomes €80 and stock becomes 10. An additional purchase costing €82 is rejected without changing cash or stock.

### A2 — Demand boundaries

For a reference price of €4:

| Selling price | Demand |
| ---: | ---: |
| €4.00 | 10 |
| €4.01 | 5 |
| €8.00 | 5 |
| €8.01 | 0 |

Zero and negative selling prices are rejected.

### A3 — Reconcile a trading day

Start with €80 cash, 10 units costing €2 each, selling price €4 at the reference price, and all other products out of stock. After one trade: revenue €40, cost of goods sold €20, gross profit €20, cash €120, and remaining stock 0.

### A4 — Stock limits sales

With demand of 10 and stock of 3, sell exactly 3 units. With zero stock, sell zero. Inventory never becomes negative.

### A5 — Resume without replay

Complete a trading day, stop and reopen the application. Cash, stock, prices, and history remain unchanged. The completed day appears exactly once in history.

### A6 — Complete and restart

After Day 5, buying and trading are disabled. If the user cancels a new run, preserve the existing run. If the user confirms, restore €100 cash, zero inventory, Day 1, and empty history.

## 6. Scope boundaries

Version 1.0 excludes random events, business upgrades, competing businesses, complex demand models, unnecessary external integrations, and paid services. Accepted actions survive restarting the application; rejected actions never change saved data; and the core experience works locally.

## 7. Quality and learning requirements

- Keep financial and simulation rules separate from input/output code so they can be understood and checked independently.
- Validate inputs before changing saved state.
- Persist each accepted action as one consistent update so partial changes are not left behind.
- Keep the implementation and its explanation suitable for a first-time programming student.
