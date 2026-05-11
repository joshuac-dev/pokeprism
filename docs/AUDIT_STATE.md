# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Lucario ex | PRE | 51 | sv08.5-051
last_run_status: BLOCKED_TCGDEX
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-11
last_first_card_audited:
last_card_fully_audited:
notes: Run 33 (2026-05-11): BLOCKED_TCGDEX — TCGDex API timed out during preflight (GET https://api.tcgdex.net/v2/en/cards/sv08.5-051 timed out after 5 s; network unreachable in sandbox environment). Per AUDIT_RULES.md, no cards were audited and the cursor is unchanged. Machine-readable report committed at docs/audit_runs/2026-05-11-33-card-effect-audit.json with completion_status BLOCKED_TCGDEX. Next run should resume from Lucario ex | PRE | 51 | sv08.5-051.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
