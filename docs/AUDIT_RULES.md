# AUDIT_RULES.md

## Purpose

This document defines the rules for the automated card-effect implementation audit workflow.

This audit is **not** a card-pool expansion workflow. It must audit cards that are already present in the application database and verify that their code-level implementations match the current TCGDex card data.

## Non-goals

The audit must not use these files to decide which cards need to be audited:

- `docs/CARDLIST.md`
- `docs/POKEMON_MASTER_LIST.md`
- `docs/CARD_EXPANSION_RULES.md`

Those files were for early development or database expansion. They are not authoritative for implementation auditing.

The audit must not add a new batch of cards to the database unless a code fix explicitly requires a small metadata correction for a card that is already in the database.

## Source-of-truth model

There are three different sources involved in this audit. Do not confuse them.

### 1. Database = audit scope

The database determines which cards are in scope for the audit.

The agent must query the application database using the repository's existing database configuration, models, scripts, migrations, or API helpers. It must discover the correct table/model names from the codebase.

The audit candidate set is:

- cards currently present in the database;
- sorted deterministically by card name, then set identifier, then card number, then database primary key or TCGDex ID;
- filtered only when the workflow explicitly provides a resume cursor.

### 2. TCGDex = card text source of truth

TCGDex is the only acceptable source of truth for card text, attacks, abilities, trainer effects, special energy effects, HP, type, weakness, resistance, retreat cost, and other card attributes.

For every audited card, fetch the current card definition from TCGDex.

Do not use local markdown card lists, cached card-list files, generated fixture data, or old database text as the source of truth for card behavior.

If TCGDex is unavailable, blocked, or returns unusable data for the run, gracefully stop the audit and report `BLOCKED_TCGDEX`. Do not guess. Do not fall back to local card lists. Do not claim the audit was completed.

### 3. Codebase = implementation source

The codebase determines how card effects are implemented.

The agent must inspect the effect registry, attack handlers, ability handlers, trainer handlers, special-energy handlers, runner/engine logic, and tests to determine whether each database card is faithfully implemented.

## TCGDex availability preflight

Before auditing cards, run a small TCGDex access preflight.

The PR report must include one of:

- `TCGDEX_PREFLIGHT=ok`
- `TCGDEX_PREFLIGHT=blocked`
- `TCGDEX_PREFLIGHT=down`
- `TCGDEX_PREFLIGHT=partial`

If the result is `blocked`, `down`, or otherwise unusable, stop. Create a short PR or issue comment whose first line is:

`BLOCKED_TCGDEX: audit could not be completed because TCGDex was unavailable or unreachable.`

Include the command attempted, the failure mode, and the next recommended action.

## Database audit discovery

The agent must discover how to query cards from the database by inspecting the repository. Appropriate discovery targets include:

- ORM models;
- migration files;
- seed/import scripts;
- existing coverage endpoints;
- existing database utilities;
- test fixtures that show how the database is initialized;
- environment documentation that identifies the local database URL or container service.

The agent should prefer existing repository utilities over hand-written SQL when such utilities exist.

The audit report must state how the database card list was obtained, for example:

`DB_CARD_SOURCE=SQLAlchemy Card model via scripts/audit_db_cards.py`

or:

`DB_CARD_SOURCE=/api/cards endpoint against local dev database`

If the agent cannot locate or initialize the database, report `BLOCKED_DB_ACCESS` and explain exactly what is missing.


## Persistent audit state and rotation

The audit must use `docs/AUDIT_STATE.md` as its persistent cursor file.

This file exists so scheduled runs do not always restart at the beginning of the alphabet. The state file does **not** define card text and does **not** define the audit candidate set. It only records where the next database-backed audit should begin.

Required state fields:

```text
next_start_cursor: START_OF_DATABASE_CARD_LIST
last_run_status: never
last_run_date_utc:
last_pr:
last_issue:
last_first_card_audited:
last_card_fully_audited:
notes:
```

`next_start_cursor` means the first database card the next run should attempt to audit. It is not a markdown file line number.

The workflow may also provide a manual start cursor override. If a manual override is present, use it instead of `docs/AUDIT_STATE.md` for that run, but still update `docs/AUDIT_STATE.md` in the PR with the next correct cursor.

The agent must update `docs/AUDIT_STATE.md` in every PR that audits at least one database card. Update it to the first database card that should be audited by the next run.

If the run ends with `BLOCKED_TCGDEX` before any card is audited, do not advance the cursor.

If the run ends with `BLOCKED_DB_ACCESS`, do not advance the cursor.

If the run ends with `TARGET_REACHED` or `PARTIAL_TIME_BUDGET`, set `next_start_cursor` to the next database card after the last fully audited card.

