# PokéPrism Hardening Sweep Report

**Date:** 2026-05-04 (Session 6 reverification)
**Branch:** main
**Prior sweep baseline:** 374 passed (2026-05-03, branch `hardening-sweep-2`)
**This sweep baseline:** 460 passed on entry → **463 passed after fixes**

This report replaces the 2026-05-03 sweep report. Each section records the
original requirement, evidence inspected, verdict, and any work performed.

---

## Section 1 — Baseline & Build Health

**Verdict: VERIFIED COMPLETE**

Evidence gathered:

| Check | Result |
|---|---|
| Backend test suite | 460 passed, 0 failed on entry (`python3 -m pytest tests/ -x -q`) |
| Frontend unit tests | 4 passed (`cd frontend && npm test -- --run --reporter=dot`) |
| Frontend build | Clean — `npm run build` exits 0, no TypeScript errors |
| Effect import smoke | Passed — all four effect modules import cleanly |
| TCGDex preflight | `ok` — API accessible at tcgdex.net |
| DB card count | 2,027 rows in `cards` table |
| Coverage endpoint | 2,026 auditable, 1,734 implemented, 292 flat-only, 0 missing, 100.0% |

---

## Section 2 — AI/AI Behavioral Audit

### 2A — AI Prompt Completeness

**Verdict: VERIFIED COMPLETE**

Inspected `backend/app/players/ai_player.py` line 101 (`_build_prompt()`).

The prompt includes:
- Full board state: active Pokémon HP/energy/status/tools, bench details
- Attack cost/damage/effect text for all active attacks
- Ability text
- Trainer card effects
- Legal action descriptions with parsed semantics
- Injection-hardening header separating system instructions from board data
- Core rules (one energy/turn, supporter limit, etc.)
- INTERRUPT types (SWITCH_ACTIVE etc.) handled by BasePlayer, not the AI

### 2B — ActionValidator Hard Gate

**Verdict: VERIFIED COMPLETE**

Inspected `backend/app/engine/actions.py` (849 lines).

- `validate()` always rebuilds legal actions via `get_legal_actions()` and compares
- `_validate_forced_action()` gates SWITCH_ACTIVE, CHOOSE_TARGET, CHOOSE_CARDS,
  CHOOSE_OPTION, DISCARD_ENERGY against their respective legal choice sets
- PARALYZED blocks attacks and retreat; ASLEEP blocks attacks; both verified via
  `backend/tests/test_engine/test_status_conditions.py` (10 tests)
- Evolution timing enforced via `turn_played`
- One energy/turn enforced via `energy_attached_this_turn`
- Tool limit (one per Pokémon) enforced

### 2C — AI/AI Behavioral Run

**Verdict: PARTIAL — BLOCKED BY RUNTIME CONSTRAINTS**

0 AI decisions exist in the DB (`SELECT COUNT(*) FROM decisions` → 0).

A diagnostic game (Dragapult vs TR-Mewtwo, 1 game, 300s timeout) was launched
and terminated with SIGTERM (exit 143). The Qwen3.5-9B model has ~52s cold
start; the game did not complete within budget.

Findings:
- Validator hard gate is sound per Section 2B; code review complete
- AI prompt is comprehensive per Section 2A; code review complete
- Decision DB remains empty — behavioral audit cannot be confirmed from DB records
- Prior sweep (2026-05-03) reported 3-game batch passed with zero illegal-action
  warnings on branch `hardening-sweep-2`; that evidence is no longer reproducible
  from this branch's DB state

Recommended follow-up: schedule a dedicated H/H simulation run (not AI-backed)
to populate DB records, then run `backend/scripts/ai_diagnostic.py` against a
warmed worker with a 600s+ timeout. Use available deck IDs: Dragapult
`3ef772f1-3446-43ff-a329-dcbfb1b77108`, TR-Mewtwo `befb48f8-a19d-4f8a-a7e0-0fd581c98333`.

---

## Section 3 — Coach Mutation Legality

### 3A — Prompt Injection Hardening

**Verdict: VERIFIED COMPLETE**

Inspected `backend/app/coach/analyst.py` (949 lines).

- `_build_prompt_messages()` returns `[system, user]` message list
- All untrusted data (deck lists, card text, memory text, battle logs) is wrapped
  in `<untrusted_data>` XML blocks with clear boundaries
- System message establishes role and evidence-enforcement rules before any data

### 3B — Evidence-Enforced Swap Decisions

**Verdict: VERIFIED COMPLETE**

- `_validate_swap_response()` returns `tuple[list|None, str|None]` and requires
  each evidence entry to have `kind`, `ref`, and `value` fields
