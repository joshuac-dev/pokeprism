"""Trainer effect handlers — Phase 2 implementation.

Handler contract:
  - Regular functions: ``handler(state, action) -> None``  (mutate state)
  - Generator functions: ``handler(state, action) -> Generator``  (yield ChoiceRequest)
  - For Item/Supporter/Stadium/Tool handlers:
      - ``action.player_id``     — player who played the trainer
      - ``action.card_instance_id`` — instance id of the trainer card played
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from app.engine.state import (
    CardInstance,
    EnergyAttachment,
    EnergyType,
    GameState,
    StatusCondition,
    Zone,
)
from app.engine.effects.base import ChoiceRequest, check_ko, draw_cards
from app.engine.effects.registry import EffectRegistry
from app.cards import registry as card_registry

if TYPE_CHECKING:
    from app.engine.actions import Action

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find_in_play(player):
    """All in-play Pokémon for a player (active + bench)."""
    result = []
    if player.active:
        result.append(player.active)
    result.extend(player.bench)
    return result


def _find_pokemon_in_play(player, instance_id):
    """Return the CardInstance with the given id from active or bench, or None."""
    if player.active and player.active.instance_id == instance_id:
        return player.active
    return next((c for c in player.bench if c.instance_id == instance_id), None)


def _switch_active_with_bench(player, bench_poke) -> None:
    """Swap bench_poke into the active slot."""
    old_active = player.active
    if old_active is None:
        # No current active — just promote bench_poke
        bench_poke.zone = Zone.ACTIVE
        player.active = bench_poke
        player.bench.remove(bench_poke)
        return
    old_active.zone = Zone.BENCH
    bench_poke.zone = Zone.ACTIVE
    player.active = bench_poke
    player.bench.remove(bench_poke)
    player.bench.append(old_active)


def _is_basic_energy_cdef(cdef) -> bool:
    """True if a CardDefinition represents a basic energy card."""
    if cdef is None:
        return False
    return cdef.category.lower() == "energy" and cdef.subcategory.lower() == "basic"


def _is_basic_energy_card(card) -> bool:
    """True if a CardInstance is a basic energy."""
    return (card.card_type.lower() == "energy"
            and card.card_subtype.lower() == "basic")


def _is_special_energy(card_def_id: str) -> bool:
    cdef = card_registry.get(card_def_id)
    return (cdef is not None
            and cdef.category.lower() == "energy"
            and cdef.subcategory.lower() != "basic")


def _has_rule_box(card) -> bool:
    """True if a CardInstance represents a rule-box Pokémon."""
    cdef = card_registry.get(card.card_def_id)
    return bool(cdef and cdef.has_rule_box)


def _is_pokemon_ex(card) -> bool:
    cdef = card_registry.get(card.card_def_id)
    return bool(cdef and cdef.is_ex)


def _is_tera(card) -> bool:
    cdef = card_registry.get(card.card_def_id)
    return bool(cdef and cdef.is_tera)


def _pokemon_has_type(card, type_str: str) -> bool:
    cdef = card_registry.get(card.card_def_id)
    return bool(cdef and type_str in (cdef.types or []))


def _energy_provides_type(card, type_str: str) -> bool:
    """True if a CardInstance energy provides the given type string."""
    return type_str in (card.energy_provides or [])


def _make_energy_attachment(energy_card):
    """Build an EnergyAttachment from a basic energy CardInstance."""
    provides_raw = energy_card.energy_provides or []
    provides = [EnergyType.from_str(t) for t in provides_raw] or [EnergyType.COLORLESS]
    return EnergyAttachment(
        energy_type=provides[0],
        source_card_id=energy_card.instance_id,
        card_def_id=energy_card.card_def_id,
        provides=provides,
    )


def _bench_pokemon(state, player_id: str, card) -> None:
    """Place a Basic Pokémon on the bench (no hand removal — caller does that).

    Handles Risky Ruins (me01-127) damage for non-Darkness Pokémon.
    """
    player = state.get_player(player_id)
    card.zone = Zone.BENCH
    card.turn_played = state.turn_number
    player.bench.append(card)
    state.emit_event("play_basic", player=player_id,
                     card=card.card_name, bench_size=len(player.bench))
    if state.active_stadium and state.active_stadium.card_def_id == "me01-127":
        cdef_rr = card_registry.get(card.card_def_id)
        if cdef_rr and "Darkness" not in (cdef_rr.types or []):
            card.current_hp = max(0, card.current_hp - 20)
            card.damage_counters += 2


def _ko_happened_last_turn(state, player_id: str, tr_only: bool = False) -> bool:
    """Return True if the given player's Pokémon was KO'd last turn.

    With tr_only=True, only TR Pokémon KOs count (for TR Archer).
    """
    for ev in state.events:
        if ev.get("event_type") != "ko":
            continue
        if ev.get("turn") != state.turn_number - 1:
            continue
        if ev.get("ko_player") != player_id:
            continue
        if tr_only:
            name = ev.get("card_name", "")
            if not name.startswith("Team Rocket's"):
                continue
        return True
    return False


def _check_tr_factory(state, player_id: str) -> None:
    """Draw 2 cards for player if Team Rocket's Factory (sv10-173) is active."""
    if (state.active_stadium
            and state.active_stadium.card_def_id == "sv10-173"):
        draw_cards(state, player_id, 2)


def _mark_tr_supporter(state, player_id: str) -> None:
    """Mark TR supporter played and trigger TR Factory if active."""
    player = state.get_player(player_id)
    player.tr_supporter_played_this_turn = True
    _check_tr_factory(state, player_id)


def _stage2_can_evolve_from_basic(stage2_def_id: str, basic_name: str) -> bool:
    """True if stage2_def_id can evolve from a Basic with the given name via Stage 1."""
    stage2_def = card_registry.get(stage2_def_id)
    if not stage2_def or not stage2_def.evolve_from:
        return False
    stage1_name = stage2_def.evolve_from.lower()
    for cdef in card_registry.all_cards().values():
        if (cdef.name and cdef.name.lower() == stage1_name
                and getattr(cdef, "evolve_from", None)
                and cdef.evolve_from.lower() == basic_name.lower()):
            return True
    return False


def _evolve_via_rare_candy(state, player, target, evo_card) -> None:
    """Perform Rare Candy evolution: skip Stage 1, go directly to Stage 2."""
    cdef = card_registry.get(evo_card.card_def_id)
    # Transfer damage counters
    evo_card.damage_counters = target.damage_counters
    evo_card.max_hp = cdef.hp if (cdef and cdef.hp) else evo_card.max_hp
    evo_card.current_hp = max(0, evo_card.max_hp - target.damage_counters * 10)
    # Transfer energy and tools
    evo_card.energy_attached = list(target.energy_attached)
    evo_card.tools_attached = list(target.tools_attached)
    evo_card.status_conditions = set(target.status_conditions)
    evo_card.evolution_stage = 2
    evo_card.turn_played = state.turn_number  # Cannot evolve again this turn

    is_active = (player.active is not None
                 and player.active.instance_id == target.instance_id)
    if is_active:
        evo_card.zone = Zone.ACTIVE
        player.active = evo_card
    else:
        evo_card.zone = Zone.BENCH
        bench_idx = next(
            (i for i, b in enumerate(player.bench)
             if b.instance_id == target.instance_id), None
        )
        if bench_idx is not None:
            player.bench[bench_idx] = evo_card
        else:
            player.bench.append(evo_card)

    # Move pre-evolution to discard
    target.zone = Zone.DISCARD
    player.discard.append(target)

    player.hand.remove(evo_card)
    state.emit_event("rare_candy_evolve",
                     player=player.instance_id if hasattr(player, "instance_id") else "?",
                     from_card=target.card_name,
                     to_card=evo_card.card_name)


# ──────────────────────────────────────────────────────────────────────────────
# No-op handler (passive tools, passive stadiums, unimplemented once-per-turn
# stadium abilities requiring a USE_STADIUM action type)
# ──────────────────────────────────────────────────────────────────────────────

def _noop(state: GameState, action) -> None:
    """Registered to suppress 'no trainer effect' warnings for passive cards."""


# ──────────────────────────────────────────────────────────────────────────────
# Supporters
# ──────────────────────────────────────────────────────────────────────────────

def _acerolas_mischief(state: GameState, action):
    """Acerola's Mischief (me01-113)

    Choose 1 of your Pokémon. During your opponent's next turn, prevent all
    damage from and effects of attacks done to that Pokémon by your opponent's
    Pokémon ex. Then, draw cards until you have 4 cards in your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    in_play = _find_in_play(player)
    if in_play:
        req = ChoiceRequest(
            "choose_target", player_id,
            "Acerola's Mischief: choose a Pokémon to protect from Pokémon ex",
            targets=in_play,
        )
        resp = yield req
        if resp and resp.target_instance_id:
            poke = _find_pokemon_in_play(player, resp.target_instance_id)
        else:
            poke = in_play[0]
        if poke:
            poke.protected_from_ex = True
            state.emit_event("acerola_protection", player=player_id,
                             card=poke.card_name)
    # Draw to 4
    shortage = max(0, 4 - len(player.hand))
    if shortage > 0:
        draw_cards(state, player_id, shortage)


def _bosss_orders(state: GameState, action):
    """Boss's Orders (me01-114)

    Choose 1 of your opponent's Benched Pokémon and switch it with their
    Active Pokémon.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if not opp.bench:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Boss's Orders: choose an opponent's Benched Pokémon to bring Active",
        targets=list(opp.bench),
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = next((b for b in opp.bench
                       if b.instance_id == resp.target_instance_id), None)
    else:
        target = opp.bench[0]
    if target:
        _switch_active_with_bench(opp, target)
        state.emit_event("boss_orders", player=player_id,
                         forced_active=target.card_name)


def _lillies_determination(state: GameState, action) -> None:
    """Lillie's Determination (me01-119)

    Shuffle your hand into your deck. If you have 6 Prize cards remaining,
    draw 8 cards. Otherwise, draw 6 cards.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    # Shuffle hand into deck (trainer card already removed by transition)
    for c in player.hand:
        c.zone = Zone.DECK
        player.deck.append(c)
    player.hand.clear()
    random.shuffle(player.deck)
    count = 8 if player.prizes_remaining == 6 else 6
    draw_cards(state, player_id, count)


def _dawn(state: GameState, action):
    """Dawn (me02-087)

    Search your deck for a Basic Pokémon, a Stage 1 Pokémon, and a Stage 2
    Pokémon. Put them into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    stage_labels = {0: "Basic", 1: "Stage 1", 2: "Stage 2"}
    for stage_int, stage_label in stage_labels.items():
        candidates = [c for c in player.deck
                      if c.card_type.lower() == "pokemon"
                      and c.evolution_stage == stage_int]
        if not candidates:
            continue
        req = ChoiceRequest(
            "choose_cards", player_id,
            f"Dawn: choose a {stage_label} Pokémon from your deck",
            cards=candidates, min_count=0, max_count=1,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [candidates[0].instance_id])
        for iid in chosen_ids[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="dawn")


def _rosas_encouragement(state: GameState, action):
    """Rosa's Encouragement (me03-084)

    You can use this card only if your opponent has more Prize cards remaining
    than you. Search your deck for up to 2 Basic Energy cards, reveal them,
    and put them into your hand. Shuffle your deck afterward. Then, choose
    1 of your Pokémon and attach those Energy cards to it.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp = state.get_player(state.opponent_id(player_id))
    if not (opp.prizes_remaining > player.prizes_remaining):
        state.emit_event("rosa_not_applicable", player=player_id,
                         reason="condition_not_met")
        return

    energy_in_deck = [c for c in player.deck if _is_basic_energy_card(c)]
    if not energy_in_deck:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Rosa's Encouragement: choose up to 2 Basic Energy from your deck",
        cards=energy_in_deck, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in energy_in_deck[:2]])

    chosen_cards = []
    for iid in chosen_ids[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            chosen_cards.append(card)

    random.shuffle(player.deck)

    if not chosen_cards:
        return

    # Choose a Pokémon to attach them to
    in_play = _find_in_play(player)
    if not in_play:
        return

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Rosa's Encouragement: choose a Pokémon to attach the energy to",
        targets=in_play,
    )
    resp2 = yield req2
    if resp2 and resp2.target_instance_id:
        poke = _find_pokemon_in_play(player, resp2.target_instance_id)
    else:
        poke = in_play[0]

    if poke is None:
        return

    for energy_card in chosen_cards:
        att = _make_energy_attachment(energy_card)
        att.energy_type = EnergyType.from_str(
            energy_card.energy_provides[0]) if energy_card.energy_provides else EnergyType.COLORLESS
        att.provides = ([EnergyType.from_str(t) for t in energy_card.energy_provides]
                        if energy_card.energy_provides else [EnergyType.COLORLESS])
        energy_card.zone = poke.zone
        poke.energy_attached.append(att)
        player.hand.remove(energy_card)
        state.emit_event("energy_attached",
                         player=player_id,
                         energy=energy_card.card_name,
                         target=poke.card_name,
                         source="rosa")


def _tarragon(state: GameState, action):
    """Tarragon (me03-085)

    Choose up to 4 Fighting-type Pokémon or Basic Fighting Energy cards from
    your discard pile and put them into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = []
    for c in player.discard:
        if c.card_type.lower() == "pokemon" and _pokemon_has_type(c, "Fighting"):
            candidates.append(c)
        elif (_is_basic_energy_card(c)
              and _energy_provides_type(c, "Fighting")):
            candidates.append(c)

    if not candidates:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Tarragon: choose up to 4 Fighting Pokémon or Basic Fighting Energy from discard",
        cards=candidates, min_count=0, max_count=4,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:4]])

    for iid in chosen_ids[:4]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    state.emit_event("tarragon", player=player_id, count=len(chosen_ids[:4]))


def _judge(state: GameState, action) -> None:
    """Judge (me03-076)

    Each player shuffles their hand into their deck and draws 4 cards.
    """
    player_id = action.player_id
    for pid in (player_id, state.opponent_id(player_id)):
        p = state.get_player(pid)
        for c in p.hand:
            c.zone = Zone.DECK
            p.deck.append(c)
        p.hand.clear()
        random.shuffle(p.deck)
        draw_cards(state, pid, 4)


def _ciphermaniacs_codebreaking(state: GameState, action):
    """Cipher Maniac's Codebreaking (sv05-145)

    Look at the top 2 cards of your deck. Put them back in any order on top
    of your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    top_cards = player.deck[:2]
    if not top_cards:
        return
    if len(top_cards) == 1:
        # Only one card — no reorder needed
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Cipher Maniac's Codebreaking: choose which card to put on TOP (the other goes 2nd)",
        cards=top_cards, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [top_cards[0].instance_id])

    top_id = chosen_ids[0]
    if top_cards[0].instance_id == top_id:
        pass  # Already in correct order
    else:
        # Swap
        player.deck[0], player.deck[1] = player.deck[1], player.deck[0]


def _eri(state: GameState, action):
    """Eri (sv05-146)

    Choose up to 2 Item cards from your opponent's hand and discard them.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    items_in_opp_hand = [c for c in opp.hand
                         if c.card_type.lower() == "trainer"
                         and c.card_subtype.lower() == "item"]
    if not items_in_opp_hand:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Eri: choose up to 2 Items from your opponent's hand to discard",
        cards=items_in_opp_hand, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in items_in_opp_hand[:2]])

    for iid in chosen_ids[:2]:
        card = next((c for c in opp.hand if c.instance_id == iid), None)
        if card:
            opp.hand.remove(card)
            card.zone = Zone.DISCARD
            opp.discard.append(card)

    state.emit_event("eri_discard", player=player_id, count=len(chosen_ids[:2]))


