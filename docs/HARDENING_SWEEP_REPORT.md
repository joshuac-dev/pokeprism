# PokéPrism Hardening Sweep Report

**Date:** 2026-05-03  
**Branch:** hardening-sweep-2  
**Final test count:** 374 passed, 4 skipped (0 failures)

---

## Section 1 — Safety Hardening (AI Prompt, Validator Gate, Coach Prompt)

**Status: Complete (prior session)**

- AI player prompt rewritten to include full card detail: attack cost/damage/effect, ability text, Trainer effects, bench details, status conditions, tools
- `ActionValidator.validate()` forced-action gap fixed: `SWITCH_ACTIVE`, `CHOOSE_TARGET`, `CHOOSE_CARDS`, `CHOOSE_OPTION`, `DISCARD_ENERGY` now all validated against legal choice sets
- Coach prompt hardened with `<untrusted_data>` blocks wrapping deck lists, battle logs, card text, and memory text
- Evidence requirement added to coach swap recommendations (kind/ref/value)
- Strict JSON-only parsing; bounded repair path excludes hostile context

---

## Section 2 — AI/AI Behavioral Audit (Section 2C)

**Status: Complete**

- Qwen3.5-9B cold start ~52s, warm ~0.33s — confirmed responsive
- 3-game batch (Dragapult vs TR Mewtwo, Dragapult vs Ogerpon, TR Mewtwo vs Ogerpon) completed
- **Validator hard gate: PASS** — Zero illegal-action warnings across all 3 games
- **Decision quality:** AI occasionally miscalculates damage (edge cases with rounded HP values), but the hard gate correctly blocks any illegal follow-through
- `backend/scripts/ai_diagnostic.py` and `backend/scripts/ai_diagnostic_3games.py` created for on-demand behavioral audits

---

## Section 3 — Coach Mutation Legality

**Status: Complete (this session)**

### 3B — `_apply_mutations()` placeholder fix

**Root cause:** `_apply_mutations()` created `CardDefinition(name=add_id)` placeholder objects instead of using the real card definition.

**Fix:**
- `_apply_mutations()` now requires non-None `card_added_def` from the mutation dict; skips with warning if absent
- Skips any mutation where the card to remove is not found in the deck (prevents unbalanced deck size)
- New `_validate_post_mutation_deck()` validates 60-card count and 4-copy limits after all mutations
- Deck reverts to original on legality failure

**Files changed:** `backend/app/tasks/simulation.py`  
**Tests added:** `TestApplyMutations` (8 tests), `TestValidatePostMutationDeck` (4 tests) in `test_simulation_task.py`

### Coach candidate pool filtering

- `analyze_and_mutate()` filters swaps to only cards from the queried candidate pool
- `card_added_def` populated from DB lookup on candidate cards
- Tests: `test_non_candidate_add_discarded`, `test_excluded_add_discarded`, `test_card_added_def_populated_in_mutations`

---

## Section 4A — Damage Calculation Tests

**Status: Complete**

New test file: `backend/tests/test_engine/test_damage_calc.py` (9 tests)

| Test | Result |
|------|--------|
| Weakness ×2 multiplier | PASS |
| No weakness = no multiplier | PASS |
| Resistance −30 subtraction | PASS |
| Resistance floor is 0 (never negative) | PASS |
| Weakness then resistance combined (50 × 2 − 30 = 70) | PASS |
| KO regular Pokémon → 1 prize | PASS |
| KO ex Pokémon → 2 prizes | PASS |
| Last prize → game over (win_condition=prizes) | PASS |
| KO last Pokémon with no bench → game over (win_condition=no_bench) | PASS |

---

## Section 4B — Status Condition Fixes

**Status: Complete**

### Bugs found and fixed

| Bug | Fix | File |
|-----|-----|------|
| PARALYZED did not block attack actions | Added `_SC.PARALYZED` check in `_get_attack_actions()` | `actions.py` |
| ASLEEP did not block attack actions | Added `_SC.ASLEEP` check in `_get_attack_actions()` | `actions.py` |
| PARALYZED did not block retreat actions | Added `_SC.PARALYZED` check in `_get_retreat_actions()` | `actions.py` |
| PARALYZED removed for both players at turn end | Now only removed for `state.active_player`'s Pokémon | `runner.py:435` |
| Burn flip direction backwards (heads = damage) | Changed `if flip:` → `if not flip:` (tails = 20 damage) | `runner.py:412` |
| CONFUSED coin flip entirely missing | Added flip before attack resolves; tails → 30 self-damage + return | `transitions.py` |

### New test file: `backend/tests/test_engine/test_status_conditions.py` (10 tests)

All 10 status condition behavior tests pass.

---

## Section 4C — Special Mechanics Audit

**Status: Complete**

New test file: `backend/tests/test_engine/test_special_mechanics.py` (10 tests)

