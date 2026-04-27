"""FastAPI router for simulation endpoints (Appendix E).

Handles creation, querying, mutation history, starring, and deletion of
PokéPrism simulations.  The router is registered at ``/api/simulations``
via ``app/api/router.py``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
import redis as redis_module
from app.db.models import Deck, DeckCard, DeckMutation, Decision, Match, MatchEvent, Round, Simulation, SimulationOpponent
from app.db.session import AsyncSessionLocal
from app.tasks.simulation import count_deck_cards, run_simulation

logger = logging.getLogger(__name__)

router = APIRouter()

MINIMUM_MATCHES_RECOMMENDED = 5_000
_VALID_GAME_MODES = {"hh", "ai_h", "ai_ai"}
_VALID_DECK_MODES = {"full", "partial", "none"}


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SimulationCreate(BaseModel):
    deck_text: str = ""
    deck_mode: str = "full"
    game_mode: str = "hh"
    deck_locked: bool = False
    num_rounds: int = Field(default=5, ge=1, le=100)
    matches_per_opponent: int = Field(default=10, ge=1, le=1000)
    target_win_rate: float = Field(default=0.60, ge=0.0, le=1.0)
    opponent_deck_texts: list[str] = Field(default_factory=list)
    excluded_card_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_modes(self) -> "SimulationCreate":
        if self.game_mode not in _VALID_GAME_MODES:
            raise ValueError(
                f"game_mode must be one of {sorted(_VALID_GAME_MODES)}, got {self.game_mode!r}"
            )
        if self.deck_mode not in _VALID_DECK_MODES:
            raise ValueError(
                f"deck_mode must be one of {sorted(_VALID_DECK_MODES)}, got {self.deck_mode!r}"
            )
        if self.deck_locked and self.deck_mode == "none":
            raise ValueError("deck_locked=True is contradictory with deck_mode='none'")
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_deck_lines(deck_text: str) -> list[tuple[int, str, str]]:
    """Return (count, name, tcgdex_id) triples from deck text.

    Supports:
      ``4 Dragapult ex sv06-130`` → (4, "Dragapult ex", "sv06-130")
      ``4 sv06-130``               → (4, "sv06-130", "sv06-130")
    """
    results: list[tuple[int, str, str]] = []
    for raw in deck_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        try:
            count = int(tokens[0])
        except ValueError:
            continue
        last = tokens[-1]
        if "-" in last and any(c.isdigit() for c in last):
            tcgdex_id = last
            name = " ".join(tokens[1:-1]) if len(tokens) > 2 else last
        else:
            continue
        results.append((count, name, tcgdex_id))
    return results


async def _get_deck_name_from_gemma(deck_text: str, timeout: float = 5.0) -> Optional[str]:
    """Ask Gemma to generate a deck name.  Returns None on any failure."""
    from app.coach.prompts import DECK_NAME_PROMPT

    lines = _parse_deck_lines(deck_text)
    if not lines:
        return None

    ex_cards = [name for _cnt, name, _tid in lines if " ex" in name.lower() or name.lower().endswith("ex")]
    main_attacker = ex_cards[0] if ex_cards else (lines[0][1] if lines else "Unknown")

    supporter_keywords = {"ball", "order", "catcher", "stretcher", "belt", "candy", "poffin"}
    support_names = [
        name for _cnt, name, _tid in lines
        if any(kw in name.lower() for kw in supporter_keywords)
    ][:3]
    support_cards = ", ".join(support_names) or "various trainer cards"

    strategy = f"Attacking with {main_attacker}"

    prompt = DECK_NAME_PROMPT.format(
        main_attacker=main_attacker,
        support_cards=support_cards,
        strategy=strategy,
    )
    payload = {
        "model": settings.OLLAMA_COACH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 20},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            name = resp.json().get("message", {}).get("content", "").strip()
            name = re.sub(r"[\"']", "", name).strip()
            return name if name else None
    except Exception as exc:
        logger.debug("Gemma deck naming failed: %s", exc)
        return None


def _fallback_deck_name(deck_text: str) -> str:
    """Return a fallback deck name by finding the first 'ex' Pokémon."""
    lines = _parse_deck_lines(deck_text)
    for _cnt, name, _tid in lines:
        if " ex" in name.lower() or name.lower().endswith("ex"):
            return f"{name} Deck"
    return "Custom Deck"


async def _create_deck_record(
    deck_text: str,
    name: str,
    archetype: str,
    source: str,
    db: AsyncSession,
) -> "Deck":
    """Insert a Deck row and return it (without DeckCard rows)."""
    card_count = count_deck_cards(deck_text)
    deck = Deck(
        name=name,
        archetype=archetype,
        deck_text=deck_text,
        card_count=card_count,
        source=source,
    )
    db.add(deck)
    await db.flush()
    return deck


# ---------------------------------------------------------------------------
# POST /api/simulations
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_simulation(
    body: SimulationCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create and enqueue a new simulation."""
    # ── deck card-count validation ──────────────────────────────────────────
    user_card_count = count_deck_cards(body.deck_text)
    if body.deck_mode != "none":
        if user_card_count != 60:
            raise HTTPException(
                status_code=422,
                detail=f"Deck must contain exactly 60 cards (got {user_card_count})",
            )
    elif body.deck_text.strip() and user_card_count != 60:
        raise HTTPException(
            status_code=422,
            detail=f"Provided deck_text must contain exactly 60 cards (got {user_card_count})",
        )

    warning: Optional[str] = None

    # ── historical match count check ────────────────────────────────────────
    if body.deck_mode in ("partial", "none"):
        count_result = await db.execute(select(func.count()).select_from(Match))
        total_matches = count_result.scalar() or 0
        if total_matches < MINIMUM_MATCHES_RECOMMENDED:
            warning = (
                f"Only {total_matches:,} historical matches available; "
                f"at least {MINIMUM_MATCHES_RECOMMENDED:,} are recommended for "
                f"deck_mode='{body.deck_mode}' to produce reliable results."
            )

    # ── attempt Gemma deck naming ────────────────────────────────────────────
    deck_name = None
    if body.deck_text.strip():
        deck_name = await _get_deck_name_from_gemma(body.deck_text)
        if not deck_name:
            deck_name = _fallback_deck_name(body.deck_text)

    # ── create user deck record ─────────────────────────────────────────────
    user_deck = None
    if body.deck_text.strip():
        user_deck = await _create_deck_record(
            deck_text=body.deck_text,
            name=deck_name or "User Deck",
            archetype=deck_name or "Unknown",
            source="user",
            db=db,
        )

    # ── create simulation record ─────────────────────────────────────────────
    target_win_rate_int = int(round(body.target_win_rate * 100))
    sim = Simulation(
        status="pending",
        game_mode=body.game_mode,
        deck_mode=body.deck_mode,
        deck_locked=body.deck_locked,
        user_deck_id=user_deck.id if user_deck else None,
        matches_per_opponent=body.matches_per_opponent,
        num_rounds=body.num_rounds,
        target_win_rate=target_win_rate_int,
        target_mode="aggregate",
        excluded_cards=body.excluded_card_ids,
        user_deck_name=deck_name,
    )
    db.add(sim)
    await db.flush()

    # ── create opponent deck records ─────────────────────────────────────────
    for idx, opp_text in enumerate(body.opponent_deck_texts):
        opp_count = count_deck_cards(opp_text)
        if opp_count != 60:
            raise HTTPException(
                status_code=422,
                detail=f"Opponent deck {idx + 1} must contain exactly 60 cards (got {opp_count})",
            )
        opp_deck = await _create_deck_record(
            deck_text=opp_text,
            name=f"Opponent {idx + 1}",
            archetype="Unknown",
            source="opponent",
            db=db,
        )
        opponent = SimulationOpponent(
            simulation_id=sim.id,
            deck_id=opp_deck.id,
            deck_name=opp_deck.name,
        )
        db.add(opponent)

    await db.commit()

    # ── update deck name on the Deck row ─────────────────────────────────────
    if user_deck and deck_name:
        user_deck.name = deck_name
        user_deck.archetype = deck_name
        db.add(user_deck)
        await db.commit()

    # ── enqueue Celery task ──────────────────────────────────────────────────
    run_simulation.delay(str(sim.id))

    response: dict = {"simulation_id": str(sim.id), "status": "pending"}
    if warning:
        response["warning"] = warning
    return response