def _mortys_conviction(state: GameState, action):
    """Morty's Conviction (sv05-155)

    Discard 1 card from your hand. If you do, draw 1 card for each of your
    opponent's Benched Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp = state.get_player(state.opponent_id(player_id))

    # Pay cost: discard 1 from hand (hand still has cards — trainer was removed)
    if not player.hand:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Morty's Conviction: discard 1 card from your hand (cost)",
        cards=list(player.hand), min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [player.hand[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)
            draw_count = len(opp.bench)
            if draw_count > 0:
                draw_cards(state, player_id, draw_count)


def _kieran(state: GameState, action):
    """Kieran (sv06-154)

    Choose 1: switch your Active Pokémon with 1 of your Benched Pokémon;
    or during this turn, attacks used by your Pokémon do 30 more damage to
    your opponent's Active Pokémon (before applying Weakness and Resistance).
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if player.bench:
        options = [
            "Switch your Active Pokémon with a Benched Pokémon",
            "Attacks do +30 damage this turn",
        ]
    else:
        options = ["Attacks do +30 damage this turn"]

    req = ChoiceRequest(
        "choose_option", player_id,
        "Kieran: choose an effect",
        options=options,
    )
    resp = yield req
    opt = (resp.selected_option if (resp is not None and resp.selected_option is not None)
           else 0)

    # Normalise: if bench empty the only option is +30 damage (regardless of opt)
    if not player.bench:
        state.active_player_damage_bonus += 30
        state.emit_event("kieran_damage_bonus", player=player_id, bonus=30)
        return

    if opt == 0:
        # Switch
        req2 = ChoiceRequest(
            "choose_target", player_id,
            "Kieran: choose a Benched Pokémon to switch in",
            targets=list(player.bench),
        )
        resp2 = yield req2
        if resp2 and resp2.target_instance_id:
            bench_poke = next((b for b in player.bench
                               if b.instance_id == resp2.target_instance_id), None)
        else:
            bench_poke = player.bench[0]
        if bench_poke:
            _switch_active_with_bench(player, bench_poke)
            state.emit_event("kieran_switch", player=player_id,
                             new_active=bench_poke.card_name)
    else:
        state.active_player_damage_bonus += 30
        state.emit_event("kieran_damage_bonus", player=player_id, bonus=30)


def _lanas_aid(state: GameState, action):
    """Lana's Aid (sv06-155)

    Choose up to 3 non-rule-box Pokémon or Basic Energy cards from your
    discard pile and put them into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = []
    for c in player.discard:
        if c.card_type.lower() == "pokemon" and not _has_rule_box(c):
            candidates.append(c)
        elif _is_basic_energy_card(c):
            candidates.append(c)

    if not candidates:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Lana's Aid: choose up to 3 non-rule-box Pokémon or Basic Energy from discard",
        cards=candidates, min_count=0, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:3]])

    for iid in chosen_ids[:3]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)


def _colresss_tenacity(state: GameState, action):
    """Colress's Tenacity (sv06.5-057)

    Search your deck for a Stadium card and an Energy card, reveal them,
    and put them into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    # Search for a Stadium
    stadiums = [c for c in player.deck
                if c.card_type.lower() == "trainer"
                and c.card_subtype.lower() == "stadium"]
    if stadiums:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Colress's Tenacity: choose a Stadium from your deck",
            cards=stadiums, min_count=0, max_count=1,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [stadiums[0].instance_id])
        for iid in chosen_ids[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    # Search for an Energy
    energies = [c for c in player.deck if c.card_type.lower() == "energy"]
    if energies:
        req2 = ChoiceRequest(
            "choose_cards", player_id,
            "Colress's Tenacity: choose an Energy card from your deck",
            cards=energies, min_count=0, max_count=1,
        )
        resp2 = yield req2
        chosen_ids2 = (resp2.selected_cards if resp2 and resp2.selected_cards
                       else [energies[0].instance_id])
        for iid in chosen_ids2[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="colress")


def _xerosics_machinations(state: GameState, action):
    """Xerosic's Machinations (sv06.5-064)

    Your opponent discards cards from their hand until they have 3 cards left.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    while len(opp.hand) > 3:
        excess = opp.hand[len(opp.hand) - 3:]
        discard_count = len(opp.hand) - 3
        if discard_count <= 0:
            break
        candidates = list(opp.hand)
        req = ChoiceRequest(
            "choose_cards", opp_id,
            "Xerosic's Machinations: discard cards down to 3 in hand",
            cards=candidates, min_count=discard_count, max_count=discard_count,
        )
        resp = yield req
        if resp and resp.selected_cards:
            chosen_ids = resp.selected_cards[:discard_count]
        else:
            chosen_ids = [c.instance_id for c in candidates[:discard_count]]

        for iid in chosen_ids:
            card = next((c for c in opp.hand if c.instance_id == iid), None)
            if card:
                opp.hand.remove(card)
                card.zone = Zone.DISCARD
                opp.discard.append(card)
        # Safety: exit if loop would repeat
        break

    state.emit_event("xerosic", player=player_id, opp_hand=len(opp.hand))


def _briar(state: GameState, action) -> None:
    """Briar (sv07-132)

    You can use this card only when your opponent has exactly 2 Prize cards
    remaining. During this turn, if your opponent's Active Pokémon is Knocked
    Out by damage from an attack from your Pokémon, you may take 1 more Prize
    card.
    """
    player_id = action.player_id
    opp = state.get_player(state.opponent_id(player_id))
    if opp.prizes_remaining != 2:
        state.emit_event("briar_not_applicable", player=player_id,
                         reason="opponent_prizes_not_2")
        return
    state.briar_active = True
    state.emit_event("briar_active", player=player_id)


def _crispin(state: GameState, action):
    """Crispin (sv07-133)

    Search your deck for up to 2 Basic Energy cards of different types, reveal
    them, and put 1 into your hand and attach the other to 1 of your Pokémon.
    Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    basic_energy_in_deck = [c for c in player.deck if _is_basic_energy_card(c)]
    if not basic_energy_in_deck:
        random.shuffle(player.deck)
        return

    # Try to find two different energy types
    seen_types: set[str] = set()
    candidates: list = []
    for c in basic_energy_in_deck:
        etype = c.energy_provides[0] if c.energy_provides else "Colorless"
        if etype not in seen_types:
            seen_types.add(etype)
            candidates.append(c)
        if len(candidates) == 2:
            break

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Crispin: choose up to 2 Basic Energy of different types from deck",
        cards=candidates if len(candidates) == 2 else basic_energy_in_deck[:2],
        min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:2]])
    chosen_cards = []
    for iid in chosen_ids[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            chosen_cards.append(card)

    random.shuffle(player.deck)

    if not chosen_cards:
        return

    if len(chosen_cards) == 1:
        # Only one — put in hand
        chosen_cards[0].zone = Zone.HAND
        player.hand.append(chosen_cards[0])
        return

    # Two cards: player picks which goes to hand; other attaches
    option_labels = [f"Put '{c.card_name}' in hand (attach the other)" for c in chosen_cards]
    req2 = ChoiceRequest(
        "choose_option", player_id,
        "Crispin: choose which Basic Energy to put in hand",
        options=option_labels,
    )
    resp2 = yield req2
    hand_idx = (resp2.selected_option
                if (resp2 is not None and resp2.selected_option is not None) else 0)
    hand_idx = max(0, min(hand_idx, len(chosen_cards) - 1))
    attach_idx = 1 - hand_idx

    hand_card = chosen_cards[hand_idx]
    attach_card = chosen_cards[attach_idx]

    hand_card.zone = Zone.HAND
    player.hand.append(hand_card)

    # Attach the other to a chosen Pokémon
    in_play = _find_in_play(player)
    if not in_play:
        attach_card.zone = Zone.HAND
        player.hand.append(attach_card)
        return

    req3 = ChoiceRequest(
        "choose_target", player_id,
        f"Crispin: choose a Pokémon to attach '{attach_card.card_name}' to",
        targets=in_play,
    )
    resp3 = yield req3
    if resp3 and resp3.target_instance_id:
        poke = _find_pokemon_in_play(player, resp3.target_instance_id)
    else:
        poke = in_play[0]

    if poke is None:
        attach_card.zone = Zone.HAND
        player.hand.append(attach_card)
        return

    att = _make_energy_attachment(attach_card)
    attach_card.zone = poke.zone
    poke.energy_attached.append(att)
    state.emit_event("energy_attached", player=player_id,
                     energy=attach_card.card_name,
                     target=poke.card_name, source="crispin")


def _cyrano(state: GameState, action):
    """Cyrano (sv08-170)

    Search your deck for up to 3 Pokémon ex, reveal them, and put them into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    ex_in_deck = [c for c in player.deck
                  if c.card_type.lower() == "pokemon" and _is_pokemon_ex(c)]
    if not ex_in_deck:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Cyrano: choose up to 3 Pokémon ex from your deck",
        cards=ex_in_deck, min_count=0, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in ex_in_deck[:3]])

    for iid in chosen_ids[:3]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="cyrano")


def _janines_secret_art(state: GameState, action):
    """Janine's Secret Art (sv08.5-112)

    Search your deck for up to 2 Darkness-type Pokémon and put them onto your
    Bench. Attach a Basic Darkness Energy from your hand to each of them. If
    you put any Pokémon on your Bench this way, your Active Pokémon is now
    Poisoned. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    dark_in_deck = [c for c in player.deck
                    if c.card_type.lower() == "pokemon"
                    and c.evolution_stage == 0
                    and _pokemon_has_type(c, "Darkness")
                    and len(player.bench) < 5]
    if not dark_in_deck:
        random.shuffle(player.deck)
        return

    max_bench = min(2, 5 - len(player.bench))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Janine's Secret Art: choose up to 2 Darkness Pokémon from your deck to bench",
        cards=dark_in_deck, min_count=0, max_count=max_bench,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in dark_in_deck[:max_bench]])

    benched_count = 0
    for iid in chosen_ids[:max_bench]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card and len(player.bench) < 5:
            player.deck.remove(card)
            _bench_pokemon(state, player_id, card)
            benched_count += 1

            # Auto-attach first Basic Darkness Energy from hand
            dark_energy = next(
                (c for c in player.hand
                 if _is_basic_energy_card(c) and _energy_provides_type(c, "Darkness")),
                None
            )
            if dark_energy:
                att = _make_energy_attachment(dark_energy)
                dark_energy.zone = card.zone
                card.energy_attached.append(att)
                player.hand.remove(dark_energy)
                state.emit_event("energy_attached", player=player_id,
                                 energy=dark_energy.card_name,
                                 target=card.card_name, source="janine")

    random.shuffle(player.deck)

    if benched_count > 0 and player.active:
        player.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_inflicted", player=player_id,
                         card=player.active.card_name, status="POISONED",
                         source="janine")


def _larrys_skill(state: GameState, action):
    """Larry's Skill (sv08.5-115)

    Discard your hand. Search your deck for a Pokémon, a Supporter card, and
    a Basic Energy card, reveal them, and put them into your hand. Shuffle
    your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    # Discard hand (trainer card already removed)
    for c in player.hand:
        c.zone = Zone.DISCARD
        player.discard.append(c)
    player.hand.clear()

    # Search for a Pokémon
    pokemon_in_deck = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if pokemon_in_deck:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Larry's Skill: choose a Pokémon from your deck",
            cards=pokemon_in_deck, min_count=0, max_count=1,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [pokemon_in_deck[0].instance_id])
        for iid in chosen_ids[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    # Search for a Supporter
    supporters_in_deck = [c for c in player.deck
                          if c.card_type.lower() == "trainer"
                          and c.card_subtype.lower() == "supporter"]
    if supporters_in_deck:
        req2 = ChoiceRequest(
            "choose_cards", player_id,
            "Larry's Skill: choose a Supporter from your deck",
            cards=supporters_in_deck, min_count=0, max_count=1,
        )
        resp2 = yield req2
        chosen_ids2 = (resp2.selected_cards if resp2 and resp2.selected_cards
                       else [supporters_in_deck[0].instance_id])
        for iid in chosen_ids2[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    # Search for a Basic Energy
    basic_energy_in_deck = [c for c in player.deck if _is_basic_energy_card(c)]
    if basic_energy_in_deck:
        req3 = ChoiceRequest(
            "choose_cards", player_id,
            "Larry's Skill: choose a Basic Energy from your deck",
            cards=basic_energy_in_deck, min_count=0, max_count=1,
        )
        resp3 = yield req3
        chosen_ids3 = (resp3.selected_cards if resp3 and resp3.selected_cards
                       else [basic_energy_in_deck[0].instance_id])
        for iid in chosen_ids3[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="larrys_skill")


def _brocks_scouting(state: GameState, action):
    """Brock's Scouting (sv09-146)

    Choose 1: search your deck for up to 2 Basic Pokémon and put them into
    your hand; or search your deck for an Evolution Pokémon and put it into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    options = [
        "Search deck for up to 2 Basic Pokémon → hand",
        "Search deck for 1 Evolution Pokémon → hand",
    ]
    req = ChoiceRequest(
        "choose_option", player_id,
        "Brock's Scouting: choose an effect",
        options=options,
    )
    resp = yield req
    opt = (resp.selected_option if (resp is not None and resp.selected_option is not None)
           else 0)

    if opt == 0:
        basics_in_deck = [c for c in player.deck
                          if c.card_type.lower() == "pokemon" and c.evolution_stage == 0]
        if basics_in_deck:
            req2 = ChoiceRequest(
                "choose_cards", player_id,
                "Brock's Scouting: choose up to 2 Basic Pokémon from deck",
                cards=basics_in_deck, min_count=0, max_count=2,
            )
            resp2 = yield req2
            chosen_ids = (resp2.selected_cards if resp2 and resp2.selected_cards
                          else [c.instance_id for c in basics_in_deck[:2]])
            for iid in chosen_ids[:2]:
                card = next((c for c in player.deck if c.instance_id == iid), None)
                if card:
                    player.deck.remove(card)
                    card.zone = Zone.HAND
                    player.hand.append(card)
    else:
        evos_in_deck = [c for c in player.deck
                        if c.card_type.lower() == "pokemon" and c.evolution_stage > 0]
        if evos_in_deck:
            req2 = ChoiceRequest(
                "choose_cards", player_id,
                "Brock's Scouting: choose 1 Evolution Pokémon from deck",
                cards=evos_in_deck, min_count=0, max_count=1,
            )
            resp2 = yield req2
            chosen_ids = (resp2.selected_cards if resp2 and resp2.selected_cards
                          else [evos_in_deck[0].instance_id])
            for iid in chosen_ids[:1]:
                card = next((c for c in player.deck if c.instance_id == iid), None)
                if card:
                    player.deck.remove(card)
                    card.zone = Zone.HAND
                    player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="brocks_scouting")


def _tr_archer(state: GameState, action):
    """Team Rocket's Archer (sv10-170)  [TR Supporter]

    You can use this card only if 1 of your Team Rocket's Pokémon was KO'd
    during your opponent's last turn. Both players shuffle their hands into
    their decks. You draw 5 cards; your opponent draws 3 cards.
    """
    player_id = action.player_id
    if not _ko_happened_last_turn(state, player_id, tr_only=True):
        state.emit_event("tr_archer_not_applicable", player=player_id,
                         reason="no_tr_ko_last_turn")
        _mark_tr_supporter(state, player_id)
        return

    opp_id = state.opponent_id(player_id)
    for pid, draw_n in ((player_id, 5), (opp_id, 3)):
        p = state.get_player(pid)
        for c in p.hand:
            c.zone = Zone.DECK
            p.deck.append(c)
        p.hand.clear()
        random.shuffle(p.deck)
        draw_cards(state, pid, draw_n)

    _mark_tr_supporter(state, player_id)


