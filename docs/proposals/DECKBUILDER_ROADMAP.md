# DeckBuilder Competitive Roadmap

**Status:** roadmap / partially implemented. Deterministic phases 1, 2, 4, and 5 have landed; Phase 3+ simulation-backed weighting remains deferred pending sufficient and reliable performance data.
**Date:** 2026-05-02  
**Current state:** Conservative deterministic builder with role/energy/staple/dead-card improvements. No generic memory/synergy weighting is active; simulation-backed preference work remains deferred.

---

## Current Limitations

- No role awareness (attacker vs support vs tech)
- No energy curve validation (deck may have wrong energy types for its Pokémon)
- No opening-hand quality assessment (Basic Pokémon density)
- No trainer balance (too many stadiums, too few searchers)
- No dead-card detection (cards that are never playable given deck composition)
- No feedback loop from simulation results
- No archetype templates or meta awareness
- No Neo4j synergy scoring

---

## Incremental Roadmap

### Phase 1 — Role Tagging and Energy Curve (prerequisite for everything)

**What:** Tag each card with a primary role before building. Roles:
- `attacker` — Basic or Stage-2 ex with ≥120 base damage
- `setup` — Stage-1/2 evolution lines, Rare Candy, search Supporters
- `energy_accel` — cards that attach extra energy (Emboar, Raihan, Energy Retrieval)
- `disruption` — Boss's Orders, Lost Vacuum, Iono
- `healing` — Hyper Potion, Mela, Miriam
- `tech` — situational counters (Forest Seal Stone, Counter Catcher)

**Energy curve:** After selecting the core attacker(s), count their attack costs, pick the matching Basic Energy type, and fill the energy slot to match. Current builder ignores energy type of the attacker's attacks.

**Deliverable:** `DeckBuilder._tag_card(card)` and `_energy_curve_for_deck(deck)` helpers.  
**Sim required:** No. Uses card definitions only.

---

### Phase 2 — Archetype Templates

**What:** Define 3–5 starting templates (aggro, control, spread, evolution-ramp, stall) as constraints on role counts. A template specifies:
- Minimum attacker count: 4–8
- Trainer composition range: {supporter: 8–12, item: 10–16, stadium: 2–4}
- Energy count: 8–15
- Whether evolution lines are required

**Integration:** `build_from_scratch(target_archetype=...)` uses the template to constrain `_fill_deck` instead of the current 18P/32T/10E hardcoded split.

**Deliverable:** `ARCHETYPE_TEMPLATES` dict; `_desired_counts_from_archetype()`.  
**Sim required:** No.

---

### Phase 3 — Synergy Scoring from Neo4j

**What:** Use `SYNERGIZES_WITH` weights to prefer cards that co-occur with the core attacker in winning games. Replace the static `_score_card` with:
1. Fetch top-N synergy partners of the core card from Neo4j.
2. Boost `_score_card` for each synergy partner by `weight * k`.
3. Fall back to static score if Neo4j is unavailable or the card has <5 games observed.

**Integration:** New `DeckBuilder.from_neo4j(core_card_id, db, graph)` async constructor that pre-fetches synergies before building. The existing `DeckBuilder` remains synchronous and deterministic for tests.

**Deliverable:** `DeckBuilder.from_neo4j()` + `_apply_synergy_boost(candidates, synergy_map)`.  
**Sim required:** Yes — need at minimum 1,000+ games involving the core card to get meaningful synergy weights. Current state: 1,145 matches, 85 card_performance rows, 1,612 Neo4j edges — enough to start but results will be noisy below ~5,000 games.

---

### Phase 4 — Opening Hand Quality and Staple Balance

**What:** Validate that a generated deck has:
- At least 4 Basic Pokémon (ensures consistent opening hand draw probability)
- At least one draw Supporter (Iono, Professor's Research, Colress's Experiment)
- At least one search Item (Nest Ball, Ultra Ball, Buddy-Buddy Poffin)
- No duplicate Stadiums (wastes slots)
- No more than 2 copies of situational tech cards

