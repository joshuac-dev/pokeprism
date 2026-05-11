# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Counter Gain | SSP | 169 | sv08-169
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-11
last_first_card_audited: Lucario ex | PRE | 51 | sv08.5-051
last_card_fully_audited: Counter Gain | ASC | 186 | me02.5-186
notes: Run 34 (2026-05-11): TARGET_REACHED — TCGDex preflight succeeded and 1035 DB cards were audited in deterministic circular order from Lucario ex | PRE | 51 | sv08.5-051 through Counter Gain | ASC | 186 | me02.5-186, wrapping once. Documented 25 engine gaps (0 code fixes) in docs/audit_runs/2026-05-11-34-card-effect-audit.json. Next run should resume from Counter Gain | SSP | 169 | sv08-169.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
