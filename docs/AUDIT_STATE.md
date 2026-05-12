# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Cryogonal | BLK | 27 | sv10.5b-027
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-12
last_pr: 65
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-12
last_first_card_audited: Cornerstone Mask Ogerpon | DRI | 111 | sv10-111
last_card_fully_audited: Crustle | DRI | 12 | sv10-012
notes: Run 39 (2026-05-12): TARGET_REACHED — TCGDex preflight succeeded and 28 DB cards were audited from Cornerstone Mask Ogerpon | DRI | 111 | sv10-111 through Crustle | DRI | 12 | sv10-012. Findings: fixes_implemented=0, engine_gaps_documented=25 (missing effect-handler coverage documented in ledger). Next run resumes at Cryogonal | BLK | 27 | sv10.5b-027. Report at docs/audit_runs/2026-05-12-39-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
