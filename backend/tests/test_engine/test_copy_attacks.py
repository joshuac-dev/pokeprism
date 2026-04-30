"""Tests for copy-attack handlers: Night Joker (N's Zoroark ex) and Gemstone Mimicry (TR Mimikyu).

Verifies:
- Night Joker copies the highest-damage attack from a benched N's Pokémon.
- Night Joker emits copy_attack_no_target when no valid bench target exists.
- Gemstone Mimicry emits copy_attack_no_target when opponent's Active is not Tera.
- Cycle guard: copy-attack keys excluded from copy candidates.
"""

from __future__ import annotations

import asyncio
import pytest

from app.cards import registry as card_registry
from app.cards.models import AttackDef, CardDefinition
from app.engine.actions import Action, ActionType
import app.engine.effects  # noqa: F401 — importing triggers register_all() via __init__
from app.engine.state import CardInstance, GameState, PlayerState, Zone


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_card(tcgdex_id: str, name: str, attacks: list[AttackDef]) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev="TST",
        set_number="000",
        category="pokemon",
        stage="Basic",
        hp=120,
        attacks=attacks,
    )


def _make_instance(cdef: CardDefinition) -> CardInstance:
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        current_hp=cdef.hp or 100,
        max_hp=cdef.hp or 100,
        zone=Zone.BENCH,
    )


def _make_action(player_id: str) -> Action:
    return Action(
        player_id=player_id,
        action_type=ActionType.ATTACK,
        attack_index=0,
    )


def _make_state(
    p1_active: CardInstance | None = None,
    p1_bench: list[CardInstance] | None = None,
    p2_active: CardInstance | None = None,
) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    if p1_active:
        p1_active.zone = Zone.ACTIVE
        state.p1.active = p1_active
    if p1_bench:
        for c in p1_bench:
            c.zone = Zone.BENCH
        state.p1.bench = p1_bench
    if p2_active:
        p2_active.zone = Zone.ACTIVE
        state.p2.active = p2_active
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_effects_and_registry():
    """Register all effects and populate card registry with test cards."""
    import app.engine.effects  # noqa: F401 — triggers register_all via __init__
    yield
    card_registry.clear()


@pytest.fixture
def ns_zoroark_cdef():
    return _make_card(
        "sv09-098", "N's Zoroark ex",
        [AttackDef(name="Night Joker", damage="0", cost=["Darkness", "Colorless"])],
    )


@pytest.fixture
def ns_pokemon_cdef():
    """N's Pokémon with two attacks — second has higher damage."""
    return _make_card(
        "sv09-050", "N's Rotom",
        [
            AttackDef(name="Static", damage="30", cost=["Lightning"]),
            AttackDef(name="Discharge", damage="90", cost=["Lightning", "Lightning"]),
        ],
    )


