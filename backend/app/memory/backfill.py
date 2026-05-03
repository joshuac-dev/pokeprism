"""Backfill utilities for historical memory aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card, CardPerformance, Deck, DeckCard, Match, Round, Simulation
from app.tasks.simulation import _parse_deck_text, _parse_ptcgl_deck_text


@dataclass
class CardPerformanceBackfillResult:
    deck_cards_inserted: int
    matches_processed: int
    card_performance_rows: int


async def backfill_card_performance(db: AsyncSession) -> CardPerformanceBackfillResult:
    """Rebuild ``card_performance`` from stored matches and deck metadata.

    The simulation API historically created ``decks`` without ``deck_cards``.
    This backfill first populates missing ``deck_cards`` from stored deck text,
    then deletes and rebuilds ``card_performance`` from all persisted matches.
    P1 cards come from each round snapshot when available so coached deck
    changes are represented; P2 cards come from the match's opponent deck.
    """
    deck_cards_inserted = await populate_missing_deck_cards(db)
    await db.execute(delete(CardPerformance))

    deck_cache: dict[UUID, set[str]] = {}
    rows = (await db.execute(
        select(Match, Round.deck_snapshot, Simulation.user_deck_id)
        .join(Round, Match.round_id == Round.id)
        .join(Simulation, Match.simulation_id == Simulation.id)
        .order_by(Match.created_at, Match.id)
    )).all()

    matches_processed = 0
    for match, deck_snapshot, user_deck_id in rows:
        p1_cards = _card_ids_from_round_snapshot(deck_snapshot)
        if not p1_cards and user_deck_id:
            p1_cards = await _deck_card_ids(db, user_deck_id, deck_cache)
        p2_cards = (
            await _deck_card_ids(db, match.opponent_deck_id, deck_cache)
            if match.opponent_deck_id
            else set()
        )

        await _upsert_performance(
            db,
            p1_cards,
            games_won=1 if match.winner == "p1" else 0,
        )
        await _upsert_performance(
            db,
            p2_cards,
            games_won=1 if match.winner == "p2" else 0,
        )
        matches_processed += 1

    card_performance_rows = (await db.execute(
        select(CardPerformance.card_tcgdex_id)
    )).scalars().all()
    await db.flush()
    return CardPerformanceBackfillResult(
        deck_cards_inserted=deck_cards_inserted,
        matches_processed=matches_processed,
        card_performance_rows=len(card_performance_rows),
    )


async def populate_missing_deck_cards(db: AsyncSession) -> int:
    """Populate ``deck_cards`` for decks that have stored text but no cards."""
    decks = (await db.execute(select(Deck))).scalars().all()
    inserted = 0
    for deck in decks:
        exists = (await db.execute(
            select(DeckCard.deck_id).where(DeckCard.deck_id == deck.id).limit(1)
        )).scalar_one_or_none()
        if exists is not None:
            continue

        counts = await _card_counts_from_deck_text(db, deck.deck_text or "")
        if not counts:
            continue

        db.add_all(
            DeckCard(deck_id=deck.id, card_tcgdex_id=card_id, quantity=qty)
            for card_id, qty in counts.items()
        )
        inserted += len(counts)
    await db.flush()
    return inserted


async def _card_counts_from_deck_text(db: AsyncSession, deck_text: str) -> dict[str, int]:
    tcgdex_entries = _parse_deck_text(deck_text)
    if tcgdex_entries:
        known_ids = set((await db.execute(
            select(Card.tcgdex_id).where(
                Card.tcgdex_id.in_([card_id for _, card_id in tcgdex_entries])
            )
        )).scalars().all())
        counts: dict[str, int] = {}
        for qty, card_id in tcgdex_entries:
            if card_id in known_ids:
                counts[card_id] = counts.get(card_id, 0) + qty
        return counts

    ptcgl_entries = _parse_ptcgl_deck_text(deck_text)
    if not ptcgl_entries:
        return {}

    abbrevs = {entry["set_abbrev"] for entry in ptcgl_entries}
    cards = (await db.execute(
        select(Card).where(Card.set_abbrev.in_(abbrevs))
    )).scalars().all()
    by_key = {
        (card.set_abbrev, _normalise_set_number(card.set_number)): card.tcgdex_id
        for card in cards
    }
    counts: dict[str, int] = {}
    for entry in ptcgl_entries:
        key = (entry["set_abbrev"], _normalise_set_number(entry["set_number"]))
        card_id = by_key.get(key)
        if card_id:
            counts[card_id] = counts.get(card_id, 0) + int(entry["count"])
    return counts


def _card_ids_from_round_snapshot(deck_snapshot: Any) -> set[str]:
    if not isinstance(deck_snapshot, dict):
        return set()
    cards = deck_snapshot.get("cards")
    if not isinstance(cards, list):
        return set()
    ids: set[str] = set()
    for item in cards:
        if isinstance(item, dict) and isinstance(item.get("tcgdex_id"), str):
            ids.add(item["tcgdex_id"])
    return ids


async def _deck_card_ids(
    db: AsyncSession,
    deck_id: UUID,
    cache: dict[UUID, set[str]],
) -> set[str]:
    if deck_id not in cache:
        cache[deck_id] = set((await db.execute(
            select(DeckCard.card_tcgdex_id).where(DeckCard.deck_id == deck_id)
        )).scalars().all())
    return cache[deck_id]


async def _upsert_performance(
    db: AsyncSession,
    card_ids: set[str],
    games_won: int,
) -> None:
    if not card_ids:
        return
    upsert_sql = text(
        "INSERT INTO card_performance (card_tcgdex_id, games_included, games_won) "
        "VALUES (:card_id, 1, :games_won) "
        "ON CONFLICT (card_tcgdex_id) DO UPDATE SET "
        "games_included = card_performance.games_included + 1, "
        "games_won = card_performance.games_won + EXCLUDED.games_won, "
        "updated_at = now()"
    )
    for card_id in card_ids:
        await db.execute(upsert_sql, {"card_id": card_id, "games_won": games_won})


def _normalise_set_number(value: str | None) -> str:
    if value and value.isdigit():
        return str(int(value))
    return value or ""
