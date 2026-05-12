# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Flutter Mane | TEF | 78 | sv05-078
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-12
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-12
last_first_card_audited: Flutter Mane | TEF | 78 | sv05-078
last_card_fully_audited: Zweilous | sv10.5w | 66 | sv10.5w-066
notes: Run 36 (2026-05-12): TARGET_REACHED — TCGDex preflight succeeded and 1132 DB cards were audited from Flutter Mane | TEF | 78 | sv05-078 through Zweilous | sv10.5w | 66 | sv10.5w-066 (indices 475–1607). Implemented 13 code fixes + 12 engine gaps documented = 25 total findings. Report at docs/audit_runs/2026-05-12-36-card-effect-audit.json. Run exhausted all remaining DB cards; next cursor wraps to start of DB.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