If the run reaches the end of the sorted database list and still has not reached the target finding count, wrap to the beginning of the sorted database list and continue. If the run audits every database card in one circular pass without reaching the target, set completion status to `DB_EXHAUSTED` and set `next_start_cursor` to the same start cursor used for that full pass, or to `START_OF_DATABASE_CARD_LIST` if no concrete start cursor was available.

This creates a rotating circular audit over time: each partial run starts where the previous merged run stopped, continues forward through the deterministic database ordering, wraps around when needed, and eventually covers the whole database instead of repeatedly spending time on A-to-early-alphabet cards.

## Stable card identity

Treat every unique set/number/TCGDex identifier as a distinct card.

Same card name does not imply same card behavior. Same-name Pokémon across sets may have different attacks, abilities, HP, or effects. Same-name Trainers and Energy cards are often alternate prints, but the agent must still compare the current TCGDex effect text before reusing an existing handler.

A database card should be identified with the most stable available fields, in this order:

1. `tcgdex_id` or equivalent;
2. TCGDex set ID plus card number;
3. set code plus card number plus card name;
4. database primary key plus enough metadata to resolve the card through TCGDex.

If a database record lacks enough identity fields to fetch a matching TCGDex card, mark it as `db-identity-gap`.

## Resume cursor and circular traversal

The workflow provides a start cursor derived from either:

1. a manual workflow input, if supplied; or
2. `docs/AUDIT_STATE.md` field `next_start_cursor`; or
3. `START_OF_DATABASE_CARD_LIST` when no persisted cursor exists.

A cursor identifies a database card, not a line in a markdown file.

Preferred cursor format:

`<card name> | <set id or set code> | <card number> | <tcgdex_id or db id>`

The agent must query the database, produce the deterministic sorted database-card list, locate the start cursor, and begin at that point. If the cursor cannot be found because the card was removed or its identity changed, start at the next lexicographically greater database card if possible; otherwise start at the beginning and report the cursor mismatch.

Traversal is circular:

1. Start at the start cursor, or the first database card if the start cursor is `START_OF_DATABASE_CARD_LIST`.
2. Move forward through the deterministic sorted database list.
3. If the end of the database list is reached before the target finding count is reached, wrap to the first database card and continue.
4. Stop only when one of the allowed completion statuses is reached.
5. `DB_EXHAUSTED` means one complete circular pass over the database-card list was audited from the chosen start point and fewer than the target findings existed.

The PR report must include:

- start cursor used;
- first database card audited;
- last database card fully audited;
- whether traversal wrapped around;
- next resume cursor for `docs/AUDIT_STATE.md`;
- whether `docs/AUDIT_STATE.md` was updated.

## Audit strategy

Do not perform a long discovery-only pass and postpone implementation until the end.

Use an atomic per-card loop:

1. Select the next database card from the circular traversal order.
2. Fetch that exact card from TCGDex.
3. Compare TCGDex behavior against implementation.
4. If a safe fix is needed, implement it immediately.
5. Add or update focused tests immediately.
6. Run the relevant focused tests.
7. Record the result in the audit ledger.
8. Update the in-progress next cursor mentally or in notes.
9. Move to the next database card.

The target finding count is a target for implemented fixes and documented engine gaps, not merely discovered possible issues.

Unfixed candidate issues do not count toward the target.

If the agent detects a time-budget warning, it must stop looking for new cards, finish only the current safe fix if practical, run focused tests, update `docs/AUDIT_STATE.md` with the next database cursor, and open the PR with status `PARTIAL_TIME_BUDGET`.

## What counts as a finding

A finding may be counted when it is one of the following:

- an implementation bug fixed in code;
- a missing handler that was implemented and registered;
- a wrong handler registration that was corrected;
- a wrong damage, damage-counter, healing, draw, search, discard, attach, switch, status, prize, condition, target, or timing behavior that was fixed;
- a trainer, Pokémon Tool, Stadium, or Supporter effect mismatch that was fixed;
- a special energy effect mismatch that was fixed;
- a systemic engine issue that was fixed;
- a true engine gap that cannot safely be implemented in this PR but is documented precisely with affected cards, required mechanics, and recommended implementation approach.

Pure cosmetic comments do not count unless the comment is misleading enough to cause an implementation or review error.

A potential issue that the agent discovered but did not fix or document as a true engine gap should be listed under `Unresolved candidates` and should not count toward the target.

## Handler requirements

### Attacks

For every attack with TCGDex effect text, verify that the correct handler exists and is registered for that exact card/effect.

Check for:

- wrong base damage;
- wrong damage multiplier;
- missing bonus damage;
- wrong damage-counter count;
- missing or incorrect coin flip behavior;
- missing or incorrect conditional behavior;
- wrong target;
- missing self-damage;
- missing bench damage;
- missing status condition;
- missing or incorrect discard requirement;
- missing or incorrect search, draw, attach, switch, shuffle, reveal, prize, or heal behavior;
- wrong timing;
- incorrect interaction with ex/V/Tera/evolution/basic/stage/card-type rules.

