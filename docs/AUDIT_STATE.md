# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Flutter Mane | TEF | 78 | sv05-078
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-12
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-11
last_first_card_audited: Counter Gain | SSP | 169 | sv08-169
last_card_fully_audited: Flutter Mane | SSP | 96 | sv08-096
notes: Run 35 (2026-05-12): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 242 DB cards were audited from Counter Gain | SSP | 169 | sv08-169 through Flutter Mane | SSP | 96 | sv08-096 (sequential rows 240–475 + 7 cross-reference cards). Implemented 17 fixes (0 documented engine gaps); target is 25. Report at docs/audit_runs/2026-05-12-35-card-effect-audit.json. Next run should resume from Flutter Mane | TEF | 78 | sv05-078.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
