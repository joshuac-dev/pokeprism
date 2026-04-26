"""Write match outcomes and card relationships to Neo4j."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.db.graph import graph_session

if TYPE_CHECKING:
    from app.engine.runner import MatchResult
    from app.cards.models import CardDefinition


class GraphMemoryWriter:
    """Updates Neo4j graph after each match.

    Nodes created/merged:
        - :Card {tcgdex_id}
        - :Deck {deck_id}
        - :MatchResult {match_id}

    Relationships updated:
        - (Card)-[:SYNERGIZES_WITH]-(Card)  — co-occurrence in a winning deck
        - (Deck)-[:BEATS]->(Deck)           — deck-level matchup record
        - (Card)-[:BELONGS_TO]->(Deck)      — deck membership (idempotent)
    """

    async def write_match(
        self,
        result: MatchResult,
        match_id: uuid.UUID,
        p1_deck_id: uuid.UUID,
        p2_deck_id: uuid.UUID,
        p1_card_defs: list[CardDefinition],
        p2_card_defs: list[CardDefinition],
    ) -> None:
        async with graph_session() as session:
            await self._ensure_deck_nodes(session, p1_deck_id, result.p1_deck_name,
                                          p1_card_defs)
            await self._ensure_deck_nodes(session, p2_deck_id, result.p2_deck_name,
                                          p2_card_defs)
            await self._write_match_result(session, match_id, result,
                                           p1_deck_id, p2_deck_id)
            winning_deck_id = p1_deck_id if result.winner == "p1" else p2_deck_id
            winning_cards = p1_card_defs if result.winner == "p1" else p2_card_defs
            await self._update_synergies(session, winning_cards, won=True)
            losing_cards = p2_card_defs if result.winner == "p1" else p1_card_defs
            await self._update_synergies(session, losing_cards, won=False)
            await self._update_matchup(session, p1_deck_id, p2_deck_id,
                                       result.winner)

    # ── private helpers ────────────────────────────────────────────────────────

    async def _ensure_deck_nodes(
        self,
        session,
        deck_id: uuid.UUID,
        deck_name: str,
        card_defs: list[CardDefinition],
    ) -> None:
        """Merge Deck + Card nodes and BELONGS_TO edges."""
        await session.run(
            """
            MERGE (d:Deck {deck_id: $deck_id})
            ON CREATE SET d.name = $name, d.created_at = datetime()
            ON MATCH SET d.name = $name
            """,
            deck_id=str(deck_id), name=deck_name,
        )
        unique_ids = {c.tcgdex_id for c in card_defs}
        for tcgdex_id in unique_ids:
            card = next(c for c in card_defs if c.tcgdex_id == tcgdex_id)
            qty = sum(1 for c in card_defs if c.tcgdex_id == tcgdex_id)
            await session.run(
                """
                MERGE (c:Card {tcgdex_id: $tid})
                ON CREATE SET c.name = $name, c.category = $category
                """,
                tid=tcgdex_id,
                name=getattr(card, "name", tcgdex_id),
                category=getattr(card, "category", "unknown"),
            )
            await session.run(
                """
                MATCH (c:Card {tcgdex_id: $tid})
                MATCH (d:Deck {deck_id: $deck_id})
                MERGE (c)-[r:BELONGS_TO]->(d)
                ON CREATE SET r.quantity = $qty
                """,
                tid=tcgdex_id,
                deck_id=str(deck_id),
                qty=qty,
            )

    async def _write_match_result(
        self,
        session,
        match_id: uuid.UUID,
        result: MatchResult,
        p1_deck_id: uuid.UUID,
        p2_deck_id: uuid.UUID,
    ) -> None:
        winner_deck_id = str(p1_deck_id if result.winner == "p1" else p2_deck_id)
        await session.run(
            """
            MERGE (m:MatchResult {match_id: $match_id})
            ON CREATE SET
                m.winner = $winner,
                m.win_condition = $condition,
                m.total_turns = $turns
            """,
            match_id=str(match_id),
            winner=result.winner,
            condition=result.win_condition,
            turns=result.total_turns,
        )
        await session.run(
            """
            MATCH (d:Deck {deck_id: $deck_id})
            MATCH (m:MatchResult {match_id: $match_id})
            MERGE (d)-[:WON]->(m)
            """,
            deck_id=winner_deck_id,
            match_id=str(match_id),
        )

    async def _update_synergies(
        self,
        session,
        card_defs: list[CardDefinition],
        won: bool,
    ) -> None:
        """Update SYNERGIZES_WITH weight for all pairs in this deck."""
        unique_ids = list({c.tcgdex_id for c in card_defs})
        delta = 1.0 if won else -0.5
        for i in range(len(unique_ids)):
            for j in range(i + 1, len(unique_ids)):
                await session.run(
                    """
                    MERGE (a:Card {tcgdex_id: $id_a})
                    MERGE (b:Card {tcgdex_id: $id_b})
                    MERGE (a)-[r:SYNERGIZES_WITH]-(b)
                    ON CREATE SET r.weight = $delta, r.games_observed = 1
                    ON MATCH SET r.weight = r.weight + $delta,
                                 r.games_observed = r.games_observed + 1
                    """,
                    id_a=unique_ids[i],
                    id_b=unique_ids[j],
                    delta=delta,
                )

    async def _update_matchup(
        self,
        session,
        p1_deck_id: uuid.UUID,
        p2_deck_id: uuid.UUID,
        winner: str,
    ) -> None:
        """Update BEATS edge between the two decks."""
        winner_id = str(p1_deck_id if winner == "p1" else p2_deck_id)
        loser_id = str(p2_deck_id if winner == "p1" else p1_deck_id)
        await session.run(
            """
            MERGE (w:Deck {deck_id: $winner_id})
            MERGE (l:Deck {deck_id: $loser_id})
            MERGE (w)-[r:BEATS]->(l)
            ON CREATE SET r.win_count = 1, r.total_games = 1,
                          r.win_rate = 1.0
            ON MATCH SET r.win_count = r.win_count + 1,
                         r.total_games = r.total_games + 1,
                         r.win_rate = toFloat(r.win_count + 1) /
                                      toFloat(r.total_games + 1)
            """,
            winner_id=winner_id,
            loser_id=loser_id,
        )
        # Also keep total_games on loser edge (even when losing)
        await session.run(
            """
            MERGE (w:Deck {deck_id: $winner_id})
            MERGE (l:Deck {deck_id: $loser_id})
            MERGE (l)-[r:BEATS]->(w)
            ON CREATE SET r.win_count = 0, r.total_games = 1,
                          r.win_rate = 0.0
            ON MATCH SET r.total_games = r.total_games + 1,
                         r.win_rate = toFloat(r.win_count) /
                                      toFloat(r.total_games + 1)
            """,
            winner_id=winner_id,
            loser_id=loser_id,
        )
