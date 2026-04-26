# PokéPrism Changelog

## Phase 1 — Game Engine Core (2026-04-26)

### What Was Built
- Pure-Python state machine covering the full Pokémon TCG turn structure:
  DRAW → MAIN (attach, evolve, play trainers, abilities) → ATTACK → KO aftermath
- `GameState` dataclass with `PlayerState`, `CardInstance`, `Phase` enum
- `ActionValidator`: 14 rules enforced, including first-turn attack ban, supporter 
  limit, energy-attachment limit, same-turn evolution ban, ex prize award
- `MatchRunner`: drives games to completion, handles forced bench promotion after KO, 
  deck-out and no-bench detection, prize-taking
- `EffectRegistry`: `_default_damage()` handles fixed-damage attacks; `×`-multiplier 
  attacks correctly yield 0 base damage (Phase 2 effect handlers will supply real values)
- `CardListLoader` + `CardRegistry`: loads 157 cards from live TCGDex fixtures; 
  SET_CODE_MAP with 13 corrected IDs and 6 ME-era sets
- `RandomPlayer` and `GreedyPlayer` as game-simulation baselines
- 157 live TCGDex fixture files captured under `backend/tests/fixtures/cards/`
- 42 unit tests all passing

### Key Files Created
- `backend/app/engine/state.py`
- `backend/app/engine/actions.py`
- `backend/app/engine/transitions.py`
- `backend/app/engine/runner.py`
- `backend/app/engine/rules.py`
- `backend/app/engine/effects/registry.py`
- `backend/app/engine/effects/base.py`
- `backend/app/cards/loader.py`
- `backend/app/cards/models.py`
- `backend/app/cards/registry.py`
- `backend/app/cards/tcgdex.py`
- `backend/app/players/base.py`
- `backend/tests/` (42 tests across 6 test files)
- `backend/tests/fixtures/cards/*.json` (157 live fixtures)

### Phase 1 Baseline Metrics
- **Greedy vs Greedy (100 games):** avg 53.9 turns, prizes=74% / no_bench=14% / 
  deck_out=12%, 26.2 attacks/game, 4.5 KOs/game, 0 crashes
- **Random vs Random (100 games):** avg 94.6 turns, deck_out=100%, 0 crashes

### Bugs Fixed During Verification
- `loader.py`: Prism Energy wrongly classified as "Basic" — fixed subcategory logic
- `players/base.py`: GreedyPlayer RETREAT priority was #7 (before PASS #8), 
  causing energy to be burned on retreat every turn before attacking — fixed to #9
- SET_CODE_MAP: 13 blueprint entries used wrong format/numbering (sv1 vs sv01, 
  wrong numbers for SSP/PRE/JTG/DRI) — all corrected to match actual TCGDex IDs
