# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Ledyba | SCR | 2 | sv07-002
last_run_status: PARTIAL_TIME_BUDGET
last_run_date_utc: 2026-05-10
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-10
last_first_card_audited: Lapras | SCR | 31 | sv07-031
last_card_fully_audited: Ledian | SCR | 3 | sv07-003
notes: 4 findings (4 code fixes + 0 engine gaps after repair). Fixes: #S11-1 sv08.5-115 Larry's Skill explicit-empty handling; #S11-2 sv07-003/svp-133 Ledian Glittering Star Pattern optional on-evolve gust; #S11-3 sv07-032 Lapras ex Larimar Rain now supports arbitrary subset selection from revealed top-20 Energy cards before per-card attachments; #S11-4 me01-101 Latios Lustrous Assist now supports moving any amount of Energy from one or more Benched donors to Active Mega Latias ex. Focused tests: 3 passed (`EG10_larimar_rain or EG10_lustrous_assist`) + 184 audit regressions passed; full backend 1333 passed / 7 skipped.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
