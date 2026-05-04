# Historical Card Expansion Rules

> Historical/supporting document. These rules were written for the expansion-era
> batch card-pool buildout. They are not the active DB-backed audit authority.
> Current implementation audits must use `docs/AUDIT_RULES.md` and
> `docs/AUDIT_STATE.md`; audit scope comes from the database and current card
> behavior comes from TCGDex. Do not use this file, `docs/CARDLIST.md`, or
> `docs/POKEMON_MASTER_LIST.md` to choose current audit candidates.

NEW PROJECT: Batch Card Pool Expansion to Full Standard Format

Read docs/PROJECT.md, docs/STATUS.md, and docs/POKEMON_MASTER_LIST.md 
in that order.

POKEMON_MASTER_LIST.md contains 1,982 Standard-legal cards in CARDLIST 
format: "CardName SET Number" (one per line, NO quantity prefix). This 
is NOT PTCGL format — there's no "4" at the start of each line.

FORMAT EXAMPLE:
  Spinarak POR 1
  Boss's Orders ASC 183
  Mega Charizard X ex PFL 13

CRITICAL RULES:

1. SAME NAME ≠ SAME CARD
   There are 527 duplicate card names across sets. You MUST treat every 
   (set, number) combination as a unique card and fetch its definition 
   from TCGDex individually. Never assume two cards with the same name 
   have the same attacks, abilities, HP, or effects.

   POKÉMON: Same-name Pokémon in different sets often have DIFFERENT 
   attacks and abilities. "Ralts MEG 58" and "Ralts ASC 87" are two 
   distinct cards that each need their own TCGDex lookup and potentially 
   their own effect handlers.

   TRAINERS: Same-name Trainers across sets almost always have IDENTICAL 
   effects (they're alternate prints). After fetching from TCGDex, 
   compare the effect text. If identical to an existing handler, register 
   the existing handler for the new tcgdex_id — one line, no new 
   implementation. If the effect text differs (rare but possible), 
   implement a new handler.

   ENERGY: Same — compare effect text before deciding whether to reuse 
   or implement.

2. VERIFY AGAINST TCGDEX, NEVER ASSUME
   For every card, fetch the full definition from TCGDex. Use the 
   on-demand fetch pipeline built in Phase 13. If TCGDex doesn't have 
   a card, log it as unresolvable and continue.

3. NEW SET CODES
   POKEMON_MASTER_LIST.md includes set codes not yet in SET_CODE_MAP:
   - MEP (Mega Evolution Promos)
   - PR-SV (SV Black Star Promos — note: uses hyphen in set code)
   - SVE (SV Energy)
   
   Before processing the first batch, add these to SET_CODE_MAP with 
   their TCGDex IDs. Query TCGDex's sets endpoint to find the correct 
   IDs. If any can't be resolved, log them and skip those cards.

4. NO STUBS, NO FLAT-DAMAGE FALLBACK FOR EFFECT CARDS
   - Cards with NO effect text on any attack → "flat damage only", no 
     handler needed, engine handles correctly
   - Cards WITH effect text → MUST have an explicit handler registered
   - The coverage gate blocks simulations using unimplemented cards
   - Every handler must be tested against the real TCGDex card definition

5. HANDLER REUSE DECISION TREE
   For each card, follow this exact decision tree:
   
   a. Fetch card from TCGDex
   b. Is it already in the DB with a handler? → Skip, remove from list
   c. Does a card with the SAME NAME already have a handler?
      → Compare the TCGDex effect text character by character
      → If IDENTICAL effects: register existing handler for new ID
      → If DIFFERENT effects: implement a new handler
   d. No existing handler for this name?
      → Is there effect text? → Implement new handler
      → No effect text? → Mark as flat-damage-only, no handler needed

6. COMPLEX EFFECTS
   If a card's effect is too complex to implement confidently (multi-step 
   player choices, unique mechanics never seen before, copying other 
   cards' attacks), flag it and move on. Add it to a FLAGGED_CARDS 
   section at the bottom of POKEMON_MASTER_LIST.md with a note explaining 
   why. I'll handle those manually.

WORKFLOW — PROCESS 100 CARDS AT A TIME:

For each batch of 100 cards (taken from the top of POKEMON_MASTER_LIST.md):

1. CHECK NEW SET CODES (first batch only)
   Resolve any unknown set codes in SET_CODE_MAP before processing.

2. FETCH AND CATEGORIZE
   For each card:
   - Fetch from TCGDex
   - Check if already in DB (skip if yes)
   - Check for same-name handler reuse (compare effects)
   - Categorize: skip / reuse handler / flat-damage-only / needs handler

3. IMPLEMENT HANDLERS
   Write effect handlers for all cards that need them.

4. REGISTER ALTERNATE PRINTS
   For cards reusing existing handlers, add the registration lines.

5. TEST
   Run the full test suite. Run 50 H/H games using decks that include 
   cards from this batch to verify 0 crashes.

6. UPDATE POKEMON_MASTER_LIST.md
   Remove all successfully processed cards from the file. Move flagged 
   cards to the FLAGGED_CARDS section at the bottom.

7. UPDATE COVERAGE
   Show me updated stats from /api/coverage.

8. REPORT
   After each batch, tell me:
   - Cards in this batch: 100
   - Already in DB (skipped): X
   - Same-name handler reuse (alternate prints): X
   - New flat-damage-only (no handler needed): X
   - New handlers implemented: X
   - Flagged (too complex): X (list them with reasons)
   - Failed to resolve from TCGDex: X (list them)
   - Removed from POKEMON_MASTER_LIST.md: X
   - Remaining in file: X
   - Test results: X passed
   - Coverage: X/X (X%)

9. WHEN THE LIST IS EMPTY
   When POKEMON_MASTER_LIST.md has only FLAGGED_CARDS remaining (or is 
   completely empty), announce: "All processable cards from 
   POKEMON_MASTER_LIST.md are implemented. Final coverage: X/X (X%). 
   Y cards remain flagged for manual implementation." Update STATUS.md.

RULES:
- Process exactly 100 cards per batch, then stop and report
- Do not start the next batch until I say "next batch"
- Cards are taken from the TOP of the file, in order
- Always fetch from TCGDex — never guess at card data
- Always compare effect text when considering handler reuse
- No stubs, no placeholders, no fake data

Start by:
1. Reading POKEMON_MASTER_LIST.md
2. Counting total cards
3. Checking how many are already in the DB
4. Identifying any unknown set codes that need SET_CODE_MAP entries
5. Telling me how many batches this will take (at 100/batch)

Do not process any cards yet — just give me the overview.
