from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.effects.attacks import _apply_damage
from app.engine.effects.base import (
    _devolve_pokemon,
    enforce_area_zero_underdepths,
    get_bench_limit,
    get_retreat_cost_reduction,
    get_tool_damage_bonus,
)
from app.engine.effects.registry import EffectRegistry
from app.engine.effects.trainers import (
    _academy_at_night,
    _anthea_concordia,
    _canari,
    _celebratory_fanfare,
    _community_center,
    _cynthias_power_weight,
    _lumiose_city,
    _powerglass,
    _spikemuth_gym,
    _strange_timepiece,
    _surfing_beach,
)
from app.engine.state import CardInstance, EnergyAttachment, EnergyType, GameState, Phase, StatusCondition, Zone


def _make_card(
    tcgdex_id: str,
    name: str,
    *,
    category: str = "pokemon",
    subcategory: str = "",
    hp: int = 100,
    stage: str = "Basic",
    types: list[str] | None = None,
    attacks: list[AttackDef] | None = None,
    abilities: list[AbilityDef] | None = None,
    is_ex: bool = False,
    is_tera: bool = False,
    retreat_cost: int = 1,
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        category=category,
        subcategory=subcategory,
        set_abbrev="TST",
        set_number="001",
        hp=hp,
        stage=stage,
        types=types or [],
        attacks=attacks or [],
        abilities=abilities or [],
        is_ex=is_ex,
        is_tera=is_tera,
        retreat_cost=retreat_cost,
    )


def _inst(cdef: CardDefinition, instance_id: str, *, zone: Zone = Zone.ACTIVE, hp: int | None = None) -> CardInstance:
    hp = cdef.hp if hp is None else hp
    return CardInstance(
        instance_id=instance_id,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        zone=zone,
        current_hp=hp,
        max_hp=hp,
        card_type=cdef.category.capitalize(),
        card_subtype=cdef.subcategory.capitalize() if cdef.subcategory else "",
        evolution_stage=0 if cdef.stage.lower() == "basic" else 1,
    )


def _energy(instance_id: str, card_def_id: str, energy_type: EnergyType, provides: list[str] | None = None) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        card_def_id=card_def_id,
        card_name=card_def_id,
        zone=Zone.HAND,
        current_hp=0,
        max_hp=0,
        card_type="Energy",
        card_subtype="Basic",
        energy_provides=provides or [energy_type.value],
    )


def _state(p1_active: CardInstance | None = None, p1_bench: list[CardInstance] | None = None,
           p2_active: CardInstance | None = None, p2_bench: list[CardInstance] | None = None) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.turn_number = 2
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
    if p2_bench:
        for c in p2_bench:
            c.zone = Zone.BENCH
        state.p2.bench = list(p2_bench)
    return state


@pytest.fixture(autouse=True)
def clear_registry():
    yield
    card_registry.clear()


def test_alt_binding_mochi_and_new_berries_apply_tool_modifiers():
    attacker = _make_card("atk-1", "Attacker", types=["Water"], attacks=[AttackDef(name="Hit", damage="50", cost=[])])
    attacker_dark = _make_card("atk-2", "Dark Attacker", types=["Darkness"], attacks=[AttackDef(name="Hit", damage="50", cost=[])], abilities=[AbilityDef(name="Ability", effect="")])
    attacker_grass = _make_card("atk-3", "Grass Attacker", types=["Grass"], attacks=[AttackDef(name="Hit", damage="50", cost=[])])
    dragon = _make_card("def-1", "Dragon Defender", types=["Dragon"])
    basic = _make_card("def-2", "Basic Defender", types=["Colorless"])
    for c in (attacker, attacker_dark, attacker_grass, dragon, basic):
        card_registry.register(c)

    atk_inst = _inst(attacker, "atk")
    atk_inst.status_conditions.add(StatusCondition.POISONED)
    atk_inst.tools_attached = ["sv06.5-055"]
    def_inst = _inst(basic, "def")
    state = _state(p1_active=atk_inst, p2_active=def_inst)
    assert get_tool_damage_bonus(atk_inst, def_inst, 0, state, "p1") == 40

    water_def = _inst(basic, "water-def")
    water_def.tools_attached = ["sv08-184"]
    assert get_tool_damage_bonus(atk_inst, water_def, 0, state, "p1") == -20

    dark_atk_inst = _inst(attacker_dark, "dark-atk")
    dark_state = _state(p1_active=dark_atk_inst, p2_active=_inst(basic, "dark-def"))
    sacred_def = _inst(basic, "sacred-def")
    sacred_def.tools_attached = ["me02-093"]
    assert get_tool_damage_bonus(dark_atk_inst, sacred_def, 0, dark_state, "p1") == -30

    grass_atk_inst = _inst(attacker_grass, "grass-atk")
    thick_def = _inst(dragon, "dragon-def")
    thick_def.tools_attached = ["me02.5-211"]
    assert get_tool_damage_bonus(grass_atk_inst, thick_def, 0, _state(p1_active=grass_atk_inst, p2_active=thick_def), "p1") == -50