Cards with attacks that have no effect text may use flat damage behavior if the engine already handles that correctly.

Cards with effect text must not silently fall back to flat damage.

### Abilities

For every TCGDex ability, verify that the code models it as the correct kind of effect.

Check whether the ability is:

- passive/static;
- activated by player choice;
- triggered by a game event;
- once-per-turn;
- conditional;
- shut off by status or board state;
- dependent on active/bench location;
- dependent on the owner's turn;
- dependent on card type, energy type, evolution state, or Pokémon name.

### Trainers

For every Trainer card, verify:

- correct Trainer subtype;
- exact effect behavior;
- correct play restrictions;
- correct target choices;
- correct draw/search/discard/attach/switch/heal/status/prize behavior;
- correct once-per-turn or supporter-per-turn handling;
- correct Stadium replacement or continuous effect handling when relevant;
- correct Tool attachment and detachment behavior when relevant.

### Special Energy

For every Special Energy card, verify:

- provided energy type or types;
- amount of energy provided;
- attachment restrictions;
- conditional behavior;
- damage modification;
- prevention effects;
- discard behavior;
- interaction with Pokémon type/stage/name/evolution status.

## Handler reuse

Handler reuse is allowed only when the current TCGDex text supports it.

For alternate prints or same-name cards:

1. Fetch the database card from TCGDex.
2. Fetch or inspect the card whose handler may be reused.
3. Compare relevant effect text.
4. Reuse the handler only when the relevant effect text is semantically identical and no set-specific behavior differs.
5. If the text differs, implement a separate handler or document a specific engine gap.

Do not assume same name means same effect.

## Complex effects and engine gaps

If a card effect is too complex to implement safely within the current run, document it as an engine gap only when the missing engine capability is clear.

A valid engine-gap entry must include:

- affected card name and set/number/TCGDex ID;
- exact TCGDex behavior summary;
- missing engine capability;
- files likely needing changes;
- suggested tests;
- why it was not safe to implement in this PR.

Do not create placeholder handlers that pretend to implement unsupported mechanics.

## Time-budget behavior

The Copilot coding agent may warn that its time budget is nearly exhausted.

When that happens:

1. Stop auditing new cards.
2. Finish the current card fix if it is already in progress and safe to complete.
3. Run the most relevant focused tests.
4. Commit the implemented changes.
5. Open the PR with status `PARTIAL_TIME_BUDGET`.
6. Include the next resume cursor.
7. Put any discovered but unfixed candidates in `Unresolved candidates`.

Do not spend the run building a large backlog of findings without implementing them.

## Tests

For every code fix, add or update focused tests wherever practical.

A test should verify the specific TCGDex behavior that was fixed. Avoid tests that only check that the handler exists or that no crash occurs.

Run focused tests after each logical group of changes. Run the full relevant suite before opening the PR if time allows.

If full tests cannot be run because of time, state that clearly in the PR report and include which focused tests were run.

## Required audit ledger

The PR must include a per-card audit ledger with these columns:

| # | DB ID | Card | Set/ID | TCGDex ID | TCGDex fetch | Effects checked | Result | Count contribution |
|---|-------|------|--------|-----------|--------------|-----------------|--------|--------------------|

Allowed result values:

- `fixed`
- `engine-gap`
- `no-issue`
- `tcgdex-unresolved`
- `db-identity-gap`
- `blocked-tcgdex`
- `blocked-db-access`
- `partial-time-budget`

## Required PR summary

The PR summary must include:

- `Completion status`: `TARGET_REACHED`, `DB_EXHAUSTED`, `BLOCKED_TCGDEX`, `BLOCKED_DB_ACCESS`, or `PARTIAL_TIME_BUDGET`
- `TCGDEX_PREFLIGHT`
- `DB_CARD_SOURCE`
- `Target findings`
- `Implemented fixes`
- `Documented engine gaps`
- `Unfixed candidate issues`
- `Database cards audited`
- `First card audited`
- `Last card fully audited`
- `Start cursor used`
- `Traversal wrapped`: yes/no
- `Next resume cursor`
- `AUDIT_STATE.md updated`: yes/no
- `Focused tests run`
- `Full tests run`
- `Coverage or implementation stats`, if available

## Hard prohibitions

The agent must not:

- use `CARDLIST.md` or `POKEMON_MASTER_LIST.md` to choose audit candidates;
- use `CARD_EXPANSION_RULES.md` as audit instructions;
- use local markdown files as card-text authority;
- use stale cached card data as source of truth;
- guess card text when TCGDex is unavailable;
- claim completion when TCGDex was blocked or down;
- run a discovery-only pass that finds many issues but implements none;
- restart from the beginning of the alphabet when `docs/AUDIT_STATE.md` provides a later cursor;
- create broad unrelated refactors;
- create stub or placeholder handlers;
- silently approximate precise card mechanics.
