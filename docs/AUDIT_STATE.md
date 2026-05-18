# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Magmar | JTG | 20 | sv09-020
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-16
last_pr: 86
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-16
last_first_card_audited: Koffing | JTG | 91 | sv09-091
last_card_fully_audited: Magearna | JTG | 107 | sv09-107
notes: Run 45 (2026-05-16): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Koffing | JTG | 91 | sv09-091 through Magearna | JTG | 107 | sv09-107. Findings: fixes_implemented=0, engine_gaps_documented=0. Behavioral accounting: required=75, verified=0, unverified=75. Next run resumes at Magmar | JTG | 20 | sv09-020. Report at docs/audit_runs/2026-05-16-45-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