def _tr_ariana(state: GameState, action):
    """Team Rocket's Ariana (sv10-171)  [TR Supporter]

    Draw cards until you have 5 cards in your hand. If all your Pokémon in
    play are Team Rocket's Pokémon, draw cards until you have 8 instead.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    all_tr = all(
        p.card_name.startswith("Team Rocket's")
        for p in _find_in_play(player)
    )
    target = 8 if all_tr else 5
    shortage = max(0, target - len(player.hand))
    if shortage > 0:
        draw_cards(state, player_id, shortage)

    _mark_tr_supporter(state, player_id)


def _tr_giovanni(state: GameState, action):
    """Team Rocket's Giovanni (sv10-174)  [TR Supporter]

    You may switch your Active Pokémon with 1 of your Benched Pokémon. Then,
    choose 1 of your opponent's Benched Pokémon and switch it with their
    Active Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    # Optional own switch
    if player.bench:
        req = ChoiceRequest(
            "choose_option", player_id,
            "Giovanni: switch your Active with a Benched Pokémon? (optional)",
            options=["Yes, switch", "No, skip"],
        )
        resp = yield req
        opt = (resp.selected_option if (resp is not None
                                        and resp.selected_option is not None) else 0)
        if opt == 0:
            req2 = ChoiceRequest(
                "choose_target", player_id,
                "Giovanni: choose a Benched Pokémon to switch in",
                targets=list(player.bench),
            )
            resp2 = yield req2
            if resp2 and resp2.target_instance_id:
                bench_poke = next((b for b in player.bench
                                   if b.instance_id == resp2.target_instance_id), None)
            else:
                bench_poke = player.bench[0]
            if bench_poke:
                _switch_active_with_bench(player, bench_poke)
                state.emit_event("giovanni_self_switch", player=player_id,
                                 new_active=bench_poke.card_name)

    # Mandatory opponent bench switch
    if opp.bench:
        req3 = ChoiceRequest(
            "choose_target", player_id,
            "Giovanni: choose one of your opponent's Benched Pokémon to bring Active",
            targets=list(opp.bench),
        )
        resp3 = yield req3
        if resp3 and resp3.target_instance_id:
            opp_target = next((b for b in opp.bench
                               if b.instance_id == resp3.target_instance_id), None)
        else:
            opp_target = opp.bench[0]
        if opp_target:
            _switch_active_with_bench(opp, opp_target)
            state.emit_event("giovanni_opp_switch", player=player_id,
                             forced_active=opp_target.card_name)

    _mark_tr_supporter(state, player_id)


def _tr_petrel(state: GameState, action):
    """Team Rocket's Petrel (sv10-176)  [TR Supporter]

    Search your deck for any Trainer card, reveal it, and put it into your
    hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    trainers_in_deck = [c for c in player.deck if c.card_type.lower() == "trainer"]
    if trainers_in_deck:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Petrel: choose any Trainer from your deck",
            cards=trainers_in_deck, min_count=0, max_count=1,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [trainers_in_deck[0].instance_id])
        for iid in chosen_ids[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tr_petrel")
    _mark_tr_supporter(state, player_id)


def _tr_proton(state: GameState, action):
    """Team Rocket's Proton (sv10-177)  [TR Supporter]

    Search your deck for up to 3 Basic Team Rocket's Pokémon, reveal them,
    and put them into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    tr_basics_in_deck = [c for c in player.deck
                         if (c.card_type.lower() == "pokemon"
                             and c.evolution_stage == 0
                             and c.card_name.startswith("Team Rocket's"))]
    if tr_basics_in_deck:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Proton: choose up to 3 Basic TR Pokémon from deck",
            cards=tr_basics_in_deck, min_count=0, max_count=3,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [c.instance_id for c in tr_basics_in_deck[:3]])
        for iid in chosen_ids[:3]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tr_proton")
    _mark_tr_supporter(state, player_id)


def _hilda(state: GameState, action):
    """Hilda (sv10.5w-084)

    Search your deck for an Evolution Pokémon and an Energy card, reveal them,
    and put them into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    # Evolution Pokémon
    evos_in_deck = [c for c in player.deck
                    if c.card_type.lower() == "pokemon" and c.evolution_stage > 0]
    if evos_in_deck:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Hilda: choose an Evolution Pokémon from your deck",
            cards=evos_in_deck, min_count=0, max_count=1,
        )
        resp = yield req
        chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                      else [evos_in_deck[0].instance_id])
        for iid in chosen_ids[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    # Energy card
    energies_in_deck = [c for c in player.deck if c.card_type.lower() == "energy"]
    if energies_in_deck:
        req2 = ChoiceRequest(
            "choose_cards", player_id,
            "Hilda: choose an Energy card from your deck",
            cards=energies_in_deck, min_count=0, max_count=1,
        )
        resp2 = yield req2
        chosen_ids2 = (resp2.selected_cards if resp2 and resp2.selected_cards
                       else [energies_in_deck[0].instance_id])
        for iid in chosen_ids2[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="hilda")


# ──────────────────────────────────────────────────────────────────────────────
# Items
# ──────────────────────────────────────────────────────────────────────────────

def _energy_switch(state: GameState, action):
    """Energy Switch (me01-115)

    Move a Basic Energy attached to 1 of your Pokémon to another of your
    Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    in_play = _find_in_play(player)

    # Find Pokémon with at least one basic energy
    sources = [p for p in in_play
               if any(_is_basic_energy_cdef(card_registry.get(a.card_def_id))
                      for a in p.energy_attached)]
    if not sources:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Energy Switch: choose a Pokémon to take a Basic Energy from",
        targets=sources,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        source = _find_pokemon_in_play(player, resp.target_instance_id)
    else:
        source = sources[0]
    if source is None:
        return

    # Pick which basic energy to move (choose first if default)
    basic_atts = [a for a in source.energy_attached
                  if _is_basic_energy_cdef(card_registry.get(a.card_def_id))]
    if not basic_atts:
        return

    chosen_att = basic_atts[0]  # Default: first basic energy

    # Choose destination
    dests = [p for p in in_play if p.instance_id != source.instance_id]
    if not dests:
        return

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Energy Switch: choose a Pokémon to attach the Basic Energy to",
        targets=dests,
    )
    resp2 = yield req2
    if resp2 and resp2.target_instance_id:
        dest = _find_pokemon_in_play(player, resp2.target_instance_id)
    else:
        dest = dests[0]
    if dest is None:
        return

    source.energy_attached.remove(chosen_att)
    chosen_att.energy_type = chosen_att.energy_type  # No change needed
    dest.energy_attached.append(chosen_att)
    state.emit_event("energy_switch", player=player_id,
                     from_pokemon=source.card_name,
                     to_pokemon=dest.card_name,
                     energy=chosen_att.card_def_id)


def _fighting_gong(state: GameState, action):
    """Fighting Gong (me01-116)

    Search your deck for a Basic Fighting Energy card or a Fighting-type
    Pokémon, reveal it, and put it into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = []
    for c in player.deck:
        if _is_basic_energy_card(c) and _energy_provides_type(c, "Fighting"):
            candidates.append(c)
        elif c.card_type.lower() == "pokemon" and _pokemon_has_type(c, "Fighting"):
            candidates.append(c)

    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Fighting Gong: choose a Basic Fighting Energy or Fighting Pokémon from deck",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="fighting_gong")


def _rare_candy(state: GameState, action):
    """Rare Candy (me01-125)

    Choose 1 of your Basic Pokémon in play. If you have a Stage 2 card in your
    hand that evolves from that Pokémon, put that Stage 2 card onto that Basic
    Pokémon to evolve it, skipping the Stage 1.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    # Stage 2 cards in hand
    stage2_in_hand = [c for c in player.hand
                      if c.card_type.lower() == "pokemon" and c.evolution_stage == 2]
    if not stage2_in_hand:
        return

    # Basic Pokémon in play that can accept a Stage 2 (not played this turn)
    basics_in_play = [p for p in _find_in_play(player)
                      if p.evolution_stage == 0
                      and p.turn_played < state.turn_number]
    if not basics_in_play:
        return

    # Find valid (basic, stage2) pairs
    valid_pairs = []
    for basic in basics_in_play:
        for s2 in stage2_in_hand:
            if _stage2_can_evolve_from_basic(s2.card_def_id, basic.card_name):
                valid_pairs.append((basic, s2))

    if not valid_pairs:
        return

    # Choose target basic
    valid_basics = []
    seen_basic_ids: set[str] = set()
    for b, _ in valid_pairs:
        if b.instance_id not in seen_basic_ids:
            seen_basic_ids.add(b.instance_id)
            valid_basics.append(b)
    req = ChoiceRequest(
        "choose_target", player_id,
        "Rare Candy: choose a Basic Pokémon to evolve directly to Stage 2",
        targets=valid_basics,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        chosen_basic = next((b for b in valid_basics
                             if b.instance_id == resp.target_instance_id), None)
    else:
        chosen_basic = valid_basics[0]
    if chosen_basic is None:
        return

    # Choose Stage 2
    valid_stage2s = [s2 for b, s2 in valid_pairs
                     if b.instance_id == chosen_basic.instance_id]
    req2 = ChoiceRequest(
        "choose_cards", player_id,
        "Rare Candy: choose a Stage 2 Pokémon from hand to evolve into",
        cards=valid_stage2s, min_count=1, max_count=1,
    )
    resp2 = yield req2
    if resp2 and resp2.selected_cards:
        evo_card = next((c for c in valid_stage2s
                         if c.instance_id == resp2.selected_cards[0]), None)
    else:
        evo_card = valid_stage2s[0]
    if evo_card is None:
        return

    _evolve_via_rare_candy(state, player, chosen_basic, evo_card)


def _ultra_ball(state: GameState, action):
    """Ultra Ball (me01-131)

    Discard 2 cards from your hand. If you do, search your deck for a Pokémon,
    reveal it, and put it into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if len(player.hand) < 2:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Ultra Ball: discard 2 cards from your hand (cost)",
        cards=list(player.hand), min_count=2, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in player.hand[:2]])

    for iid in chosen_ids[:2]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    # Search for any Pokémon
    pokemon_in_deck = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if not pokemon_in_deck:
        random.shuffle(player.deck)
        return

    req2 = ChoiceRequest(
        "choose_cards", player_id,
        "Ultra Ball: choose a Pokémon from your deck",
        cards=pokemon_in_deck, min_count=0, max_count=1,
    )
    resp2 = yield req2
    chosen_ids2 = (resp2.selected_cards if resp2 and resp2.selected_cards
                   else [pokemon_in_deck[0].instance_id])

    for iid in chosen_ids2[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="ultra_ball")


def _jumbo_ice_cream(state: GameState, action) -> None:
    """Jumbo Ice Cream (me02-091)

    If your Active Pokémon has at least 3 Energy attached to it, heal 80
    damage from it.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if player.active is None:
        return
    if len(player.active.energy_attached) < 3:
        return
    heal = min(80, player.active.max_hp - player.active.current_hp)
    player.active.current_hp += heal
    healed_counters = heal // 10
    player.active.damage_counters = max(0, player.active.damage_counters - healed_counters)
    state.emit_event("heal", player=player_id,
                     card=player.active.card_name, amount=heal, source="jumbo_ice_cream")


def _wondrous_patch(state: GameState, action):
    """Wondrous Patch (me02-094)

    Choose 1 of your Benched Psychic-type Pokémon. Attach a Basic Psychic
    Energy card from your discard pile to that Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    psychic_bench = [b for b in player.bench if _pokemon_has_type(b, "Psychic")]
    if not psychic_bench:
        return

    psychic_energy_discard = [c for c in player.discard
                               if _is_basic_energy_card(c)
                               and _energy_provides_type(c, "Psychic")]
    if not psychic_energy_discard:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Wondrous Patch: choose a Benched Psychic Pokémon to attach Basic Psychic Energy",
        targets=psychic_bench,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        poke = next((b for b in psychic_bench
                     if b.instance_id == resp.target_instance_id), None)
    else:
        poke = psychic_bench[0]
    if poke is None:
        return

    energy_card = psychic_energy_discard[0]
    att = _make_energy_attachment(energy_card)
    energy_card.zone = poke.zone
    poke.energy_attached.append(att)
    player.discard.remove(energy_card)
    state.emit_event("energy_attached", player=player_id,
                     energy=energy_card.card_name,
                     target=poke.card_name, source="wondrous_patch")


def _night_stretcher(state: GameState, action):
    """Night Stretcher (me02.5-196)

    Choose 1 Pokémon or 1 Basic Energy card from your discard pile and put it
    into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = [c for c in player.discard
                  if c.card_type.lower() == "pokemon" or _is_basic_energy_card(c)]
    if not candidates:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Night Stretcher: choose a Pokémon or Basic Energy from discard",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)


def _tool_scrapper(state: GameState, action):
    """Tool Scrapper (me02.5-212)

    Discard up to 2 Pokémon Tool cards from either player's Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp = state.get_player(state.opponent_id(player_id))

    for _ in range(2):
        # Build list of all Pokémon with tools from both players
        tool_options: list[tuple] = []
        for pid, p in ((player_id, player), (state.opponent_id(player_id), opp)):
            for poke in _find_in_play(p):
                for tool_def_id in list(poke.tools_attached):
                    tool_options.append((poke, tool_def_id, pid))

        if not tool_options:
            break

        # Present options as labels
        labels = [f"{poke.card_name}'s {tool_def_id}" for poke, tool_def_id, _ in tool_options]
        req = ChoiceRequest(
            "choose_option", player_id,
            "Tool Scrapper: choose a Pokémon Tool to discard (or skip)",
            options=labels + ["Skip"],
        )
        resp = yield req
        opt = (resp.selected_option if (resp is not None
                                        and resp.selected_option is not None) else 0)

        if opt >= len(tool_options):
            break  # Skip chosen

        chosen_poke, chosen_tool_def_id, tool_owner_id = tool_options[opt]
        tool_owner = state.get_player(tool_owner_id)
        chosen_poke.tools_attached.remove(chosen_tool_def_id)
        state.emit_event("tool_discarded", player=player_id,
                         tool=chosen_tool_def_id,
                         pokemon=chosen_poke.card_name)


def _poke_pad(state: GameState, action):
    """Poké Pad (me03-081, me02.5-198)

    Search your deck for a non-rule-box Pokémon, reveal it, and put it into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = [c for c in player.deck
                  if c.card_type.lower() == "pokemon" and not _has_rule_box(c)]
    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Poké Pad: choose a non-rule-box Pokémon from your deck",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="poke_pad")


def _black_belt_training(state: GameState, action):
    """Black Belt's Training (sv09-143)

    During this turn, attacks used by your Pokémon do 40 more damage to your
    opponent's Active Pokémon ex (before applying Weakness and Resistance).
    """
    state.active_player_damage_bonus_vs_ex += 40
    state.emit_event("black_belt_training", player=action.player_id, bonus=40)


def _energy_retrieval(state: GameState, action):
    """Energy Retrieval (sv01-171)

    Choose up to 2 Basic Energy cards from your discard pile and put them into
    your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    basic_energy_discard = [c for c in player.discard if _is_basic_energy_card(c)]
    if not basic_energy_discard:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Energy Retrieval: choose up to 2 Basic Energy from discard",
        cards=basic_energy_discard, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in basic_energy_discard[:2]])

    for iid in chosen_ids[:2]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)


def _pokegear(state: GameState, action):
    """Pokégear 3.0 (sv01-186)

    Look at the top 7 cards of your deck. You may reveal a Supporter card you
    find there and put it into your hand. Shuffle the other cards back in.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    top7 = player.deck[:7]
    if not top7:
        return

    supporters = [c for c in top7
                  if c.card_type.lower() == "trainer"
                  and c.card_subtype.lower() == "supporter"]

    if not supporters:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Pokégear 3.0: choose 0 or 1 Supporter from the top 7 cards",
        cards=supporters, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if (resp and resp.selected_cards) else []

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="pokegear")