def test_retreat_tools_and_counter_gain_alt_and_nighttime_mine_modify_actions():
    attacker = _make_card(
        "tera-1", "Tera Mon", is_tera=True, types=["Fire"], retreat_cost=2,
        attacks=[AttackDef(name="Blast", damage="50", cost=["Fire", "Colorless"])],
    )
    basic = _make_card("bench-1", "Bench Mon", attacks=[AttackDef(name="Tap", damage="10", cost=["Colorless"])])
    card_registry.register(attacker)
    card_registry.register(basic)

    active = _inst(attacker, "active")
    active.energy_attached = [
        EnergyAttachment(EnergyType.FIRE, "e1", "e1", [EnergyType.FIRE]),
        EnergyAttachment(EnergyType.COLORLESS, "e2", "e2", [EnergyType.COLORLESS]),
    ]
    active.tools_attached = ["me02.5-186", "sv10.5b-079"]
    state = _state(p1_active=active, p2_active=_inst(basic, "opp"))
    state.active_stadium = CardInstance(instance_id="mine", card_def_id="me02.5-197", card_name="Nighttime Mine", zone=Zone.STADIUM)
    state.p1.prizes_remaining = 6
    state.p2.prizes_remaining = 5
    state.phase = Phase.ATTACK

    legal = ActionValidator.get_legal_actions(state, "p1")
    attack_actions = [a for a in legal if a.action_type == ActionType.ATTACK]
    assert attack_actions, "Counter Gain alt should offset Nighttime Mine's extra Colorless cost"
    assert get_retreat_cost_reduction(active, state, "p1") == 2

    active.tools_attached = ["sv08.5-126"]
    active.current_hp = 30
    assert get_retreat_cost_reduction(active, state, "p1") >= 9999


def test_punk_helmet_tr_hypnotizer_and_berry_discard_trigger_on_damage():
    atk_def = _make_card("atk-fire", "Fire Attacker", types=["Fire"], attacks=[AttackDef(name="Burn", damage="100", cost=[])])
    dark_def = _make_card("def-dark", "Dark Holder", types=["Darkness"])
    tr_def = _make_card("def-tr", "Team Rocket's Holder", types=["Psychic"])
    for c in (atk_def, dark_def, tr_def):
        card_registry.register(c)

    attacker = _inst(atk_def, "atk")
    attacker.card_name = "Fire Attacker"
    defender = _inst(dark_def, "def")
    defender.tools_attached = ["me02-092", "sv07-140"]
    state = _state(p1_active=attacker, p2_active=defender)
    _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)
    assert attacker.damage_counters == 4
    assert "sv07-140" not in defender.tools_attached

    attacker2 = _inst(atk_def, "atk2")
    defender2 = _inst(tr_def, "def2")
    defender2.tools_attached = ["me02.5-206"]
    state2 = _state(p1_active=attacker2, p2_active=defender2)
    _apply_damage(state2, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert StatusCondition.ASLEEP in attacker2.status_conditions


@pytest.mark.parametrize(
    "stadium_id,setup",
    [
        ("me03-077", "lumiose"),
        ("sv10-169", "spikemuth"),
        ("me01-129", "surfing"),
        ("sv06.5-054", "academy"),
        ("sv06-146", "community"),
        ("mep-028", "fanfare"),
    ],
)
def test_new_stadium_actions_are_offered(stadium_id: str, setup: str):
    active_def = _make_card("p1a", "Active", types=["Water"])
    bench_def = _make_card("p1b", "Bench", types=["Water"])
    opp_def = _make_card("opp", "Opp")
    for c in (active_def, bench_def, opp_def):
        card_registry.register(c)
    active = _inst(active_def, "a1")
    bench = _inst(bench_def, "b1", zone=Zone.BENCH)
    state = _state(p1_active=active, p1_bench=[bench], p2_active=_inst(opp_def, "opp"))
    state.active_stadium = CardInstance(instance_id="stad", card_def_id=stadium_id, card_name="Stadium", zone=Zone.STADIUM)
    if setup == "lumiose":
        state.p1.deck = [_inst(_make_card("basic-1", "Basic", types=["Lightning"]), "deck-basic", zone=Zone.DECK)]
        card_registry.register(_make_card("basic-1", "Basic", types=["Lightning"]))
    elif setup == "spikemuth":
        card_registry.register(_make_card("marnie-1", "Marnie's Imp", types=["Darkness"]))
        state.p1.deck = [_inst(_make_card("marnie-1", "Marnie's Imp", types=["Darkness"]), "marnie", zone=Zone.DECK)]
    elif setup == "academy":
        card_registry.register(_make_card("hand-1", "Hand Card"))
        state.p1.hand = [_inst(_make_card("hand-1", "Hand Card"), "hand")]
    elif setup == "community":
        state.p1.supporter_played_this_turn = True
        active.damage_counters = 1
        active.current_hp -= 10
    elif setup == "fanfare":
        active.damage_counters = 1
        active.current_hp -= 10
    legal = ActionValidator.get_legal_actions(state, "p1")
    assert any(a.action_type == ActionType.USE_STADIUM for a in legal)


def test_lumiose_city_handler_benches_and_ends_turn():
    basic = _make_card("basic-1", "Deck Basic", types=["Lightning"])
    active = _make_card("active-1", "Active")
    card_registry.register(basic)
    card_registry.register(active)
    state = _state(p1_active=_inst(active, "active"), p2_active=_inst(active, "opp"))
    state.active_stadium = CardInstance(instance_id="stad", card_def_id="me03-077", card_name="Lumiose City", zone=Zone.STADIUM)
    deck_basic = _inst(basic, "deck-basic", zone=Zone.DECK)
    state.p1.deck = [deck_basic]
    gen = _lumiose_city(state, Action(ActionType.USE_STADIUM, "p1"))
    req = next(gen)
    with pytest.raises(StopIteration):
        gen.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["deck-basic"]))
    assert any(b.instance_id == "deck-basic" for b in state.p1.bench)
    assert state.force_end_turn is True


