# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Lucario ex | PRE | 51 | sv08.5-051
last_run_status: PARTIAL_TIME_BUDGET
last_run_date_utc: 2026-05-11
last_pr:
last_issue: Standalone Codex DB-backed card effect audit pass 2 - 2026-05-11
last_first_card_audited: Lightning Energy | MEE | 4 | mee-004
last_card_fully_audited: Lt. Surge's Bargain | MEG | 120 | me01-120
notes: Standalone Codex audit pass 2 resumed after TCGDex recovery, confirmed DB access with 2223 cards and TCGDex preflight OK, then audited 36 contiguous database cards from Lightning Energy through Lt. Surge's Bargain before stopping with PARTIAL_TIME_BUDGET. Implemented fixes: Lillie's Pearl (sv09-151) now only reduces prizes for Lillie's Pokémon; Lillie's Comfey (sv09-068) Inviting Flowers now honors explicit empty selection; Lillie's Ribombee (sv09-067 / svp-183) Inviting Wink now has the ability owner choose opponent-hand Basics and ignores duplicate/non-eligible selections; Linoone (me02-082) Excited Dash now switches a Benched Linoone with the Active Pokémon instead of drawing cards. Documented engine gaps: Lively Stadium (sv08-180) requires continuous Stadium HP-modifier support plus KO recalculation when the Stadium leaves play. Focused tests: backend container `python3 -m pytest tests/test_engine/test_audit_fixes.py -q` passed 199 tests with 1 pytest cache permission warning. Full tests: backend container `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` passed 1350 tests / 5 skipped with 1 pytest cache permission warning.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.