@pytest.fixture
def tr_mimikyu_cdef():
    return _make_card(
        "sv10-087", "TR Mimikyu",
        [AttackDef(name="Gemstone Mimicry", damage="0", cost=["Psychic"])],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Night Joker tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_night_joker_copies_bench_ns_pokemon(ns_zoroark_cdef, ns_pokemon_cdef):
    """Night Joker should copy the highest-damage attack from a benched N's Pokémon."""
    card_registry.register(ns_zoroark_cdef)
    card_registry.register(ns_pokemon_cdef)

    # N's Rotom has Discharge (90 dmg) as atk index 1 — should be chosen.
    bench_poke = _make_instance(ns_pokemon_cdef)
    zoroark = _make_instance(ns_zoroark_cdef)

    # Add a plausible HP target
    p2_active = CardInstance(
        instance_id="p2-active", card_def_id="dummy", card_name="Dummy",
        current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=zoroark, p1_bench=[bench_poke], p2_active=p2_active)
    action = _make_action("p1")

    from app.engine.effects.registry import EffectRegistry
    await EffectRegistry.instance().resolve_attack("sv09-098", 0, state, action)

    event_types = [e["event_type"] for e in state.events]
    assert "copy_attack" in event_types

    copy_evt = next(e for e in state.events if e["event_type"] == "copy_attack")
    assert copy_evt["source_card"] == "N's Rotom"
    assert copy_evt["copied_attack"] == "Discharge"


@pytest.mark.asyncio
async def test_night_joker_no_target_emits_event(ns_zoroark_cdef):
    """Night Joker with no benched N's Pokémon emits copy_attack_no_target."""
    card_registry.register(ns_zoroark_cdef)

    zoroark = _make_instance(ns_zoroark_cdef)
    state = _make_state(p1_active=zoroark, p1_bench=[])
    action = _make_action("p1")

    from app.engine.effects.registry import EffectRegistry
    await EffectRegistry.instance().resolve_attack("sv09-098", 0, state, action)

    event_types = [e["event_type"] for e in state.events]
    assert "copy_attack_no_target" in event_types
    no_target_evt = next(e for e in state.events if e["event_type"] == "copy_attack_no_target")
    assert "N's Zoroark ex" in no_target_evt["card"]


@pytest.mark.asyncio
async def test_night_joker_cycle_guard_excludes_copy_attacks(ns_zoroark_cdef):
    """If the only bench N's Pokémon has only copy-attacks, no copy should happen."""
    # Register another N's Zoroark ex on the bench — it only has Night Joker (index 0)
    # which is in _COPY_ATTACK_KEYS and must be excluded.
    card_registry.register(ns_zoroark_cdef)

    bench_zoroark = _make_instance(ns_zoroark_cdef)
    bench_zoroark.instance_id = "bench-zoroark"
    zoroark_active = _make_instance(ns_zoroark_cdef)
    zoroark_active.instance_id = "active-zoroark"

    state = _make_state(p1_active=zoroark_active, p1_bench=[bench_zoroark])
    action = _make_action("p1")

    from app.engine.effects.registry import EffectRegistry
    await EffectRegistry.instance().resolve_attack("sv09-098", 0, state, action)

    event_types = [e["event_type"] for e in state.events]
    # copy_attack should NOT fire since bench only has copy-attack keys
    assert "copy_attack_no_target" in event_types
    assert "copy_attack" not in event_types


# ──────────────────────────────────────────────────────────────────────────────
# Gemstone Mimicry tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gemstone_mimicry_no_tera_emits_event(tr_mimikyu_cdef):
    """Gemstone Mimicry against a non-Tera opponent emits copy_attack_no_target."""
    card_registry.register(tr_mimikyu_cdef)

    non_tera = _make_card(
        "test-non-tera-001", "Garchomp ex",
        [AttackDef(name="Sonic Slash", damage="180", cost=["Fighting", "Colorless"])],
    )
    card_registry.register(non_tera)

    mimikyu = _make_instance(tr_mimikyu_cdef)
    opp_active = _make_instance(non_tera)

    state = _make_state(p1_active=mimikyu, p2_active=opp_active)
    action = _make_action("p1")

    from app.engine.effects.registry import EffectRegistry
    await EffectRegistry.instance().resolve_attack("sv10-087", 0, state, action)

    event_types = [e["event_type"] for e in state.events]
    assert "copy_attack_no_target" in event_types
    no_target_evt = next(e for e in state.events if e["event_type"] == "copy_attack_no_target")
    assert "not a Tera" in no_target_evt["reason"]


@pytest.mark.asyncio
async def test_gemstone_mimicry_tera_copies_attack(tr_mimikyu_cdef):
    """Gemstone Mimicry against a Tera Pokémon copies its highest attack."""
    card_registry.register(tr_mimikyu_cdef)

    tera_poke = _make_card(
        "test-tera-001", "Tera Charizard ex",
        [AttackDef(name="Burning Darkness", damage="230", cost=["Fire", "Fire"])],
    )
    card_registry.register(tera_poke)

    mimikyu = _make_instance(tr_mimikyu_cdef)
    opp_active = _make_instance(tera_poke)

    state = _make_state(p1_active=mimikyu, p2_active=opp_active)
    action = _make_action("p1")

    from app.engine.effects.registry import EffectRegistry
    await EffectRegistry.instance().resolve_attack("sv10-087", 0, state, action)

    event_types = [e["event_type"] for e in state.events]
    assert "copy_attack" in event_types
    copy_evt = next(e for e in state.events if e["event_type"] == "copy_attack")
    assert copy_evt["source_card"] == "Tera Charizard ex"
    assert copy_evt["copied_attack"] == "Burning Darkness"
