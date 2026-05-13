# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Farigiraf ex | TEF | 108 | sv05-108
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-13
last_pr: 65
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-13
last_first_card_audited: Drifloon | MEP | 5 | mep-005
last_card_fully_audited: Farigiraf | TWM | 84 | sv06-084
notes: Run 40 (2026-05-13): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Drifloon | MEP | 5 | mep-005 through Farigiraf | TWM | 84 | sv06-084. Findings: fixes_implemented=0, engine_gaps_documented=0. Next run resumes at Farigiraf ex | TEF | 108 | sv05-108. Report at docs/audit_runs/2026-05-13-40-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
