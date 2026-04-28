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
# Registration
# ──────────────────────────────────────────────────────────────────────────────

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
    registry.register_trainer("sv07-141", _noop)    # Binding Mochi (base.py)
    registry.register_trainer("sv08.5-095", _noop)  # Brave Bangle (base.py)
    registry.register_trainer("sv09-151", _noop)    # Lillie's Pearl (base.py)
    registry.register_trainer("sv10.5w-080", _noop) # Payapa Berry (base.py)
