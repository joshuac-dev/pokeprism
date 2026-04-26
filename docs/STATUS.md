# PokéPrism — Development Status

> This file is updated at the end of every development session.
> Read this BEFORE reading PROJECT.md to understand current state.

## Current Phase
Phase 2 — Card Effect Registry (157 cards)

## Last Session
- **Date:** 2026-04-26
- **Duration:** ~3 hours
- **Phase 1 completed and verified.** All verification checks passed.

## What Was Built (Cumulative)
- [x] Phase 1: Game Engine Core (state machine, actions, transitions, runner)
- [ ] Phase 2: Card Effect Registry
- [ ] Phase 3: Heuristic Player & H/H Loop
- [ ] Phase 4+: Not started

## Current Phase Progress
Phase 2 has not been started yet. Next action: begin Phase 2 per PROJECT.md.

## Active Files Changed This Session
- `backend/app/cards/loader.py` — Fixed `_derive_subcategory`: Prism Energy (and any energy with `energyType:"Normal"` whose name contains no basic-type keyword) now correctly classified as "Special" instead of "Basic"
- `backend/app/players/base.py` — Fixed GreedyPlayer priority order: RETREAT moved from #7 to #9 (after PASS and END_TURN); prevents burning attached energy before attacking

## Known Issues / Gaps
- Pecharunt PR-SV 149: no SET_CODE_MAP entry for promo set. Non-blocking.
- M4 cards excluded (Chaos Rising unreleased until May 22, 2026).
- ME-era TCGDex set IDs (MEG, PFL, ASC, POR, MEE, WHT) are estimates — 
  actual IDs were discovered during fixture capture but should be re-verified 
  if any card loading fails.
- `×` multiplier attacks (e.g., Fezandipiti "Energy Feather" 30×) correctly 
  return 0 base damage in Phase 1 — effect handlers for these are Phase 2 work.
- GreedyPlayer has no "at risk" condition for retreat — it simply makes retreat 
  a last resort (after PASS/END_TURN). Phase 3 HeuristicPlayer should be smarter.
- USE_ABILITY not in GreedyPlayer's `_PRIORITY` list — falls through to 
  `legal_actions[0]` as a catch-all. Minor correctness gap, acceptable for Phase 1.
- RandomPlayer rarely attacks → all its games end via deck_out. Expected behavior.

## Key Decisions Made
- Test decks: Dragapult ex/Dusknoir (P1) vs Team Rocket's Mewtwo ex (P2)
- RandomPlayer + GreedyPlayer built as Phase 1 baselines (not the full 
  HeuristicPlayer, which is Phase 3)
- GreedyPlayer priority fix: PASS→#7, END_TURN→#8, RETREAT→#9
- SET_CODE_MAP uses zero-padded TCGDex IDs (sv01 not sv1)
- TCGDex card URL format: /cards/{setId}-{localId:03d}

## Phase 1 Baseline Metrics (for regression testing)
- Greedy vs Greedy (100 games): 53.9 avg turns, 74% prizes / 14% no_bench / 
  12% deck_out, 0 crashes
- Random vs Random (100 games): 94.6 avg turns, 100% deck_out, 0 crashes

## Notes for Next Session
- Phase 2 begins next: implement attack effect handlers for all 157 cards.
- Entry point: `backend/app/engine/effects/registry.py`. `_default_damage()` 
  handles fixed-damage attacks already. Phase 2 adds per-attack registrations.
- Priority order for Phase 2 implementation:
    1. Fixed-damage attacks with no special condition (bulk of the 157 cards)
    2. `×` multiplier attacks (e.g., "30× the number of…") — need state inspection
    3. Conditional damage modifiers (weakness/resistance already applied in default handler)
    4. Special energy effects (Prism Energy = any type for Basic Pokémon; Mist Energy = {C})
- `parse_damage()` in `effects/base.py` already extracts base integers; 0 returned
  for `×` attacks. Phase 2 effect handlers receive full GameState to compute real value.
- Prism Energy (ASC 216) currently provides Colorless. Its effect (any type for 
  Basic Pokémon) must be registered as a special energy handler in Phase 2.
- HeuristicPlayer (`players/heuristic.py`) is Phase 3 — do NOT build it in Phase 2.
- All 42 tests pass. Run `cd backend && pytest tests/ -q` to confirm baseline before 
  making any changes.
- Phase 1 baseline metrics are stored in STATUS.md under "Phase 1 Baseline Metrics" — 
  re-run the 200-game simulation after any engine change to detect regressions.
