"""Section 4A — Damage calculation regression tests.

Covers:
  - Weakness × 2 multiplier
  - Resistance − 30 subtraction
  - Weakness + resistance applied together
  - Floor of 0 (damage never goes negative)
  - Prize counting: regular Pokémon = 1 prize, ex Pokémon = 2 prizes
  - Game ends when all prizes taken
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401 — register_all
from app.cards import registry as card_registry
from app.cards.models import AttackDef, CardDefinition, ResistanceDef, WeaknessDef
from app.engine.effects.base import apply_weakness_resistance, check_ko
from app.engine.state import CardInstance, GameState, Phase, Zone


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_card(
    tcgdex_id: str, name: str, hp: int = 100,
    types: list[str] | None = None,
    weaknesses: list[WeaknessDef] | None = None,
    resistances: list[ResistanceDef] | None = None,
    stage: str = "Basic",
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id, name=name, set_abbrev="TST", set_number="001",
        category="pokemon", stage=stage, hp=hp,
        types=types or ["Colorless"],
        weaknesses=weaknesses or [],
        resistances=resistances or [],
        attacks=[AttackDef(name="Tackle", damage="50", cost=[])],
    )


def _make_instance(cdef: CardDefinition, hp: int | None = None) -> CardInstance:
    hp = hp or cdef.hp or 100
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id,
        card_def_id=cdef.tcgdex_id, card_name=cdef.name,
        current_hp=hp, max_hp=hp, zone=Zone.ACTIVE,
    )


def _make_state(p1_active=None, p2_active=None,
                p1_prizes: int = 6, p2_prizes: int = 6) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.active_player = "p1"
    if p1_active:
        state.p1.active = p1_active
    if p2_active:
        state.p2.active = p2_active
    state.p1.prizes_remaining = p1_prizes
    state.p2.prizes_remaining = p2_prizes
    # Populate prize cards so check_ko can pop them
    for i in range(p1_prizes):
        prize = CardInstance(
            instance_id=f"p1-prize-{i}", card_def_id="dummy",
            card_name="Prize", current_hp=100, max_hp=100, zone=Zone.PRIZES,
        )
        state.p1.prizes.append(prize)
    for i in range(p2_prizes):
        prize = CardInstance(
            instance_id=f"p2-prize-{i}", card_def_id="dummy",
            card_name="Prize", current_hp=100, max_hp=100, zone=Zone.PRIZES,
        )
        state.p2.prizes.append(prize)
    return state


@pytest.fixture(autouse=True)
def clear_card_registry():
    yield
    card_registry.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Weakness
# ──────────────────────────────────────────────────────────────────────────────

def test_weakness_doubles_damage():
    """Weakness × 2: attacker's type matches defender's weakness."""
    fire_attacker = _make_card("tst-dc-001", "Fire Attacker", types=["Fire"])
    grass_defender = _make_card(
        "tst-dc-002", "Grass Defender",
        weaknesses=[WeaknessDef(type="Fire", value="×2")],
    )
    card_registry.register(fire_attacker)
    card_registry.register(grass_defender)

    atk = _make_instance(fire_attacker)
    dfd = _make_instance(grass_defender)

    result = apply_weakness_resistance(100, atk, dfd)
    assert result == 200, f"Expected 200 (100 × 2), got {result}"


def test_no_weakness_no_multiplier():
    """No weakness match → damage unchanged."""
    fire_attacker = _make_card("tst-dc-003", "Fire Attacker", types=["Fire"])
    water_defender = _make_card(
        "tst-dc-004", "Water Defender",
        weaknesses=[WeaknessDef(type="Lightning", value="×2")],
    )
    card_registry.register(fire_attacker)
    card_registry.register(water_defender)

    atk = _make_instance(fire_attacker)
    dfd = _make_instance(water_defender)

    result = apply_weakness_resistance(100, atk, dfd)
    assert result == 100, f"Expected 100 (no weakness), got {result}"


# ──────────────────────────────────────────────────────────────────────────────
# Resistance
# ──────────────────────────────────────────────────────────────────────────────

def test_resistance_subtracts_30():
    """Resistance -30: attacker's type matches defender's resistance."""
    fighting_attacker = _make_card("tst-dc-005", "Fighting Attacker", types=["Fighting"])
    psychic_defender = _make_card(
        "tst-dc-006", "Psychic Defender",
        resistances=[ResistanceDef(type="Fighting", value="-30")],
    )
    card_registry.register(fighting_attacker)
    card_registry.register(psychic_defender)

    atk = _make_instance(fighting_attacker)
    dfd = _make_instance(psychic_defender)

    result = apply_weakness_resistance(80, atk, dfd)
    assert result == 50, f"Expected 50 (80 - 30), got {result}"


def test_resistance_floor_is_zero():
    """Damage after resistance cannot go below 0."""
    fighting_attacker = _make_card("tst-dc-007", "Fighting Attacker", types=["Fighting"])
    psychic_defender = _make_card(
        "tst-dc-008", "Tanky Defender",
        resistances=[ResistanceDef(type="Fighting", value="-30")],
    )
    card_registry.register(fighting_attacker)
    card_registry.register(psychic_defender)

    atk = _make_instance(fighting_attacker)
    dfd = _make_instance(psychic_defender)

    result = apply_weakness_resistance(20, atk, dfd)
    assert result == 0, f"Expected 0 (20 - 30, floored), got {result}"


# ──────────────────────────────────────────────────────────────────────────────
# Weakness + Resistance combined
# ──────────────────────────────────────────────────────────────────────────────

def test_weakness_then_resistance():
    """Weakness × 2 applies first, then resistance − 30."""
    fire_attacker = _make_card("tst-dc-009", "Fire Attacker", types=["Fire"])
    combo_defender = _make_card(
        "tst-dc-010", "Combo Defender",
        weaknesses=[WeaknessDef(type="Fire", value="×2")],
        resistances=[ResistanceDef(type="Fire", value="-30")],
    )
    card_registry.register(fire_attacker)
    card_registry.register(combo_defender)

    atk = _make_instance(fire_attacker)
    dfd = _make_instance(combo_defender)

    result = apply_weakness_resistance(50, atk, dfd)
    assert result == 70, f"Expected 70 (50 × 2 = 100, then - 30 = 70), got {result}"


# ──────────────────────────────────────────────────────────────────────────────
# Prize counting
# ──────────────────────────────────────────────────────────────────────────────

def test_ko_regular_pokemon_awards_1_prize():
    """KO'ing a regular Pokémon takes exactly 1 prize."""
    regular = _make_card("tst-dc-011", "Regular Mon", hp=60)
    attacker_cdef = _make_card("tst-dc-012", "Attacker")
    card_registry.register(regular)
    card_registry.register(attacker_cdef)

    defender = _make_instance(regular, hp=60)
    attacker = _make_instance(attacker_cdef)

    state = _make_state(p1_active=attacker, p2_active=defender, p1_prizes=6)

    defender.current_hp = 0
    check_ko(state, defender, "p2")

    assert state.p1.prizes_remaining == 5
    prizes_events = [e for e in state.events if e["event_type"] == "prizes_taken"]
    assert prizes_events and prizes_events[-1]["count"] == 1