**Integration:** `validate_deck` gains new checks; `_fill_deck` prioritizes staples when below thresholds.

**Deliverable:** Extend `validate_deck()` with opening-hand checks; add `_trainer_role_counts()`.  
**Sim required:** No.

---

### Phase 5 — Dead-Card Detection

**What:** A dead card is one that is structurally unplayable given deck composition:
- An Ability card for a Pokémon not in the deck (e.g., Moon Stone Seal for a non-Ditto deck)
- An evolution card with no base form in the deck
- An energy card of a type that no Pokémon in the deck can use

**Integration:** Post-build validation pass. Detected dead cards are replaced with synergy-scored alternatives.

**Deliverable:** `_find_dead_cards(deck)` + loop in `_fill_deck` to replace them.  
**Sim required:** No.

---

### Phase 6 — Simulation Feedback Loop

**What:** After each round of simulation, the coach currently proposes card swaps via the LLM analyst. Add a secondary deterministic feedback path:
- Identify the 3 deck cards with the lowest `card_performance.win_rate` AND `games_included ≥ 20`.
- Identify the 3 top-performing non-deck cards from `card_performance` that share a role tag with the low performers.
- Propose these as deterministic swap candidates alongside LLM proposals.

**Integration:** New `CardPerformanceQueries.get_low_performers(deck_ids, min_games=20)` and `get_replacement_candidates(role_tag, exclude_ids)`.

**Deliverable:** `DeckBuilder.propose_performance_swaps(deck, db)` → `list[SwapCandidate]`.  
**Sim required:** Yes — needs ≥20 games per card for reliable win-rate signal.

---

### Phase 7 — Win-Rate-Based Flex-Slot Evolution

**What:** Designate 4–8 "flex slots" in the deck (the lowest-scoring non-core non-staple cards). After each simulation round, replace flex-slot cards if a better candidate exists (by `win_rate × synergy_weight` composite score). This replaces the current LLM-only swap model for high-volume H/H optimization.

**Integration:** Round loop in `simulation.py` gets an optional `flex_evolution` path before the LLM coach call.

**Deliverable:** `DeckBuilder.evolve_flex_slots(deck, performance_data, synergy_data, n_slots=4)`.  
**Sim required:** Yes — needs ≥5,000 matches for stable win-rate convergence.

---

### Phase 8 — Matchup-Specific Construction

**What:** When opponent deck data is available (from `SimulationOpponent` and `matches`), weight flex-slot candidates by their matchup win-rate against the expected meta opponent rather than overall win-rate.

**Integration:** `CardPerformanceQueries` extended with matchup-specific queries joining `matches.p2_deck_name`.

**Deliverable:** `get_matchup_win_rate(card_id, opponent_deck_name)`.  
**Sim required:** Yes — needs ≥500 games against each specific opponent to be stable.

---

## Implementation Order

| Phase | Prerequisite | Sim data needed | Estimated complexity |
|---|---|---|---|
| 1 — Role tagging + energy curve | None | No | Low |
| 2 — Archetype templates | Phase 1 | No | Low |
| 4 — Opening hand / staple balance | None | No | Low |
| 5 — Dead-card detection | Phase 1 | No | Low |
| 3 — Neo4j synergy scoring | Phase 1, ≥1k games | Yes | Medium |
| 6 — Performance feedback loop | Phases 1+3 | Yes (≥20/card) | Medium |
| 7 — Flex-slot evolution | Phase 6 | Yes (≥5k matches) | High |
| 8 — Matchup construction | Phase 7 | Yes (≥500/matchup) | High |

**Recommended start:** Phases 1, 2, 4, 5 (no sim data required, all deterministic) — implement together as a single PR. This brings the DeckBuilder from "random within category" to "role-aware with staple validation" without any database dependencies.
