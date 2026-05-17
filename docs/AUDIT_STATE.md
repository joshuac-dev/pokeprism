# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Marill | TEF | 64 | sv05-064
last_run_status: CONTINUATION_REQUIRED
last_run_date_utc: 2026-05-17
last_pr: 84
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-17
last_first_card_audited: Koffing | JTG | 91 | sv09-091
last_card_fully_audited: Marill | SSP | 73 | sv08-073
notes: Run 46 (2026-05-17): CONTINUATION_REQUIRED — 120 DB cards audited from Koffing (sv09-091, pos 730) through Marill (sv08-073, pos 849). Findings: fixes_implemented=6, engine_gaps_documented=5. Fixes: Bemusing Aroma wrong-target bug, Fade Out energy-return bug, svp-153/svp-159 Magneton Overvolt Discharge passive-only (added handler), Koraidon Unrelenting Onslaught missing Ancient filter, Alcremie ex Confectionary Gift wrong caster. Gaps: Lucky Helmet draw-on-hit, Light Ball damage-modifier, Legacy Energy prize-reduction, Lillie's Pearl prize-reduction, N's Zoroark ex Night Joker player-choice. Report at docs/audit_runs/2026-05-17-46-card-effect-audit.json.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `CONTINUATION_REQUIRED`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