# ---------------------------------------------------------------------------
# GET /api/simulations/
# ---------------------------------------------------------------------------

@router.get("/")
async def list_simulations(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return a summary list of all simulations, newest first."""
    rows = (await db.execute(
        select(Simulation).order_by(Simulation.created_at.desc())
    )).scalars().all()
    return [
        {
            "id": str(s.id),
            "status": s.status,
            "game_mode": s.game_mode,
            "deck_mode": s.deck_mode,
            "num_rounds": s.num_rounds,
            "rounds_completed": s.rounds_completed,
            "total_matches": s.total_matches,
            "final_win_rate": (s.final_win_rate / 100.0) if s.final_win_rate is not None else None,
            "user_deck_name": s.user_deck_name,
            "starred": s.starred,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}")
async def get_simulation(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return full simulation detail."""
    try:
        sim_uuid = __import__("uuid").UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    row = (await db.execute(
        select(Simulation).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    return {
        "id": str(row.id),
        "status": row.status,
        "game_mode": row.game_mode,
        "deck_mode": row.deck_mode,
        "deck_locked": row.deck_locked,
        "num_rounds": row.num_rounds,
        "rounds_completed": row.rounds_completed,
        "matches_per_opponent": row.matches_per_opponent,
        "total_matches": row.total_matches,
        "target_win_rate": row.target_win_rate / 100.0 if row.target_win_rate is not None else None,
        "final_win_rate": row.final_win_rate / 100.0 if row.final_win_rate is not None else None,
        "user_deck_name": row.user_deck_name,
        "starred": row.starred,
        "error_message": row.error_message,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/rounds
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/rounds")
async def get_simulation_rounds(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all rounds for a simulation."""
    try:
        sim_uuid = __import__("uuid").UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    rows = (await db.execute(
        select(Round)
        .where(Round.simulation_id == sim_uuid)
        .order_by(Round.round_number)
    )).scalars().all()

    return [
        {
            "id": str(r.id),
            "round_number": r.round_number,
            "win_rate": r.win_rate / 100.0 if r.win_rate is not None else None,
            "total_matches": r.total_matches,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/mutations
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/mutations")
async def get_simulation_mutations(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all deck mutations for a simulation."""
    try:
        sim_uuid = __import__("uuid").UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    rows = (await db.execute(
        select(DeckMutation)
        .where(DeckMutation.simulation_id == sim_uuid)
        .order_by(DeckMutation.round_number, DeckMutation.created_at)
    )).scalars().all()

    return [
        {
            "id": str(m.id),
            "round_number": m.round_number,
            "card_removed": m.card_removed,
            "card_added": m.card_added,
            "reasoning": m.reasoning,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /api/simulations/{id}/star
# ---------------------------------------------------------------------------

@router.patch("/{simulation_id}/star")
async def star_simulation(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle the starred flag for a simulation."""
    try:
        sim_uuid = __import__("uuid").UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    row = (await db.execute(
        select(Simulation).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    row.starred = not row.starred
    await db.commit()
    return {"starred": row.starred}


# ---------------------------------------------------------------------------
# DELETE /api/simulations/{id}
# ---------------------------------------------------------------------------

@router.delete("/{simulation_id}", status_code=204)
async def delete_simulation(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a simulation and all its associated data."""
    try:
        sim_uuid = __import__("uuid").UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    row = (await db.execute(
        select(Simulation).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/events
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/events")
async def get_simulation_events(
    simulation_id: str,
    limit: int = 500,
    before_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return paginated match events for a simulation, newest-last (chronological).

    Pagination: use ``before_id=<smallest id from previous page>`` to load earlier events.
    Response: ``{ events, total, has_more }``
    """
    import uuid as _uuid_mod

    try:
        sim_uuid = _uuid_mod.UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    # Verify simulation exists
    sim_exists = (await db.execute(
        select(Simulation.id).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if sim_exists is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    limit = max(1, min(limit, 1000))

    # Total event count for this simulation
    total_q = (
        select(func.count(MatchEvent.id))
        .join(Match, MatchEvent.match_id == Match.id)
        .where(Match.simulation_id == sim_uuid)
    )
    total: int = (await db.execute(total_q)).scalar() or 0

    # Build base query
    base_q = (
        select(
            MatchEvent.id,
            MatchEvent.event_type,
            MatchEvent.turn,
            MatchEvent.player,
            MatchEvent.data,
            Match.round_number,
            Match.id.label("match_id"),
            Match.p1_deck_name,
            Match.p2_deck_name,
        )
        .join(Match, MatchEvent.match_id == Match.id)
        .where(Match.simulation_id == sim_uuid)
    )

    if before_id is not None:
        # Load events older than before_id (cursor-based, going backwards)
        events_q = (
            base_q
            .where(MatchEvent.id < before_id)
            .order_by(MatchEvent.id.desc())
            .limit(limit)
        )
    else:
        # Initial load: return the last `limit` events (newest)
        events_q = (
            base_q
            .order_by(MatchEvent.id.desc())
            .limit(limit)
        )

    rows = (await db.execute(events_q)).all()
    # Reverse so oldest-first (chronological) for frontend display
    rows = list(reversed(rows))

    events = [
        {
            "id": int(r.id),
            "type": "match_event",
            "event_type": r.event_type,
            "round_number": r.round_number,
            "match_id": str(r.match_id),
            "p1_deck_name": r.p1_deck_name,
            "p2_deck_name": r.p2_deck_name,
            "turn": r.turn,
            "player": r.player,
            "data": r.data or {},
        }
        for r in rows
    ]

    # has_more: are there events older than the oldest one we returned?
    has_more = False
    if events:
        oldest_id = events[0]["id"]
        count_older = (await db.execute(
            select(func.count(MatchEvent.id))
            .join(Match, MatchEvent.match_id == Match.id)
            .where(Match.simulation_id == sim_uuid, MatchEvent.id < oldest_id)
        )).scalar() or 0
        has_more = count_older > 0

    return {"events": events, "total": total, "has_more": has_more}


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/decisions
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/decisions")
async def get_simulation_decisions(
    simulation_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return paginated AI decisions for a simulation.

    Only populated for ai_h / ai_ai game modes.
    """
    import uuid as _uuid_mod

    try:
        sim_uuid = _uuid_mod.UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    total: int = (await db.execute(
        select(func.count(Decision.id)).where(Decision.simulation_id == sim_uuid)
    )).scalar() or 0

    rows = (await db.execute(
        select(Decision)
        .where(Decision.simulation_id == sim_uuid)
        .order_by(Decision.created_at.asc())
        .limit(limit)
        .offset(offset)
    )).scalars().all()

    return {
        "decisions": [
            {
                "id": str(d.id),
                "match_id": str(d.match_id) if d.match_id else None,
                "turn_number": d.turn_number,
                "player_id": d.player_id,
                "action_type": d.action_type,
                "card_played": d.card_played,
                "target": d.target,
                "reasoning": d.reasoning,
                "legal_action_count": d.legal_action_count,
                "game_state_summary": d.game_state_summary,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ],
        "total": total,
    }


# ---------------------------------------------------------------------------
# POST /api/simulations/{id}/cancel
# ---------------------------------------------------------------------------

@router.post("/{simulation_id}/cancel")
async def cancel_simulation(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a running or pending simulation.

    Sets status to 'cancelled' in the DB and publishes a cancellation event
    to the Redis channel.  The Celery task checks for cancellation at the
    start of each round and will stop cleanly on the next check.
    """
    import uuid as _uuid_mod

    try:
        sim_uuid = _uuid_mod.UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    row = (await db.execute(
        select(Simulation).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    if row.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel simulation with status '{row.status}'"
        )

    row.status = "cancelled"
    await db.commit()

    # Publish cancellation to Redis so the WebSocket client sees it immediately
    try:
        r = redis_module.Redis.from_url(settings.REDIS_URL)
        channel = f"simulation:{simulation_id}"
        r.publish(channel, json.dumps({
            "type": "simulation_cancelled",
            "simulation_id": simulation_id,
        }))
        r.close()
    except Exception as exc:
        logger.warning("Redis publish failed during cancel: %s", exc)

    return {"cancelled": True, "id": simulation_id}


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/matches
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/matches")
async def get_simulation_matches(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all matches for a simulation with outcome and prize data.

    Used by the reporting dashboard for tiles 5 (opponent win rates),
    7 (matchup matrix), 8 (win-rate distribution), and 9 (prize race).
    """
    import uuid as _uuid_mod

    try:
        sim_uuid = _uuid_mod.UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    sim_exists = (await db.execute(
        select(Simulation.id).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if sim_exists is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    rows = (await db.execute(
        select(Match)
        .where(Match.simulation_id == sim_uuid)
        .order_by(Match.round_number, Match.created_at)
    )).scalars().all()

    return [
        {
            "id": str(m.id),
            "round_number": m.round_number,
            "winner": m.winner,
            "win_condition": m.win_condition,
            "total_turns": m.total_turns,
            "p1_prizes_taken": m.p1_prizes_taken,
            "p2_prizes_taken": m.p2_prizes_taken,
            "p1_deck_name": m.p1_deck_name,
            "p2_deck_name": m.p2_deck_name,
            "opponent_deck_id": str(m.opponent_deck_id) if m.opponent_deck_id else None,
        }
        for m in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/prize-race
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/prize-race")
async def get_simulation_prize_race(
    simulation_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return prize progression data for the prize race graph (Tile 9).

    Derives per-match prize curves from ``prizes_taken`` match events.
    Returns:
      - ``matches``: list of {match_id, round_number, p1_deck_name,
        p2_deck_name, turns: [{turn, p1_cumulative, p2_cumulative}]}
      - ``average``: [{turn, p1_avg, p2_avg}] averaged across all matches
    """
    import uuid as _uuid_mod

    try:
        sim_uuid = _uuid_mod.UUID(simulation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid simulation_id format")

    sim_exists = (await db.execute(
        select(Simulation.id).where(Simulation.id == sim_uuid)
    )).scalar_one_or_none()
    if sim_exists is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    # Fetch all matches for this simulation
    match_rows = (await db.execute(
        select(Match).where(Match.simulation_id == sim_uuid).order_by(Match.created_at)
    )).scalars().all()

    if not match_rows:
        return {"matches": [], "average": []}

    match_ids = [m.id for m in match_rows]
    match_meta = {m.id: m for m in match_rows}

    # Fetch all prizes_taken events for these matches in one query
    events = (await db.execute(
        select(
            MatchEvent.match_id,
            MatchEvent.turn,
            MatchEvent.data,
        )
        .where(
            MatchEvent.match_id.in_(match_ids),
            MatchEvent.event_type == "prizes_taken",
        )
        .order_by(MatchEvent.match_id, MatchEvent.id)
    )).all()

    # Build per-match turn-indexed prize curves
    from collections import defaultdict
    events_by_match: dict = defaultdict(list)
    for ev in events:
        events_by_match[ev.match_id].append(ev)

    per_match = []
    max_turn = 0

    for m in match_rows:
        p1_cum = 0
        p2_cum = 0
        turns: list[dict] = []
        last_turn = 0

        for ev in events_by_match.get(m.id, []):
            turn = ev.turn or 0
            data = ev.data or {}
            count = int(data.get("count", 1))
            taker = data.get("taking_player", "p1")

            if taker == "p1":
                p1_cum += count
            else:
                p2_cum += count

            # Extend to current turn if there are gaps
            if turn > last_turn + 1:
                turns.append({"turn": last_turn + 1, "p1_cumulative": p1_cum - (count if taker == "p1" else 0), "p2_cumulative": p2_cum - (count if taker == "p2" else 0)})
            turns.append({"turn": turn, "p1_cumulative": p1_cum, "p2_cumulative": p2_cum})
            last_turn = turn

        # Extend curve to final turn if needed
        total_turns = m.total_turns or last_turn
        if total_turns > last_turn:
            turns.append({"turn": total_turns, "p1_cumulative": p1_cum, "p2_cumulative": p2_cum})

        max_turn = max(max_turn, total_turns)

        per_match.append({
            "match_id": str(m.id),
            "round_number": m.round_number,
            "p1_deck_name": m.p1_deck_name,
            "p2_deck_name": m.p2_deck_name,
            "turns": turns,
        })

    # Compute average curve across all matches
    average: list[dict] = []
    if per_match and max_turn > 0:
        for t in range(1, max_turn + 1):
            p1_vals = []
            p2_vals = []
            for pm in per_match:
                # Find last known value at or before turn t
                p1_at_t = 0
                p2_at_t = 0
                for pt in pm["turns"]:
                    if pt["turn"] <= t:
                        p1_at_t = pt["p1_cumulative"]
                        p2_at_t = pt["p2_cumulative"]
                p1_vals.append(p1_at_t)
                p2_vals.append(p2_at_t)
            average.append({
                "turn": t,
                "p1_avg": round(sum(p1_vals) / len(p1_vals), 2),
                "p2_avg": round(sum(p2_vals) / len(p2_vals), 2),
            })

    return {"matches": per_match, "average": average}