- `kind` must be in `{"card_performance", "synergy", "round_result", "candidate_metric"}`
- `_get_swap_decisions()` uses a repair prompt that excludes untrusted context on retry
- Evidence sourcing confirmed from DB: `card_performance` table has 270 rows with
  valid `games_included`, `games_won`, `avg_damage`, `avg_survival_turns` data

---

## Section 4 — Engine Test Coverage

### 4A — Damage Calculation Tests

**Verdict: VERIFIED COMPLETE**

`backend/tests/test_engine/test_damage_calc.py` — 9 tests:

- weakness ×2 (type match)
- no-weakness (type mismatch)
- resistance −30
- floor at 0 (negative result clamped)
- combined: 50×2−30=70
- 1 prize regular KO
- 2 prize ex KO
- last prize → game over
- no-bench → game over (no_bench condition)

### 4B — Status Condition Tests

**Verdict: VERIFIED COMPLETE**

`backend/tests/test_engine/test_status_conditions.py` — 10 tests:

- PARALYZED blocks attacks
- PARALYZED blocks retreat
- ASLEEP blocks attacks
- CONFUSED does not block attacks
- POISONED does not block attacks
- PARALYZED timing (only removed for the active player's own turn end)
- Burn with tails → 20 damage applied between turns
- Burn with heads → no extra damage
- Confused with tails → 30 self-damage, attack cancelled
- Confused with heads → attack proceeds normally

### 4C — Special Mechanics Tests

**Verdict: VERIFIED COMPLETE**

`backend/tests/test_engine/test_special_mechanics.py` — 10 tests:

- CHOOSE_CARDS: `min_count` and `max_count` bounds enforced
- CHOOSE_TARGET: target must be in the declared legal set
- Copy-attack exclusion keys (`sv10-087:0`, `sv09-098:0`) in `_COPY_ATTACK_KEYS`
- Stadium placement sets `state.active_stadium`
- Tool stored as string (card_def_id) on `tools_attached`
- Special energy `provides` propagated through `EnergyAttachment`

---

## Section 5 — Handler Logic vs. Card Text

**Verdict: 3 BUGS FOUND AND FIXED; 2 ENGINE GAPS DOCUMENTED**

Spot-check inspected: me02-068 Sinister Surge, sv08-178 Jasmine's Gaze,
me02-090 Grimsley's Move, svp-089 Feraligatr Torrential Heart, svp-134
Crabominable Food Prep.

### Fix 1 — `_sinister_surge` duplicate (me02-068 Toxtricity) — CRITICAL

**Root cause:** `abilities.py` contained two definitions of `_sinister_surge`:

- **Line 676 (correct):** Attaches to a benched Darkness-type Pokémon only;
  places 2 damage counters on the target. Matches card text: "Search your deck
  for a Basic Darkness Energy and attach it to 1 of your Benched Pokémon that
  has Darkness in its name. Put 2 damage counters on that Pokémon."

- **Lines 2313–2358 (incorrect duplicate — now deleted):** Attached to ANY
  in-play Pokémon (`_in_play(player)`); placed no damage counters. Shadowed the
  correct definition at Python module level, so the registration at line 4295
  was silently using the wrong handler.

**Fix:** Deleted the incorrect duplicate function body and its companion
module-level `_cond_sinister_surge` (lines 2360–2368). The local
`_cond_sinister_surge` at line 4284 (inside the registration block, correctly
requiring `has_d_energy AND has_d_bench`) was already correct and remains.

**Files changed:** `backend/app/engine/effects/abilities.py`

**Regression test added:**
`test_sinister_surge_targets_darkness_bench_and_places_counters` in
`test_audit_fixes.py` — asserts that energy attaches to the Darkness-bench
Pokémon (not the non-Darkness bench), 2 damage counters are placed
(damage_counters=2, current_hp=80 from 100), and non-Darkness bench Pokémon
receives no energy.

### Fix 2 — `_jasmine_gaze` (sv08-178) — MODERATE

**Root cause:** Handler applied `incoming_damage_reduction += 30` only to
`player.active`. TCGDex text: "During your opponent's next turn, all of your
Pokémon take 30 less damage from attacks from your opponent's Pokémon (after
applying Weakness and Resistance). (This includes new Pokémon that come into
play.)"

**Fix:** Handler now applies `incoming_damage_reduction += 30` to all in-play
Pokémon (`[player.active] + list(player.bench)`).

