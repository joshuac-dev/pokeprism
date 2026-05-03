# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Wondrous Patch | PFL | 94 | me02-094
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-03
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-03
last_first_card_audited: Mimikyu ex | JTG | 69 | sv09-069
last_card_fully_audited: Wo-Chien | PAR | 15 | sv08-015
notes: TARGET_REACHED with 31 findings. Start sv09-069, end sv08-015. Key fixes: deck.pop(0) for top-card discard in 9 handlers (Sudden Shearing, Outlaw Leg, Mountain Ramming x2, Brighten and Burn, Land Collapse x2, Hammer-lanche, Entangling Whip, Sandy Flapping); torment_blocked_attack_name not cleared for Active (runner.py); Hop's Choice Band unimplemented tool (damage bonus + cost reduction); Auto Heal wrong amount (90->10); Mammoth Hauler wrong behavior; Postwick damage bonus; Snack Seek passivization; 14 option_index->selected_option fixes. Engine gap: Wide Wall (sv07-076).
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.

