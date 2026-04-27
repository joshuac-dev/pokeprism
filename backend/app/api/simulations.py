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
from app.db.models import Deck, DeckCard, DeckMutation, Match, Round, Simulation, SimulationOpponent
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
