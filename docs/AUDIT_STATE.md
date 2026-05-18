# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Pancham | JTG | 83 | sv09-083
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-18
last_pr: 90
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-18
last_first_card_audited: Miraidon | SSP | 69 | sv08-069
last_card_fully_audited: Palpitoad | BLK | 20 | sv10.5b-020
notes: Run 47 (2026-05-18): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Miraidon | SSP | 69 | sv08-069 through Palpitoad | BLK | 20 | sv10.5b-020. Findings: fixes_implemented=0, engine_gaps_documented=0. Behavioral accounting: required=77, verified=0, unverified=77. Next run resumes at Pancham | JTG | 83 | sv09-083. Report at docs/audit_runs/2026-05-18-47-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
