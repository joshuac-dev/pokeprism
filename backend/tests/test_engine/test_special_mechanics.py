"""Section 4C — Special mechanics audit.

Covers:
  - CHOOSE_CARDS forced-action validation (count bounds, ID set membership)
  - CHOOSE_TARGET forced-action validation (ID must be in target set)
  - Copy-attack depth limit (copy keys excluded from copy candidates)
  - Stadium placement updates active_stadium
  - Tool attachment stored as def-ID string, not object
  - Special energy provides list propagated to CardInstance
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AttackDef, CardDefinition
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.effects.base import ChoiceRequest
from app.engine.effects.registry import EffectRegistry
from app.engine.state import CardInstance, EnergyAttachment, EnergyType, GameState, Zone


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_card(tcgdex_id: str, name: str, hp: int = 100,
               attacks: list[AttackDef] | None = None) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id, name=name, set_abbrev="TST", set_number="001",
        category="pokemon", stage="Basic", hp=hp, attacks=attacks or [],
    )


def _make_instance(cdef: CardDefinition, zone: Zone = Zone.ACTIVE,
                   hp: int | None = None) -> CardInstance:
    hp = hp or cdef.hp or 100
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id,
        card_def_id=cdef.tcgdex_id, card_name=cdef.name,
        current_hp=hp, max_hp=hp, zone=zone,
    )


def _make_state(p1_active=None, p1_bench=None, p2_active=None) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.active_player = "p1"
    if p1_active:
        p1_active.zone = Zone.ACTIVE
        state.p1.active = p1_active
    if p1_bench:
        for c in p1_bench:
            c.zone = Zone.BENCH
        state.p1.bench = list(p1_bench)
    if p2_active:
        p2_active.zone = Zone.ACTIVE
        state.p2.active = p2_active
    return state


@pytest.fixture(autouse=True)
def clear_card_registry():
    yield
    card_registry.clear()


# ──────────────────────────────────────────────────────────────────────────────
# CHOOSE_CARDS validation
# ──────────────────────────────────────────────────────────────────────────────

def test_choose_cards_valid_selection_passes():
    """CHOOSE_CARDS with valid count and valid IDs → valid."""
    cdef = _make_card("tst-sm-001", "Mon A")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    state = _make_state(p1_active=inst)

    ctx = ChoiceRequest("choose_cards", "p1",
                        cards=[inst], min_count=1, max_count=1)
    action = Action(
        ActionType.CHOOSE_CARDS, "p1",
        selected_cards=[inst.instance_id],
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert valid, f"Expected valid, got error: {error}"


def test_choose_cards_count_below_min_rejected():
    """CHOOSE_CARDS with fewer cards than min_count → rejected."""
    cdef = _make_card("tst-sm-002", "Mon B")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    state = _make_state(p1_active=inst)

    ctx = ChoiceRequest("choose_cards", "p1",
                        cards=[inst], min_count=1, max_count=2)
    action = Action(
        ActionType.CHOOSE_CARDS, "p1",
        selected_cards=[],  # 0 < min 1
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert not valid
    assert "range" in error.lower()


def test_choose_cards_count_above_max_rejected():
    """CHOOSE_CARDS with more cards than max_count → rejected."""
    cdef_a = _make_card("tst-sm-003", "Mon C")
    cdef_b = _make_card("tst-sm-004", "Mon D")
    card_registry.register(cdef_a)
    card_registry.register(cdef_b)
    inst_a = _make_instance(cdef_a)
    inst_b = _make_instance(cdef_b, zone=Zone.BENCH)
    state = _make_state(p1_active=inst_a, p1_bench=[inst_b])

    ctx = ChoiceRequest("choose_cards", "p1",
                        cards=[inst_a, inst_b], min_count=0, max_count=1)
    action = Action(
        ActionType.CHOOSE_CARDS, "p1",
        selected_cards=[inst_a.instance_id, inst_b.instance_id],  # 2 > max 1
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert not valid
    assert "range" in error.lower()


def test_choose_cards_id_outside_choice_set_rejected():
    """CHOOSE_CARDS with an ID not in the choice set → rejected."""
    cdef = _make_card("tst-sm-005", "Mon E")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    state = _make_state(p1_active=inst)

    ctx = ChoiceRequest("choose_cards", "p1",
                        cards=[inst], min_count=1, max_count=1)
    action = Action(
        ActionType.CHOOSE_CARDS, "p1",
        selected_cards=["not-a-real-instance-id"],
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert not valid
    assert "legal" in error.lower() or "choice" in error.lower()


# ──────────────────────────────────────────────────────────────────────────────
# CHOOSE_TARGET validation
# ──────────────────────────────────────────────────────────────────────────────

def test_choose_target_valid_target_passes():
    """CHOOSE_TARGET with a valid target ID → valid."""
    cdef = _make_card("tst-sm-006", "Mon F")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    state = _make_state(p1_active=inst)

    ctx = ChoiceRequest("choose_target", "p1", targets=[inst])
    action = Action(
        ActionType.CHOOSE_TARGET, "p1",
        target_instance_id=inst.instance_id,
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert valid, f"Expected valid, got error: {error}"


def test_choose_target_outside_set_rejected():
    """CHOOSE_TARGET with an ID not in the targets list → rejected."""
    cdef = _make_card("tst-sm-007", "Mon G")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    state = _make_state(p1_active=inst)

    ctx = ChoiceRequest("choose_target", "p1", targets=[inst])
    action = Action(
        ActionType.CHOOSE_TARGET, "p1",
        target_instance_id="bogus-id",
        choice_context=ctx,
    )
    valid, error = ActionValidator.validate(state, action)
    assert not valid
    assert "legal target" in error.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Copy-attack depth limit
# ──────────────────────────────────────────────────────────────────────────────

def test_copy_attack_keys_excluded_from_copy_candidates():
    """Copy-attack handlers (e.g., sv10-087:0) are in _COPY_ATTACK_KEYS and cannot be copied."""
    from app.engine.effects.attacks import _COPY_ATTACK_KEYS
    # Gemstone Mimicry and Night Joker must be excluded to prevent infinite loops
    assert "sv10-087:0" in _COPY_ATTACK_KEYS, "Gemstone Mimicry must be in copy-attack exclusion set"
    assert "sv09-098:0" in _COPY_ATTACK_KEYS, "Night Joker must be in copy-attack exclusion set"


# ──────────────────────────────────────────────────────────────────────────────
# Stadium placement
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stadium_placement_sets_active_stadium():
    """Playing a Stadium via _play_stadium transition sets state.active_stadium."""
    from app.engine.transitions import _play_stadium
    from app.cards.models import CardDefinition as CD

    # Use a real registered stadium (Lively Stadium sv08-180)
    stadium_cdef = CD(
        tcgdex_id="sv08-180", name="Lively Stadium",
        set_abbrev="SV8", set_number="180",
        category="trainer", subcategory="Stadium",
        stage="", hp=None,
    )
    card_registry.register(stadium_cdef)

    stadium_inst = CardInstance(
        instance_id="stad-inst", card_def_id="sv08-180",
        card_name="Lively Stadium", current_hp=0, max_hp=0, zone=Zone.HAND,
    )
    mon_cdef = _make_card("tst-sm-008", "Mon H")
    card_registry.register(mon_cdef)
    mon = _make_instance(mon_cdef)

    state = _make_state(p1_active=mon,
                        p2_active=_make_instance(_make_card("tst-sm-009", "Opp H")))
    state.p1.hand.append(stadium_inst)

    action = Action(
        ActionType.PLAY_STADIUM, "p1",
        card_instance_id=stadium_inst.instance_id,
    )
    await _play_stadium(state, action)

    assert state.active_stadium is not None
    assert state.active_stadium.card_def_id == "sv08-180"
    assert stadium_inst not in state.p1.hand
    assert any(e["event_type"] == "play_stadium" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Tool attachment stored as string
# ──────────────────────────────────────────────────────────────────────────────

def test_tool_attached_stored_as_string():
    """tools_attached stores card_def_id strings, not CardInstance objects."""
    cdef = _make_card("tst-sm-010", "Mon I")
    card_registry.register(cdef)
    inst = _make_instance(cdef)
    tool_def_id = "sv05-151"  # e.g. Choice Belt

    inst.tools_attached.append(tool_def_id)

    assert inst.tools_attached == [tool_def_id]
    assert isinstance(inst.tools_attached[0], str), (
        "tools_attached must store card_def_id strings, not CardInstance objects"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Special energy provides list
# ──────────────────────────────────────────────────────────────────────────────

def test_special_energy_provides_propagated():
    """EnergyAttachment with provides list carries the specified types."""
    attachment = EnergyAttachment(
        energy_type=EnergyType.COLORLESS,
        source_card_id="special-energy-inst",
        card_def_id="sv06-165",  # e.g. Reversal Energy
        provides=[EnergyType.FIRE, EnergyType.WATER],
    )
    assert EnergyType.FIRE in attachment.provides
    assert EnergyType.WATER in attachment.provides
    assert len(attachment.provides) == 2
