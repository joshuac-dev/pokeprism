from __future__ import annotations

import pytest

from app.cards.models import AttackDef, CardDefinition
from app.coach.deck_builder import DECK_SIZE, DeckBuildError, DeckBuilder


def _pokemon(
    tcgdex_id: str,
    name: str,
    *,
    hp: int = 80,
    stage: str = "Basic",
    evolve_from: str | None = None,
    types: list[str] | None = None,
    damage: str = "60",
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Pokemon",
        stage=stage,
        hp=hp,
        evolve_from=evolve_from,
        types=types or ["Psychic"],
        attacks=[AttackDef(name="Hit", cost=types or ["Psychic"], damage=damage)],
    )


def _trainer(tcgdex_id: str, name: str, subtype: str = "Item") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Trainer",
        subcategory=subtype,
    )


def _energy(tcgdex_id: str, name: str, energy_type: str = "Psychic") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Energy",
        subcategory="Basic",
        energy_provides=[energy_type],
    )


def _pool() -> list[CardDefinition]:
    cards: list[CardDefinition] = [
        _pokemon("tst-001", "Dreepy", hp=70, types=["Psychic"], damage="30"),
        _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1", evolve_from="Dreepy", damage="70"),
        _pokemon("tst-003", "Dragapult ex", hp=230, stage="ex", evolve_from="Drakloak", damage="200"),
        _pokemon("tst-004", "Munkidori", hp=110, types=["Darkness"], damage="90"),
        _pokemon("tst-005", "Fezandipiti ex", hp=210, stage="ex", damage="160"),
        _energy("mee-005", "Psychic Energy", "Psychic"),
        _energy("mee-007", "Darkness Energy", "Darkness"),
    ]
    for i, name in enumerate(
        [
            "Ultra Ball", "Rare Candy", "Boss's Orders", "Nest Ball",
            "Iono", "Switch", "Energy Search", "Night Stretcher",
            "Buddy-Buddy Poffin", "Prime Catcher", "Professor's Research",
            "Super Rod",
        ],
        start=101,
    ):
        cards.append(_trainer(f"trn-{i}", name, "Supporter" if name in {"Iono", "Boss's Orders", "Professor's Research"} else "Item"))
    return cards


def test_complete_deck_preserves_partial_and_fills_to_legal_size():
    pool = _pool()
    partial = [pool[0]] * 4 + [pool[1]] * 2 + [pool[2]] * 2
    result = DeckBuilder(pool, rng_seed=123).complete_deck(partial)

    assert len(result.deck) == DECK_SIZE
    assert result.metadata["mode"] == "partial"
    assert result.metadata["cards_preserved"] == [c.tcgdex_id for c in partial]
    assert not DeckBuilder(pool).validate_deck(result.deck)


def test_complete_deck_rejects_banned_card():
    pool = _pool()
    builder = DeckBuilder(pool, excluded_ids=["tst-001"])

    with pytest.raises(DeckBuildError, match="excluded cards"):
        builder.complete_deck([pool[0]])


def test_complete_deck_rejects_excess_non_energy_copies():
    pool = _pool()
    partial = [pool[0]] * 5

    with pytest.raises(DeckBuildError, match="Too many copies"):
        DeckBuilder(pool).complete_deck(partial)


def test_complete_deck_rejects_unknown_card():
    pool = _pool()
    unknown = _pokemon("bad-999", "Unknownmon")

    with pytest.raises(DeckBuildError, match="outside available pool"):
        DeckBuilder(pool).complete_deck([unknown])


def test_complete_deck_is_deterministic_with_seed():
    pool = _pool()
    partial = [pool[0]] * 2

    first = DeckBuilder(pool, rng_seed=7).complete_deck(partial).deck_text
    second = DeckBuilder(pool, rng_seed=7).complete_deck(partial).deck_text

    assert first == second


def test_build_from_scratch_creates_valid_deck_with_core_metadata():
    pool = _pool()
    result = DeckBuilder(pool, rng_seed=1).build_from_scratch(build_around_ids=["tst-003"])

    assert len(result.deck) == DECK_SIZE
    assert "tst-003" in result.metadata["core_cards"]
    assert not DeckBuilder(pool).validate_deck(result.deck)


def test_build_from_scratch_fails_without_basic_pokemon():
    pool = [_trainer("trn-200", "Ultra Ball"), _energy("mee-005", "Psychic Energy")]

    with pytest.raises(DeckBuildError, match="no Basic Pokémon"):
        DeckBuilder(pool).build_from_scratch()


def test_build_from_scratch_respects_exclusions():
    pool = _pool()
    result = DeckBuilder(pool, excluded_ids=["tst-003"], rng_seed=2).build_from_scratch()

    assert "tst-003" not in [c.tcgdex_id for c in result.deck]
    assert not DeckBuilder(pool, excluded_ids=["tst-003"]).validate_deck(result.deck)
