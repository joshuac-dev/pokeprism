# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Accelgor | JTG | 13 | sv09-013
last_run_status: PARTIAL_TIME_BUDGET
last_run_date_utc: 2026-05-01
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-01
last_first_card_audited: Abomasnow | DRI | 60 | sv10-060
last_card_fully_audited: Academy at Night | SFA | 54 | sv06.5-054
notes: Audited 5 cards from start cursor. Fixed sv06-080 Teleporter ability; documented sv06.5-054 Academy at Night as a true stadium-action engine gap.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
```
