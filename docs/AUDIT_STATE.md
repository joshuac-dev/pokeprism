# AUDIT_STATE.md

This file stores the rotating cursor for the DB-backed card effect audit workflow.

It does not define card text. It does not define the audit candidate set. The database defines audit scope, and TCGDex defines card behavior.

```text
next_start_cursor: Lapras | SCR | 31 | sv07-031
last_run_status: TARGET_REACHED
last_run_date_utc: 2026-05-06
last_pr:
last_issue: DB-backed card effect audit session 10
last_first_card_audited: Arboliva ex | SV9 | 23 | sv10-023
last_card_fully_audited: Lanturn | SCR | 49 | sv07-049
notes: 25 findings (15 code fixes + 10 engine gaps). Fixes: #1 sv05-015 Wafting Heal passive→real handler, #2 sv10-023 Oil Salvo bypass_wr=True, #3 sv06-087 Floette Minor Errand-Running max_count 1→3, #4 sv06-089 Swirlix Sneaky Placement any-opp-target, #5 sv06-021 Poltchageist Tea Server implemented, #6 sv06-022 Sinistcha Cursed Drop implemented, #7 sv06-022 Sinistcha Spill the Tea implemented, #8 sv06-023 Sinistcha ex Re-Brew implemented, #9 sv06-045 Seaking Peck Off implemented, #10 sv06-046 Jynx Inviting Kiss+Confused, #11 sv06-056 Froakie Flock implemented, #12 sv06-048 Crawdaunt Snip Snip+mill, #13 sv06.5-050 Eevee Colorful Catch, #14 sv06.5-051 Furfrou Energy Assist, #15 sv07-037 Tirtouga Splashing Turn. Engine gaps EG4–EG13 documented in test_audit_fixes.py. Full suite: 488 passed / 17 skipped.
```

## Cursor rules

- `next_start_cursor` is the first database card the next audit should attempt.
- The workflow should read this value when no manual start cursor override is supplied.
- Copilot should update this file in each PR after auditing cards.
- On `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.
- On `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.
- On `BLOCKED_DB_ACCESS`, do not advance the cursor.
- On `DB_EXHAUSTED`, keep or reset the cursor as described in `docs/AUDIT_RULES.md`.

