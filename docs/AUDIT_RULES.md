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

## Stable card identity

Treat every unique set/number/TCGDex identifier as a distinct card.

Same card name does not imply same card behavior. Same-name Pokémon across sets may have different attacks, abilities, HP, or effects. Same-name Trainers and Energy cards are often alternate prints, but the agent must still compare the current TCGDex effect text before reusing an existing handler.

A database card should be identified with the most stable available fields, in this order:

1. `tcgdex_id` or equivalent;
2. TCGDex set ID plus card number;
3. set code plus card number plus card name;
4. database primary key plus enough metadata to resolve the card through TCGDex.

If a database record lacks enough identity fields to fetch a matching TCGDex card, mark it as `db-identity-gap`.

## Resume cursor

The workflow may provide a resume cursor.

A cursor should identify the last fully audited database card, not a line in a markdown file.

Preferred cursor format:

`<card name> | <set id or set code> | <card number> | <tcgdex_id or db id>`

When resuming, continue with the first database card after that cursor in deterministic sort order.

The PR report must include:

- first database card audited;
- last database card fully audited;
- next resume cursor, if the database was not exhausted.

## Audit strategy

Do not perform a long discovery-only pass and postpone implementation until the end.

Use an atomic per-card loop:

1. Select the next database card.
2. Fetch that exact card from TCGDex.
3. Compare TCGDex behavior against implementation.
4. If a safe fix is needed, implement it immediately.
5. Add or update focused tests immediately.
6. Run the relevant focused tests.
7. Record the result in the audit ledger.
8. Move to the next database card.

The target finding count is a target for implemented fixes and documented engine gaps, not merely discovered possible issues.

Unfixed candidate issues do not count toward the target.

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
- `Next resume cursor`
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
- create broad unrelated refactors;
- create stub or placeholder handlers;
- silently approximate precise card mechanics.