def test_spikemuth_gym_surfing_beach_and_academy_handlers():
    water = _make_card("water-1", "Water Active", types=["Water"])
    bench_water = _make_card("water-2", "Water Bench", types=["Water"])
    marnie = _make_card("marnie-1", "Marnie's Poké", types=["Darkness"])
    other = _make_card("other-1", "Hand Card")
    for c in (water, bench_water, marnie, other):
        card_registry.register(c)

    state = _state(p1_active=_inst(water, "active"), p1_bench=[_inst(bench_water, "bench", zone=Zone.BENCH)], p2_active=_inst(other, "opp"))
    state.active_stadium = CardInstance(instance_id="spike", card_def_id="sv10-169", card_name="Spikemuth Gym", zone=Zone.STADIUM)
    deck_card = _inst(marnie, "marnie", zone=Zone.DECK)
    state.p1.deck = [deck_card]
    gen = _spikemuth_gym(state, Action(ActionType.USE_STADIUM, "p1"))
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["marnie"]))
    assert deck_card in state.p1.hand

    state.active_stadium = CardInstance(instance_id="surf", card_def_id="me01-129", card_name="Surfing Beach", zone=Zone.STADIUM)
    gen2 = _surfing_beach(state, Action(ActionType.USE_STADIUM, "p1"))
    next(gen2)
    with pytest.raises(StopIteration):
        gen2.send(Action(ActionType.CHOOSE_TARGET, "p1", target_instance_id="bench"))
    assert state.p1.active.instance_id == "bench"

    hand_card = _inst(other, "hand", zone=Zone.HAND)
    state.p1.hand = [hand_card]
    state.active_stadium = CardInstance(instance_id="academy", card_def_id="sv06.5-054", card_name="Academy at Night", zone=Zone.STADIUM)
    gen3 = _academy_at_night(state, Action(ActionType.USE_STADIUM, "p1"))
    next(gen3)
    with pytest.raises(StopIteration):
        gen3.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["hand"]))
    assert state.p1.deck[0].instance_id == "hand"


def test_community_center_and_celebratory_fanfare_heal_and_end_turn():
    active_def = _make_card("active-1", "Active")
    card_registry.register(active_def)
    active = _inst(active_def, "active", hp=100)
    active.damage_counters = 3
    active.current_hp = 70
    state = _state(p1_active=active, p2_active=_inst(active_def, "opp"))
    state.p1.supporter_played_this_turn = True
    _community_center(state, Action(ActionType.USE_STADIUM, "p1"))
    assert active.damage_counters == 2
    assert state.force_end_turn is True

    active.damage_counters = 3
    active.current_hp = 70
    state.force_end_turn = False
    _celebratory_fanfare(state, Action(ActionType.USE_STADIUM, "p1"))
    assert active.damage_counters == 2
    assert state.force_end_turn is True