def _buddy_buddy_poffin(state: GameState, action):
    """Buddy-Buddy Poffin (sv05-144)

    Search your deck for up to 2 Basic Pokémon with 70 HP or less and put them
    onto your Bench. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    bench_space = 5 - len(player.bench)
    if bench_space <= 0:
        random.shuffle(player.deck)
        return

    candidates = [c for c in player.deck
                  if c.card_type.lower() == "pokemon"
                  and c.evolution_stage == 0
                  and c.current_hp <= 70]
    if not candidates:
        random.shuffle(player.deck)
        return

    max_choose = min(2, bench_space)
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Buddy-Buddy Poffin: choose up to 2 Basic Pokémon (HP ≤ 70) from deck to bench",
        cards=candidates, min_count=0, max_count=max_choose,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:max_choose]])

    for iid in chosen_ids[:max_choose]:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            _bench_pokemon(state, player_id, card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="buddy_buddy_poffin")


def _prime_catcher(state: GameState, action):
    """Prime Catcher (sv05-157)

    Switch 1 of your opponent's Benched Pokémon with their Active Pokémon.
    Then, switch your Active Pokémon with 1 of your Benched Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    # Force opponent bench switch
    if opp.bench:
        req = ChoiceRequest(
            "choose_target", player_id,
            "Prime Catcher: choose an opponent's Benched Pokémon to bring Active",
            targets=list(opp.bench),
        )
        resp = yield req
        if resp and resp.target_instance_id:
            opp_target = next((b for b in opp.bench
                               if b.instance_id == resp.target_instance_id), None)
        else:
            opp_target = opp.bench[0]
        if opp_target:
            _switch_active_with_bench(opp, opp_target)
            state.emit_event("prime_catcher_opp_switch", player=player_id,
                             forced_active=opp_target.card_name)

    # Player bench switch
    if player.bench:
        req2 = ChoiceRequest(
            "choose_target", player_id,
            "Prime Catcher: choose a Benched Pokémon to switch in",
            targets=list(player.bench),
        )
        resp2 = yield req2
        if resp2 and resp2.target_instance_id:
            bench_poke = next((b for b in player.bench
                               if b.instance_id == resp2.target_instance_id), None)
        else:
            bench_poke = player.bench[0]
        if bench_poke:
            _switch_active_with_bench(player, bench_poke)
            state.emit_event("prime_catcher_self_switch", player=player_id,
                             new_active=bench_poke.card_name)


def _bug_catching_set(state: GameState, action):
    """Bug Catching Set (sv06-143)

    Look at the top 7 cards of your deck. Choose up to 2 Grass-type Pokémon
    or Basic Grass Energy cards from those cards and put them into your hand.
    Shuffle the other cards back in.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    top7 = list(player.deck[:7])
    if not top7:
        return

    candidates = []
    for c in top7:
        if c.card_type.lower() == "pokemon" and _pokemon_has_type(c, "Grass"):
            candidates.append(c)
        elif _is_basic_energy_card(c) and _energy_provides_type(c, "Grass"):
            candidates.append(c)

    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Bug Catching Set: choose up to 2 Grass Pokémon or Basic Grass Energy from top 7",
        cards=candidates, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:2]])

    for iid in chosen_ids[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="bug_catching_set")


def _enhanced_hammer(state: GameState, action):
    """Enhanced Hammer (sv06-148)

    Choose 1 of your opponent's Pokémon with a Special Energy attached to it.
    Discard a Special Energy card from it.
    """
    player_id = action.player_id
    opp = state.get_player(state.opponent_id(player_id))

    # Find opponent Pokémon with special energy
    targets = [p for p in _find_in_play(opp)
               if any(_is_special_energy(a.card_def_id) for a in p.energy_attached)]
    if not targets:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Enhanced Hammer: choose an opponent's Pokémon to discard a Special Energy from",
        targets=targets,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        poke = _find_pokemon_in_play(opp, resp.target_instance_id)
    else:
        poke = targets[0]
    if poke is None:
        return

    special_atts = [a for a in poke.energy_attached
                    if _is_special_energy(a.card_def_id)]
    if not special_atts:
        return

    att = special_atts[0]
    poke.energy_attached.remove(att)
    state.emit_event("energy_discarded", player=player_id,
                     card_def_id=att.card_def_id,
                     pokemon=poke.card_name,
                     reason="enhanced_hammer")


def _secret_box(state: GameState, action):
    """Secret Box (sv06-163)

    Discard 3 cards from your hand. If you do, search your deck for an Item,
    a Pokémon Tool, a Supporter, and a Stadium card, reveal them, and put them
    into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if len(player.hand) < 3:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Secret Box: discard 3 cards from your hand (cost)",
        cards=list(player.hand), min_count=3, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in player.hand[:3]])

    for iid in chosen_ids[:3]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    # Search for Item, Tool, Supporter, Stadium
    for subtype in ("Item", "Tool", "Supporter", "Stadium"):
        candidates = [c for c in player.deck
                      if c.card_type.lower() == "trainer"
                      and c.card_subtype.lower() == subtype.lower()]
        if not candidates:
            continue
        req2 = ChoiceRequest(
            "choose_cards", player_id,
            f"Secret Box: choose a {subtype} from your deck",
            cards=candidates, min_count=0, max_count=1,
        )
        resp2 = yield req2
        chosen_ids2 = (resp2.selected_cards if resp2 and resp2.selected_cards
                       else [candidates[0].instance_id])
        for iid in chosen_ids2[:1]:
            card = next((c for c in player.deck if c.instance_id == iid), None)
            if card:
                player.deck.remove(card)
                card.zone = Zone.HAND
                player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="secret_box")


def _unfair_stamp(state: GameState, action):
    """Unfair Stamp (sv06-165)

    You can use this card only if your opponent KO'd 1 of your Pokémon during
    their last turn. Both players shuffle their hands into their decks. You
    draw 3 cards; your opponent draws 2 cards.
    """
    player_id = action.player_id
    if not _ko_happened_last_turn(state, player_id):
        state.emit_event("unfair_stamp_not_applicable", player=player_id,
                         reason="no_ko_last_turn")
        return

    opp_id = state.opponent_id(player_id)
    for pid, draw_n in ((player_id, 3), (opp_id, 2)):
        p = state.get_player(pid)
        for c in p.hand:
            c.zone = Zone.DECK
            p.deck.append(c)
        p.hand.clear()
        random.shuffle(p.deck)
        draw_cards(state, pid, draw_n)


def _glass_trumpet(state: GameState, action):
    """Glass Trumpet (sv07-135)

    You can use this card only if you have a Tera Pokémon in play. Choose up
    to 2 of your Benched Colorless-type Pokémon. Search your deck for a Basic
    Energy card for each of those Pokémon and attach them. Shuffle your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    # Check condition: must have a Tera Pokémon in play
    if not any(_is_tera(p) for p in _find_in_play(player)):
        state.emit_event("glass_trumpet_not_applicable", player=player_id,
                         reason="no_tera_in_play")
        return

    colorless_bench = [b for b in player.bench if _pokemon_has_type(b, "Colorless")]
    if not colorless_bench:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Glass Trumpet: choose up to 2 Benched Colorless Pokémon to attach energy to",
        cards=colorless_bench, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in colorless_bench[:2]])

    for iid in chosen_ids[:2]:
        poke = next((b for b in player.bench if b.instance_id == iid), None)
        if poke is None:
            continue
        energy_in_deck = [c for c in player.deck if _is_basic_energy_card(c)]
        if not energy_in_deck:
            break
        energy_card = energy_in_deck[0]
        player.deck.remove(energy_card)
        att = _make_energy_attachment(energy_card)
        energy_card.zone = poke.zone
        poke.energy_attached.append(att)
        state.emit_event("energy_attached", player=player_id,
                         energy=energy_card.card_name,
                         target=poke.card_name, source="glass_trumpet")

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="glass_trumpet")


def _ns_pp_up(state: GameState, action):
    """N's PP Up (sv09-153)

    Choose 1 of your Benched N's Pokémon. Attach a Basic Energy card from your
    discard pile to it.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    ns_bench = [b for b in player.bench if b.card_name.startswith("N's")]
    if not ns_bench:
        return

    basic_energy_discard = [c for c in player.discard if _is_basic_energy_card(c)]
    if not basic_energy_discard:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "N's PP Up: choose a Benched N's Pokémon to attach Basic Energy to",
        targets=ns_bench,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        poke = next((b for b in ns_bench if b.instance_id == resp.target_instance_id), None)
    else:
        poke = ns_bench[0]
    if poke is None:
        return

    energy_card = basic_energy_discard[0]
    att = _make_energy_attachment(energy_card)
    energy_card.zone = poke.zone
    poke.energy_attached.append(att)
    player.discard.remove(energy_card)
    state.emit_event("energy_attached", player=player_id,
                     energy=energy_card.card_name,
                     target=poke.card_name, source="ns_pp_up")


def _energy_recycler(state: GameState, action):
    """Energy Recycler (sv10-164)

    Choose up to 5 Basic Energy cards from your discard pile and shuffle them
    into your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    basic_energy_discard = [c for c in player.discard if _is_basic_energy_card(c)]
    if not basic_energy_discard:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Energy Recycler: choose up to 5 Basic Energy from discard to shuffle into deck",
        cards=basic_energy_discard, min_count=0, max_count=5,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in basic_energy_discard[:5]])

    for iid in chosen_ids[:5]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.DECK
            player.deck.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="energy_recycler")


def _sacred_ash(state: GameState, action):
    """Sacred Ash (sv10-168)

    Choose up to 5 Pokémon from your discard pile and shuffle them into your
    deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    pokemon_discard = [c for c in player.discard if c.card_type.lower() == "pokemon"]
    if not pokemon_discard:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Sacred Ash: choose up to 5 Pokémon from discard to shuffle into deck",
        cards=pokemon_discard, min_count=0, max_count=5,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in pokemon_discard[:5]])

    for iid in chosen_ids[:5]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.DECK
            player.deck.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="sacred_ash")


