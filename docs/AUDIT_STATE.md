# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Drifloon | MEP | 5 | mep-005
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-12
last_pr: 65
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-12
last_first_card_audited: Cornerstone Mask Ogerpon | DRI | 111 | sv10-111
last_card_fully_audited: Drifblim | SCR | 61 | sv07-061
notes: Run 39 (2026-05-12): CONTINUATION_REQUIRED — hardening review corrected false-positive engine-gap classifications (including Counter Gain me02.5-186 and sv08-169). TCGDex preflight succeeded and 100 DB cards were audited from Cornerstone Mask Ogerpon | DRI | 111 | sv10-111 through Drifblim | SCR | 61 | sv07-061. Findings: fixes_implemented=0, engine_gaps_documented=0. Next run resumes at Drifloon | MEP | 5 | mep-005. Report at docs/audit_runs/2026-05-12-39-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
