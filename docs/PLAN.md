# Historical document — original Campus Tycoon V1

> This plan records the original Campus Tycoon V1 development and is not the specification for the current Coffee Shop Empire application. Current Version 1.0 Single Player and Version 2.0 Multiplayer use the shared current game implementation. For the current project, see [README.md](../README.md) and [V2_ARCHITECTURE.md](V2_ARCHITECTURE.md).

# Campus Tycoon — Development Plan

This plan proposes a small Python command-line application using only the standard library. A text interface keeps the first version approachable for a programming beginner, while the game logic remains usable independently of that interface. If the course requires another language or interface, agree on that before implementation.

## Proposed project structure

```text
campus-tycoon/
├── AGENTS.md
├── docs/
│   ├── BRD.md
│   └── PLAN.md
├── campus_tycoon/
│   ├── __init__.py
│   ├── models.py       # Data shapes for products, run state, and daily results
│   ├── game.py         # Rules: purchases, prices, demand, trading, and totals
│   ├── storage.py      # Local save/load and safe, consistent writes
│   └── cli.py          # Menus, prompts, display, and confirmation
├── main.py             # Starts the application
└── tests/
    ├── test_game.py    # Deterministic business-rule and acceptance tests
    └── test_storage.py # Save, reload, and no-replay tests
```

The files above are a proposal, not an implementation. Exact test and launch commands will be documented once the project files exist.

## Stages

### Stage 1 — Set up and represent the game

Agree on the language and interface, create the package and test layout, and define product data and the run-state fields. Establish a simple test command. No menus or full simulation yet.

### Stage 2 — Implement and check the business rules

Add pure game operations for validating quantities and prices, calculating demand, buying stock, trading one day, computing daily results, and calculating final gain/loss. Write deterministic tests for A1–A4 and the monetary boundaries. Keep this layer independent of menus and files.

### Stage 3 — Save and resume locally

Add local persistence for cash, inventory, selected prices, current day, and history. Save accepted actions consistently and load the existing run at startup. Test A5, including that one completed day is recorded only once and never replayed on reopening.

### Stage 4 — Add the player interface

Build a simple text menu for viewing the run, purchasing, setting prices, trading, reviewing history, and starting a new run. Explain the demand tiers in the price screen. Validate input and show clear rejection messages without altering the run.

### Stage 5 — Finish run completion and verify acceptance

Show final cash, remaining stock at purchase cost, and overall gain/loss after five days. Disable buying and trading then. Add the confirm/cancel restart flow and verify A6. Walk through all six acceptance scenarios and document how to launch and play the finished version.

## Completion checks

- All six acceptance scenarios pass.
- Money uses integer cents or precise decimal arithmetic throughout.
- A rejected operation leaves in-memory and saved game state unchanged.
- Restarting the program retains the run and does not repeat a trading day.
- No paid service is required; dependencies are limited to what the agreed implementation actually needs.
