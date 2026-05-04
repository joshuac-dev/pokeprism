"""Celery task: run_simulation — full simulation lifecycle.

Phase 7: wraps the async simulation engine in a synchronous Celery task.
Publishes real-time events to Redis pub/sub for WebSocket forwarding.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import redis  # module-level import so tests can patch `app.tasks.simulation.redis`

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import (
    Card,
    Deck,
    DeckMutation,
    Match,
    MatchEvent,
    Round,
    Simulation,
    SimulationOpponent,
    SimulationOpponentResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deck text helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PTCGL format regexes
# ---------------------------------------------------------------------------

# Section headers: "Pokémon: 14", "Trainer:", "Energy: 7" — always skipped
_PTCGL_SECTION_RE = re.compile(
    r"^(?:Pok[eé]mon|Trainer|Energy)\s*:", re.IGNORECASE
)

# PTCGL card line: "4 Dreepy PRE 71" or "1 Pecharunt PR-SV 149"
# Groups: (count, card_name, set_abbrev, card_number)
_PTCGL_LINE_RE = re.compile(
    r"^(\d+)\s+(.+?)\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)\s+(\d+)\s*$"
)

_BASIC_ENERGY_PTCGL_NUMBERS = {
    "Grass Energy": "1",
    "Fire Energy": "2",
    "Water Energy": "3",
    "Lightning Energy": "4",
    "Psychic Energy": "5",
    "Fighting Energy": "6",
    "Darkness Energy": "7",
    "Metal Energy": "8",
}


def _parse_ptcgl_deck_text(deck_text: str) -> list[dict]:
    """Parse PTCGL export format into structured entries.

    Handles:
      - "4 Dreepy PRE 71"
      - "2 Boss's Orders MEG 114"
      - "1 Pecharunt PR-SV 149"
      - "10 Psychic Energy" (PTCGL basic-energy shorthand; maps to SVE)
      - Section headers (Pokémon:, Trainer:, Energy:) — skipped
      - Blank lines and # comments — skipped

    Returns list of dicts: {count, name, set_abbrev, set_number}
    """
    entries: list[dict] = []
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _PTCGL_SECTION_RE.match(line):
            continue
        m = _PTCGL_LINE_RE.match(line)
        if m:
            entries.append({
                "count": int(m.group(1)),
                "name": m.group(2).strip(),
                "set_abbrev": m.group(3),
                "set_number": m.group(4),
            })
            continue

        shorthand = re.match(r"^(\d+)\s+(.+ Energy)\s*$", line, re.IGNORECASE)
        if not shorthand:
            continue
        energy_name = shorthand.group(2).strip()
        canonical_name = next(
            (name for name in _BASIC_ENERGY_PTCGL_NUMBERS if name.lower() == energy_name.lower()),
            None,
        )
        if canonical_name is None:
            continue
        entries.append({
            "count": int(shorthand.group(1)),
            "name": canonical_name,
            "set_abbrev": "SVE",
            "set_number": _BASIC_ENERGY_PTCGL_NUMBERS[canonical_name],
        })
    return entries


def _parse_deck_text(deck_text: str) -> list[tuple[int, str]]:
    """Parse TCGdex-format deck text into (count, tcgdex_id) pairs.

    Handles:
      - "4 Dragapult ex sv06-130"  → count=4, tcgdex_id="sv06-130"
      - "4 sv06-130"               → count=4, tcgdex_id="sv06-130"
    The last space-separated token on each line is treated as the tcgdex_id
    when it contains a hyphen; otherwise the second token is used.
    """
    entries: list[tuple[int, str]] = []
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        try:
            count = int(tokens[0])
        except ValueError:
            continue
        # Prefer the last token when it looks like a tcgdex_id (e.g. sv06-130)
        last = tokens[-1]
        if "-" in last and any(c.isdigit() for c in last):
            tcgdex_id = last
        elif len(tokens) == 2:
            tcgdex_id = tokens[1]
        else:
            continue
        entries.append((count, tcgdex_id))
    return entries


def count_deck_cards(deck_text: str) -> int:
    """Return the total number of cards described in *deck_text*.

    Handles both TCGdex format (``4 Dragapult ex sv06-130``) and
    PTCGO/PTCGL export format (``4 Dragapult ex SVI 186``).  Any line
    whose first token is a positive integer is counted; section headers
    such as ``Pokémon: 14`` are skipped because their first token is
    not a plain integer.
    """
    total = 0
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        try:
            count = int(tokens[0])
            if count > 0:
                total += count
        except ValueError:
            continue
    return total


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------

def _check_regression(
    win_rate_pct: int,
    prev_win_rate: int | None,
    consecutive_regressions: int,
) -> int:
    """Return the updated consecutive-regressions counter.

    Increments when win_rate_pct < prev_win_rate; resets to 0 otherwise.
    Returns 0 when there is no previous round to compare against.
    """
    if prev_win_rate is None:
        return 0
    if win_rate_pct < prev_win_rate:
        return consecutive_regressions + 1
    return 0


def _win_rate_pct(p1_wins: int, total: int) -> int:
    return int(round(p1_wins / total * 100)) if total > 0 else 0


def _deck_text_from_cards(cards: list) -> str:
    counts: dict[str, tuple[str, int]] = {}
    for card in cards:
        if card.tcgdex_id in counts:
            name, cnt = counts[card.tcgdex_id]
            counts[card.tcgdex_id] = (name, cnt + 1)
        else:
            counts[card.tcgdex_id] = (card.name, 1)
    return "\n".join(
        f"{cnt} {name} {tid}" for tid, (name, cnt) in sorted(counts.items())
    )


async def _card_defs_from_snapshot(
    snapshot_cards: list[dict],
    SessionFactory: async_sessionmaker,
) -> list:
    """Rebuild CardDefinition copies from a persisted round deck snapshot."""
    ids = [item.get("tcgdex_id") for item in snapshot_cards if item.get("tcgdex_id")]
    if not ids:
        return []
    async with SessionFactory() as db:
        rows = (await db.execute(select(Card).where(Card.tcgdex_id.in_(set(ids))))).scalars().all()
        by_id = {row.tcgdex_id: _card_def_from_row(row) for row in rows}
    missing = sorted({tid for tid in ids if tid not in by_id})
    if missing:
        raise ValueError(
            "Round deck snapshot references cards missing from DB: "
            + ", ".join(missing)
        )
    return [by_id[tid] for tid in ids]


async def _persisted_match_count(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_number: int,
    opponent_deck_id: uuid.UUID,
) -> int:
    return (await db.execute(
        select(func.count(Match.id)).where(
            Match.simulation_id == simulation_id,
            Match.round_number == round_number,
            Match.opponent_deck_id == opponent_deck_id,
        )
    )).scalar() or 0


async def _load_opponent_match_results(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_number: int,
    opponent_deck_id: uuid.UUID,
) -> list["MatchResult"]:
    """Reconstruct MatchResult objects, including events, from persisted rows."""
    from app.engine.runner import MatchResult

    matches = (await db.execute(
        select(Match)
        .where(
            Match.simulation_id == simulation_id,
            Match.round_number == round_number,
            Match.opponent_deck_id == opponent_deck_id,
        )
        .order_by(Match.created_at.asc(), Match.id.asc())
    )).scalars().all()
    if not matches:
        return []

    match_ids = [m.id for m in matches]
    event_rows = (await db.execute(
        select(MatchEvent)
        .where(MatchEvent.match_id.in_(match_ids))
        .order_by(MatchEvent.match_id.asc(), MatchEvent.sequence.asc())
    )).scalars().all()
    events_by_match: dict[uuid.UUID, list[dict]] = {}
    for event in event_rows:
        events_by_match.setdefault(event.match_id, []).append(event.data or {})

    return [
        MatchResult(
            game_id=str(match.id),
            winner=match.winner,
            win_condition=match.win_condition,
            total_turns=match.total_turns,
            p1_prizes_taken=match.p1_prizes_taken,
            p2_prizes_taken=match.p2_prizes_taken,
            events=events_by_match.get(match.id, []),
            p1_deck_name=match.p1_deck_name or "",
            p2_deck_name=match.p2_deck_name or "",
        )
        for match in matches
    ]


async def _finalize_checkpoint_from_matches(
    db: AsyncSession,
    checkpoint: SimulationOpponentResult,
    graph_status: str,
    error_message: str | None = None,
) -> None:
    results = await _load_opponent_match_results(
        db,
        checkpoint.simulation_id,
        checkpoint.round_number,
        checkpoint.opponent_deck_id,
    )
    total = len(results)
    p1_wins = sum(1 for result in results if result.winner == "p1")
    checkpoint.status = "complete"
    checkpoint.matches_completed = total
    checkpoint.p1_wins = p1_wins
    checkpoint.p2_wins = total - p1_wins
    checkpoint.total_turns = sum(result.total_turns for result in results)
    checkpoint.win_rate = _win_rate_pct(p1_wins, total)
    checkpoint.graph_status = graph_status
    checkpoint.completed_at = datetime.now(timezone.utc)
    checkpoint.error_message = error_message


async def _ensure_opponent_checkpoint(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_id: uuid.UUID,
    round_number: int,
    opponent_deck_id: uuid.UUID,
    opponent_deck_name: str,
    matches_target: int,
) -> SimulationOpponentResult:
    checkpoint = (await db.execute(
        select(SimulationOpponentResult)
        .where(
            SimulationOpponentResult.simulation_id == simulation_id,
            SimulationOpponentResult.round_number == round_number,
            SimulationOpponentResult.opponent_deck_id == opponent_deck_id,
        )
        .with_for_update()
    )).scalar_one_or_none()
    if checkpoint is None:
        checkpoint = SimulationOpponentResult(
            simulation_id=simulation_id,
            round_id=round_id,
            round_number=round_number,
            opponent_deck_id=opponent_deck_id,
            opponent_deck_name=opponent_deck_name,
            matches_target=matches_target,
        )
        db.add(checkpoint)
        await db.flush()
    else:
        checkpoint.round_id = round_id
        checkpoint.opponent_deck_name = opponent_deck_name
        checkpoint.matches_target = matches_target
    return checkpoint


async def _prepare_opponent_checkpoint(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_id: uuid.UUID,
    round_number: int,
    opponent_deck_id: uuid.UUID,
    opponent_deck_name: str,
    matches_target: int,
) -> str:
    """Return 'run' or 'skip' after applying retry-safe checkpoint rules."""
    checkpoint = await _ensure_opponent_checkpoint(
        db,
        simulation_id,
        round_id,
        round_number,
        opponent_deck_id,
        opponent_deck_name,
        matches_target,
    )
    persisted_count = await _persisted_match_count(
        db, simulation_id, round_number, opponent_deck_id
    )

    if checkpoint.status == "complete":
        if (
            persisted_count != checkpoint.matches_completed
            or checkpoint.matches_completed != checkpoint.matches_target
        ):
            checkpoint.status = "failed"
            checkpoint.error_message = (
                "Completed opponent checkpoint does not match persisted match count "
                f"(persisted={persisted_count}, checkpoint={checkpoint.matches_completed}, "
                f"target={checkpoint.matches_target})"
            )
            raise ValueError(checkpoint.error_message)
        return "skip"

    if checkpoint.status == "running":
        if persisted_count == 0:
            checkpoint.status = "pending"
            checkpoint.matches_completed = 0
            checkpoint.p1_wins = 0
            checkpoint.p2_wins = 0
            checkpoint.total_turns = 0
            checkpoint.win_rate = None
            checkpoint.graph_status = "pending"
            checkpoint.error_message = None
        elif persisted_count == checkpoint.matches_target:
            await _finalize_checkpoint_from_matches(
                db,
                checkpoint,
                graph_status=(
                    checkpoint.graph_status
                    if checkpoint.graph_status in {"complete", "failed"}
                    else "failed"
                ),
                error_message=(
                    "Finalized from persisted matches after retry; graph status "
                    "may be incomplete."
                ),
            )
            return "skip"
        else:
            checkpoint.status = "failed"
            checkpoint.matches_completed = persisted_count
            checkpoint.error_message = (
                "Partial persisted opponent batch detected on retry "
                f"(persisted={persisted_count}, target={checkpoint.matches_target}); "
                "manual repair required."
            )
            raise ValueError(checkpoint.error_message)

    if checkpoint.status == "failed":
        raise ValueError(
            checkpoint.error_message
            or "Opponent batch checkpoint is failed; manual repair required."
        )

    if persisted_count > 0:
        if persisted_count == checkpoint.matches_target:
            await _finalize_checkpoint_from_matches(
                db,
                checkpoint,
                graph_status="failed",
                error_message=(
                    "Finalized from persisted matches before rerun; graph status "
                    "may be incomplete."
                ),
            )
            return "skip"
        checkpoint.status = "failed"
        checkpoint.matches_completed = persisted_count
        checkpoint.error_message = (
            "Persisted opponent matches exist before checkpoint run "
            f"(persisted={persisted_count}, target={checkpoint.matches_target}); "
            "manual repair required."
        )
        raise ValueError(checkpoint.error_message)

    checkpoint.status = "running"
    checkpoint.graph_status = "pending"
    checkpoint.started_at = datetime.now(timezone.utc)
    checkpoint.completed_at = None
    checkpoint.error_message = None
    return "run"


async def _complete_opponent_checkpoint(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_number: int,
    opponent_deck_id: uuid.UUID,
    results: list["MatchResult"],
    graph_status: str,
) -> None:
    checkpoint = (await db.execute(
        select(SimulationOpponentResult)
        .where(
            SimulationOpponentResult.simulation_id == simulation_id,
            SimulationOpponentResult.round_number == round_number,
            SimulationOpponentResult.opponent_deck_id == opponent_deck_id,
        )
        .with_for_update()
    )).scalar_one()
    p1_wins = sum(1 for result in results if result.winner == "p1")
    checkpoint.status = "complete"
    checkpoint.matches_completed = len(results)
    checkpoint.p1_wins = p1_wins
    checkpoint.p2_wins = len(results) - p1_wins
    checkpoint.total_turns = sum(result.total_turns for result in results)
    checkpoint.win_rate = _win_rate_pct(p1_wins, len(results))
    checkpoint.graph_status = graph_status
    checkpoint.completed_at = datetime.now(timezone.utc)
    checkpoint.error_message = None


async def _round_has_persisted_mutations(
    db: AsyncSession,
    simulation_id: uuid.UUID,
    round_number: int,
) -> bool:
    count = (await db.execute(
        select(func.count(DeckMutation.id)).where(
            DeckMutation.simulation_id == simulation_id,
            DeckMutation.round_number == round_number,
        )
    )).scalar() or 0
    return count > 0


from app.tasks.celery_app import celery_app  # noqa: E402


async def _dispatch_next_queued() -> None:
    """Promote the oldest queued simulation to pending and dispatch it.

    No-ops if any simulation is already pending or running.
    Uses SELECT FOR UPDATE SKIP LOCKED so concurrent callers never
    double-dispatch the same simulation.
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    next_id: str | None = None
    try:
        async with SessionFactory() as db:
            active = (await db.execute(
                select(func.count(Simulation.id))
                .where(Simulation.status.in_(["pending", "running"]))
            )).scalar() or 0
            if active > 0:
                return

            row = (await db.execute(
                select(Simulation)
                .where(Simulation.status == "queued")
                .order_by(Simulation.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()

            if row is None:
                return

            row.status = "pending"
            next_id = str(row.id)
            await db.commit()
    finally:
        await engine.dispose()

    if next_id:
        run_simulation.delay(next_id)
        logger.info("Queue: dispatched simulation %s", next_id)


@celery_app.task(bind=True, name="pokeprism.run_simulation")
def run_simulation(self, simulation_id: str) -> dict:
    """Synchronous Celery entry point — wraps async implementation."""
    # Each Celery task runs in a fresh asyncio event loop. The Neo4j AsyncDriver
    # singleton is bound to whichever loop first called get_driver(); reusing it
    # across loops raises "Future attached to a different loop". Nil it here so
    # it is recreated inside the new loop below (mirrors reset_neo4j_singleton
    # in tests/test_memory/conftest.py which fixes the same issue for pytest).
    from app.db import graph as _graph_module
    _graph_module._driver = None

    loop = asyncio.new_event_loop()
    exc_to_raise: BaseException | None = None
    result: dict | None = None
    try:
        result = loop.run_until_complete(_run_simulation_async(self, simulation_id))
    except Exception as exc:
        exc_to_raise = exc
    finally:
        # Advance the queue regardless of success, failure, or cancellation.
        try:
            loop.run_until_complete(_dispatch_next_queued())
        except Exception as exc:
            logger.warning("Queue: dispatch-next failed after %s: %s", simulation_id, exc)
        loop.close()
        # Belt-and-suspenders: nil again in case close_driver() failed inside the task.
        _graph_module._driver = None

    if exc_to_raise is not None:
        raise exc_to_raise
    return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------

async def _run_simulation_async(task_self: Any, simulation_id: str) -> dict:
    """Full simulation lifecycle."""
    from app.engine.batch import run_hh_batch
    from app.memory.postgres import MatchMemoryWriter
    from app.memory.graph import GraphMemoryWriter

    sim_uuid = uuid.UUID(simulation_id)
    r = redis.Redis.from_url(settings.REDIS_URL)
    channel = f"simulation:{simulation_id}"

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _publish(event: dict) -> None:
        try:
            r.publish(channel, json.dumps(event))
        except Exception as exc:
            logger.warning("Redis publish failed: %s", exc)

    try:
        # ── 1 & 2. Load simulation and set status = running ─────────────────
        async with SessionFactory() as db:
            row = await db.execute(select(Simulation).where(Simulation.id == sim_uuid))
            sim = row.scalar_one_or_none()
            if sim is None:
                raise ValueError(f"Simulation {simulation_id} not found")
            if sim.status == "cancelled":
                logger.info("Simulation %s was cancelled before worker start", simulation_id)
                _publish({"type": "simulation_cancelled", "simulation_id": simulation_id})
                return {"status": "cancelled"}

            num_rounds = sim.num_rounds
            matches_per_opponent = sim.matches_per_opponent
            target_win_rate = sim.target_win_rate  # integer percentage (e.g. 60)
            target_consecutive_rounds = sim.target_consecutive_rounds if sim.target_consecutive_rounds is not None else 1
            deck_locked = sim.deck_locked
            game_mode = sim.game_mode
            user_deck_id = sim.user_deck_id
            user_deck_name = sim.user_deck_name or "User Deck"

            sim.status = "running"
            sim.started_at = datetime.now(timezone.utc)
            sim.error_message = None
            await db.commit()

        # ── 3 & 4. Load user deck and opponent decks ────────────────────────
        async with SessionFactory() as db:
            if user_deck_id:
                dr = await db.execute(select(Deck).where(Deck.id == user_deck_id))
                user_deck_row = dr.scalar_one_or_none()
                user_deck_text = user_deck_row.deck_text if user_deck_row else ""
            else:
                user_deck_text = ""

            opp_rows = await db.execute(
                select(SimulationOpponent).where(
                    SimulationOpponent.simulation_id == sim_uuid
                )
            )
            opponents = opp_rows.scalars().all()

            # (deck_id, deck_name, deck_text)
            opponent_decks: list[tuple[uuid.UUID, str, str]] = []
            for opp in opponents:
                dr = await db.execute(select(Deck).where(Deck.id == opp.deck_id))
                deck_row = dr.scalar_one_or_none()
                if deck_row:
                    opponent_decks.append(
                        (opp.deck_id, opp.deck_name or deck_row.name or "", deck_row.deck_text)
                    )

        current_deck_cards = await _deck_text_to_card_defs(user_deck_text, SessionFactory)
        if not current_deck_cards:
            raise ValueError(
                "User deck could not be parsed — no valid card lines found. "
                "Accepted formats: TCGdex ('4 sv06-130'), TCGdex verbose "
                "('4 Dragapult ex sv06-130'), or PTCGL export ('4 Dragapult ex TWM 130')."
            )
        current_deck_text = user_deck_text
        writer = MatchMemoryWriter()
        graph_writer = GraphMemoryWriter()
        final_win_rate = 0
        total_round_matches = 0
        consecutive_target_hits = 0

        # Regression tracking state
        prev_win_rate: int | None = None
        consecutive_regressions: int = 0
        best_win_rate: int = -1
        best_deck_text: str = current_deck_text
        best_deck_cards: list = list(current_deck_cards)
        win_rate_history: list[int] = []       # one entry per completed round
        last_mutations_summary: list[dict] = []  # mutations applied after the last round

        # ── 5. Round loop ───────────────────────────────────────────────────
        for round_number in range(1, num_rounds + 1):
            # Check if simulation was cancelled between rounds
            async with SessionFactory() as db:
                status_row = await db.execute(
                    select(Simulation.status).where(Simulation.id == sim_uuid)
                )
                current_status = status_row.scalar_one_or_none()
                if current_status == "cancelled":
                    logger.info("Simulation %s cancelled — stopping at round %d", simulation_id, round_number)
                    _publish({"type": "simulation_cancelled", "simulation_id": simulation_id})
                    return {"status": "cancelled"}

            if task_self is not None and hasattr(task_self, "update_state"):
                task_self.update_state(
                    state="PROGRESS",
                    meta={"round": round_number, "total_rounds": num_rounds},
                )

            deck_snapshot = [
                {"tcgdex_id": c.tcgdex_id, "name": c.name}
                for c in current_deck_cards
            ]

            _publish({
                "type": "round_start",
                "simulation_id": simulation_id,
                "round_number": round_number,
                "deck_snapshot": deck_snapshot,
            })

            # Idempotent round creation: on Celery retry the row may already exist.
            round_id = uuid.uuid4()
            async with SessionFactory() as db:
                existing = await db.execute(
                    select(Round).where(
                        Round.simulation_id == sim_uuid,
                        Round.round_number == round_number,
                    )
                )
                existing_row = existing.scalar_one_or_none()
                if existing_row is not None:
                    round_id = existing_row.id
                    snapshot_cards = (existing_row.deck_snapshot or {}).get("cards", [])
                    if snapshot_cards:
                        current_deck_cards = await _card_defs_from_snapshot(
                            snapshot_cards, SessionFactory
                        )
                        current_deck_text = _deck_text_from_cards(current_deck_cards)
                    logger.info(
                        "Simulation %s round %d already exists (retry) — reusing id %s",
                        simulation_id, round_number, round_id,
                    )
                else:
                    rnd = Round(
                        id=round_id,
                        simulation_id=sim_uuid,
                        round_number=round_number,
                        deck_snapshot={"cards": deck_snapshot},
                        started_at=datetime.now(timezone.utc),
                        total_matches=0,
                    )
                    db.add(rnd)
                    await db.commit()

            player_classes = _get_player_classes(game_mode)
            all_round_results = []
            p1_wins_round = 0
            p1_total_round = 0
            skipped_checkpoint = False

            for opp_deck_id, opp_name, opp_deck_text in opponent_decks:
                opp_cards = await _deck_text_to_card_defs(opp_deck_text, SessionFactory)
                if not opp_cards:
                    continue

                async with SessionFactory() as db:
                    try:
                        checkpoint_action = await _prepare_opponent_checkpoint(
                            db,
                            sim_uuid,
                            round_id,
                            round_number,
                            opp_deck_id,
                            opp_name,
                            matches_per_opponent,
                        )
                    except Exception:
                        # _prepare_opponent_checkpoint marks partial/corrupt
                        # checkpoint states as failed. Commit that marker before
                        # the task-level failure path updates Simulation.status.
                        await db.commit()
                        raise
                    await db.commit()

                if checkpoint_action == "skip":
                    skipped_checkpoint = True
                    async with SessionFactory() as db:
                        skipped_results = await _load_opponent_match_results(
                            db, sim_uuid, round_number, opp_deck_id
                        )
                    all_round_results.extend(skipped_results)
                    p1_wins_round += sum(1 for result in skipped_results if result.winner == "p1")
                    p1_total_round += len(skipped_results)
                    _publish({
                        "type": "opponent_batch_skipped",
                        "simulation_id": simulation_id,
                        "round_number": round_number,
                        "opponent_deck_id": str(opp_deck_id),
                        "opponent_deck_name": opp_name,
                        "matches": len(skipped_results),
                    })
                    continue

                match_counter = {"n": 0}

                def _make_match_event_callback(
                    _sim_id: str,
                    _round_num: int,
                    _counter: dict,
                ) -> None:
                    def _cb(event: dict) -> None:
                        etype = event.get("event_type", "") or event.get("type", "")
                        if etype == "game_start":
                            _counter["n"] += 1
                            _publish({
                                "type": "match_start",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "p1_deck": event.get("p1_deck"),
                                "p2_deck": event.get("p2_deck"),
                            })
                        elif etype == "game_over":
                            _publish({
                                "type": "match_end",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "winner": event.get("winner"),
                                "condition": event.get("condition"),
                            })
                        else:
                            _publish({
                                "type": "match_event",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "event": etype,
                                "turn": event.get("turn"),
                                "player": event.get("player") or event.get("active_player"),
                                "data": {k: v for k, v in event.items() if k != "event_type"},
                            })
                    return _cb

                batch = await run_hh_batch(
                    p1_deck=current_deck_cards,
                    p2_deck=opp_cards,
                    num_games=matches_per_opponent,
                    p1_deck_name=user_deck_name,
                    p2_deck_name=opp_name,
                    p1_player_class=player_classes[0],
                    p2_player_class=player_classes[1],
                    event_callback=_make_match_event_callback(
                        simulation_id, round_number, match_counter
                    ),
                    verbose=False,
                )

                async with SessionFactory() as db:
                    all_card_defs = list(
                        {c.tcgdex_id: c for c in current_deck_cards + opp_cards}.values()
                    )
                    await writer.ensure_cards(all_card_defs, db)
                    if user_deck_id:
                        p1_deck_db_id = await writer.ensure_deck_cards_for_id(
                            user_deck_id, user_deck_name, current_deck_cards, db
                        )
                    else:
                        p1_deck_db_id = await writer.ensure_deck(
                            user_deck_name, current_deck_cards, db
                        )
                    p2_deck_db_id = await writer.ensure_deck_cards_for_id(
                        opp_deck_id, opp_name, opp_cards, db
                    )
                    match_ids: list[uuid.UUID] = []
                    for idx, result_item in enumerate(batch.results):
                        match_id = await writer.write_match(
                            result=result_item,
                            simulation_id=sim_uuid,
                            round_id=round_id,
                            round_number=round_number,
                            p1_deck_id=p1_deck_db_id,
                            p2_deck_id=p2_deck_db_id,
                            db=db,
                        )
                        match_ids.append(match_id)
                        game_decisions = (
                            batch.decisions_per_game[idx]
                            if idx < len(batch.decisions_per_game) else []
                        )
                        if game_decisions:
                            await writer.write_decisions(
                                game_decisions,
                                match_id=match_id,
                                simulation_id=sim_uuid,
                                db=db,
                            )
                    await db.commit()

                graph_failed = False
                for idx, result_item in enumerate(batch.results):
                    try:
                        await graph_writer.write_match(
                            result=result_item,
                            match_id=match_ids[idx],
                            p1_deck_id=p1_deck_db_id,
                            p2_deck_id=p2_deck_db_id,
                            p1_card_defs=current_deck_cards,
                            p2_card_defs=opp_cards,
                        )
                    except Exception as exc:
                        graph_failed = True
                        logger.warning("Graph write failed for match %s: %s", match_ids[idx], exc)

                async with SessionFactory() as db:
                    await _complete_opponent_checkpoint(
                        db,
                        sim_uuid,
                        round_number,
                        opp_deck_id,
                        batch.results,
                        graph_status="failed" if graph_failed else "complete",
                    )
                    await db.commit()

                all_round_results.extend(batch.results)
                p1_wins_round += batch.p1_wins
                p1_total_round += batch.total_games

            win_rate_pct = (
                int(round(p1_wins_round / p1_total_round * 100))
                if p1_total_round > 0 else 0
            )
            final_win_rate = win_rate_pct
            total_round_matches += p1_total_round

            async with SessionFactory() as db:
                await db.execute(
                    update(Round)
                    .where(Round.id == round_id)
                    .values(
                        win_rate=win_rate_pct,
                        total_matches=p1_total_round,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.execute(
                    update(Simulation)
                    .where(Simulation.id == sim_uuid)
                    .values(
                        rounds_completed=round_number,
                        total_matches=total_round_matches,
                    )
                )
                await db.commit()

            # ── Regression tracking ─────────────────────────────────────────
            # Capture best deck BEFORE coaching (deck that produced win_rate_pct)
            if win_rate_pct > best_win_rate:
                best_win_rate = win_rate_pct
                best_deck_text = current_deck_text
                best_deck_cards = list(current_deck_cards)
                best_snap = [
                    {"tcgdex_id": c.tcgdex_id, "name": c.name}
                    for c in current_deck_cards
                ]
                async with SessionFactory() as db:
                    await db.execute(
                        update(Simulation)
                        .where(Simulation.id == sim_uuid)
                        .values(
                            best_deck_snapshot={"cards": best_snap, "win_rate": win_rate_pct}
                        )
                    )
                    await db.commit()

            consecutive_regressions = _check_regression(
                win_rate_pct, prev_win_rate, consecutive_regressions
            )
            prev_win_rate = win_rate_pct
            win_rate_history.append(win_rate_pct)

            mutations_for_event: list[dict] = []

            # Run coach before target check so mutations are always applied on
            # non-final rounds when the deck is unlocked, even if target is met.
            if not deck_locked and round_number < num_rounds and current_deck_cards:
                if skipped_checkpoint:
                    async with SessionFactory() as db:
                        if await _round_has_persisted_mutations(db, sim_uuid, round_number):
                            raise ValueError(
                                "Retry reached a round whose coach mutations were already "
                                "persisted; automatic replay is blocked to avoid duplicate "
                                "mutation decisions."
                            )
                if consecutive_regressions >= 3:
                    # Third+ consecutive regression — skip Coach entirely
                    logger.info(
                        "Coach skipped for round %d: %d consecutive regressions",
                        round_number, consecutive_regressions,
                    )
                    _publish({
                        "type": "coach_skipped",
                        "simulation_id": simulation_id,
                        "round_number": round_number,
                        "reason": f"{consecutive_regressions} consecutive win-rate regressions",
                    })
                else:
                    was_reverted = False
                    if consecutive_regressions == 2:
                        # Two consecutive regressions — revert to best known deck
                        logger.info(
                            "Reverting deck at round %d: 2 consecutive regressions "
                            "(best win rate was %d%%)",
                            round_number, best_win_rate,
                        )
                        current_deck_cards = list(best_deck_cards)
                        current_deck_text = best_deck_text
                        consecutive_regressions = 0
                        was_reverted = True
                        _publish({
                            "type": "deck_reverted",
                            "simulation_id": simulation_id,
                            "round_number": round_number,
                            "reverted_to_win_rate": best_win_rate,
                        })

                    regression_info = {
                        "consecutive_regressions": consecutive_regressions,
                        "prev_win_rate": prev_win_rate,
                        "current_win_rate": win_rate_pct,
                        "best_win_rate": best_win_rate,
                        "reverted": was_reverted,
                        "win_rate_history": list(win_rate_history),
                        "last_mutations": list(last_mutations_summary),
                    }

                    try:
                        async with SessionFactory() as db:
                            from app.coach.analyst import CoachAnalyst
                            analyst = CoachAnalyst(db=db)
                            mutations = await analyst.analyze_and_mutate(
                                current_deck=current_deck_cards,
                                round_results=all_round_results,
                                simulation_id=sim_uuid,
                                round_number=round_number,
                                regression_info=regression_info,
                            )
                            await db.commit()

                        current_deck_cards, current_deck_text = _apply_mutations(
                            current_deck_cards, current_deck_text, mutations
                        )
                        mutations_for_event = [
                            {
                                "remove": m.get("card_removed"),
                                "add": m.get("card_added"),
                                "reasoning": m.get("reasoning"),
                                "evidence": m.get("evidence", []),
                            }
                            for m in mutations
                        ]
                        for mut in mutations_for_event:
                            _publish({
                                "type": "deck_mutation",
                                "simulation_id": simulation_id,
                                "round_number": round_number,
                                "remove": mut["remove"],
                                "add": mut["add"],
                                "reasoning": mut["reasoning"],
                                "evidence": mut["evidence"],
                            })
                    except Exception as exc:
                        logger.warning(
                            "Coach mutation failed (round %d): %s", round_number, exc,
                            exc_info=True,
                        )

            # Persist Coach mutations for the next round's history context
            last_mutations_summary = list(mutations_for_event)

            if win_rate_pct >= target_win_rate:
                consecutive_target_hits += 1
            else:
                consecutive_target_hits = 0

            _publish({
                "type": "round_end",
                "simulation_id": simulation_id,
                "round_number": round_number,
                "win_rate": win_rate_pct / 100.0,
                "wins": p1_wins_round,
                "total": p1_total_round,
                "mutations": mutations_for_event,
            })

            if consecutive_target_hits >= target_consecutive_rounds:
                _publish({
                    "type": "target_reached",
                    "simulation_id": simulation_id,
                    "round_number": round_number,
                    "win_rate": win_rate_pct / 100.0,
                    "consecutive_hits": consecutive_target_hits,
                })
                break

        # ── 6. Mark complete ────────────────────────────────────────────────
        async with SessionFactory() as db:
            await db.execute(
                update(Simulation)
                .where(Simulation.id == sim_uuid)
                .values(
                    status="complete",
                    final_win_rate=final_win_rate,
                    error_message=None,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        _publish({
            "type": "simulation_complete",
            "simulation_id": simulation_id,
            "final_win_rate": final_win_rate / 100.0,
            "rounds_completed": num_rounds,
        })
        return {"status": "complete", "final_win_rate": final_win_rate}

    except Exception as exc:
        logger.exception("Simulation %s failed: %s", simulation_id, exc)
        try:
            async with SessionFactory() as db:
                await db.execute(
                    update(Simulation)
                    .where(Simulation.id == sim_uuid)
                    .values(
                        status="failed",
                        error_message=str(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
        except Exception:
            pass
        _publish({
            "type": "simulation_error",
            "simulation_id": simulation_id,
            "error": str(exc),
        })
        raise

    finally:
        await engine.dispose()
        from app.db.graph import close_driver
        try:
            await close_driver()
        except Exception as exc:
            logger.warning("Neo4j driver close failed: %s", exc)
        try:
            r.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def ensure_deck_cards_in_db(deck_texts: list[str], db: AsyncSession) -> None:
    """Fetch any PTCGL-format cards missing from DB and persist them.

    Must be called BEFORE the coverage gate so all deck cards exist in the DB
    when check_card_coverage runs.  TCGdex-format decks (explicit tcgdex_id
    tokens) reference already-seeded cards and are skipped.

    Raises ``ValueError`` if a set abbreviation is unknown or TCGDex 404s.
    """
    from app.cards.loader import CardListLoader, SET_CODE_MAP
    from app.cards.tcgdex import TCGDexClient
    from app.db.models import Card
    from app.memory.postgres import MatchMemoryWriter

    all_ptcgl_entries: list[dict] = []
    for text in deck_texts:
        if not text.strip():
            continue
        if not _parse_deck_text(text):
            all_ptcgl_entries.extend(_parse_ptcgl_deck_text(text))

    if not all_ptcgl_entries:
        return

    abbrevs = list({e["set_abbrev"] for e in all_ptcgl_entries})
    result = await db.execute(select(Card).where(Card.set_abbrev.in_(abbrevs)))
    db_keys: set[tuple[str, str]] = set()
    for row in result.scalars().all():
        norm = str(int(row.set_number)) if (row.set_number and row.set_number.isdigit()) else (row.set_number or "")
        db_keys.add((row.set_abbrev, norm))

    misses: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for entry in all_ptcgl_entries:
        abbrev = entry["set_abbrev"]
        number = entry["set_number"]
        norm = str(int(number)) if number.isdigit() else number
        key = (abbrev, norm)
        if key not in db_keys and key not in seen_keys:
            seen_keys.add(key)
            misses.append(entry)

    if not misses:
        return

    loader = CardListLoader()
    writer = MatchMemoryWriter()
    fresh_defs = {}

    async with TCGDexClient() as tcgdex:
        for entry in misses:
            abbrev = entry["set_abbrev"]
            number = entry["set_number"]
            set_id = SET_CODE_MAP.get(abbrev)
            if set_id is None:
                raise ValueError(
                    f"Unknown set abbreviation '{abbrev}' for card "
                    f"'{entry['name']} {abbrev} {number}'. "
                    f"Add it to SET_CODE_MAP in loader.py."
                )
            try:
                raw = await tcgdex.get_card(set_id, number)
            except Exception as exc:
                raise ValueError(
                    f"Card not found in TCGDex: {entry['name']} {abbrev} {number}. "
                    f"Error: {exc}"
                ) from exc
            norm = str(int(number)) if number.isdigit() else number
            card_def = loader._transform(
                raw, {"name": entry["name"], "set_abbrev": abbrev, "number": number}
            )
            fresh_defs[(abbrev, norm)] = card_def
            logger.info("Pre-fetched card from TCGDex: %s (%s)", card_def.name, card_def.tcgdex_id)

    await writer.ensure_cards(list(fresh_defs.values()), db)
    await db.commit()


def _card_def_from_row(row) -> "CardDefinition":
    """Build a complete CardDefinition from a DB Card row.

    Populates attacks, abilities, energy_provides, weaknesses, and resistances
    from DB JSONB columns — fields omitted here cause silent engine failures
    (no attacks → 100% deck-out; no registry entry → wrong active placement).
    """
    from app.cards.models import CardDefinition, AttackDef, AbilityDef, WeaknessDef, ResistanceDef

    attacks = [
        AttackDef(
            name=a.get("name", ""),
            cost=a.get("cost") or [],
            damage=str(a.get("damage", "")),
            effect=a.get("effect", ""),
        )
        for a in (row.attacks or [])
    ]

    abilities = [
        AbilityDef(
            name=a.get("name", ""),
            type=a.get("type", "Ability"),
            effect=a.get("effect", ""),
        )
        for a in (row.abilities or [])
    ]

    weaknesses = [
        WeaknessDef(type=w.get("type", ""), value=w.get("value", ""))
        for w in (row.weaknesses or [])
    ]

    resistances = [
        ResistanceDef(type=r.get("type", ""), value=r.get("value", ""))
        for r in (row.resistances or [])
    ]

    # Derive energy_provides for basic energy cards from the card name
    energy_provides: list[str] = []
    if (row.category or "").lower() == "energy" and (row.subcategory or "").lower() == "basic":
        name_lower = (row.name or "").lower()
        for etype in ("Grass", "Fire", "Water", "Lightning", "Psychic",
                      "Fighting", "Darkness", "Metal", "Dragon", "Fairy"):
            if etype.lower() in name_lower:
                energy_provides = [etype]
                break
        if not energy_provides and (row.types or []):
            energy_provides = [row.types[0]]

    return CardDefinition(
        tcgdex_id=row.tcgdex_id,
        name=row.name,
        set_abbrev=row.set_abbrev,
        set_number=row.set_number,
        category=row.category or "",
        subcategory=row.subcategory or "",
        hp=row.hp,
        types=row.types or [],
        evolve_from=row.evolve_from,
        stage=row.stage or "",
        attacks=attacks,
        abilities=abilities,
        weaknesses=weaknesses,
        resistances=resistances,
        energy_provides=energy_provides,
        retreat_cost=row.retreat_cost or 0,
        regulation_mark=row.regulation_mark,
        rarity=row.rarity,
        image_url=row.image_url,
    )


async def _deck_text_to_card_defs(
    deck_text: str,
    SessionFactory: async_sessionmaker,
) -> list:
    """Convert deck text to ``list[CardDefinition]`` (with duplicates for count).

    Accepts both TCGdex format (e.g. ``4 sv06-130``) and PTCGL export format
    (e.g. ``4 Dreepy PRE 71``).  All cards are expected to be in the DB already
    (fetched via ``ensure_deck_cards_in_db`` at submission time).

    Raises ``ValueError`` if a PTCGL card is not found in the DB.

    Side effect: registers all loaded CardDefinitions in the global in-memory
    registry so engine helpers (choose_setup, _best_energy_target, etc.) can
    look up card data by tcgdex_id during the simulation.
    """
    if not deck_text.strip():
        return []

    from app.cards.models import CardDefinition
    from app.cards import registry as card_registry
    from app.db.models import Card

    # ── 1. Try TCGdex format (existing path: last token contains a hyphen) ───
    tcgdex_entries = _parse_deck_text(deck_text)
    if tcgdex_entries:
        tcgdex_ids = [tid for _, tid in tcgdex_entries]
        async with SessionFactory() as db:
            result = await db.execute(
                select(Card).where(Card.tcgdex_id.in_(tcgdex_ids))
            )
            card_rows = {row.tcgdex_id: row for row in result.scalars().all()}

        defs: list[CardDefinition] = []
        unique_defs: dict[str, CardDefinition] = {}
        for count, tcgdex_id in tcgdex_entries:
            if tcgdex_id in card_rows:
                card_def = _card_def_from_row(card_rows[tcgdex_id])
            else:
                parts = tcgdex_id.rsplit("-", 1)
                card_def = CardDefinition(
                    tcgdex_id=tcgdex_id,
                    name=tcgdex_id,
                    set_abbrev=parts[0] if len(parts) == 2 else "",
                    set_number=parts[1] if len(parts) == 2 else "",
                )
            unique_defs[tcgdex_id] = card_def
            defs.extend([card_def] * count)

        card_registry.register_many(unique_defs)
        return defs

    # ── 2. Try PTCGL export format ────────────────────────────────────────────
    ptcgl_entries = _parse_ptcgl_deck_text(deck_text)
    if not ptcgl_entries:
        return []

    # ── 2a. Batch DB lookup by (set_abbrev, normalised set_number) ────────────
    # Cards must already be in DB (ensure_deck_cards_in_db was called at submission).
    abbrevs = list({e["set_abbrev"] for e in ptcgl_entries})
    async with SessionFactory() as db:
        result = await db.execute(
            select(Card).where(Card.set_abbrev.in_(abbrevs))
        )
        db_cards: dict[tuple[str, str], Card] = {}
        for row in result.scalars().all():
            norm = str(int(row.set_number)) if (row.set_number and row.set_number.isdigit()) else (row.set_number or "")
            db_cards[(row.set_abbrev, norm)] = row

    # ── 2b. Build CardDefinition list and register in global registry ─────────
    defs_ptcgl: list[CardDefinition] = []
    unique_defs_ptcgl: dict[str, CardDefinition] = {}
    for entry in ptcgl_entries:
        abbrev = entry["set_abbrev"]
        number = entry["set_number"]
        count = entry["count"]
        norm = str(int(number)) if number.isdigit() else number
        key = (abbrev, norm)

        row = db_cards.get(key)
        if row is None:
            raise ValueError(
                f"Card not in DB: {entry['name']} {abbrev} {number}. "
                f"ensure_deck_cards_in_db must be called before queueing this task."
            )

        card_def = _card_def_from_row(row)
        unique_defs_ptcgl[card_def.tcgdex_id] = card_def
        defs_ptcgl.extend([card_def] * count)

    card_registry.register_many(unique_defs_ptcgl)
    return defs_ptcgl


_TCGDEX_ID_RE = re.compile(r"^[a-z][a-z0-9.]*-[0-9]+[a-z]*$")

_BASIC_ENERGY_NAMES: frozenset[str] = frozenset({
    "Grass Energy", "Fire Energy", "Water Energy", "Lightning Energy",
    "Psychic Energy", "Fighting Energy", "Darkness Energy", "Metal Energy",
    "Dragon Energy", "Fairy Energy", "Colorless Energy",
})


def _validate_post_mutation_deck(deck: list) -> list[str]:
    """Return legality errors for a post-mutation deck. Empty list means valid."""
    errors: list[str] = []
    if len(deck) != 60:
        errors.append(f"Deck must be exactly 60 cards, got {len(deck)}")
    name_counts: dict[str, int] = {}
    for card in deck:
        name_counts[card.name] = name_counts.get(card.name, 0) + 1
    for name, count in name_counts.items():
        if name not in _BASIC_ENERGY_NAMES and count > 4:
            errors.append(f"Too many copies of '{name}': {count} (max 4)")
    return errors


def _apply_mutations(
    current_deck: list,
    current_deck_text: str,
    mutations: list[dict],
) -> tuple[list, str]:
    """Apply analyst mutations to the in-memory deck and return updated (deck, deck_text).

    Each mutation must carry a ``card_added_def`` (a real CardDefinition from the
    candidate pool).  Mutations with a missing or None def are skipped so that
    placeholder cards never enter the live deck.  When the original deck is
    exactly 60 cards the result is also validated for 60-card count and copy
    limits; if validation fails the original deck is returned unchanged.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    original_size = len(current_deck)
    new_deck = list(current_deck)
    for mutation in mutations:
        remove_id = mutation.get("card_removed")
        add_id = mutation.get("card_added")
        if not remove_id or not add_id:
            continue
        # Reject any add_id that isn't a valid tcgdex_id pattern
        if not _TCGDEX_ID_RE.match(add_id):
            _log.warning(
                "Coach proposed invalid card_added '%s' — skipping mutation", add_id
            )
            continue
        # Require a real card definition from the candidate pool; never create placeholders
        new_card = mutation.get("card_added_def")
        if new_card is None:
            _log.warning(
                "Coach proposed adding '%s' but no card definition is available "
                "(not in candidate pool or DB) — skipping mutation",
                add_id,
            )
            continue
        removed = False
        for i, card in enumerate(new_deck):
            if card.tcgdex_id == remove_id:
                new_deck.pop(i)
                removed = True
                break
        if not removed:
            _log.warning(
                "Coach proposed removing '%s' but card not found in deck — skipping mutation",
                remove_id,
            )
            continue
        new_deck.append(new_card)

    # Validate legality when the original was a full 60-card deck
    if original_size == 60:
        errors = _validate_post_mutation_deck(new_deck)
        if errors:
            _log.warning(
                "Post-mutation deck failed legality (%s) — reverting to original deck.",
                "; ".join(errors[:3]),
            )
            return current_deck, current_deck_text

    counts: dict[str, tuple[str, int]] = {}
    for card in new_deck:
        if card.tcgdex_id in counts:
            name, cnt = counts[card.tcgdex_id]
            counts[card.tcgdex_id] = (name, cnt + 1)
        else:
            counts[card.tcgdex_id] = (card.name, 1)

    new_deck_text = "\n".join(
        f"{cnt} {name} {tid}" for tid, (name, cnt) in sorted(counts.items())
    )
    return new_deck, new_deck_text


def _get_player_classes(game_mode: str) -> tuple:
    """Return (P1PlayerClass, P2PlayerClass) for the given game mode."""
    from app.players.heuristic import HeuristicPlayer

    if game_mode == "ai_h":
        try:
            from app.players.ai_player import AIPlayer
            return (AIPlayer, HeuristicPlayer)
        except ImportError:
            pass
    elif game_mode == "ai_ai":
        try:
            from app.players.ai_player import AIPlayer
            return (AIPlayer, AIPlayer)
        except ImportError:
            pass
    return (HeuristicPlayer, HeuristicPlayer)
