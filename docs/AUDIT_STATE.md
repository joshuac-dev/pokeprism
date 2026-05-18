# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Miraidon | SSP | 69 | sv08-069
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-17
last_pr: 88
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-17
last_first_card_audited: Magmar | JTG | 20 | sv09-020
last_card_fully_audited: Miraidon | PR-SV | 92 | svp-092
notes: Run 46 (2026-05-17): CONTINUATION_REQUIRED — TCGDex preflight succeeded and 104 DB cards were audited from Magmar | JTG | 20 | sv09-020 through Miraidon | PR-SV | 92 | svp-092. Findings: fixes_implemented=6, engine_gaps_documented=0. Fixes: Bemusing Aroma self-confusion bug (sv10.5b-007), Fade Out energy-return bug (sv09-068), Magneton Overvolt Discharge passive-only registration x2 (svp-153, svp-159), Koraidon Unrelenting Onslaught missing Ancient filter (sv08-116), Alcremie ex Confectionary Gift wrong caster (sv09-075). Behavioral accounting: required=79, verified=0, unverified=79. Next run resumes at Miraidon | SSP | 69 | sv08-069. Report at docs/audit_runs/2026-05-17-46-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
