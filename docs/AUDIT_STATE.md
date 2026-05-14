# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Hop's Wooloo | JTG | 135 | sv09-135
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-14
last_pr: 80
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-14
last_first_card_audited: Glimmora | TWM | 109 | sv06-109
last_card_fully_audited: Hop's Snorlax | PR-SV | 184 | svp-184
notes: Run 43 (2026-05-14): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Glimmora | TWM | 109 | sv06-109 through Hop's Snorlax | PR-SV | 184 | svp-184. Findings: fixes_implemented=4, engine_gaps_documented=2. Behavioral accounting: required=73, verified=0, unverified=73. Next run resumes at Hop's Wooloo | JTG | 135 | sv09-135. Report at docs/audit_runs/2026-05-14-43-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