**Engine gap documented (not fixed):** The TCGDex text says "includes new Pokémon
that come into play." Implementing this requires a player-level
`jasmine_gaze_active` flag and a hook in the bench-entry path; that refactor is
out of scope for this sweep. Additionally, `incoming_damage_reduction` is reset
unconditionally for all Pokémon in `_end_turn()` (`runner.py` lines 532/555),
which means protection effects set during the current player's turn are cleared
before the opponent attacks. This systemic timing issue affects Gaia Wave and
other "opponent's next turn" protection effects; it is documented here as a
known engine gap, not fixed in this sweep.

**Files changed:** `backend/app/engine/effects/trainers.py`

**Regression test added:** `test_jasmine_gaze_applies_to_active_and_bench` —
asserts that both active and all bench Pokémon get `incoming_damage_reduction==30`
and the opponent's Pokémon is unaffected.

### Fix 3 — `_grimsleys_move_b18` (me02-090 Grimsley's Move) — MINOR

**Root cause:** Handler used `max_count=max_choose` (capped by bench space and
candidate count) when issuing the `ChoiceRequest`. TCGDex text: "You may put
**a** (1) Darkness-type Pokémon you find there onto your Bench." The card places
at most 1 Pokémon.

**Fix:** Changed `max_count=max_choose` to `max_count=1` in the `ChoiceRequest`.

**Files changed:** `backend/app/engine/effects/trainers.py`

**Regression test added:** `test_grimsleys_move_max_one_pokemon` — drives the
generator to the first yield, asserts `req.max_count == 1`, then sends back a
response choosing only `dark1`, and asserts `dark1` is benched while `dark2` is not.

### Engine Gap 1 — svp-089 Feraligatr Torrential Heart — DOCUMENTED, NOT FIXED

Card text: "Once during your turn, when you attach an Energy from your hand to
this Pokémon, you may move any Energy from your Benched Pokémon to this Pokémon."
The engine tracks `energy_attached_this_turn` (bool) but does not track the
source of the energy attachment or expose a "triggered on attach" callback. The
handler is a noop stub. Implementing this requires an ability-trigger callback
for energy attachment events; deferred.

### Engine Gap 2 — svp-134 Crabominable Food Prep — DOCUMENTED, NOT FIXED

Card text: "If you played a Supporter card during this turn, you may move any
amount of Basic Energy from your Pokémon to your other Pokémon." The engine has
no mechanism for targeting a specific bench Pokémon as energy source in an
ability handler. The handler is a noop stub. Implementing this requires a
multi-target energy redistribution choice flow; deferred.

### Post-fix test run

**463 passed, 0 failed** (up from 460 on entry — 3 new regression tests added).

---

## Section 6 — Data Integrity & API

### 6A — Database Integrity

**Verdict: VERIFIED COMPLETE**

Evidence gathered with `docker compose exec postgres psql -U pokeprism`:

- Zero orphaned match events: left join of `match_events` onto `matches` found 0 orphans
- All simulations in terminal state: no stale `running` rows
- Valid `card_performance` data: 270 rows with non-zero `games_included`; `win_rate`
  computed as `games_won::float/NULLIF(games_included,0)` (no stored `win_rate` column)

### 6B — Neo4j Graph Orphan Nodes

**Verdict: KNOWN PRE-CHECKPOINTING ARTIFACT — NOT A REGRESSION**

MatchResult and Card nodes exist. Orphaned MatchResult nodes with no WON
relationship are a known artifact of the pre-checkpointing era when Celery
retries could create duplicate nodes. This data pre-dates the Session 5
opponent-batch checkpointing fix and was not caused by any change in this sweep.
No destructive cleanup was performed.

### 6C — API Endpoint Coverage

**Verdict: VERIFIED COMPLETE**

All frontend `api/*.ts` calls mapped against backend route definitions. All 20
active frontend endpoints have matching backend handlers. The `history.py` stub
returning 501 is a Phase 11 placeholder; the History page uses `/api/simulations/`
which is fully implemented with pagination support.

### 6D — Frontend State Management

**Verdict: VERIFIED COMPLETE**

- **WebSocket cleanup:** `useSocket.ts` `useEffect` cleanup calls `socket.disconnect()`
  and nulls the ref on unmount or `simulationId` change. Verified.
- **History pagination:** `History.tsx` tracks `page`/`total`/`PER_PAGE=25` state;
  calls `listSimulations({ page, per_page })` → `/api/simulations/` which accepts
  `page` and `per_page` query params and returns `{ items, total, page, per_page }`.
  Full prev/next UI present. Verified.
- **Zustand store reset:** `useSimulation.ts` `useEffect` calls `reset()` on
  `simulationId` change; `simulationStore.ts` `reset()` resets to `INITIAL` state.
  Verified.

---

## Section 7 — Celery / Beat / Redis