def _tr_transceiver(state: GameState, action):
    """Team Rocket's Transceiver (sv10-178)

    Search your deck for a Team Rocket's Supporter card, reveal it, and put it
    into your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    tr_supporters_in_deck = [c for c in player.deck
                              if c.card_type.lower() == "trainer"
                              and c.card_subtype.lower() == "supporter"
                              and c.card_name.startswith("Team Rocket's")]
    if not tr_supporters_in_deck:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "TR Transceiver: choose a TR Supporter from your deck",
        cards=tr_supporters_in_deck, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [tr_supporters_in_deck[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tr_transceiver")


# ──────────────────────────────────────────────────────────────────────────────
# Stadiums
# ──────────────────────────────────────────────────────────────────────────────

def _gravity_mountain(state: GameState, action) -> None:
    """Gravity Mountain (sv08-177)

    Each Stage 2 Pokémon in play (both yours and your opponent's) gets -30 HP.
    This is applied when the stadium enters play.
    """
    for pid in ("p1", "p2"):
        p = state.get_player(pid)
        for poke in list(_find_in_play(p)):
            if poke.evolution_stage == 2:
                poke.max_hp = max(0, poke.max_hp - 30)
                poke.current_hp = max(0, poke.current_hp - 30)
                poke.damage_counters += 3
                state.emit_event("gravity_mountain_reduce", player=pid,
                                 card=poke.card_name)
                check_ko(state, poke, pid)
                if state.phase.name == "GAME_OVER":
                    return


def _lively_stadium(state: GameState, action) -> None:
    """Lively Stadium (sv08-180)

    Each Basic Pokémon in play (both yours and your opponent's) gets +30 HP.
    Applied when the stadium enters play.
    """
    for pid in ("p1", "p2"):
        p = state.get_player(pid)
        for poke in list(_find_in_play(p)):
            if poke.evolution_stage == 0:
                poke.max_hp += 30
                poke.current_hp += 30
                state.emit_event("lively_stadium_boost", player=pid,
                                 card=poke.card_name)


def _tr_factory_on_play(state: GameState, action) -> None:
    """Team Rocket's Factory (sv10-173) — on-play effect.

    When this Stadium comes into play, if the player who played it has already
    used a TR Supporter this turn, draw 2 cards.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if player.tr_supporter_played_this_turn:
        draw_cards(state, player_id, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

def _hero_cape(state: GameState, action) -> None:
    """Hero's Cape (sv05-152)

    The Pokémon this card is attached to gets +100 HP.
    Applied when the Tool is attached.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    # action.target_instance_id is the Pokémon the tool was attached to
    poke = _find_pokemon_in_play(player, action.target_instance_id)
    if poke is None:
        return
    poke.max_hp += 100
    poke.current_hp += 100
    state.emit_event("hero_cape_attached", player=player_id,
                     card=poke.card_name, hp_bonus=100)


# ──────────────────────────────────────────────────────────────────────────────
# Mega Signal
# ──────────────────────────────────────────────────────────────────────────────

def _mega_signal(state: GameState, action):
    """me01-121 Mega Signal — search deck for a Mega Evolution Pokémon ex, put it in hand."""
    player_id = action.player_id
    player = state.get_player(player_id)

    def _is_mega_ex(card) -> bool:
        cdef = card_registry.get(card.card_def_id)
        return bool(
            cdef
            and cdef.is_ex
            and cdef.name
            and cdef.name.lower().startswith("mega ")
        )

    targets = [c for c in player.deck if c.card_type.lower() == "pokemon" and _is_mega_ex(c)]
    if not targets:
        random.shuffle(player.deck)
        state.emit_event("shuffle_deck", player=player_id, reason="mega_signal_no_target")
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Mega Signal: choose a Mega Evolution Pokémon ex from your deck",
        cards=targets, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [targets[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            state.emit_event("search_to_hand", player=player_id, card=card.card_name,
                             reason="mega_signal")

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="mega_signal")


# ──────────────────────────────────────────────────────────────────────────────
# Batch 18 trainers
# ──────────────────────────────────────────────────────────────────────────────

def _crushing_hammer_b18(state: GameState, action):
    """Crushing Hammer (me03-071)

    Flip a coin. If heads, choose 1 Energy attached to 1 of your opponent's
    Pokémon and discard it.
    """
    player_id = action.player_id
    opp = state.get_player(state.opponent_id(player_id))

    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Crushing Hammer", heads=int(heads))
    if not heads:
        return

    options: list[tuple] = []
    for poke in _find_in_play(opp):
        for att in poke.energy_attached:
            options.append((poke, att))

    if not options:
        return

    labels = [f"{att.card_def_id} on {poke.card_name}" for poke, att in options]
    req = ChoiceRequest(
        "choose_option", player_id,
        "Crushing Hammer: choose an Energy to discard from opponent's Pokémon",
        options=labels,
    )
    resp = yield req
    opt = (resp.selected_option if (resp is not None and resp.selected_option is not None) else 0)
    if opt < len(options):
        poke, att = options[opt]
        poke.energy_attached.remove(att)
        state.emit_event("energy_discarded", player=player_id,
                         card_def_id=att.card_def_id, pokemon=poke.card_name,
                         reason="crushing_hammer")


def _energy_search_b18(state: GameState, action):
    """Energy Search (me03-072)

    Search your deck for a Basic Energy card, reveal it, and put it into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = [c for c in player.deck if _is_basic_energy_card(c)]
    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Energy Search: choose a Basic Energy card from your deck",
        cards=candidates, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="energy_search")


def _hole_digging_shovel_b18(state: GameState, action):
    """Hole-Digging Shovel (me03-074)

    Discard the top 2 cards of your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    for _ in range(2):
        if not player.deck:
            break
        card = player.deck.pop(0)
        card.zone = Zone.DISCARD
        player.discard.append(card)
        state.emit_event("card_discarded", player=player_id, card=card.card_name,
                         reason="hole_digging_shovel")


def _jacinthe_b18(state: GameState, action):
    """Jacinthe (me03-075)

    Choose 1 of your Psychic-type Pokémon. Heal 150 damage from it.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    targets = [p for p in _find_in_play(player) if _pokemon_has_type(p, "Psychic")]
    if not targets:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Jacinthe: choose a Psychic-type Pokémon to heal 150 damage",
        targets=targets,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = _find_pokemon_in_play(player, resp.target_instance_id)
        if target not in targets:
            target = targets[0]
    else:
        target = targets[0]

    if target:
        heal = min(150, target.max_hp - target.current_hp)
        target.current_hp += heal
        target.damage_counters = max(0, target.damage_counters - heal // 10)
        state.emit_event("heal", player=player_id, pokemon=target.card_name,
                         amount=heal, source="jacinthe")


def _lumiose_galette_b18(state: GameState, action):
    """Lumiose Galette (me03-078)

    Heal 20 damage from your Active Pokémon. Then, remove 1 Special Condition
    from your Active Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.active:
        return

    heal = min(20, player.active.max_hp - player.active.current_hp)
    player.active.current_hp += heal
    player.active.damage_counters = max(0, player.active.damage_counters - heal // 10)
    if player.active.status_conditions:
        cond = next(iter(player.active.status_conditions))
        player.active.status_conditions.discard(cond)
    state.emit_event("heal", player=player_id, pokemon=player.active.card_name,
                     amount=heal, source="lumiose_galette")


def _naveen_b18(state: GameState, action):
    """Naveen (me03-079)

    You may discard any number of cards from your hand. Then, draw cards
    until you have 5 cards in your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if player.hand:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Naveen: discard any cards from your hand (optional)",
            cards=list(player.hand), min_count=0, max_count=len(player.hand),
        )
        resp = yield req
        chosen_ids = resp.selected_cards if (resp and resp.selected_cards) else []

        for iid in chosen_ids:
            card = next((c for c in player.hand if c.instance_id == iid), None)
            if card:
                player.hand.remove(card)
                card.zone = Zone.DISCARD
                player.discard.append(card)

    to_draw = max(0, 5 - len(player.hand))
    if to_draw > 0:
        draw_cards(state, player_id, to_draw)


def _poke_ball_b18(state: GameState, action):
    """Poké Ball (me03-080)

    Flip a coin. If heads, search your deck for a Pokémon and put it into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Poké Ball", heads=int(heads))
    if not heads:
        return

    candidates = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Poké Ball: choose a Pokémon from your deck",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="poke_ball")


def _pokemon_catcher_b18(state: GameState, action):
    """Pokémon Catcher (me03-082)

    Flip a coin. If heads, switch 1 of your opponent's Benched Pokémon with
    their Active Pokémon.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Pokémon Catcher", heads=int(heads))
    if not heads:
        return

    if not opp.bench:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Pokémon Catcher: choose an opponent's Benched Pokémon to bring Active",
        targets=list(opp.bench),
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = next((b for b in opp.bench
                       if b.instance_id == resp.target_instance_id), None)
    else:
        target = opp.bench[0]

    if target:
        _switch_active_with_bench(opp, target)
        state.emit_event("pokemon_catcher", player=player_id, forced_active=target.card_name)


def _potion_b18(state: GameState, action):
    """Potion (me03-083)

    Heal 30 damage from 1 of your Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    in_play = _find_in_play(player)
    if not in_play:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Potion: choose a Pokémon to heal 30 damage",
        targets=in_play,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = _find_pokemon_in_play(player, resp.target_instance_id)
    else:
        target = player.active

    if target:
        heal = min(30, target.max_hp - target.current_hp)
        target.current_hp += heal
        target.damage_counters = max(0, target.damage_counters - heal // 10)
        state.emit_event("heal", player=player_id, pokemon=target.card_name,
                         amount=heal, source="potion")


def _iris_b18(state: GameState, action):
    """Iris (me02.5-190)

    Discard 1 card from your hand. Then, draw cards until you have 6 cards
    in your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.hand:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Iris: discard 1 card from your hand",
        cards=list(player.hand), min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [player.hand[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    to_draw = max(0, 6 - len(player.hand))
    if to_draw > 0:
        draw_cards(state, player_id, to_draw)


def _surfer_b18(state: GameState, action):
    """Surfer (me02.5-200)

    Switch your Active Pokémon with 1 of your Benched Pokémon. Then, draw
    cards until you have 5 cards in your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if player.bench:
        req = ChoiceRequest(
            "choose_target", player_id,
            "Surfer: choose a Benched Pokémon to switch in as your Active",
            targets=list(player.bench),
        )
        resp = yield req
        if resp and resp.target_instance_id:
            target = next((b for b in player.bench
                           if b.instance_id == resp.target_instance_id), None)
        else:
            target = player.bench[0]

        if target:
            _switch_active_with_bench(player, target)
            state.emit_event("switch", player=player_id, new_active=target.card_name,
                             source="surfer")

    to_draw = max(0, 5 - len(player.hand))
    if to_draw > 0:
        draw_cards(state, player_id, to_draw)


def _tr_great_ball_b18(state: GameState, action):
    """Team Rocket's Great Ball (me02.5-205)

    Flip a coin. If heads, search your deck for a Team Rocket's Evolution Pokémon
    (excluding Pokémon ex) and put it into your hand. If tails, search for a
    Team Rocket's Basic Pokémon. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Team Rocket's Great Ball", heads=int(heads))

    if heads:
        candidates = [c for c in player.deck
                      if c.card_type.lower() == "pokemon"
                      and c.evolution_stage > 0
                      and "team rocket" in c.card_name.lower()
                      and not _is_pokemon_ex(c)]
        prompt = "Team Rocket's Great Ball: choose a TR Evolution Pokémon (non-ex) from your deck"
    else:
        candidates = [c for c in player.deck
                      if c.card_type.lower() == "pokemon"
                      and c.evolution_stage == 0
                      and "team rocket" in c.card_name.lower()]
        prompt = "Team Rocket's Great Ball: choose a TR Basic Pokémon from your deck"

    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest("choose_cards", player_id, prompt,
                        cards=candidates, min_count=0, max_count=1)
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tr_great_ball")


def _draw_3_b18(state: GameState, action):
    """Urbain / Cheren (me02.5-214, sv10.5w-081)

    Draw 3 cards.
    """
    draw_cards(state, action.player_id, 3)


def _waitress_b18(state: GameState, action):
    """Waitress (me02.5-215)

    Look at the top 6 cards of your deck. You may attach a Basic Energy card
    you find there to 1 of your Pokémon. Shuffle the other cards back in.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    top6 = list(player.deck[:6])
    if not top6:
        return

    energy_candidates = [c for c in top6 if _is_basic_energy_card(c)]
    if not energy_candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Waitress: choose a Basic Energy from top 6 to attach (optional)",
        cards=energy_candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if (resp and resp.selected_cards) else []

    if chosen_ids:
        energy_card = next((c for c in player.deck if c.instance_id == chosen_ids[0]), None)
        if energy_card:
            in_play = _find_in_play(player)
            if in_play:
                req2 = ChoiceRequest(
                    "choose_target", player_id,
                    "Waitress: choose a Pokémon to attach the energy to",
                    targets=in_play,
                )
                resp2 = yield req2
                if resp2 and resp2.target_instance_id:
                    target = _find_pokemon_in_play(player, resp2.target_instance_id)
                else:
                    target = player.active

                if target:
                    player.deck.remove(energy_card)
                    att = _make_energy_attachment(energy_card)
                    target.energy_attached.append(att)
                    state.emit_event("energy_attached", player=player_id,
                                     energy=energy_card.card_name, target=target.card_name,
                                     source="waitress")

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="waitress")


def _blowtorch_b18(state: GameState, action):
    """Blowtorch (me02-086)

    Discard a Basic Fire Energy from your hand. Then, discard 1 of your
    opponent's Pokémon Tool cards, Special Energy cards, or the active Stadium.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp = state.get_player(state.opponent_id(player_id))

    fire_energy = [c for c in player.hand
                   if _is_basic_energy_card(c) and _energy_provides_type(c, "Fire")]
    if not fire_energy:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Blowtorch: discard a Basic Fire Energy from your hand (cost)",
        cards=fire_energy, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [fire_energy[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    options: list[str] = []
    option_actions: list[tuple] = []

    for poke in _find_in_play(opp):
        for tool_def_id in poke.tools_attached:
            options.append(f"Tool {tool_def_id} on {poke.card_name}")
            option_actions.append(("tool", poke, tool_def_id))
        for att in poke.energy_attached:
            if _is_special_energy(att.card_def_id):
                options.append(f"Special Energy {att.card_def_id} on {poke.card_name}")
                option_actions.append(("special_energy", poke, att))

    if state.active_stadium:
        options.append(f"Stadium: {state.active_stadium.card_name}")
        option_actions.append(("stadium", None, None))

    if not options:
        return

    req2 = ChoiceRequest(
        "choose_option", player_id,
        "Blowtorch: choose a Tool, Special Energy, or Stadium to discard",
        options=options,
    )
    resp2 = yield req2
    opt = (resp2.selected_option
           if (resp2 is not None and resp2.selected_option is not None) else 0)

    if opt >= len(option_actions):
        return

    otype, target, data = option_actions[opt]
    if otype == "tool":
        target.tools_attached.remove(data)
        state.emit_event("tool_discarded", player=player_id, tool=data,
                         pokemon=target.card_name, reason="blowtorch")
    elif otype == "special_energy":
        target.energy_attached.remove(data)
        state.emit_event("energy_discarded", player=player_id, card_def_id=data.card_def_id,
                         pokemon=target.card_name, reason="blowtorch")
    elif otype == "stadium":
        state.active_stadium = None
        state.emit_event("stadium_discarded", player=player_id, reason="blowtorch")


def _firebreather_b18(state: GameState, action):
    """Firebreather (me02-089)

    Search your deck for up to 7 Basic Fire Energy cards and put them into
    your hand. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    candidates = [c for c in player.deck
                  if _is_basic_energy_card(c) and _energy_provides_type(c, "Fire")]
    if not candidates:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Firebreather: choose up to 7 Basic Fire Energy cards from your deck",
        cards=candidates, min_count=0, max_count=7,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:7]])

    for iid in chosen_ids[:7]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="firebreather")


def _grimsleys_move_b18(state: GameState, action):
    """Grimsley's Move (me02-090)

    Look at the top 7 cards of your deck. You may put any Darkness-type
    Pokémon you find there onto your Bench. Shuffle the other cards back in.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    bench_space = 5 - len(player.bench)
    top7 = list(player.deck[:7])
    if not top7:
        return

    candidates = [c for c in top7
                  if c.card_type.lower() == "pokemon"
                  and _pokemon_has_type(c, "Darkness")]
    if not candidates or bench_space <= 0:
        random.shuffle(player.deck)
        return

    max_choose = min(len(candidates), bench_space)
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Grimsley's Move: choose Darkness-type Pokémon from top 7 to Bench (optional)",
        cards=candidates, min_count=0, max_count=max_choose,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if (resp and resp.selected_cards) else []

    for iid in chosen_ids:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            _bench_pokemon(state, player_id, card)

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="grimsleys_move")


def _iron_defender_b18(state: GameState, action):
    """Iron Defender (me01-118) — noop stub.

    During your opponent's next turn, each of your Metal-type Pokémon takes
    30 less damage (player-level type-filtered reduction not implemented).
    """
    state.emit_event("flagged_effect", card="Iron Defender",
                     reason="metal_damage_reduction_per_player_not_implemented")


def _pokemon_center_lady_b18(state: GameState, action):
    """Pokémon Center Lady (me01-123)

    Choose 1 of your Pokémon. Heal 60 damage from it and remove all Special
    Conditions from it.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    in_play = _find_in_play(player)
    if not in_play:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Pokémon Center Lady: choose a Pokémon to heal 60 and remove all conditions",
        targets=in_play,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = _find_pokemon_in_play(player, resp.target_instance_id)
    else:
        target = player.active

    if target:
        heal = min(60, target.max_hp - target.current_hp)
        target.current_hp += heal
        target.damage_counters = max(0, target.damage_counters - heal // 10)
        target.status_conditions.clear()
        state.emit_event("heal", player=player_id, pokemon=target.card_name,
                         amount=heal, source="pokemon_center_lady")


def _premium_power_pro_b18(state: GameState, action):
    """Premium Power Pro (me01-124, me02.5-199) — noop stub.

    During this turn, attacks used by each player's Fighting-type Pokémon do
    30 more damage (type-filtered bonus not implemented).
    """
    state.emit_event("flagged_effect", card="Premium Power Pro",
                     reason="fighting_bonus_not_implemented")


def _repel_b18(state: GameState, action):
    """Repel (me01-126)

    Switch your opponent's Active Pokémon with 1 of their Benched Pokémon.
    Your opponent chooses which Benched Pokémon to switch in.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    if not opp.bench:
        return

    req = ChoiceRequest(
        "choose_target", opp_id,
        "Repel: choose a Benched Pokémon to switch in as your Active",
        targets=list(opp.bench),
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = next((b for b in opp.bench
                       if b.instance_id == resp.target_instance_id), None)
    else:
        target = opp.bench[0]

    if target:
        _switch_active_with_bench(opp, target)
        state.emit_event("repel", player=player_id, new_active=target.card_name)


def _switch_b18(state: GameState, action):
    """Switch (me01-130)

    Switch your Active Pokémon with 1 of your Benched Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.bench:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Switch: choose a Benched Pokémon to switch in as your Active",
        targets=list(player.bench),
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = next((b for b in player.bench
                       if b.instance_id == resp.target_instance_id), None)
    else:
        target = player.bench[0]

    if target:
        _switch_active_with_bench(player, target)
        state.emit_event("switch", player=player_id, new_active=target.card_name)


def _wally_b18(state: GameState, action):
    """Wally's Compassion (me01-132) — FLAGGED noop stub.

    Heal all damage from 1 Mega Evolution Pokémon ex and put all its attached
    Energy into your hand (energy-return-to-hand not supported).
    """
    state.emit_event("flagged_effect", card="Wally's Compassion",
                     reason="energy_to_hand_not_supported")


def _energy_coin_b18(state: GameState, action):
    """Energy Coin (sv10.5b-081)

    Flip 2 coins. If both are heads, search your deck for a Basic Energy card
    and attach it to 1 of your Pokémon. Shuffle your deck afterward.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    flips = [random.choice([True, False]) for _ in range(2)]
    state.emit_event("coin_flip_result", card="Energy Coin", heads=sum(flips), flips=2)

    if not all(flips):
        return

    in_play = _find_in_play(player)
    candidates = [c for c in player.deck if _is_basic_energy_card(c)]
    if not candidates or not in_play:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Energy Coin: choose a Basic Energy from your deck to attach",
        cards=candidates, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])

    energy_card = None
    for iid in chosen_ids[:1]:
        energy_card = next((c for c in player.deck if c.instance_id == iid), None)

    if not energy_card:
        random.shuffle(player.deck)
        return

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Energy Coin: choose a Pokémon to attach the energy to",
        targets=in_play,
    )
    resp2 = yield req2
    if resp2 and resp2.target_instance_id:
        target = _find_pokemon_in_play(player, resp2.target_instance_id)
    else:
        target = player.active

    if target:
        player.deck.remove(energy_card)
        att = _make_energy_attachment(energy_card)
        target.energy_attached.append(att)
        state.emit_event("energy_attached", player=player_id,
                         energy=energy_card.card_name, target=target.card_name,
                         source="energy_coin")

    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="energy_coin")


def _fennel_b18(state: GameState, action):
    """Fennel (sv10.5b-082)

    Heal 40 damage from each of your Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    for poke in _find_in_play(player):
        heal = min(40, poke.max_hp - poke.current_hp)
        if heal > 0:
            poke.current_hp += heal
            poke.damage_counters = max(0, poke.damage_counters - heal // 10)
            state.emit_event("heal", player=player_id, pokemon=poke.card_name,
                             amount=heal, source="fennel")


def _ns_plan_b18(state: GameState, action):
    """N's Plan (sv10.5b-083)

    Move up to 2 Energy cards from your Benched Pokémon to your Active Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.active or not player.bench:
        return

    bench_energy: list[tuple] = []
    for poke in player.bench:
        for att in poke.energy_attached:
            bench_energy.append((poke, att))

    if not bench_energy:
        return

    for _ in range(2):
        if not bench_energy:
            break
        labels = [f"{att.card_def_id} on {poke.card_name}" for poke, att in bench_energy]
        req = ChoiceRequest(
            "choose_option", player_id,
            "N's Plan: choose an Energy to move to your Active Pokémon (or Skip)",
            options=labels + ["Skip"],
        )
        resp = yield req
        opt = (resp.selected_option
               if (resp is not None and resp.selected_option is not None)
               else len(bench_energy))
        if opt >= len(bench_energy):
            break
        poke, att = bench_energy[opt]
        poke.energy_attached.remove(att)
        player.active.energy_attached.append(att)
        bench_energy.pop(opt)
        state.emit_event("energy_moved", player=player_id, from_pokemon=poke.card_name,
                         to_pokemon=player.active.card_name, energy=att.card_def_id)


def _harlequin_b18(state: GameState, action):
    """Harlequin (sv10.5w-083)

    Each player shuffles their hand into their deck. Flip a coin.
    Heads: you draw 5 cards and your opponent draws 3.
    Tails: you draw 3 cards and your opponent draws 5.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)

    for pid in (player_id, opp_id):
        p = state.get_player(pid)
        for c in p.hand:
            c.zone = Zone.DECK
            p.deck.append(c)
        p.hand.clear()
        random.shuffle(p.deck)

    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Harlequin", heads=int(heads))

    if heads:
        draw_cards(state, player_id, 5)
        draw_cards(state, opp_id, 3)
    else:
        draw_cards(state, player_id, 3)
        draw_cards(state, opp_id, 5)


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────


# ── Batch 19 Handlers ─────────────────────────────────────────────────────────

def _arvens_sandwich_b19(state: GameState, action):
    """Arven's Sandwich (sv10-161)

    Heal 30 damage from 1 of your Pokémon. If that Pokémon has 'Arven's' in
    its name, heal 100 damage instead.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    in_play = _find_in_play(player)
    if not in_play:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Arven's Sandwich: choose a Pokémon to heal",
        targets=in_play,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = _find_pokemon_in_play(player, resp.target_instance_id)
        if target not in in_play:
            target = in_play[0]
    else:
        target = in_play[0]
    if target is None:
        return
    amount = 100 if "arven's" in target.card_name.lower() else 30
    heal = min(amount, target.max_hp - target.current_hp)
    target.current_hp += heal
    target.damage_counters = max(0, target.damage_counters - heal // 10)
    state.emit_event("heal", player=player_id, pokemon=target.card_name,
                     amount=heal, source="arvens_sandwich")


def _emcees_hype_b19(state: GameState, action):
    """Emcee's Hype (sv10-163)

    Draw 2 cards. If your opponent has 3 or fewer Prize cards remaining,
    draw 2 more.
    """
    player_id = action.player_id
    opp = state.get_player(state.opponent_id(player_id))
    draw_cards(state, player_id, 2)
    if len(opp.prizes) <= 3:
        draw_cards(state, player_id, 2)


def _ethans_adventure_b19(state: GameState, action):
    """Ethan's Adventure (sv10-165)

    Search your deck for up to 3 in any combination of Ethan's Pokémon and
    Basic Fire Energy cards, reveal them, and put them into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    candidates = [
        c for c in player.deck
        if (c.card_type.lower() == "pokemon" and "ethan's" in c.card_name.lower())
        or (_is_basic_energy_card(c) and _energy_provides_type(c, "Fire"))
    ]
    if not candidates:
        random.shuffle(player.deck)
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Ethan's Adventure: choose up to 3 Ethan's Pokémon and/or Basic Fire Energy from deck",
        cards=candidates, min_count=0, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:3]])
    for iid in chosen_ids[:3]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="ethans_adventure")


def _tr_venture_bomb_b19(state: GameState, action):
    """Team Rocket's Venture Bomb (sv10-179)

    Flip a coin. If heads, put 2 damage counters on 1 of your opponent's
    Pokémon. If tails, put 2 damage counters on your Active Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Team Rocket's Venture Bomb",
                     heads=int(heads))
    if heads:
        opp_targets = _find_in_play(opp)
        if not opp_targets:
            return
        req = ChoiceRequest(
            "choose_target", player_id,
            "Team Rocket's Venture Bomb: choose an opponent's Pokémon for 20 damage",
            targets=opp_targets,
        )
        resp = yield req
        if resp and resp.target_instance_id:
            target = _find_pokemon_in_play(opp, resp.target_instance_id)
        else:
            target = opp.active
        if target:
            target.current_hp = max(0, target.current_hp - 20)
            target.damage_counters += 2
            check_ko(state, opp_id, target)
    else:
        if player.active:
            player.active.current_hp = max(0, player.active.current_hp - 20)
            player.active.damage_counters += 2
            check_ko(state, player_id, player.active)


def _tm_machine_b19(state: GameState, action):
    """TM Machine (sv10-181)

    Search your deck for up to 3 Pokémon Tool cards that have 'Technical
    Machine' in their name, reveal them, and put them into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    candidates = [
        c for c in player.deck
        if c.card_type.lower() == "trainer"
        and c.card_subtype.lower() in ("tool", "pokémon tool", "pokemon tool")
        and "technical machine" in c.card_name.lower()
    ]
    if not candidates:
        random.shuffle(player.deck)
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "TM Machine: choose up to 3 Technical Machine Tool cards from your deck",
        cards=candidates, min_count=0, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:3]])
    for iid in chosen_ids[:3]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tm_machine")


def _billy_and_onare_b19(state: GameState, action):
    """Billy & O'Nare (sv09-142)

    Draw 2 cards. Then, if you have 10 or more cards in your hand,
    draw 2 more.
    """
    player_id = action.player_id
    draw_cards(state, player_id, 2)
    if len(state.get_player(player_id).hand) >= 10:
        draw_cards(state, player_id, 2)


def _hops_bag_b19(state: GameState, action):
    """Hop's Bag (sv09-147)

    Search your deck for up to 2 Basic Hop's Pokémon and put them onto
    your Bench.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    bench_space = 5 - len(player.bench)
    if bench_space <= 0:
        random.shuffle(player.deck)
        return
    candidates = [
        c for c in player.deck
        if c.card_type.lower() == "pokemon"
        and c.evolution_stage == 0
        and "hop's" in c.card_name.lower()
    ]
    if not candidates:
        random.shuffle(player.deck)
        return
    max_choose = min(2, bench_space)
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Hop's Bag: choose up to 2 Basic Hop's Pokémon from deck to bench",
        cards=candidates, min_count=0, max_count=max_choose,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:max_choose]])
    for iid in chosen_ids[:max_choose]:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            _bench_pokemon(state, player_id, card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="hops_bag")


