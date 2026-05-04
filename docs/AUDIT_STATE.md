# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Unfair Stamp | SV6 | 165 | sv06-165
last_run_status: PARTIAL_TIME_BUDGET
last_run_date_utc: 2026-05-05
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-05
last_first_card_audited: Wondrous Patch | PFL | 94 | me02-094
last_card_fully_audited: Unfair Stamp | SV6 | 165 | sv06-165
notes: 9 bugs fixed this session (#A1–#A9). Bugs: #A1 duplicate _strong_bash_b2 removed, #A2+#A3 _acerolas_mischief removed bogus draw-to-4 and added missing prize-count gate (opp must have ≤2 prizes), #A4 _lucian_b5 completely rewritten (shuffle hands to deck, coin flip → 6/3 draw), #A5 sv06-159 re-registered to _ogres_mask (was _noop), #A6 _unfair_stamp player draw corrected 3→5, #A7 _dangle_tail_flag → real discard-to-hand, #A8 _recovery_net_flag → real 2-Pokemon discard-to-hand, #A9 _avenging_edge_flag → real 100+60-if-ko-last-turn. Full suite: 411 passed / 3 skipped.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.

