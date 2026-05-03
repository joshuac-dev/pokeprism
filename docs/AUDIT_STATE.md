# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Mimikyu ex | JTG | 69 | sv09-069
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-03
last_pr:
last_issue: Nightly DB-backed card effect implementation audit - 2026-05-03
last_first_card_audited: Accelgor | JTG | 13 | sv09-013
last_card_fully_audited: Miltank | PRE | 81 | sv08.5-081
notes: Audited 25+ cards from start cursor. TARGET_REACHED with 25 implemented fixes/renames: Gnaw Through timing, Power Charger, Ready to Ram, Parabolic Charge, Familial March, Prism Charge, Infernal Slash, Nasal Lariat, Astonish, Bring Down the Axe, Angelite (sv08-086), Colorful Confection, Guarded Rolling, Surf Back, Mischievous Painting, Cinnabar Lure, Time Manipulation, Barite Jail rename, Zap Cannon rename, Aqua Wash bug fix, Crimson Blaster, Cursed Edge, Upthrusting Horns, Onyx rename, Moomoo Rolling rename.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.

