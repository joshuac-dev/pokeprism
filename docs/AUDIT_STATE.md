# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Wondrous Patch | PFL | 94 | me02-094
last_run_status: PARTIAL_TIME_BUDGET
last_run_date_utc: 2026-05-03
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-03
last_first_card_audited: Wondrous Patch | PFL | 94 | me02-094
last_card_fully_audited:
notes: PARTIAL_TIME_BUDGET. DB verified (1606 cards). TCGDEX_PREFLIGHT=ok (Wondrous Patch and Xerosic's Machinations fetched successfully). Start cursor located at DB index 1565. Registration grep completed for all 41 tail-of-alphabet cards. Time budget exhausted before card-by-card TCGDex comparison and fixes could be completed. Next run should restart at same cursor.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.

