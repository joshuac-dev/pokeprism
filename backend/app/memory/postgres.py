"""Write match results and events to PostgreSQL."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Card, CardPerformance, Deck, DeckCard, DeckMutation,
    Decision, Match, MatchEvent, Round, Simulation,
)

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
                weaknesses=[w.model_dump() if hasattr(w, "model_dump") else
                             (w.__dict__ if hasattr(w, "__dict__") else w)
                             for w in getattr(c, "weaknesses", [])],
                resistances=[r.model_dump() if hasattr(r, "model_dump") else
                              (r.__dict__ if hasattr(r, "__dict__") else r)
                              for r in getattr(c, "resistances", [])],
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
        deck = result.scalars().first()
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

        await self._update_card_performance(result, p1_deck_id, p2_deck_id, db)
        return match_id

    async def _update_card_performance(
        self,
        result: MatchResult,
        p1_deck_id: uuid.UUID,
        p2_deck_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Upsert card_performance rows for both decks after a match."""
        p1_cards = list((await db.execute(
            select(DeckCard.card_tcgdex_id).where(DeckCard.deck_id == p1_deck_id)
        )).scalars().all())
        p2_cards = list((await db.execute(
            select(DeckCard.card_tcgdex_id).where(DeckCard.deck_id == p2_deck_id)
        )).scalars().all())

        winning_cards = p1_cards if result.winner == "p1" else p2_cards
        losing_cards = p2_cards if result.winner == "p1" else p1_cards

        upsert_sql = text(
            "INSERT INTO card_performance (card_tcgdex_id, games_included, games_won) "
            "VALUES (:card_id, 1, :games_won) "
            "ON CONFLICT (card_tcgdex_id) DO UPDATE SET "
            "games_included = card_performance.games_included + 1, "
            "games_won = card_performance.games_won + EXCLUDED.games_won"
        )
        for card_id in winning_cards:
            await db.execute(upsert_sql, {"card_id": card_id, "games_won": 1})
        for card_id in losing_cards:
            await db.execute(upsert_sql, {"card_id": card_id, "games_won": 0})
        await db.flush()

    async def write_decisions(
        self,
        decisions: list[dict],
        match_id: uuid.UUID,
        simulation_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[tuple[uuid.UUID, str | None]]:
        """Bulk-insert AI decision records. Returns list of (id, game_state_summary) for embedding."""
        if not decisions:
            return []
        rows = [
            Decision(
                match_id=match_id,
                simulation_id=simulation_id,
                turn_number=d["turn_number"],
                player_id=d["player_id"],
                action_type=d["action_type"],
                card_played=d.get("card_played"),
                card_def_id=d.get("card_def_id"),
                target=d.get("target"),
                reasoning=d.get("reasoning"),
                legal_action_count=d.get("legal_action_count"),
                game_state_summary=d.get("game_state_summary"),
            )
            for d in decisions
        ]
        db.add_all(rows)
        await db.flush()
        return [(row.id, row.game_state_summary) for row in rows]

    async def write_mutations(
        self,
        mutations: list[dict],
        simulation_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Bulk-insert DeckMutation records produced by the Coach."""
        if not mutations:
            return
        db.add_all(
            DeckMutation(
                simulation_id=simulation_id,
                round_number=m["round_number"],
                card_removed=m["card_removed"],
                card_added=m["card_added"],
                reasoning=m.get("reasoning"),
            )
            for m in mutations
        )
        await db.flush()


class CardPerformanceQueries:
    """Read card performance stats from Postgres for the Coach/Analyst."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_card_performance(
        self, card_ids: list[str]
    ) -> dict[str, dict]:
        """Return performance stats for each card ID.

        Returns a mapping tcgdex_id → {games_included, games_won, win_rate,
        total_kos, total_damage, total_prizes}.  Missing cards get zero stats.
        """
        if not card_ids:
            return {}
        rows = (await self._db.execute(
            select(CardPerformance).where(
                CardPerformance.card_tcgdex_id.in_(card_ids)
            )
        )).scalars().all()

        result: dict[str, dict] = {cid: {
            "games_included": 0, "games_won": 0, "win_rate": 0.0,
            "total_kos": 0, "total_damage": 0, "total_prizes": 0,
        } for cid in card_ids}

        for row in rows:
            win_rate = (row.games_won / row.games_included) if row.games_included else 0.0
            result[row.card_tcgdex_id] = {
                "games_included": row.games_included,
                "games_won": row.games_won,
                "win_rate": round(win_rate, 3),
                "total_kos": row.total_kos or 0,
                "total_damage": row.total_damage or 0,
                "total_prizes": row.total_prizes or 0,
            }
        return result

    async def get_top_performing_cards(
        self,
        exclude_ids: list[str],
        limit: int = 20,
    ) -> list[dict]:
        """Return top-performing cards NOT in the current deck.

        Ordered by win_rate descending, filtered to cards with at least 5 games.
        Returns list of {tcgdex_id, name, games_included, win_rate}.
        """
        conditions = [CardPerformance.games_included >= 5]
        if exclude_ids:
            conditions.append(CardPerformance.card_tcgdex_id.not_in(exclude_ids))
        rows = (await self._db.execute(
            select(CardPerformance, Card.name)
            .join(Card, Card.tcgdex_id == CardPerformance.card_tcgdex_id)
            .where(*conditions)
            .order_by(
                (CardPerformance.games_won / CardPerformance.games_included).desc()
            )
            .limit(limit)
        )).all()

        return [
            {
                "tcgdex_id": perf.card_tcgdex_id,
                "name": name,
                "games_included": perf.games_included,
                "win_rate": round(perf.games_won / perf.games_included, 3),
            }
            for perf, name in rows
        ]

    async def get_total_historical_games(self) -> int:
        """Return the total number of matches recorded in the DB."""
        result = await self._db.execute(
            select(text("COUNT(*)")).select_from(Match)
        )
        return result.scalar() or 0