def test_powerglass_choice_attaches_selected_basic_energy_from_discard():
    active_def = _make_card("active-1", "Active")
    card_registry.register(active_def)
    state = _state(p1_active=_inst(active_def, "active"), p2_active=_inst(active_def, "opp"))
    state.p1.active.tools_attached = ["sv06.5-063"]
    fire = _energy("fire", "fire-basic", EnergyType.FIRE, ["Fire"])
    water = _energy("water", "water-basic", EnergyType.WATER, ["Water"])
    fire.zone = Zone.DISCARD
    water.zone = Zone.DISCARD
    state.p1.discard = [fire, water]
    gen = _powerglass(state, Action(ActionType.END_TURN, "p1"))
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["water"]))
    assert any(att.card_def_id == "water-basic" for att in state.p1.active.energy_attached)


def test_canari_discards_cost_and_searches_lightning_pokemon():
    lightning = _make_card("light-1", "Lightning Mon", types=["Lightning"])
    filler = _make_card("fill-1", "Filler")
    card_registry.register(lightning)
    card_registry.register(filler)
    state = _state(p1_active=_inst(filler, "active"), p2_active=_inst(filler, "opp"))
    cost_card = _inst(filler, "cost", zone=Zone.HAND)
    state.p1.hand = [cost_card]
    deck_target = _inst(lightning, "lightning", zone=Zone.DECK)
    state.p1.deck = [deck_target]
    gen = _canari(state, Action(ActionType.PLAY_ITEM, "p1", card_instance_id="canari"))
    next(gen)
    req2 = gen.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["cost"]))
    assert req2.choice_type == "choose_cards"
    with pytest.raises(StopIteration):
        gen.send(Action(ActionType.CHOOSE_CARDS, "p1", selected_cards=["lightning"]))
    assert deck_target in state.p1.hand
    assert cost_card in state.p1.discard


def test_cynthias_power_weight_and_anthea_concordia_and_strange_timepiece():
    cynthia = _make_card("cyn-1", "Cynthia's Garchomp", types=["Dragon"], hp=130)
    base = _make_card("nbase", "N's Zorua", types=["Psychic"], hp=60)
    stage1 = _make_card("nstage", "N's Zoroark ex", types=["Psychic"], hp=120, stage="Stage 1")
    for c in (cynthia, base, stage1):
        card_registry.register(c)

    state = _state(p1_active=_inst(cynthia, "cyn"), p2_active=_inst(cynthia, "opp"))
    _cynthias_power_weight(state, Action(ActionType.PLAY_TOOL, "p1", target_instance_id="cyn"))
    assert state.p1.active.max_hp == 200

    # Anthea & Concordia gate
    required_names = ["N's Darmanitan", "N's Zoroark ex", "N's Vanilluxe", "N's Klinklang", "N's Reshiram", "N's Zekrom"]
    state2 = _state(
        p1_active=CardInstance(instance_id="n0", card_def_id="n0", card_name=required_names[0], zone=Zone.ACTIVE, current_hp=100, max_hp=100),
        p1_bench=[CardInstance(instance_id=f"n{i}", card_def_id=f"n{i}", card_name=name, zone=Zone.BENCH, current_hp=100, max_hp=100) for i, name in enumerate(required_names[1:], start=1)],
        p2_active=_inst(cynthia, "opp2"),
    )
    _anthea_concordia(state2, Action(ActionType.PLAY_SUPPORTER, "p1"))
    assert state2.anthea_concordia_active is True

    # Strange Timepiece full devolve to base, returning evolution to hand
    base_inst = _inst(base, "base", zone=Zone.BENCH, hp=60)
    stage1_inst = _inst(stage1, "stage1", zone=Zone.BENCH, hp=120)
    stage1_inst.evolution_stage = 1
    stage1_inst.evolved_from = "base"
    stage1_inst.damage_counters = 2
    stage1_inst.current_hp = 100
    stage1_inst.status_conditions.add(StatusCondition.CONFUSED)
    state3 = _state(p1_active=_inst(cynthia, "active3"), p1_bench=[stage1_inst], p2_active=_inst(cynthia, "opp3"))
    state3.p1.discard = [base_inst]
    gen = _strange_timepiece(state3, Action(ActionType.PLAY_ITEM, "p1"))
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(Action(ActionType.CHOOSE_TARGET, "p1", target_instance_id="stage1"))
    assert any(b.instance_id == "base" for b in state3.p1.bench)
    assert any(c.instance_id == "stage1" for c in state3.p1.hand)