| Mechanic | Verdict |
|---------|---------|
| CHOOSE_CARDS: valid selection passes | PASS |
| CHOOSE_CARDS: count below min rejected | PASS |
| CHOOSE_CARDS: count above max rejected | PASS |
| CHOOSE_CARDS: ID outside choice set rejected | PASS |
| CHOOSE_TARGET: valid target passes | PASS |
| CHOOSE_TARGET: ID outside set rejected | PASS |
| Copy-attack keys excluded from copy candidates | PASS — `sv10-087:0` and `sv09-098:0` in `_COPY_ATTACK_KEYS` |
| Stadium placement sets `active_stadium` | PASS |
| Tool attachment stored as string (not object) | PASS |
| Special energy `provides` list propagated | PASS |

---

## Section 5 — Effect Handler Spot Check

**Status: Complete**

New test file: `backend/tests/test_engine/test_effect_coverage_spot_check.py` (2 tests)

- Loaded 50 randomly-sampled cards from 1,606 fixture files (deterministic seed 12345)
- All 50 sampled cards have registered handlers for all attacks/abilities/trainers/energy effects
- Zero unregistered effects detected

---

## Section 6 — DB Integrity, API Endpoints, Frontend State

**Status: Complete**

### DB integrity
- Schema review: all tables have appropriate NOT NULL constraints and FK relationships with CASCADE
- `Simulation`, `Round`, `Match`, `Event`, `Decision`, `DeckMutation` tables all have `simulation_id` FK with `ondelete="CASCADE"`
- No missing indexes on foreign key columns identified

### Neo4j graph integrity
- Previously validated (2026-05-02): zero "Future attached to a different loop" warnings
- Driver isolation fix (nil `_driver` before/after each Celery task) confirmed production-ready

### API endpoint coverage
Previously untested routes now covered in `test_simulations.py`:

| Endpoint | Tests Added |
|----------|-------------|
| `GET /api/simulations/{id}/rounds` | 3 tests (invalid UUID, empty, shape) |
| `GET /api/simulations/{id}/mutations` | 3 tests (invalid UUID, empty, shape) |
| `PATCH /api/simulations/{id}/star` | 3 tests (invalid UUID, 404, toggle) |

---

## Section 7 — Docker Compose, Error Handling, Celery Beat

**Status: Audited (no changes needed)**

### Docker compose
- All services have healthchecks (`postgres`, `neo4j`, `redis`, `ollama`, `backend`)
- `depends_on` uses `condition: service_healthy` for backend ✓
- `restart: unless-stopped` on all services ✓
- `celery-beat` correctly only has `REDIS_URL` (it only dispatches tasks, doesn't need DB) ✓

### Celery beat schedule
- Nightly H/H simulation at 02:00 UTC (`crontab(hour=2, minute=0)`)
- Task: `pokeprism.run_scheduled_hh`
- Schedule file: `/tmp/celerybeat-schedule`

### Error handling
- Simulation task: catches all exceptions, sets `status=failed`, re-raises
- Graph writes: non-fatal `try/except` with `logger.warning`
- Redis publish: non-fatal `try/except`

---

## Section 8 — Prompt Injection Resilience, Data Quality Gates

**Status: Audited (existing coverage confirmed)**

### Prompt injection
6 tests in `TestPromptInjectionHardening` (test_analyst.py):
- Hostile card name not in system message
- Hostile card name inside `<untrusted_data>` block
- Hostile memory text inside `<untrusted_data>` block
- Hostile candidate name inside `<untrusted_data>` block
- Hostile card name in tiers inside `<untrusted_data>` block
- Repair prompt does not include hostile card name

### Data quality gates
- `_check_deck_coverage()` in `simulations.py` validates all deck cards have registered effect handlers before enqueueing
- Coach evidence requirement: `analyze_and_mutate()` requires `kind`/`ref`/`value` evidence fields
- Candidate pool filtering: coach can only recommend cards from the queried candidate pool

---

## Summary

| Section | Status | Tests Added |
|---------|--------|-------------|
| 1 — Safety hardening | ✅ Complete (prior) | — |
| 2C — AI/AI audit | ✅ Complete | — |
| 3B — Coach mutation legality | ✅ Complete | 12 new tests |
| 4A — Damage calculation | ✅ Complete | 9 new tests |
| 4B — Status conditions | ✅ Complete | 10 new tests |
| 4C — Special mechanics | ✅ Complete | 10 new tests |
| 5 — Effect handler spot check | ✅ Complete | 2 new tests |
| 6 — DB/API/Neo4j | ✅ Complete | 9 new tests |
| 7 — Docker/Celery | ✅ Audited | — |
| 8 — Injection/Quality | ✅ Audited | — |

**Total new tests this sweep:** 52  
**Final suite:** 374 passed, 4 skipped, 0 failures