def test_ko_ex_pokemon_awards_2_prizes():
    """KO'ing an ex Pokémon takes 2 prizes."""
    ex_card = _make_card("tst-dc-013", "Big ex", hp=220, stage="ex")
    attacker_cdef = _make_card("tst-dc-014", "Attacker")
    card_registry.register(ex_card)
    card_registry.register(attacker_cdef)

    defender = _make_instance(ex_card, hp=220)
    attacker = _make_instance(attacker_cdef)

    state = _make_state(p1_active=attacker, p2_active=defender, p1_prizes=6)

    defender.current_hp = 0
    check_ko(state, defender, "p2")

    assert state.p1.prizes_remaining == 4
    prizes_events = [e for e in state.events if e["event_type"] == "prizes_taken"]
    assert prizes_events and prizes_events[-1]["count"] == 2


def test_last_prize_triggers_game_over():
    """Taking the last prize ends the game with win_condition='prizes'."""
    regular = _make_card("tst-dc-015", "Target", hp=60)
    attacker_cdef = _make_card("tst-dc-016", "Attacker")
    card_registry.register(regular)
    card_registry.register(attacker_cdef)

    defender = _make_instance(regular, hp=60)
    attacker = _make_instance(attacker_cdef)

    state = _make_state(p1_active=attacker, p2_active=defender, p1_prizes=1)

    defender.current_hp = 0
    check_ko(state, defender, "p2")

    assert state.phase == Phase.GAME_OVER
    assert state.winner == "p1"
    assert state.win_condition == "prizes"


def test_ko_with_no_bench_triggers_no_bench_game_over():
    """KO'ing the last Pokémon (no bench) ends the game with win_condition='no_bench'."""
    regular = _make_card("tst-dc-017", "Last Mon", hp=60)
    attacker_cdef = _make_card("tst-dc-018", "Attacker")
    card_registry.register(regular)
    card_registry.register(attacker_cdef)

    defender = _make_instance(regular, hp=60)
    attacker = _make_instance(attacker_cdef)

    state = _make_state(p1_active=attacker, p2_active=defender, p1_prizes=6)
    # p2 has no bench — clearing happens inside check_ko when active is KO'd
    state.p2.bench = []

    defender.current_hp = 0
    check_ko(state, defender, "p2")

    assert state.phase == Phase.GAME_OVER
    assert state.winner == "p1"
    assert state.win_condition == "no_bench"
