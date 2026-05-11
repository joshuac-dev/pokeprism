# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Lucario ex | PRE | 51 | sv08.5-051
last_run_status: DB_EXHAUSTED
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-11
last_first_card_audited: Lucario ex | PRE | 51 | sv08.5-051
last_card_fully_audited: Lt. Surge's Bargain | MEG | 120 | me01-120
notes: Robust-audit-v2 full-cycle DB-backed verification run from Lucario ex | PRE | 51 | sv08.5-051 completed one circular pass over all 1607 cards sorted by name/set_abbrev/set_number/tcgdex_id. TCGDex preflight and per-card fetches succeeded for the run. No new implementation fixes or engine gaps were identified by this pass-level coverage comparison. Machine-readable report committed at docs/audit_runs/2026-05-11-30-card-effect-audit.json with completion_status DB_EXHAUSTED and traversal_wrapped=true.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
