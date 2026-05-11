# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Ledyba | SCR | 2 | sv07-002
last_run_status: DB_EXHAUSTED
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-11
last_first_card_audited: Ledyba | SCR | 2 | sv07-002
last_card_fully_audited: Ledian | SCR | 3 | sv07-003
notes: Full circular DB-backed pass from start cursor audited 1607 database cards and reached DB_EXHAUSTED with 0 implemented fixes and 0 documented engine gaps. TCGDex preflight was OK; all live card fetches resolved successfully and no current db-identity-gap rows were observed. Tests: backend baseline 1337 passed / 7 skipped.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