def _ruffian_b19(state: GameState, action):
    """Ruffian (sv09-157)

    Discard a Pokémon Tool and a Special Energy from 1 of your opponent's
    Pokémon.
    """
    player_id = action.player_id
    opp = state.get_player(state.opponent_id(player_id))
    targets = [
        p for p in _find_in_play(opp)
        if p.tools_attached
        and any(_is_special_energy(a.card_def_id) for a in p.energy_attached)
    ]
    if not targets:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Ruffian: choose opponent's Pokémon to discard a Tool and Special Energy from",
        targets=targets,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        poke = _find_pokemon_in_play(opp, resp.target_instance_id)
        if poke not in targets:
            poke = targets[0]
    else:
        poke = targets[0]
    if poke is None:
        return
    tool_def_id = poke.tools_attached[0]
    poke.tools_attached.remove(tool_def_id)
    state.emit_event("tool_discarded", player=player_id, tool=tool_def_id,
                     pokemon=poke.card_name, reason="ruffian")
    special_att = next(
        (a for a in poke.energy_attached if _is_special_energy(a.card_def_id)), None
    )
    if special_att:
        poke.energy_attached.remove(special_att)
        state.emit_event("energy_discarded", player=player_id,
                         card_def_id=special_att.card_def_id,
                         pokemon=poke.card_name, reason="ruffian")


def _super_potion_b19(state: GameState, action):
    """Super Potion (sv09-158)

    Heal 60 damage from 1 of your Pokémon. If you healed any damage in this
    way, discard an Energy from that Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    in_play = _find_in_play(player)
    if not in_play:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Super Potion: choose a Pokémon to heal 60 damage",
        targets=in_play,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = _find_pokemon_in_play(player, resp.target_instance_id)
        if target not in in_play:
            target = in_play[0]
    else:
        target = in_play[0]
    if target is None:
        return
    heal = min(60, target.max_hp - target.current_hp)
    target.current_hp += heal
    target.damage_counters = max(0, target.damage_counters - heal // 10)
    state.emit_event("heal", player=player_id, pokemon=target.card_name,
                     amount=heal, source="super_potion")
    if heal > 0 and target.energy_attached:
        req2 = ChoiceRequest(
            "choose_option", player_id,
            "Super Potion: choose an Energy to discard from the healed Pokémon",
            options=[a.card_def_id for a in target.energy_attached],
        )
        resp2 = yield req2
        opt = (resp2.selected_option
               if resp2 is not None and resp2.selected_option is not None else 0)
        if opt < len(target.energy_attached):
            att = target.energy_attached[opt]
            target.energy_attached.remove(att)
            state.emit_event("energy_discarded", player=player_id,
                             card_def_id=att.card_def_id,
                             pokemon=target.card_name, reason="super_potion")


def _carmine_b19(state: GameState, action):
    """Carmine (sv08.5-103)

    Discard your hand and draw 5 cards.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    for c in list(player.hand):
        c.zone = Zone.DISCARD
        player.discard.append(c)
    player.hand.clear()
    draw_cards(state, player_id, 5)


def _ciphermaniacs_codebreaking_b19(state: GameState, action):
    """Ciphermaniac's Codebreaking (sv08.5-104)

    Search your deck for 2 cards, shuffle your deck, then put those 2 cards
    on top of your deck in any order.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_count = min(2, len(player.deck))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Ciphermaniac's Codebreaking: choose 2 cards from your deck to put on top",
        cards=list(player.deck), min_count=0, max_count=take_count,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in player.deck[:take_count]])
    chosen = []
    for iid in chosen_ids[:take_count]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            chosen.append(card)
    random.shuffle(player.deck)
    if len(chosen) == 2:
        req2 = ChoiceRequest(
            "choose_option", player_id,
            "Ciphermaniac's Codebreaking: which card goes on TOP of deck?",
            options=[chosen[0].card_name, chosen[1].card_name],
        )
        resp2 = yield req2
        top_idx = (resp2.selected_option
                   if resp2 is not None and resp2.selected_option is not None else 0)
        if top_idx == 1:
            chosen.reverse()
    for c in reversed(chosen):
        player.deck.insert(0, c)
    state.emit_event("shuffle_deck", player=player_id,
                     reason="ciphermaniacs_codebreaking")


def _explorers_guidance_b19(state: GameState, action):
    """Explorer's Guidance (sv08.5-107)

    Look at the top 6 cards of your deck. Put 2 of them into your hand.
    Discard the other cards.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_n = min(6, len(player.deck))
    top6 = list(player.deck[:take_n])
    player.deck = player.deck[take_n:]
    max_take = min(2, len(top6))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Explorer's Guidance: choose up to 2 cards from top 6 to put into your hand",
        cards=top6, min_count=0, max_count=max_take,
    )
    resp = yield req
    chosen_ids = set(resp.selected_cards if resp and resp.selected_cards else [])
    for card in top6:
        if card.instance_id in chosen_ids:
            card.zone = Zone.HAND
            player.hand.append(card)
        else:
            card.zone = Zone.DISCARD
            player.discard.append(card)


def _lacey_b19(state: GameState, action):
    """Lacey (sv08.5-114, sv07-139)

    Shuffle your hand into your deck. Then, draw 4 cards. If your opponent
    has 3 or fewer Prize cards remaining, draw 8 cards instead.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    opp = state.get_player(state.opponent_id(player_id))
    for c in list(player.hand):
        c.zone = Zone.DECK
        player.deck.append(c)
    player.hand.clear()
    random.shuffle(player.deck)
    draw_count = 8 if len(opp.prizes) <= 3 else 4
    draw_cards(state, player_id, draw_count)


def _max_rod_b19(state: GameState, action):
    """Max Rod (sv08.5-116)

    Put up to 5 in any combination of Pokémon and Basic Energy cards from
    your discard pile into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    candidates = [
        c for c in player.discard
        if c.card_type.lower() == "pokemon" or _is_basic_energy_card(c)
    ]
    if not candidates:
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Max Rod: choose up to 5 Pokémon and/or Basic Energy from discard",
        cards=candidates, min_count=0, max_count=5,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in candidates[:5]])
    for iid in chosen_ids[:5]:
        card = next((c for c in player.discard if c.instance_id == iid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)


def _roto_stick_b19(state: GameState, action):
    """Roto-Stick (sv08.5-127)

    Look at the top 4 cards of your deck. You may put any Supporter cards
    you find there into your hand. Shuffle the other cards back into your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_n = min(4, len(player.deck))
    top4 = list(player.deck[:take_n])
    player.deck = player.deck[take_n:]
    supporters = [
        c for c in top4
        if c.card_type.lower() == "trainer"
        and c.card_subtype.lower() == "supporter"
    ]
    chosen_ids: set = set()
    if supporters:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Roto-Stick: choose Supporter cards from top 4 to put into your hand",
            cards=supporters, min_count=0, max_count=len(supporters),
        )
        resp = yield req
        chosen_ids = set(resp.selected_cards if resp and resp.selected_cards else [])
    for card in top4:
        if card.instance_id in chosen_ids:
            card.zone = Zone.HAND
            player.hand.append(card)
        else:
            player.deck.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="roto_stick")


def _call_bell_b19(state: GameState, action):
    """Call Bell (sv08-165)

    Search your deck for a Supporter card, reveal it, and put it into
    your hand. (Going-second first-turn restriction not enforced.)
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    candidates = [
        c for c in player.deck
        if c.card_type.lower() == "trainer"
        and c.card_subtype.lower() == "supporter"
    ]
    if not candidates:
        random.shuffle(player.deck)
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Call Bell: choose a Supporter card from your deck",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])
    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="call_bell")


