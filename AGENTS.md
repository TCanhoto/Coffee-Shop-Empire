# Project instructions

## Working approach

- Build Campus Tycoon in small, reviewable stages. Follow `docs/PLAN.md` and explain new concepts in beginner-friendly language.
- Do not implement future stages before the user asks to continue.
- Keep business rules and calculations separate from the user interface and persistence code.
- Use integer cents (or another precise decimal representation) for money calculations; do not use binary floating-point for euro amounts.
- Validate an action completely before changing state. Accepted updates must be saved consistently; rejected actions must not change state or saved data.
- Keep the application local and avoid paid services or unnecessary dependencies.

## Tests

- Add tests for business rules and acceptance scenarios as their implementation stages are built.
- Run the relevant test command after changes that affect behavior, and report the command and result.
- Do not weaken, delete, skip, or rewrite tests merely to hide a failure. Fix the implementation or explain a genuine change in requirements before changing expected behavior.
- Keep tests deterministic; demand has no randomness in version 1.0.

## Project hygiene

- Keep documentation in `docs/` and update it when agreed requirements or the plan change.
- Avoid adding dependencies unless a clear project need justifies them; explain the reason first.
- Do not commit secrets or user data. Store save data locally in the location agreed during implementation.
