# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Redeemable Ticket | JTG | 156 | sv09-156
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-19
last_pr: 93
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-19
last_first_card_audited: Pancham | JTG | 83 | sv09-083
last_card_fully_audited: Rare Candy | MEG | 125 | me01-125
notes: Run 48 (2026-05-19): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Pancham | JTG | 83 | sv09-083 through Rare Candy | MEG | 125 | me01-125. Findings: fixes_implemented=0, engine_gaps_documented=0. Behavioral accounting: required=76, verified=0, unverified=76. Next run resumes at Redeemable Ticket | JTG | 156 | sv09-156. Report at docs/audit_runs/2026-05-19-48-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