def _chill_teaser_toy_b19(state: GameState, action):
    """Chill Teaser Toy (sv08-166)

    Put an Energy attached to 1 of your opponent's Pokémon into their hand.
    (Going-second first-turn restriction not enforced.)
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    targets_with_energy = [p for p in _find_in_play(opp) if p.energy_attached]
    if not targets_with_energy:
        return
    if len(targets_with_energy) == 1:
        poke = targets_with_energy[0]
    else:
        req = ChoiceRequest(
            "choose_target", player_id,
            "Chill Teaser Toy: choose an opponent's Pokémon to take an Energy from",
            targets=targets_with_energy,
        )
        resp = yield req
        if resp and resp.target_instance_id:
            poke = (_find_pokemon_in_play(opp, resp.target_instance_id)
                    or targets_with_energy[0])
        else:
            poke = targets_with_energy[0]
    if not poke.energy_attached:
        return
    if len(poke.energy_attached) > 1:
        req2 = ChoiceRequest(
            "choose_option", player_id,
            "Chill Teaser Toy: choose which Energy to put into opponent's hand",
            options=[a.card_def_id for a in poke.energy_attached],
        )
        resp2 = yield req2
        opt = (resp2.selected_option
               if resp2 is not None and resp2.selected_option is not None else 0)
        att = (poke.energy_attached[opt]
               if opt < len(poke.energy_attached) else poke.energy_attached[0])
    else:
        att = poke.energy_attached[0]
    poke.energy_attached.remove(att)
    cdef = card_registry.get(att.card_def_id)
    if cdef:
        new_card = CardInstance(
            card_def_id=cdef.tcgdex_id,
            card_name=cdef.name,
            card_type=cdef.category,
            card_subtype=cdef.subcategory,
            energy_provides=list(cdef.energy_provides),
            zone=Zone.HAND,
        )
        opp.hand.append(new_card)
    state.emit_event("energy_bounced_to_hand", player=player_id,
                     card_def_id=att.card_def_id, pokemon=poke.card_name,
                     reason="chill_teaser_toy")


def _clemont_b19(state: GameState, action):
    """Clemont's Quick Wit (sv08-167)

    Heal 60 damage from each of your Lightning-type Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    for poke in _find_in_play(player):
        if _pokemon_has_type(poke, "Lightning"):
            heal = min(60, poke.max_hp - poke.current_hp)
            poke.current_hp += heal
            poke.damage_counters = max(0, poke.damage_counters - heal // 10)
            if heal:
                state.emit_event("heal", player=player_id, pokemon=poke.card_name,
                                 amount=heal, source="clemont")


def _deduction_kit_b19(state: GameState, action):
    """Deduction Kit (sv08-171)

    Look at the top 3 cards of your deck and put them back in any order,
    or shuffle them and put them on the bottom of your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_n = min(3, len(player.deck))
    top3 = list(player.deck[:take_n])
    player.deck = player.deck[take_n:]
    req = ChoiceRequest(
        "choose_option", player_id,
        "Deduction Kit: put top cards back in any order, or shuffle to bottom?",
        options=["Keep on top (reorder)", "Shuffle to bottom"],
    )
    resp = yield req
    opt = (resp.selected_option
           if resp is not None and resp.selected_option is not None else 0)
    if opt == 1:
        random.shuffle(top3)
        player.deck.extend(top3)
        return
    # Reorder: player picks card for each position from top
    ordered = []
    remaining = list(top3)
    while len(remaining) > 1:
        req2 = ChoiceRequest(
            "choose_option", player_id,
            f"Deduction Kit: choose card for position {len(ordered) + 1} (top of deck)",
            options=[c.card_name for c in remaining],
        )
        resp2 = yield req2
        idx = (resp2.selected_option
               if resp2 is not None and resp2.selected_option is not None else 0)
        idx = min(idx, len(remaining) - 1)
        ordered.append(remaining.pop(idx))
    ordered.extend(remaining)
    for c in reversed(ordered):
        player.deck.insert(0, c)


def _dragon_elixir_b19(state: GameState, action):
    """Dragon Elixir (sv08-172)

    Heal 60 damage from your Active Dragon-type Pokémon.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if player.active and _pokemon_has_type(player.active, "Dragon"):
        heal = min(60, player.active.max_hp - player.active.current_hp)
        player.active.current_hp += heal
        player.active.damage_counters = max(0,
                                            player.active.damage_counters - heal // 10)
        state.emit_event("heal", player=player_id, pokemon=player.active.card_name,
                         amount=heal, source="dragon_elixir")


def _drasna_b19(state: GameState, action):
    """Drasna (sv08-173)

    Shuffle your hand into your deck. Then, flip a coin. If heads, draw 8.
    If tails, draw 3.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    for c in list(player.hand):
        c.zone = Zone.DECK
        player.deck.append(c)
    player.hand.clear()
    random.shuffle(player.deck)
    heads = random.choice([True, False])
    state.emit_event("coin_flip_result", card="Drasna", heads=int(heads))
    draw_cards(state, player_id, 8 if heads else 3)


def _drayton_b19(state: GameState, action):
    """Drayton (sv08-174)

    Look at the top 7 cards of your deck. You may put 1 Pokémon and 1
    Trainer you find there into your hand. Shuffle the other cards back.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_n = min(7, len(player.deck))
    top7 = list(player.deck[:take_n])
    player.deck = player.deck[take_n:]
    chosen_ids: set = set()
    poke_candidates = [c for c in top7 if c.card_type.lower() == "pokemon"]
    trainer_candidates = [c for c in top7 if c.card_type.lower() == "trainer"]
    if poke_candidates:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Drayton: choose 1 Pokémon from top 7 to put into your hand (optional)",
            cards=poke_candidates, min_count=0, max_count=1,
        )
        resp = yield req
        if resp and resp.selected_cards:
            chosen_ids.update(resp.selected_cards[:1])
    if trainer_candidates:
        req2 = ChoiceRequest(
            "choose_cards", player_id,
            "Drayton: choose 1 Trainer from top 7 to put into your hand (optional)",
            cards=trainer_candidates, min_count=0, max_count=1,
        )
        resp2 = yield req2
        if resp2 and resp2.selected_cards:
            chosen_ids.update(resp2.selected_cards[:1])
    for card in top7:
        if card.instance_id in chosen_ids:
            card.zone = Zone.HAND
            player.hand.append(card)
        else:
            player.deck.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="drayton")


def _dusk_ball_b19(state: GameState, action):
    """Dusk Ball (sv08-175)

    Look at the bottom 7 cards of your deck. You may put 1 Pokémon you find
    there into your hand. Shuffle the other cards back into your deck.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_n = min(7, len(player.deck))
    bottom7 = list(player.deck[-take_n:])
    remaining_deck = list(player.deck[:-take_n])
    poke_candidates = [c for c in bottom7 if c.card_type.lower() == "pokemon"]
    chosen_id = None
    if poke_candidates:
        req = ChoiceRequest(
            "choose_cards", player_id,
            "Dusk Ball: choose 1 Pokémon from bottom 7 to put into your hand (optional)",
            cards=poke_candidates, min_count=0, max_count=1,
        )
        resp = yield req
        if resp and resp.selected_cards:
            chosen_id = resp.selected_cards[0]
    for card in bottom7:
        if card.instance_id == chosen_id:
            card.zone = Zone.HAND
            player.hand.append(card)
        else:
            remaining_deck.append(card)
    random.shuffle(remaining_deck)
    player.deck = remaining_deck
    state.emit_event("shuffle_deck", player=player_id, reason="dusk_ball")


def _lisias_appeal_b19(state: GameState, action):
    """Lisia's Appeal (sv08-179)

    Switch in 1 of your opponent's Benched Basic Pokémon to the Active
    Spot. That Pokémon is now Confused.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    basic_bench = [p for p in opp.bench if p.evolution_stage == 0]
    if not basic_bench:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Lisia's Appeal: choose an opponent's Benched Basic Pokémon to switch in",
        targets=basic_bench,
    )
    resp = yield req
    if resp and resp.target_instance_id:
        target = next(
            (p for p in basic_bench if p.instance_id == resp.target_instance_id), None
        )
    else:
        target = basic_bench[0]
    if target:
        _switch_active_with_bench(opp, target)
        target.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("gust", player=player_id, new_opp_active=target.card_name,
                         source="lisias_appeal")
        state.emit_event("status_inflicted", player=opp_id,
                         card=target.card_name, status="CONFUSED",
                         source="lisias_appeal")


def _meddling_memo_b19(state: GameState, action):
    """Meddling Memo (sv08-181)

    Your opponent counts the cards in their hand, shuffles those cards, and
    puts them on the bottom of their deck. Then they draw that many cards.
    """
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    count = len(opp.hand)
    if count == 0:
        return
    for c in opp.hand:
        c.zone = Zone.DECK
    random.shuffle(opp.hand)
    opp.deck.extend(opp.hand)
    opp.hand.clear()
    draw_cards(state, opp_id, count)
    state.emit_event("meddling_memo", player=player_id, opp_redrew=count)


def _tera_orb_b19(state: GameState, action):
    """Tera Orb (sv08-189)

    Search your deck for a Tera Pokémon, reveal it, and put it into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    candidates = [
        c for c in player.deck
        if c.card_type.lower() == "pokemon" and _is_tera(c)
    ]
    if not candidates:
        random.shuffle(player.deck)
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Tera Orb: choose a Tera Pokémon from your deck",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [candidates[0].instance_id])
    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="tera_orb")


def _kofu_b19(state: GameState, action):
    """Kofu (sv07-138)

    Put 2 cards from your hand on the bottom of your deck. Then draw 4.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if len(player.hand) < 2:
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Kofu: choose 2 cards from your hand to put on the bottom of your deck",
        cards=list(player.hand), min_count=2, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in player.hand[:2]])
    for iid in chosen_ids[:2]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DECK
            player.deck.append(card)
    draw_cards(state, player_id, 4)