### 7A — Beat Schedule

**Verdict: VERIFIED COMPLETE**

`backend/app/tasks/celery_app.py` beat_schedule:
- `nightly-hh-simulation`: `crontab(hour=2, minute=0)` UTC nightly
- `advance-simulation-queue`: every `60.0` seconds (crash-recovery fallback)

### 7C — Retry Safety

**Verdict: VERIFIED COMPLETE**

Opponent-batch checkpointing fully implemented (Session 5):
- `simulation_opponent_results` table keyed by `(simulation_id, round_number, opponent_deck_id)`
- Completed checkpoints verified against persisted match counts and skipped on retry
- Stale running/zero-persisted checkpoints reset and rerun
- Graph failures remain non-fatal with `graph_status` tracking
- Live Docker/Celery replay validation passed

---

## Section 8 — Docker / Services / Environment

### 8A — Service Health

**Verdict: VERIFIED COMPLETE**

- Effect import smoke: all four effect modules import cleanly under Docker
- TCGDex preflight: API accessible
- Worker rebuild procedure documented: must rebuild `celery-worker` image after
  `effects/` changes since worker runs baked code

### 8B — Environment Config

**Verdict: VERIFIED COMPLETE**

`.env` file present with all required vars including `DATABASE_URL`, `REDIS_URL`,
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `SECRET_KEY`, `TCGDEX_BASE_URL`.

---

## Summary Table

| Section | Item | Verdict |
|---|---|---|
| 1 | Baseline & Build | VERIFIED COMPLETE |
| 2A | AI Prompt Completeness | VERIFIED COMPLETE |
| 2B | ActionValidator Hard Gate | VERIFIED COMPLETE |
| 2C | AI/AI Behavioral Run | PARTIAL — BLOCKED BY RUNTIME |
| 3A | Coach Prompt Injection Hardening | VERIFIED COMPLETE |
| 3B | Coach Evidence-Enforced Mutations | VERIFIED COMPLETE |
| 4A | Damage Calculation Tests | VERIFIED COMPLETE |
| 4B | Status Condition Tests | VERIFIED COMPLETE |
| 4C | Special Mechanics Tests | VERIFIED COMPLETE |
| 5 | Handler Logic vs. Card Text | 3 BUGS FIXED, 2 GAPS DOCUMENTED |
| 6A | DB Integrity | VERIFIED COMPLETE |
| 6B | Neo4j Graph Orphans | KNOWN ARTIFACT — NOT A REGRESSION |
| 6C | API Endpoint Coverage | VERIFIED COMPLETE |
| 6D | Frontend State Management | VERIFIED COMPLETE |
| 7A | Celery Beat Schedule | VERIFIED COMPLETE |
| 7C | Celery Retry Safety | VERIFIED COMPLETE |
| 8A | Docker/Service Health | VERIFIED COMPLETE |
| 8B | Environment Config | VERIFIED COMPLETE |

---

## Fixes Applied in This Sweep

| Card | Handler | Bug | Fix |
|---|---|---|---|
| me02-068 Toxtricity Sinister Surge | `_sinister_surge` | Duplicate at lines 2313–2368 shadowed correct implementation; attached to any Pokémon instead of only Darkness bench; placed no damage counters | Deleted duplicate; correct implementation at line 676 now active |
| sv08-178 Jasmine's Gaze | `_jasmine_gaze` | Applied 30-reduction only to Active; TCGDex: all Pokémon | Now applies to active + bench |
| me02-090 Grimsley's Move | `_grimsleys_move_b18` | `max_count=max_choose` allowed multiple Pokémon; card says "a" (1) | Fixed to `max_count=1` |

**Post-fix test count: 463 passed** (460 on entry, +3 regression tests).

---

## Known Engine Gaps (Not Fixed, Documented)

| Card | Gap | Reason deferred |
|---|---|---|
| svp-089 Feraligatr Torrential Heart | Energy-attach trigger callback absent | Requires new event-hook architecture for energy attachment |
| svp-134 Crabominable Food Prep | Multi-target bench-to-bench energy redistribution absent | Requires new multi-source choice flow |
| All "opponent's next turn" damage-reduction effects (Gaia Wave, Jasmine's Gaze new-Pokémon clause, etc.) | `incoming_damage_reduction` reset unconditionally in `_end_turn()` for all Pokémon before opponent attacks | Systemic timing fix needed; out of scope for this sweep |

---

*This report was produced via manual code review, DB queries, API spot-checks,
and live TCGDex text verification. Section 2C behavioral run was blocked by
Qwen3.5-9B cold-start latency exceeding the sweep time budget.*
