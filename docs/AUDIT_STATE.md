# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Koffing | JTG | 91 | sv09-091
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-15
last_pr: 83
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-15
last_first_card_audited: Hop's Wooloo | JTG | 135 | sv09-135
last_card_fully_audited: Klinklang | SCR | 101 | sv07-101
notes: Run 44 (2026-05-15): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Hop's Wooloo | JTG | 135 | sv09-135 through Klinklang | SCR | 101 | sv07-101. Findings: fixes_implemented=0, engine_gaps_documented=0. Behavioral accounting: required=88, verified=0, unverified=88. Next run resumes at Koffing | JTG | 91 | sv09-091. Report at docs/audit_runs/2026-05-15-44-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