def _cassiopeia_b19(state: GameState, action):
    """Cassiopeia (sv06.5-056)

    (Restriction: only usable as last card in hand — not enforced.)
    Search your deck for up to 2 cards and put them into your hand.
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.deck:
        return
    take_count = min(2, len(player.deck))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Cassiopeia: choose up to 2 cards from your deck",
        cards=list(player.deck), min_count=0, max_count=take_count,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [c.instance_id for c in player.deck[:take_count]])
    for iid in chosen_ids[:take_count]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    random.shuffle(player.deck)
    state.emit_event("shuffle_deck", player=player_id, reason="cassiopeia")


def _janines_secret_art_sfa_b19(state: GameState, action):
    """Janine's Secret Art (sv06.5-059)

    Choose up to 2 of your Darkness-type Pokémon. For each, search your deck
    for a Basic Darkness Energy and attach it to that Pokémon. If you attach
    Energy to your Active Pokémon this way, it is now Poisoned.

    (Note: different from sv08.5-112 which benches new Darkness Pokémon.)
    """
    player_id = action.player_id
    player = state.get_player(player_id)
    darkness_pokemon = [p for p in _find_in_play(player)
                        if _pokemon_has_type(p, "Darkness")]
    if not darkness_pokemon:
        return
    dark_energy_in_deck = [c for c in player.deck
                            if _is_basic_energy_card(c)
                            and _energy_provides_type(c, "Darkness")]
    if not dark_energy_in_deck:
        random.shuffle(player.deck)
        return
    max_targets = min(2, len(darkness_pokemon), len(dark_energy_in_deck))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Janine's Secret Art: choose up to 2 Darkness Pokémon to attach Basic Darkness Energy to",
        cards=darkness_pokemon, min_count=0, max_count=max_targets,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [darkness_pokemon[0].instance_id])
    attached_to_active = False
    for iid in chosen_ids[:max_targets]:
        poke = next((p for p in darkness_pokemon if p.instance_id == iid), None)
        if poke is None:
            continue
        energy = next(
            (c for c in player.deck
             if _is_basic_energy_card(c) and _energy_provides_type(c, "Darkness")),
            None,
        )
        if energy is None:
            break
        player.deck.remove(energy)
        att = _make_energy_attachment(energy)
        energy.zone = poke.zone
        poke.energy_attached.append(att)
        state.emit_event("energy_attached", player=player_id,
                         energy=energy.card_name, target=poke.card_name,
                         source="janines_secret_art_sfa")
        if poke is player.active:
            attached_to_active = True
    random.shuffle(player.deck)
    if attached_to_active and player.active:
        player.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_inflicted", player=player_id,
                         card=player.active.card_name, status="POISONED",
                         source="janines_secret_art_sfa")

def register_all(registry: EffectRegistry) -> None:
    """Register all trainer effect handlers."""

    # ── Supporters ──────────────────────────────────────────────────────────
    registry.register_trainer("me01-113", _acerolas_mischief)
    registry.register_trainer("me01-114", _bosss_orders)
    registry.register_trainer("me01-119", _lillies_determination)
    registry.register_trainer("me02-087", _dawn)
    registry.register_trainer("me03-084", _rosas_encouragement)
    registry.register_trainer("me03-085", _tarragon)
    registry.register_trainer("me03-076", _judge)
    registry.register_trainer("sv05-145", _ciphermaniacs_codebreaking)
    registry.register_trainer("sv05-146", _eri)
    registry.register_trainer("sv05-155", _mortys_conviction)
    registry.register_trainer("sv06-154", _kieran)
    registry.register_trainer("sv06-155", _lanas_aid)
    registry.register_trainer("sv06.5-057", _colresss_tenacity)
    registry.register_trainer("sv06.5-064", _xerosics_machinations)
    registry.register_trainer("sv07-132", _briar)
    registry.register_trainer("sv07-133", _crispin)
    registry.register_trainer("sv08.5-105", _crispin)     # Crispin alternate print
    registry.register_trainer("me02.5-183", _bosss_orders)         # Boss's Orders alt print
    registry.register_trainer("me02.5-192", _lillies_determination) # Lillie's Determination alt
    registry.register_trainer("sv08-170", _cyrano)
    registry.register_trainer("sv08.5-112", _janines_secret_art)
    registry.register_trainer("sv08.5-115", _larrys_skill)
    registry.register_trainer("sv09-146", _brocks_scouting)
    registry.register_trainer("sv10-170", _tr_archer)
    registry.register_trainer("sv10-171", _tr_ariana)
    registry.register_trainer("sv10-174", _tr_giovanni)
    registry.register_trainer("sv10-176", _tr_petrel)
    registry.register_trainer("me02.5-207", _tr_petrel)            # Team Rocket's Petrel alt print
    registry.register_trainer("sv10-177", _tr_proton)
    registry.register_trainer("sv10.5w-084", _hilda)

    # ── Items ───────────────────────────────────────────────────────────────
    registry.register_trainer("me01-115", _energy_switch)
    registry.register_trainer("me01-116", _fighting_gong)
    registry.register_trainer("me01-125", _rare_candy)
    registry.register_trainer("me01-131", _ultra_ball)
    registry.register_trainer("me02.5-213", _ultra_ball)          # Ultra Ball alt print
    registry.register_trainer("me02-091", _jumbo_ice_cream)
    registry.register_trainer("me02-094", _wondrous_patch)
    registry.register_trainer("me02.5-196", _night_stretcher)
    registry.register_trainer("sv06.5-061", _night_stretcher)  # Night Stretcher alt print
    registry.register_trainer("me02.5-212", _tool_scrapper)
    registry.register_trainer("me03-081", _poke_pad)
    registry.register_trainer("me02.5-198", _poke_pad)             # Poké Pad alt print
    registry.register_trainer("me01-121", _mega_signal)
    registry.register_trainer("sv09-143", _black_belt_training)
    registry.register_trainer("sv01-171", _energy_retrieval)
    registry.register_trainer("sv01-186", _pokegear)
    registry.register_trainer("sv05-144", _buddy_buddy_poffin)
    registry.register_trainer("me02.5-184", _buddy_buddy_poffin)  # Buddy-Buddy Poffin alt print
    registry.register_trainer("sv05-157", _prime_catcher)
    registry.register_trainer("sv06-143", _bug_catching_set)
    registry.register_trainer("sv08.5-102", _bug_catching_set)  # Bug Catching Set (PE alt)
    registry.register_trainer("sv06-148", _enhanced_hammer)
    registry.register_trainer("sv06-163", _secret_box)
    registry.register_trainer("sv06-165", _unfair_stamp)
    registry.register_trainer("sv07-135", _glass_trumpet)
    registry.register_trainer("sv09-153", _ns_pp_up)
    registry.register_trainer("sv10-164", _energy_recycler)
    registry.register_trainer("sv10-168", _sacred_ash)
    registry.register_trainer("sv10-178", _tr_transceiver)

    # ── Stadiums ────────────────────────────────────────────────────────────
    # Passive stadiums — effects handled elsewhere in the engine
    registry.register_trainer("me01-117", _noop)   # Forest of Vitality (actions.py)
    registry.register_trainer("me01-127", _noop)   # Risky Ruins (transitions.py)
    registry.register_trainer("me02-085", _noop)   # N's Castle (base.py / actions.py)
    registry.register_trainer("sv06-153", _noop)   # Jamming Tower (base.py)
    registry.register_trainer("sv08-177", _gravity_mountain)
    registry.register_trainer("sv08-180", _lively_stadium)
    # Stadiums requiring USE_STADIUM action (not yet implemented — future)
    registry.register_trainer("sv07-131", _noop)   # Area Zero Underdepths
    registry.register_trainer("sv07-136", _noop)   # Grand Tree
    registry.register_trainer("sv09-152", _noop)   # N's Royal Blades
    registry.register_trainer("sv10-169", _noop)   # Spikemuth Gym
    registry.register_trainer("sv10-173", _tr_factory_on_play)
    registry.register_trainer("sv10-180", _noop)   # Watchtower (passive / future)
    registry.register_trainer("me02.5-210", _noop) # Team Rocket's Watchtower alt print
    registry.register_trainer("me02.5-194", _noop) # Mystery Garden (USE_STADIUM — future)

    # ── Tools (passive — effects handled in base.py / registry.py) ──────────
    registry.register_trainer("me02.5-181", _noop)   # Air Balloon
    registry.register_trainer("sv05-152", _hero_cape)
    registry.register_trainer("sv05-154", _noop)    # Maximum Belt (base.py)
    registry.register_trainer("sv07-141", _noop)    # Payapa Berry (base.py)
    registry.register_trainer("sv08.5-095", _noop)  # Binding Mochi (base.py)
    registry.register_trainer("sv09-151", _noop)    # Lillie's Pearl (base.py)
    registry.register_trainer("sv10.5w-080", _noop) # Payapa Berry (base.py)

    # ── Batch 18 registrations ───────────────────────────────────────────────

    # Supporters
    registry.register_trainer("me02.5-180", _acerolas_mischief)       # Acerola's Mischief alt
    registry.register_trainer("me02.5-190", _iris_b18)                # Iris
    registry.register_trainer("me02.5-200", _surfer_b18)              # Surfer
    registry.register_trainer("me02.5-201", _tr_archer)               # TR Archer alt
    registry.register_trainer("me02.5-202", _tr_ariana)               # TR Ariana alt
    registry.register_trainer("me02.5-204", _tr_giovanni)             # TR Giovanni alt
    registry.register_trainer("me02.5-208", _tr_proton)               # TR Proton alt
    registry.register_trainer("me02.5-209", _tr_transceiver)          # TR Transceiver alt
    registry.register_trainer("me02.5-214", _draw_3_b18)              # Urbain
    registry.register_trainer("me02.5-215", _waitress_b18)            # Waitress
    registry.register_trainer("me01-123", _pokemon_center_lady_b18)   # Pokémon Center Lady
    registry.register_trainer("me01-126", _repel_b18)                 # Repel
    registry.register_trainer("me01-132", _wally_b18)                 # Wally's Compassion (flagged)
    registry.register_trainer("sv10.5w-081", _draw_3_b18)             # Cheren
    registry.register_trainer("sv10.5w-083", _harlequin_b18)          # Harlequin

    # Items
    registry.register_trainer("me03-068", _noop)   # Antique Jaw Fossil (fossil mechanic)
    registry.register_trainer("me03-069", _noop)   # Antique Sail Fossil (fossil mechanic)
    registry.register_trainer("me03-070", _noop)   # Core Memory (grants attack to Mega Zygarde ex)
    registry.register_trainer("me03-071", _crushing_hammer_b18)
    registry.register_trainer("me03-072", _energy_search_b18)
    registry.register_trainer("me03-073", _noop)   # Energy Swatter (hand reveal — flagged)
    registry.register_trainer("me03-074", _hole_digging_shovel_b18)
    registry.register_trainer("me03-075", _jacinthe_b18)
    registry.register_trainer("me03-078", _lumiose_galette_b18)
    registry.register_trainer("me03-079", _naveen_b18)
    registry.register_trainer("me03-080", _poke_ball_b18)
    registry.register_trainer("me03-082", _pokemon_catcher_b18)
    registry.register_trainer("me03-083", _potion_b18)
    registry.register_trainer("me02.5-182", _noop)  # Anthea & Concordia (complex passive)
    registry.register_trainer("me02.5-185", _noop)  # Canari ({L} type search + discard cost)
    registry.register_trainer("me02.5-187", _fighting_gong)           # Fighting Gong alt
    registry.register_trainer("me02.5-188", _noop)  # Forest of Vitality alt (passive)
    registry.register_trainer("me02.5-189", _glass_trumpet)           # Glass Trumpet alt
    registry.register_trainer("me02.5-193", _mega_signal)             # Mega Signal alt
    registry.register_trainer("me02.5-195", _ns_pp_up)                # NS PP Up alt
    registry.register_trainer("me02.5-199", _premium_power_pro_b18)   # Premium Power Pro alt
    registry.register_trainer("me02.5-203", _tr_factory_on_play)      # TR Factory alt
    registry.register_trainer("me02.5-205", _tr_great_ball_b18)       # TR Great Ball
    registry.register_trainer("me01-118", _iron_defender_b18)         # Iron Defender (noop)
    registry.register_trainer("me01-120", _noop)   # Lt. Surge's Bargain (opponent decision — flagged)
    registry.register_trainer("me01-122", _noop)   # Mystery Garden alt (passive stadium)
    registry.register_trainer("me01-124", _premium_power_pro_b18)     # Premium Power Pro
    registry.register_trainer("me01-128", _noop)   # Strange Timepiece (devolve — not supported)
    registry.register_trainer("me01-129", _noop)   # Surfing Beach (passive stadium)
    registry.register_trainer("me01-130", _switch_b18)                # Switch
    registry.register_trainer("me02-086", _blowtorch_b18)             # Blowtorch
    registry.register_trainer("me02-088", _noop)   # Dizzying Valley (passive stadium)
    registry.register_trainer("me02-089", _firebreather_b18)          # Firebreather
    registry.register_trainer("me02-090", _grimsleys_move_b18)        # Grimsley's Move
    registry.register_trainer("sv10.5b-079", _noop) # Air Balloon alt (passive tool)
    registry.register_trainer("sv10.5b-080", _noop) # Antique Cover Fossil (fossil mechanic)
    registry.register_trainer("sv10.5b-081", _energy_coin_b18)        # Energy Coin
    registry.register_trainer("sv10.5b-082", _fennel_b18)             # Fennel
    registry.register_trainer("sv10.5b-083", _ns_plan_b18)            # N's Plan
    registry.register_trainer("sv10.5b-084", _pokegear)               # Pokégear 3.0 alt
    registry.register_trainer("sv10.5w-079", _noop) # Antique Plume Fossil (fossil mechanic)
    registry.register_trainer("sv10.5w-082", _energy_retrieval)       # Energy Retrieval alt

    # Tools (passive — handled in base.py)
    registry.register_trainer("me02.5-186", _noop)  # Counter Gain (cost reduction tool)
    registry.register_trainer("me02.5-191", _noop)  # Light Ball (+50 for Pikachu ex)
    registry.register_trainer("me02.5-206", _noop)  # TR Hypnotizer (on-damage Sleep)
    registry.register_trainer("me02.5-211", _noop)  # Thick Scale (-50 type-specific)
    registry.register_trainer("me02-092", _noop)    # Punk Helmet (on-damage 4 counters)
    registry.register_trainer("me02-093", _noop)    # Sacred Charm (-30 from Ability Pokémon)

    # Stadiums (passive — handled elsewhere)
    registry.register_trainer("me03-077", _noop)   # Lumiose City (bench Basic per turn)
    registry.register_trainer("me02.5-197", _noop) # Nighttime Mine (Tera cost +{C})

    # ── Batch 19 registrations ───────────────────────────────────────────────

    # Alt prints reusing existing handlers
    registry.register_trainer("sv10.5w-085", _tool_scrapper)          # Tool Scrapper alt
    registry.register_trainer("sv10-175", _tr_great_ball_b18)         # TR Great Ball alt
    registry.register_trainer("sv09-144", _black_belt_training)       # Black Belt's Training alt
    registry.register_trainer("sv09-145", _black_belt_training)       # Black Belt's Training alt
    registry.register_trainer("sv09-149", _iris_b18)                  # Iris's Fighting Spirit alt
    registry.register_trainer("sv08.5-096", _black_belt_training)     # Black Belt's Training alt
    registry.register_trainer("sv08.5-100", _briar)                   # Briar alt
    registry.register_trainer("sv08.5-101", _buddy_buddy_poffin)      # Buddy-Buddy Poffin alt
    registry.register_trainer("sv08.5-109", _draw_3_b18)              # Friends in Paldea alt
    registry.register_trainer("sv08.5-110", _glass_trumpet)           # Glass Trumpet alt
    registry.register_trainer("sv08.5-113", _kieran)                  # Kieran alt
    registry.register_trainer("sv08-187", _surfer_b18)                # Surfer alt

    # New Supporter handlers
    registry.register_trainer("sv10-163", _emcees_hype_b19)           # Emcee's Hype
    registry.register_trainer("sv10-165", _ethans_adventure_b19)      # Ethan's Adventure
    registry.register_trainer("sv09-142", _billy_and_onare_b19)       # Billy & O'Nare
    registry.register_trainer("sv09-157", _ruffian_b19)               # Ruffian
    registry.register_trainer("sv08.5-103", _carmine_b19)             # Carmine
    registry.register_trainer("sv08.5-107", _explorers_guidance_b19)  # Explorer's Guidance
    registry.register_trainer("sv08.5-114", _lacey_b19)               # Lacey
    registry.register_trainer("sv07-139", _lacey_b19)                 # Lacey alt
    registry.register_trainer("sv08-167", _clemont_b19)               # Clemont's Quick Wit
    registry.register_trainer("sv08-173", _drasna_b19)                # Drasna
    registry.register_trainer("sv08-174", _drayton_b19)               # Drayton
    registry.register_trainer("sv08-179", _lisias_appeal_b19)         # Lisia's Appeal
    registry.register_trainer("sv06.5-056", _cassiopeia_b19)          # Cassiopeia
    registry.register_trainer("sv06.5-059", _janines_secret_art_sfa_b19)  # Janine's Secret Art SFA

    # New Item handlers
    registry.register_trainer("sv10-161", _arvens_sandwich_b19)       # Arven's Sandwich
    registry.register_trainer("sv10-179", _tr_venture_bomb_b19)       # TR Venture Bomb
    registry.register_trainer("sv10-181", _tm_machine_b19)            # TM Machine
    registry.register_trainer("sv09-147", _hops_bag_b19)              # Hop's Bag
    registry.register_trainer("sv09-158", _super_potion_b19)          # Super Potion
    registry.register_trainer("sv08.5-104", _ciphermaniacs_codebreaking_b19)  # Ciphermaniac's Codebreaking
    registry.register_trainer("sv08.5-116", _max_rod_b19)             # Max Rod
    registry.register_trainer("sv08.5-127", _roto_stick_b19)          # Roto-Stick
    registry.register_trainer("sv08-165", _call_bell_b19)             # Call Bell
    registry.register_trainer("sv08-166", _chill_teaser_toy_b19)      # Chill Teaser Toy
    registry.register_trainer("sv08-171", _deduction_kit_b19)         # Deduction Kit
    registry.register_trainer("sv08-172", _dragon_elixir_b19)         # Dragon Elixir
    registry.register_trainer("sv08-175", _dusk_ball_b19)             # Dusk Ball
    registry.register_trainer("sv08-181", _meddling_memo_b19)         # Meddling Memo
    registry.register_trainer("sv08-189", _tera_orb_b19)              # Tera Orb
    registry.register_trainer("sv07-138", _kofu_b19)                  # Kofu

    # Tools (passive — effects handled elsewhere in engine)
    registry.register_trainer("sv10-162", _noop)   # Cynthia's Power Weight (+70HP for Cynthia's Pokémon)
    registry.register_trainer("sv09-148", _noop)   # Hop's Choice Band (damage/cost boost)
    registry.register_trainer("sv08.5-111", _noop) # Haban Berry (type-damage reduction)
    registry.register_trainer("sv08.5-126", _noop) # Rescue Board (retreat cost reduction)
    registry.register_trainer("sv08-163", _noop)   # Babiri Berry (type-damage reduction)
    registry.register_trainer("sv08-168", _noop)   # Colbur Berry (type-damage reduction)
    registry.register_trainer("sv08-169", _noop)   # Counter Gain (cost reduction tool)
    registry.register_trainer("sv08-184", _noop)   # Passho Berry (type-damage reduction)
    registry.register_trainer("sv07-137", _noop)   # Gravity Gemstone (retreat cost +{C})
    registry.register_trainer("sv07-140", _noop)   # Occa Berry (type-damage reduction)
    registry.register_trainer("sv06.5-055", _noop) # Binding Mochi (damage boost when Poisoned)

    # Stadiums (passive — effects handled elsewhere in engine)
    registry.register_trainer("sv10-166", _noop)   # Granite Cave (damage reduction for Steven's Pokémon)
    registry.register_trainer("sv09-154", _noop)   # Postwick (damage boost for Hop's Pokémon)
    registry.register_trainer("sv08.5-094", _noop) # Area Zero Underdepths (Tera bench expansion)
    registry.register_trainer("sv08.5-108", _noop) # Festival Grounds (Special Condition immunity)
    registry.register_trainer("sv06.5-054", _noop) # Academy at Night (per-turn optional topdeck)

    # Fossil Items (fossil mechanic not yet supported)
    registry.register_trainer("sv07-129", _noop)   # Antique Cover Fossil
    registry.register_trainer("sv07-130", _noop)   # Antique Root Fossil

    # Flagged — complex effects not yet modelled in engine
    registry.register_trainer("sv10-172", _noop)   # TR Bother-Bot (face-up prize + hand reveal — flagged)
    registry.register_trainer("sv09-150", _noop)   # Levincia (per-turn energy recovery — flagged)
    registry.register_trainer("sv09-156", _noop)   # Redeemable Ticket (prize zone manipulation — flagged)
    registry.register_trainer("sv08.5-093", _noop) # Amarys (end-of-turn trigger — flagged)
    registry.register_trainer("sv08.5-118", _noop) # Ogre's Mask (Pokémon swap w/ full state transfer — flagged)
    registry.register_trainer("sv08-178", _noop)   # Jasmine's Gaze (cross-turn damage reduction — flagged)
    registry.register_trainer("sv08-188", _noop)   # TM: Fluorite (Tera-wide full heal TM — flagged)
    registry.register_trainer("sv08-190", _noop)   # Tyme (interactive guessing game — flagged)
    registry.register_trainer("sv06.5-063", _noop) # Powerglass (end-of-turn trigger tool — flagged)