def test_anthea_concordia_awards_three_extra_prizes_on_active_ko():
    attacker_def = _make_card("ns_reshiram", "N's Reshiram", attacks=[AttackDef(name="Burst", damage="100", cost=[])])
    defender_def = _make_card("defender", "Defender", hp=60)
    bench_def = _make_card("bench", "Bench")
    for c in (attacker_def, defender_def, bench_def):
        card_registry.register(c)

    attacker = _inst(attacker_def, "ns_reshiram")
    defender = _inst(defender_def, "defender")
    state = _state(
        p1_active=attacker,
        p2_active=defender,
        p2_bench=[_inst(bench_def, "bench", zone=Zone.BENCH)],
    )
    state.p1.prizes = [_inst(bench_def, f"prize-{i}", zone=Zone.PRIZES) for i in range(6)]
    state.p1.prizes_remaining = 6
    state.anthea_concordia_active = True

    _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert state.p1.prizes_remaining == 2  # 6 start - 1 normal prize - 3 Anthea prizes
    assert len(state.p1.prizes) == 2


def test_rescue_board_and_area_zero_alt_prints_match_primary_behavior():
    tera = _make_card("tera-alt", "Tera Alt", is_tera=True, retreat_cost=2)
    bench = _make_card("bench-alt", "Bench Alt")
    card_registry.register(tera)
    card_registry.register(bench)

    active = _inst(tera, "active-alt")
    active.tools_attached = ["sv05-159"]  # Rescue Board alt print
    bench_target = _inst(bench, "bench-target", zone=Zone.BENCH)
    state = _state(p1_active=active, p1_bench=[bench_target], p2_active=_inst(bench, "opp-alt"))
    assert get_retreat_cost_reduction(active, state, "p1") == 1
    active.current_hp = 30
    legal = ActionValidator.get_legal_actions(state, "p1")
    assert any(a.action_type == ActionType.RETREAT for a in legal)

    tera_active = _inst(tera, "tera-active")
    benches = [_inst(bench, f"bench-slot-{i}", zone=Zone.BENCH) for i in range(6)]
    state2 = _state(p1_active=tera_active, p1_bench=benches, p2_active=_inst(bench, "opp2-alt"))
    state2.active_stadium = CardInstance(instance_id="az-alt", card_def_id="sv07-131", card_name="Area Zero Underdepths", zone=Zone.STADIUM)
    assert get_bench_limit(state2, "p1") == 8

    state2.p1.active = _inst(bench, "not-tera-alt")
    enforce_area_zero_underdepths(state2)
    assert len(state2.p1.bench) == 5


def test_area_zero_bench_limit_and_prune_and_dizzying_valley_confusion_persists():
    tera = _make_card("tera", "Tera Mon", is_tera=True)
    bench = _make_card("bench", "Bench")
    stage1 = _make_card("stage1", "Stage1", stage="Stage 1", types=["Psychic"], hp=100)
    base = _make_card("base", "Base", types=["Psychic"], hp=60)
    for c in (tera, bench, stage1, base):
        card_registry.register(c)

    tera_inst = _inst(tera, "tera")
    benches = [_inst(bench, f"b{i}", zone=Zone.BENCH) for i in range(6)]
    state = _state(p1_active=tera_inst, p1_bench=benches, p2_active=_inst(bench, "opp"))
    state.active_stadium = CardInstance(instance_id="az", card_def_id="sv08.5-094", card_name="Area Zero Underdepths", zone=Zone.STADIUM)
    assert get_bench_limit(state, "p1") == 8

    state.p1.active = _inst(bench, "not-tera")
    enforce_area_zero_underdepths(state)
    assert len(state.p1.bench) == 5

    base_inst = _inst(base, "base", zone=Zone.BENCH, hp=60)
    evo = _inst(stage1, "evo", zone=Zone.BENCH, hp=100)
    evo.evolution_stage = 1
    evo.evolved_from = "base"
    evo.status_conditions.add(StatusCondition.CONFUSED)
    state2 = _state(p1_active=_inst(bench, "a2"), p1_bench=[evo], p2_active=_inst(bench, "opp2"))
    state2.active_stadium = CardInstance(instance_id="dv", card_def_id="me02-088", card_name="Dizzying Valley", zone=Zone.STADIUM)
    state2.p1.discard = [base_inst]
    _devolve_pokemon(state2, "p1", evo, "hand")
    assert StatusCondition.CONFUSED in state2.p1.bench[0].status_conditions
