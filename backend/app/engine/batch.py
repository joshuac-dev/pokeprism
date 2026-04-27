"""Batch runner for H/H (and H/G, G/G) simulation.

Orchestrates N MatchRunner games and returns aggregate statistics.

Phase 3: output is an in-memory BatchResult.
Phase 4: accepts optional memory writers to persist results to Postgres + Neo4j.
Phase 7: app/tasks/simulation.py wraps this as a Celery task.

Usage (programmatic):
    from app.engine.batch import run_hh_batch
    result = await run_hh_batch(p1_deck, p2_deck, num_games=1000)

Usage (CLI):
    python scripts/run_hh.py --num-games 100
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional, Type

from app.engine.runner import MatchResult, MatchRunner
from app.cards.models import CardDefinition
from app.players.base import PlayerInterface

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    total_games: int
    p1_wins: int
    p2_wins: int
    p1_win_rate: float
    avg_turns: float
    deck_out_pct: float
    no_bench_pct: float
    turn_limit_pct: float
    results: list[MatchResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Games:        {self.total_games}",
            f"P1 win rate:  {self.p1_win_rate:.1%}  ({self.p1_wins}W / {self.p2_wins}L)",
            f"Avg turns:    {self.avg_turns:.1f}",
            f"Deck-out:     {self.deck_out_pct:.1f}%",
            f"No-bench:     {self.no_bench_pct:.1f}%",
        ]
        if self.turn_limit_pct > 0:
            lines.append(f"Turn limit:   {self.turn_limit_pct:.1f}%")
        return "\n".join(lines)


async def run_hh_batch(
    p1_deck: list[CardDefinition],
    p2_deck: list[CardDefinition],
    num_games: int = 1000,
    p1_deck_name: str = "p1_deck",
    p2_deck_name: str = "p2_deck",
    event_callback: Optional[Callable[[dict], None]] = None,
    p1_player_class: Optional[Type[PlayerInterface]] = None,
    p2_player_class: Optional[Type[PlayerInterface]] = None,
    verbose: bool = True,
    simulation_id: Optional[uuid.UUID] = None,
    persist: bool = False,
) -> BatchResult:
    """Run ``num_games`` matches and return aggregate statistics.

    Args:
        p1_deck / p2_deck: CardDefinition lists (60-card decks).
        num_games: Number of games to simulate.
        p1_deck_name / p2_deck_name: Labels for logging.
        event_callback: Optional hook called for every game event.
        p1_player_class: Player class for P1 (default: HeuristicPlayer).
        p2_player_class: Player class for P2 (default: same as P1).
        verbose: Print progress every 100 games.
        simulation_id: UUID to group results under in the DB. Auto-generated
            if persist=True and no ID is supplied.
        persist: If True, write each match to Postgres + Neo4j via
            MatchMemoryWriter and GraphMemoryWriter.

    Returns:
        BatchResult with win rates, average turns, and all MatchResult objects.
    """
    from app.players.heuristic import HeuristicPlayer

    PlayerCls1 = p1_player_class or HeuristicPlayer
    PlayerCls2 = p2_player_class or PlayerCls1

    p1_player = PlayerCls1()
    p2_player = PlayerCls2()

    # --- memory writers (lazily imported to avoid import cycles) ---
    pg_writer = None
    graph_writer = None
    db_session_cm = None
    p1_deck_db_id: Optional[uuid.UUID] = None
    p2_deck_db_id: Optional[uuid.UUID] = None
    round_id: Optional[uuid.UUID] = None

    if persist:
        from app.db.session import AsyncSessionLocal
        from app.memory.postgres import MatchMemoryWriter
        from app.memory.graph import GraphMemoryWriter

        if simulation_id is None:
            simulation_id = uuid.uuid4()
        round_id = uuid.uuid4()
        pg_writer = MatchMemoryWriter()
        graph_writer = GraphMemoryWriter()

        # Bootstrap: ensure simulation, round, cards, and deck rows exist.
        async with AsyncSessionLocal() as db:
            await pg_writer.ensure_cards(
                list({c.tcgdex_id: c for c in p1_deck + p2_deck}.values()), db
            )
            p1_deck_db_id = await pg_writer.ensure_deck(p1_deck_name, p1_deck, db)
            p2_deck_db_id = await pg_writer.ensure_deck(p2_deck_name, p2_deck, db)
            await pg_writer.ensure_simulation(simulation_id, db)
            await pg_writer.ensure_round(
                round_id, simulation_id, 1,
                {"p1": p1_deck_name, "p2": p2_deck_name}, db
            )
            await db.commit()

    results: list[MatchResult] = []

    for i in range(num_games):
        runner = MatchRunner(
            p1_player=p1_player,
            p2_player=p2_player,
            p1_deck=p1_deck,
            p2_deck=p2_deck,
            p1_deck_name=p1_deck_name,
            p2_deck_name=p2_deck_name,
            event_callback=event_callback,
        )
        result = await runner.run()
        results.append(result)

        if persist and pg_writer and graph_writer:
            # Drain AI decisions before opening the DB session.
            p1_decisions = (
                p1_player.drain_decisions()
                if hasattr(p1_player, "drain_decisions") else []
            )
            p2_decisions = (
                p2_player.drain_decisions()
                if hasattr(p2_player, "drain_decisions") else []
            )
            all_decisions = p1_decisions + p2_decisions
            async with AsyncSessionLocal() as db:
                match_id = await pg_writer.write_match(
                    result=result,
                    simulation_id=simulation_id,
                    round_id=round_id,
                    round_number=1,
                    p1_deck_id=p1_deck_db_id,
                    p2_deck_id=p2_deck_db_id,
                    db=db,
                )
                stored = []
                if all_decisions:
                    stored = await pg_writer.write_decisions(
                        all_decisions,
                        match_id=match_id,
                        simulation_id=simulation_id,
                        db=db,
                    )
                if stored:
                    from app.memory.embeddings import EmbeddingService
                    embed_svc = EmbeddingService()
                    for decision_id, summary in stored:
                        if summary:
                            await embed_svc.embed_and_store(
                                text=summary,
                                source_type="decision",
                                source_id=str(decision_id),
                                db=db,
                            )
                await db.commit()
            await graph_writer.write_match(
                result=result,
                match_id=match_id,
                p1_deck_id=p1_deck_db_id,
                p2_deck_id=p2_deck_db_id,
                p1_card_defs=p1_deck,
                p2_card_defs=p2_deck,
            )

        if verbose and (i + 1) % 100 == 0:
            logger.info("Completed %d/%d games", i + 1, num_games)
            print(f"  {i + 1}/{num_games} games done …")

    p1_wins = sum(1 for r in results if r.winner == "p1")
    total_turns = sum(r.total_turns for r in results)
    deck_outs = sum(1 for r in results if r.win_condition == "deck_out")
    no_bench = sum(1 for r in results if r.win_condition == "no_bench")
    turn_limit = sum(1 for r in results if r.win_condition == "turn_limit")

    return BatchResult(
        total_games=num_games,
        p1_wins=p1_wins,
        p2_wins=num_games - p1_wins,
        p1_win_rate=p1_wins / num_games,
        avg_turns=total_turns / num_games,
        deck_out_pct=deck_outs / num_games * 100,
        no_bench_pct=no_bench / num_games * 100,
        turn_limit_pct=turn_limit / num_games * 100,
        results=results,
    )
