"""Write match results and events to PostgreSQL."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card, Deck, DeckCard, Match, MatchEvent, Round, Simulation

if TYPE_CHECKING:
    from app.engine.runner import MatchResult
    from app.cards.models import CardDefinition

_CHUNK = 500  # batch-insert match_events in chunks of this size


class MatchMemoryWriter:
    """Persists a single match (result + events) to PostgreSQL.

    Usage::

        async with AsyncSessionLocal() as db:
            writer = MatchMemoryWriter()
            match_id = await writer.write_match(result, simulation_id, round_id, 1, db)
            await db.commit()
    """

    async def ensure_cards(
        self,
        card_defs: list[CardDefinition],
        db: AsyncSession,
    ) -> None:
        """Upsert card definitions into the `cards` table (idempotent)."""
        existing = {
            row[0]
            for row in (
                await db.execute(
                    select(Card.tcgdex_id).where(
                        Card.tcgdex_id.in_([c.tcgdex_id for c in card_defs])
                    )
                )
            ).all()
        }
        new_cards = [
            Card(
                tcgdex_id=c.tcgdex_id,
                name=c.name,
                set_abbrev=c.set_abbrev,
                set_number=c.set_number,
                category=c.category,
                subcategory=getattr(c, "subcategory", None),
                hp=getattr(c, "hp", None),
                types=getattr(c, "types", []),
                evolve_from=getattr(c, "evolve_from", None),
                stage=getattr(c, "stage", None),
                attacks=[a.__dict__ if hasattr(a, "__dict__") else a
                         for a in getattr(c, "attacks", [])],
                abilities=[a.__dict__ if hasattr(a, "__dict__") else a
                           for a in getattr(c, "abilities", [])],
                weaknesses=getattr(c, "weaknesses", []),
                resistances=getattr(c, "resistances", []),
                retreat_cost=getattr(c, "retreat_cost", 0),
                regulation_mark=getattr(c, "regulation_mark", None),
                rarity=getattr(c, "rarity", None),
                image_url=getattr(c, "image_url", None),
            )
            for c in card_defs
            if c.tcgdex_id not in existing
        ]
        if new_cards:
            db.add_all(new_cards)
            await db.flush()

    async def ensure_deck(
        self,
        deck_name: str,
        card_defs: list[CardDefinition],
        db: AsyncSession,
    ) -> uuid.UUID:
        """Upsert a deck (by name) and return its UUID."""
        result = await db.execute(select(Deck).where(Deck.name == deck_name))
        deck = result.scalar_one_or_none()
        if deck is None:
            counts: dict[str, int] = {}
            for c in card_defs:
                counts[c.tcgdex_id] = counts.get(c.tcgdex_id, 0) + 1
            deck_text = "\n".join(
                f"{qty} {tid}" for tid, qty in sorted(counts.items())
            )
            deck = Deck(
                name=deck_name,
                archetype=deck_name,
                deck_text=deck_text,
                card_count=len(card_defs),
                source="simulation",
            )
            db.add(deck)
            await db.flush()
            deck_cards = [
                DeckCard(deck_id=deck.id, card_tcgdex_id=tid, quantity=qty)
                for tid, qty in counts.items()
            ]
            db.add_all(deck_cards)
            await db.flush()
        return deck.id

    async def ensure_simulation(
        self,
        simulation_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Ensure a simulation row exists for this batch run."""
        result = await db.execute(
            select(Simulation).where(Simulation.id == simulation_id)
        )
        if result.scalar_one_or_none() is None:
            sim = Simulation(
                id=simulation_id,
                status="running",
                game_mode="hh",
                deck_mode="none",
                matches_per_opponent=0,
                num_rounds=1,
                target_win_rate=60,
            )
            db.add(sim)
            await db.flush()

    async def ensure_round(
        self,
        round_id: uuid.UUID,
        simulation_id: uuid.UUID,
        round_number: int,
        deck_snapshot: dict,
        db: AsyncSession,
    ) -> None:
        """Ensure a round row exists."""
        result = await db.execute(select(Round).where(Round.id == round_id))
        if result.scalar_one_or_none() is None:
            rnd = Round(
                id=round_id,
                simulation_id=simulation_id,
                round_number=round_number,
                deck_snapshot=deck_snapshot,
            )
            db.add(rnd)
            await db.flush()

    async def write_match(
        self,
        result: MatchResult,
        simulation_id: uuid.UUID,
        round_id: uuid.UUID,
        round_number: int,
        p1_deck_id: uuid.UUID,
        p2_deck_id: uuid.UUID,
        db: AsyncSession,
    ) -> uuid.UUID:
        """Insert a match row and all its events. Returns the new match UUID."""
        match_id = uuid.uuid4()
        match = Match(
            id=match_id,
            simulation_id=simulation_id,
            round_id=round_id,
            round_number=round_number,
            opponent_deck_id=p2_deck_id,
            winner=result.winner,
            win_condition=result.win_condition,
            total_turns=result.total_turns,
            p1_prizes_taken=result.p1_prizes_taken,
            p2_prizes_taken=result.p2_prizes_taken,
            p1_deck_name=result.p1_deck_name,
            p2_deck_name=result.p2_deck_name,
        )
        db.add(match)
        await db.flush()

        # Bulk-insert events in chunks to keep memory usage bounded.
        events = result.events
        for chunk_start in range(0, len(events), _CHUNK):
            chunk = events[chunk_start: chunk_start + _CHUNK]
            db.add_all(
                MatchEvent(
                    match_id=match_id,
                    sequence=chunk_start + i,
                    event_type=e.get("event_type", "unknown"),
                    turn=e.get("turn"),
                    player=e.get("active_player"),
                    data=e,
                )
                for i, e in enumerate(chunk)
            )
            await db.flush()

        return match_id
