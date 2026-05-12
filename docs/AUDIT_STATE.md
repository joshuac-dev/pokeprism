# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Cornerstone Mask Ogerpon | DRI | 111 | sv10-111
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-12
last_pr: 65
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-12
last_first_card_audited: Boxed Order | TEF | 143 | sv05-143
last_card_fully_audited: Core Memory | POR | 70 | me03-070
notes: Run 38 (2026-05-12): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 100 DB cards were audited from Boxed Order | TEF | 143 | sv05-143 through Core Memory | POR | 70 | me03-070. No fixable gaps found in this slice (fixes_implemented=0, engine_gaps_documented=0). Stopping with CONTINUATION_REQUIRED; next run resumes at Cornerstone Mask Ogerpon | DRI | 111 | sv10-111. Report at docs/audit_runs/2026-05-12-38-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
