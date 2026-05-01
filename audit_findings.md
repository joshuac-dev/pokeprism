# PokéPrism Engine — Security & Correctness Audit Findings

**Audited files:**
- `backend/app/engine/effects/attacks.py` (26 968 lines, 1 427 handlers)
- `backend/app/engine/effects/abilities.py` (5 078 lines)
- `backend/app/engine/effects/trainers.py` (5 468 lines)

**Reference corpus:** 1 606 fixture JSON files in `backend/tests/fixtures/cards/`

**Total confirmed bugs: 24**

---

## Critical Bugs

### Bug 1 — Python function shadowing: `_finishing_blow` (attacks.py)
- **Affected cards:** me02-038 Granbull *(first definition, dead)*; sv10.5b-065 Bisharp *(second definition, live)*
- **Lines:** first definition line 6091 (Granbull, dead code); second definition line 8497 (Bisharp, wins)
- **Card text (Granbull):** "If your opponent's Active Pokémon is Knocked Out by damage from this attack, this attack does 90 more damage." → max 180 damage
- **Card text (Bisharp):** max 120 damage (60 base + 60 bonus)
- **Bug:** Python uses the *last* definition of a name at module scope. Both cards are registered against `_finishing_blow`, but only the second definition (Bisharp's 60/120 formula) executes at runtime. Granbull's attack always produces 60 or 120 damage instead of the correct 90 or 180.
- **Severity:** **Critical**

---

### Bug 2 — Python function shadowing: `_garnet_volley` (attacks.py)
- **Affected cards:** me02.5-038 Cinderace ex, sv07-028 Cinderace ex *(first definition, dead)*; second definition line 18 486 *(wins)*
- **Lines:** first definition line 3 935 (bench-targeting version); second definition line 18 486
- **Card text:** "This attack does 180 damage to 1 of your opponent's Pokémon. (Don't apply Weakness and Resistance for Benched Pokémon.)"
- **Bug:** The first definition prompts the attacking player to choose any of the opponent's Pokémon (Active or Bench) and correctly applies no W/R for bench targets. The second definition that wins simply calls `_apply_damage(state, action, 180)`, which always hits the Active Pokémon and applies Weakness/Resistance. Bench targeting is completely lost.
- **Severity:** **Critical**

---

### Bug 3 — Python function shadowing: `_roasting_heat` (attacks.py)
- **Affected cards:** me01-022 Mega Camerupt ex *(first definition, dead)*; sv05-028 Slugma *(second definition, wins)*
- **Lines:** first definition line 6 912 (Mega Camerupt ex version, dead); second definition line 21 705 (Slugma version, wins); registration line 16 390
- **Card text (Mega Camerupt ex):** "Roasting Heat: 80 damage. If your opponent's Active Pokémon is Burned, this attack does 160 more damage." → 80 or 240 total
- **Card text (Slugma):** "Roasting Heat: 10 damage. If your opponent's Active Pokémon is Burned, this attack does 40 more damage." → 10 or 50 total
- **Bug:** Slugma's version shadows Mega Camerupt ex's definition. Mega Camerupt ex deals 10 or 50 total damage instead of 80 or 240. The card is rendered unusable in offensive play.
- **Severity:** **Critical**

---

### Bug 4 — Python function shadowing: `_sinister_surge` (abilities.py)
- **Affected card:** me02-068 Toxtricity *(first definition, dead)*
- **Lines:** first definition line 676 (correct); second definition line 2 250 (wins); double registration at lines 4 119 and 4 532
- **Card text:** "Once during your turn, you may attach a Basic [D] Energy card from your hand to 1 of your Benched [D] Pokémon. If you do, place 2 damage counters on that Pokémon."
- **Bug:** The second definition wins at runtime and has two errors: (a) it allows attaching to *any* Pokémon in play, not just Benched Darkness-type Pokémon; (b) it never places the 2 damage counters required by the card text. The card is also registered twice.
- **Severity:** **Critical**

---

### Bug 5 — Python function shadowing: `_run_errand` (abilities.py)
- **Affected card:** me01-104 Mega Kangaskhan ex
- **Lines:** first definition line 663 (correct, checks Active Spot); second definition line 1 129 (wins, no check)
- **Card text:** "You can use this Ability only if this Pokémon is in the Active Spot."
- **Bug:** The first definition correctly returns early if the Pokémon is not in the Active Spot (`if poke is not player.active: return`). The second definition that wins has no such guard, so the Ability can be triggered from the Bench, which the card explicitly forbids.
- **Severity:** **Critical**

---

### Bug 6 — Bounce effect discards instead of returning to hand: `_tuck_tail` (attacks.py)
- **Card:** me03-062 Meowth ex, attack 0 — "Tuck Tail"
- **Line:** 1 797
- **Card text:** "Put this Pokémon and all cards attached to it into your hand."
- **Bug:** The handler calls `meowth.energy_attached.clear()` and `meowth.tools_attached.clear()`. All attached Energy and Tool cards are silently destroyed (removed from all game zones) rather than placed into the player's hand.
- **Severity:** **Critical**

---

### Bug 7 — Bounce effect discards instead of returning to hand: `_swoobat_happy_return` (attacks.py)
- **Card:** sv10.5w-037 Swoobat, attack 0 — "Happy Return"
- **Line:** 9 084
- **Card text:** "Return this Pokémon and all cards attached to it to your hand."
- **Bug:** Same pattern as Bug 6 — `target.energy_attached.clear()` and `target.tools_attached.clear()` destroy all attached cards instead of adding them to `player.hand`.
- **Severity:** **Critical**

---

### Bug 8 — Wrong handler registration: me01-100 Mega Latias ex atk0 (attacks.py)
- **Card:** me01-100 Mega Latias ex, attack 0 — "Strafe"
- **Line:** registration line 16 458
- **Card text:** "40 damage. You *may* switch this Pokémon with 1 of your Benched Pokémon."
- **Bug:** Attack is registered with `_teleportation_attack`, which performs a *mandatory* switch. The card says "you may," making the switch optional. Players are forced to switch even when they do not want to.
- **Severity:** **Critical**

---

## High Severity Bugs

### Bug 9 — Energy card lost on bounce: `_icicle_loop` (attacks.py)
- **Card:** sv08-056 Chien-Pao, attack 0 — "Icicle Loop"
- **Line:** 1 875
- **Card text:** "Put an Energy attached to this Pokémon into your hand."
- **Bug:** The handler removes an `EnergyAttachment` from `poke.energy_attached`, but never locates the corresponding Card object (by `source_card_id`) and never appends it to `player.hand`. The Energy card is effectively destroyed.
- **Severity:** **High**

---

### Bug 10 — "You may" bypass discards all energy: `_bellowing_thunder` (attacks.py)
- **Card:** sv05-123 Raging Bolt ex, attack 0 — "Bellowing Thunder"
- **Lines:** 1 828–1 857
- **Card text:** "You may discard any amount of Basic Lightning Energy cards from your hand. This attack does 50 more damage for each card you discarded this way."
- **Bug:** When the player's response contains an empty selection (i.e., opts out by selecting 0 cards), the fallback at lines 1 855–1 857 executes `chosen_ids = [c.instance_id for c in l_energy]`, discarding *all* Lightning Energy from the hand. A player intending to skip the discard effect is punished by losing all their Lightning Energy.
- **Severity:** **High**

---

### Bug 11 — Wrong mechanic + wrong value: `_roggenrola_harden` (attacks.py)
- **Card:** sv10.5w-046 Roggenrola, attack 0 — "Harden"
- **Line:** 9 242
- **Card text:** "Prevent all damage done to this Pokémon by attacks if that damage is 40 or less during your opponent's next turn."
- **Bug:** The handler sets `incoming_damage_reduction += 30` (flat damage reduction, wrong mechanic, wrong value). It should set `prevent_damage_threshold = 40`, which prevents all damage below the threshold. Using flat reduction instead of threshold prevention is both mechanically wrong and uses an incorrect number (30 vs. 40).
- **Severity:** **High**

---

### Bug 12 — No player choice of Special Condition: `_miraculous_paint` (attacks.py)
- **Card:** me01-092 Grafaiai, attack 0 — "Miraculous Paint"
- **Line:** 7 526
- **Card text:** "Flip a coin. If heads, choose a Special Condition. Your opponent's Active Pokémon is now affected by that Special Condition."
- **Bug:** On heads the handler unconditionally applies `StatusCondition.PARALYZED`. The player is never offered a `ChoiceRequest` to select which Special Condition to inflict. Any Special Condition can be applied under the rules, but Paralyzed is the only possible outcome.
- **Severity:** **High**

---

### Bug 13 — "You may" not honored: `_chrono_burst` (attacks.py)
- **Card:** me01-095 Dialga, attack 1 — "Chrono Burst"
- **Line:** 7 748
- **Card text:** "You may shuffle all Energy attached to your opponent's Active Pokémon into their deck. If you do, this attack does 160 more damage."
- **Bug:** The handler always shuffles energy if any is attached and always deals the 160 bonus. There is no `ChoiceRequest` asking the player whether they wish to activate the shuffle. Players cannot opt out.
- **Severity:** **High**

---

### Bug 14 — "You may" bypass in ability: `_teal_dance` (abilities.py)
- **Card:** sv06-025 Teal Mask Ogerpon ex — "Teal Dance" ability
- **Line:** 845
- **Card text:** "Once during your turn, you may attach a Basic [G] Energy card from your hand to 1 of your Pokémon."
- **Bug:** When the player responds with 0 selected cards (declining the optional effect), the fallback `else [g_energy[0].instance_id]` auto-selects the first available Grass Energy and attaches it. The player's decision to skip is ignored.
- **Severity:** **High**

---

### Bug 15 — Wrong zone on energy attachment: `_golden_flame` duplicate (abilities.py)
- **Affected card:** me02.5-026 / sv10-039 Ethan's Ho-Oh ex — "Golden Flame" ability
- **Lines:** first definition line 1 449 (dead); second definition line 2 662 (wins)
- **Card text:** "Once during your turn, you may attach a Basic [R] Energy card from your discard pile to 1 of your Pokémon in play."
- **Bug:** The second (winning) definition sets `e_card.zone = Zone.DISCARD` on the energy card being attached, rather than updating it to the zone of the Pokémon it is attached to (e.g., `Zone.ACTIVE` or `Zone.BENCH`). The energy card is simultaneously listed as attached to the Pokémon *and* flagged as being in the discard pile, creating an inconsistent game state.
  Additionally, the first (dead) definition contains its own "you may" bypass bug: when the player selects 0 cards, the fallback attaches all Fire Energy from the discard pile.
- **Severity:** **High**

---

### Bug 16 — No player choice for energy move targets: `_slight_shift` (attacks.py)
- **Card:** sv10.5b-040 Elgyem, attack 0 — "Slight Shift"
- **Line:** 8 155
- **Card text:** "Move an Energy from 1 of your opponent's Pokémon to another of your opponent's Pokémon."
- **Bug:** The handler automatically selects `pokes_with_energy[0]` as the source and `targets[0]` as the destination with no `ChoiceRequest`. The attacking player should be allowed to choose the source and destination Pokémon.
- **Severity:** **High**

---

### Bug 17 — Bonus attack damage never triggers: `_echoed_voice` (attacks.py)
- **Card:** sv10.5b-044 Meloetta ex, attack 0 — "Echoed Voice"
- **Line:** 8 206
- **Card text:** "If this Pokémon used Echoed Voice last turn, this attack does 130 more damage."
- **Bug:** The bonus check listens for `ev.get("type") == "attack_start"` events, but no such event is ever emitted anywhere in the codebase (searches confirm zero occurrences of `"attack_start"` in event emission calls). The bonus condition is permanently `False`; Meloetta ex's second-turn bonus never fires.
- **Severity:** **High**

---

### Bug 18 — Missing play condition: `_acerolas_mischief` (trainers.py)
- **Card:** me01-113 Acerola's Mischief (Supporter)
- **Line:** 265
- **Card text:** "You can play this card only if your opponent has 2 or fewer Prize cards remaining."
- **Bug:** The handler has no check for the opponent's prize card count. The card can be played at any point in the game, not just when the opponent is near winning.
- **Severity:** **High**

---

### Bug 19 — Python function shadowing: `_poison_chain` double-registration (attacks.py)
- **Card:** svp-149 Pecharunt, attack 0 — "Poison Chain"
- **Lines:** first definition line 854 (40 damage + TOXIC + can't attack); second definition line 2 211 (10 damage + POISON + can't retreat, **wins**)
- **Registration lines:** 15 667 and 15 739 (registered **twice**)
- **Bug:** The first definition applies a Toxic status and prevents the opponent from attacking next turn (40 damage). The second (winning) definition applies regular Poison and prevents the opponent from retreating (10 damage). The card effectively has completely different gameplay from what its first-registered behavior describes. Additionally, the card is registered twice under two different `register_all` blocks; the second registration is redundant but overwrites with the same (second) function.
- **Severity:** **High**

---

## Medium Severity Bugs

### Bug 20 — Energy return uses wrong energy lookup: `_energy_loop` duplicate (attacks.py)
- **Affected cards:** sv10-017 Dipplin *(first definition, dead)*; both cards affected by second definition
- **Lines:** first definition line 9 781 (searches by `source_card_id`); second definition line 21 496 (searches by `card_def_id`, **wins**)
- **Card text (Dipplin):** "Put an Energy card attached to this Pokémon into your hand."
- **Bug:** Dipplin's (correct) version locates the energy card by matching `source_card_id` — the instance ID of the actual Card object attached. The winning version searches `player.hand + player.discard` by `card_def_id` (card type), which will (a) never find the attached energy card (it is not in hand/discard) and (b) may inadvertently return a different copy of the same energy card type. The energy card is neither found nor returned to hand.
- **Severity:** **Medium**

---

### Bug 21 — Python function shadowing: `_double_smash` (attacks.py)
- **Affected cards:** sv10.5b-043 Golurk *(first definition, dead)*; sv08-023 Simisear *(second definition, wins)*
- **Lines:** first definition line 8195 (Golurk, 80 per heads); second definition line 14414 (Simisear, **wins**, 70 per heads); Golurk registration line 16510
- **Card text (Golurk):** "Flip 2 coins. This attack does 80 damage for each heads." *(confirmed by fixture)*
- **Bug:** The winning Simisear definition uses `_apply_damage(state, action, 70 * heads)`. Golurk's attack produces 0, 70, or 140 damage instead of the correct 0, 80, or 160.
- **Severity:** **High**

---

### Bug 22 — Python function shadowing: `_bubble_drain` (attacks.py)
- **Affected cards:** me02-021 Seel atk0, me01-013 Seedot atk0 *(first definition, dead)*; sv10-067 Misty's Suicune *(second definition, wins)*
- **Lines:** first definition line 6270 (heals up to 20); second definition line 10417 (**wins**, heals 30); Seel registration line 16332, Seedot registration line 16383
- **Card text (Seel / Seedot):** Both cards heal 20 from this Pokémon after dealing damage.
- **Bug:** The winning definition removes 3 damage counters (30 HP) from the attacker. Seel and Seedot now over-heal by 10 each time their attack is used.
- **Severity:** **Medium**

---

### Bug 23 — Python function shadowing: `_megaton_fall` (attacks.py)
- **Affected cards:** me02.5-108 Groudon atk1 *(first definition, dead)*; sv09-046 Alolan Golem *(second definition, wins)*
- **Lines:** first definition line 4919 (30 recoil); second definition line 11961 (**wins**, 40 recoil); Groudon registration line 16074
- **Card text (Groudon):** "This Pokémon also does 30 damage to itself." *(per first definition docstring)*
- **Bug:** The winning definition applies 40 recoil (`damage_counters += 4`). Groudon takes 40 damage to itself instead of 30 after every Megaton Fall, potentially causing premature self-KO.
- **Severity:** **Medium**

---

### Bug 24 — Python function shadowing: `_sneaky_placement` (attacks.py)
- **Affected cards:** me02-046 Bramblin atk0 *(first definition, dead)*; sv06-089 Swirlix atk0 *(second definition, wins)*
- **Lines:** first definition line 6001 (10 damage to any 1 opp Pokémon, bench or active); second definition line 20956 (**wins**, 20 damage to opp Active only); Bramblin registration line 16311
- **Card text (Bramblin):** "Put 1 damage counter on 1 of your opponent's Pokémon." (bench or active, 10 damage)
- **Bug:** The winning Swirlix definition always targets the opponent's Active Pokémon for 20 damage. Bramblin can no longer place a damage counter on a Benched Pokémon, and deals double the intended damage.
- **Severity:** **Medium**

---

## Summary Table

| # | Severity | File | Card(s) | Handler | Description |
|---|----------|------|---------|---------|-------------|
| 1 | Critical | attacks.py:6091/8497 | me02-038 Granbull | `_finishing_blow` | Shadowed by Bisharp's formula: 60/120 instead of 90/180 |
| 2 | Critical | attacks.py:3935/18486 | me02.5-038, sv07-028 Cinderace ex | `_garnet_volley` | No bench targeting in winning definition |
| 3 | Critical | attacks.py:6912/21705 | me01-022 Mega Camerupt ex | `_roasting_heat` | Shadowed by Slugma's formula: 10/50 instead of 80/240 |
| 4 | Critical | abilities.py:676/2250 | me02-068 Toxtricity | `_sinister_surge` | Wrong target type; missing 2 damage counters |
| 5 | Critical | abilities.py:663/1129 | me01-104 Mega Kangaskhan ex | `_run_errand` | Active Spot requirement lost in winning definition |
| 6 | Critical | attacks.py:1797 | me03-062 Meowth ex | `_tuck_tail` | Attached cards cleared (destroyed) instead of bounced to hand |
| 7 | Critical | attacks.py:9084 | sv10.5w-037 Swoobat | `_swoobat_happy_return` | Attached cards cleared (destroyed) instead of bounced to hand |
| 8 | Critical | attacks.py:16458 | me01-100 Mega Latias ex | (registration) | Wrong handler `_teleportation_attack`; switch should be optional |
| 9 | High | attacks.py:1875 | sv08-056 Chien-Pao | `_icicle_loop` | Energy card never retrieved or added to hand |
| 10 | High | attacks.py:1828 | sv05-123 Raging Bolt ex | `_bellowing_thunder` | Empty selection fallback discards ALL Lightning Energy |
| 11 | High | attacks.py:9242 | sv10.5w-046 Roggenrola | `_roggenrola_harden` | Uses flat reduction (30) instead of threshold prevention (40) |
| 12 | High | attacks.py:7526 | me01-092 Grafaiai | `_miraculous_paint` | Always PARALYZED; no player choice of Special Condition |
| 13 | High | attacks.py:7748 | me01-095 Dialga | `_chrono_burst` | Always shuffles energy; "you may" not implemented |
| 14 | High | abilities.py:845 | sv06-025 Teal Mask Ogerpon ex | `_teal_dance` | "You may" bypassed; Energy auto-attached on empty selection |
| 15 | High | abilities.py:1449/2662 | me02.5-026, sv10-039 Ethan's Ho-Oh ex | `_golden_flame` | Winning definition sets `Zone.DISCARD` on attached energy |
| 16 | High | attacks.py:8155 | sv10.5b-040 Elgyem | `_slight_shift` | No player choice; always moves first available energy |
| 17 | High | attacks.py:8206 | sv10.5b-044 Meloetta ex | `_echoed_voice` | `"attack_start"` event never emitted; bonus permanently disabled |
| 18 | High | trainers.py:265 | me01-113 Acerola's Mischief | `_acerolas_mischief` | Missing opponent prize-count condition check |
| 19 | High | attacks.py:854/2211 | svp-149 Pecharunt | `_poison_chain` | Wrong damage/status/restriction in winning definition; double registration |
| 20 | Medium | attacks.py:9781/21496 | sv10-017 Dipplin | `_energy_loop` | Winning definition searches wrong field; energy card never found |
| 21 | High | attacks.py:8195/14414 | sv10.5b-043 Golurk | `_double_smash` | Shadowed by Simisear's formula: 70× per heads instead of 80× |
| 22 | Medium | attacks.py:6270/10417 | me02-021 Seel, me01-013 Seedot | `_bubble_drain` | Winning definition heals 30 instead of 20 |
| 23 | Medium | attacks.py:4919/11961 | me02.5-108 Groudon | `_megaton_fall` | Winning definition applies 40 recoil instead of 30 |
| 24 | Medium | attacks.py:6001/20956 | me02-046 Bramblin | `_sneaky_placement` | Winning definition targets Active only for 20 instead of any Pokémon for 10 |

---

## Root Cause Patterns

### Pattern A — Python function-name shadowing (14 of 24 bugs)
Python resolves a bare function name to the *last* assignment at module scope. When two handlers share the same Python function name, every card registered against that name silently receives the behavior of the second definition, even if only one card was intended to use it. All 1 427 handlers in `attacks.py` are plain module-level functions; any name collision causes this failure silently and without error. **Recommendation:** use a linter rule (e.g., `flake8-bugbear B006`, or a custom AST check) to forbid duplicate top-level function names in these files.

### Pattern B — "You may" fallback auto-executes on empty selection (4 of 24 bugs)
Several optional effects use the pattern:
```python
chosen_ids = resp.chosen_card_ids if resp and resp.chosen_card_ids else [auto_default]
```
When the player declines (responds with an empty list), the `else` branch fires the auto-default, violating card text. **Recommendation:** test `resp is None` and `bool(resp.chosen_card_ids)` separately; when `resp` is not `None` but the list is empty, respect the player's decline.

### Pattern C — Bounce discards instead of returning to hand (2 of 24 bugs)
Handlers that implement "put this Pokémon and its attached cards into your hand" call `.clear()` on the attached-cards lists, which destroys the Card objects. The correct implementation is to locate each Card by `source_card_id`, remove it from whatever zone tracking it is in, update `card.zone`, and append it to `player.hand`. **Recommendation:** extract a `_bounce_pokemon_to_hand(player, poke)` helper.

### Pattern D — Missing game-rule precondition checks (2 of 24 bugs)
At least one Supporter card (Acerola's Mischief) and one Ability (Run Errand) lack the board-state precondition check specified on the card. **Recommendation:** add a unit test that calls each handler from an illegal board state and verifies the handler returns without effect.
