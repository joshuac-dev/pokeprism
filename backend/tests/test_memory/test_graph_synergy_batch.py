"""Unit tests for batched Neo4j synergy pair updates."""

import uuid

import pytest

from app.cards.models import CardDefinition
from app.memory import graph as graph_module
from app.memory.graph import (
    GraphMemoryWriter,
    _build_deck_card_rows,
    _build_synergy_pairs,
    _deck_setup_cache_key,
)


def _card(tcgdex_id: str, name: str | None = None, category: str = "Pokemon") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name or tcgdex_id,
        set_abbrev="TST",
        set_number="1",
        category=category,
    )


def test_build_synergy_pairs_ignores_duplicate_copies():
    pairs = _build_synergy_pairs([
        _card("a"),
        _card("a"),
        _card("b"),
        _card("c"),
    ])

    assert pairs == [
        {"id_a": "a", "id_b": "b"},
        {"id_a": "a", "id_b": "c"},
        {"id_a": "b", "id_b": "c"},
    ]


def test_build_synergy_pairs_is_deterministic_for_input_order():
    ordered = [_card("a"), _card("b"), _card("c"), _card("d")]
    shuffled = [_card("d"), _card("b"), _card("a"), _card("c")]

    assert _build_synergy_pairs(shuffled) == _build_synergy_pairs(ordered)


def test_build_synergy_pairs_returns_empty_for_fewer_than_two_unique_cards():
    assert _build_synergy_pairs([]) == []
    assert _build_synergy_pairs([_card("a")]) == []
    assert _build_synergy_pairs([_card("a"), _card("a")]) == []


class FakeSession:
    def __init__(self):
        self.calls = []

    async def run(self, query, **params):
        self.calls.append((query, params))


def test_build_deck_card_rows_counts_duplicates_deterministically():
    first = [
        _card("b", name="Beta", category="Trainer"),
        _card("a", name="Alpha"),
        _card("b", name="Beta", category="Trainer"),
        _card("c", name="Gamma", category="Energy"),
    ]
    second = [
        _card("c", name="Gamma", category="Energy"),
        _card("b", name="Beta", category="Trainer"),
        _card("a", name="Alpha"),
        _card("b", name="Beta", category="Trainer"),
    ]

    expected = [
        {"tcgdex_id": "a", "name": "Alpha", "category": "Pokemon", "quantity": 1},
        {"tcgdex_id": "b", "name": "Beta", "category": "Trainer", "quantity": 2},
        {"tcgdex_id": "c", "name": "Gamma", "category": "Energy", "quantity": 1},
    ]
    assert _build_deck_card_rows(first) == expected
    assert _build_deck_card_rows(second) == expected


def test_deck_setup_cache_key_is_deterministic_for_card_order():
    deck_id = uuid.uuid4()
    first = [_card("b"), _card("a"), _card("b")]
    second = [_card("b"), _card("b"), _card("a")]

    assert (
        _deck_setup_cache_key(deck_id, "Deck", first)
        == _deck_setup_cache_key(deck_id, "Deck", second)
    )


@pytest.mark.asyncio
async def test_ensure_deck_nodes_batches_card_and_belongs_to_merges():
    session = FakeSession()
    writer = GraphMemoryWriter()
    deck_id = uuid.uuid4()

    await writer._ensure_deck_nodes(
        session,
        deck_id,
        "Batch Deck",
        [_card("a"), _card("b"), _card("b"), _card("c")],
    )

    assert len(session.calls) == 3
    deck_query, deck_params = session.calls[0]
    card_query, card_params = session.calls[1]
    belongs_query, belongs_params = session.calls[2]
    assert "MERGE (d:Deck" in deck_query
    assert deck_params == {"deck_id": str(deck_id), "name": "Batch Deck"}
    assert "UNWIND $cards AS card" in card_query
    assert "MERGE (c:Card" in card_query
    assert "UNWIND $cards AS card" in belongs_query
    assert "MERGE (c)-[r:BELONGS_TO]->(d)" in belongs_query
    assert card_params["cards"] == [
        {"tcgdex_id": "a", "name": "a", "category": "Pokemon", "quantity": 1},
        {"tcgdex_id": "b", "name": "b", "category": "Pokemon", "quantity": 2},
        {"tcgdex_id": "c", "name": "c", "category": "Pokemon", "quantity": 1},
    ]
    assert belongs_params["cards"] == card_params["cards"]
    assert belongs_params["deck_id"] == str(deck_id)


@pytest.mark.asyncio
async def test_ensure_deck_nodes_once_skips_repeated_deck_setup():
    session = FakeSession()
    writer = GraphMemoryWriter()
    deck_id = uuid.uuid4()
    cards = [_card("a"), _card("b"), _card("b")]

    await writer._ensure_deck_nodes_once(session, deck_id, "Cached Deck", cards)
    await writer._ensure_deck_nodes_once(session, deck_id, "Cached Deck", list(reversed(cards)))

    assert len(session.calls) == 3


@pytest.mark.asyncio
async def test_ensure_deck_nodes_once_does_not_cache_failed_setup(monkeypatch):
    session = FakeSession()
    writer = GraphMemoryWriter()
    deck_id = uuid.uuid4()
    cards = [_card("a"), _card("b")]
    calls = {"n": 0}

    async def failing_once(_session, _deck_id, _deck_name, _card_defs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(writer, "_ensure_deck_nodes", failing_once)

    with pytest.raises(RuntimeError):
        await writer._ensure_deck_nodes_once(session, deck_id, "Retry Deck", cards)
    await writer._ensure_deck_nodes_once(session, deck_id, "Retry Deck", cards)

    assert calls["n"] == 2
    assert _deck_setup_cache_key(deck_id, "Retry Deck", cards) in writer._ensured_decks


@pytest.mark.asyncio
async def test_update_synergies_writes_once_per_chunk(monkeypatch):
    monkeypatch.setattr(graph_module, "_SYNERGY_PAIR_CHUNK_SIZE", 2)
    session = FakeSession()
    writer = GraphMemoryWriter()

    await writer._update_synergies(
        session,
        [_card("a"), _card("b"), _card("c"), _card("d")],
        won=True,
    )

    assert len(session.calls) == 3
    assert [len(params["pairs"]) for _query, params in session.calls] == [2, 2, 2]


@pytest.mark.asyncio
async def test_update_synergies_uses_positive_delta_for_wins():
    session = FakeSession()
    writer = GraphMemoryWriter()

    await writer._update_synergies(session, [_card("a"), _card("b")], won=True)

    assert len(session.calls) == 1
    assert session.calls[0][1]["delta"] == 1.0


@pytest.mark.asyncio
async def test_update_synergies_uses_negative_delta_for_losses():
    session = FakeSession()
    writer = GraphMemoryWriter()

    await writer._update_synergies(session, [_card("a"), _card("b")], won=False)

    assert len(session.calls) == 1
    assert session.calls[0][1]["delta"] == -0.5


@pytest.mark.asyncio
async def test_update_synergies_skips_writes_for_no_pairs():
    session = FakeSession()
    writer = GraphMemoryWriter()

    await writer._update_synergies(session, [_card("a"), _card("a")], won=True)

    assert session.calls == []
