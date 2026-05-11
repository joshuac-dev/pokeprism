# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Lightning Energy | MEE | 4 | mee-004
last_run_status: BLOCKED_TCGDEX
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Standalone Codex DB-backed card effect audit - 2026-05-11
last_first_card_audited: Ledyba | SCR | 2 | sv07-002
last_card_fully_audited: Light Ball | ASC | 191 | me02.5-191
notes: Standalone Codex audit confirmed DB access with 2223 cards and TCGDex preflight OK, then audited 7 contiguous database cards from Ledyba through Light Ball before TCGDex timed out on follow-up live fetches. Implemented fixes: Levincia (sv09-150) now uses explicit USE_STADIUM instead of automatic end-turn recovery; Light Ball (me02.5-191) now applies its +50 Pikachu ex vs ex damage bonus before Weakness/Resistance. Documented engine gaps: 0. Focused tests: backend container `python3 -m pytest tests/test_engine/test_audit_fixes.py -q` passed 195 tests with 1 pytest cache permission warning. Full tests: initial container run failed because local env had OBSERVED_PLAY_MEMORY_ENABLED=true; rerun with `OBSERVED_PLAY_MEMORY_ENABLED=false` passed 1346 tests / 5 skipped with 1 pytest cache permission warning.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
