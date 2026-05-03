"""Memory API — card profiles, synergy graph, and decision history.

Endpoints registered at ``/api/memory`` via ``app/api/router.py``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card, CardPerformance, Decision
from app.db.session import AsyncSessionLocal
from app.db.graph import graph_session
from app.api.cards import card_image_url

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# GET /api/memory/top-card
# ---------------------------------------------------------------------------

@router.get("/memory/top-card", tags=["memory"])
async def get_top_card(db: AsyncSession = Depends(get_db)) -> dict:
    """Return the most-played card by games_included.

    Returns ``{"card_id": "<tcgdex_id>"}`` or 204 if card_performance is empty.
    """
    row = (await db.execute(
        select(CardPerformance.card_tcgdex_id)
        .order_by(CardPerformance.games_included.desc())
        .limit(1)
    )).scalar_one_or_none()

    if row is None:
        from fastapi.responses import Response
        return Response(status_code=204)

    return {"card_id": row}


# ---------------------------------------------------------------------------
# GET /api/memory/card/{card_id}/profile
# ---------------------------------------------------------------------------

@router.get("/memory/card/{card_id}/profile", tags=["memory"])
async def get_card_profile(card_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Return card profile: performance stats + Neo4j top partners.

    Performance stats come from ``card_performance`` + ``cards`` tables.
    Partners come from the top-5 SYNERGIZES_WITH edges in Neo4j.
    """
    card = (await db.execute(
        select(Card).where(Card.tcgdex_id == card_id)
    )).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    perf = (await db.execute(
        select(CardPerformance).where(CardPerformance.card_tcgdex_id == card_id)
    )).scalar_one_or_none()

    stats = {
        "games_included": perf.games_included if perf else 0,
        "games_won": perf.games_won if perf else 0,
        "win_rate": round(perf.games_won / perf.games_included, 4) if (perf and perf.games_included) else 0.0,
        "total_kos": perf.total_kos or 0 if perf else 0,
        "total_damage": perf.total_damage or 0 if perf else 0,
        "total_prizes": perf.total_prizes or 0 if perf else 0,
    }

    partners: list[dict] = []
    try:
        async with graph_session() as session:
            result = await session.run(
                """
                MATCH (a:Card {tcgdex_id: $card_id})-[r:SYNERGIZES_WITH]-(b:Card)
                RETURN b.tcgdex_id AS id, b.name AS name, r.weight AS weight,
                       r.games_observed AS games_observed
                ORDER BY r.weight DESC
                LIMIT 5
                """,
                card_id=card_id,
            )
            partners = [
                {
                    "card_id": rec["id"],
                    "name": rec["name"],
                    "weight": rec["weight"],
                    "games_observed": rec["games_observed"],
                }
                async for rec in result
            ]
    except Exception:
        partners = []

    return {
        "card_id": card_id,
        "name": card.name,
        "set_abbrev": card.set_abbrev,
        "set_number": card.set_number,
        "category": card.category,
        "image_url": card_image_url(card.image_url),
        "stats": stats,
        "partners": partners,
    }


# ---------------------------------------------------------------------------
# GET /api/memory/graph
# ---------------------------------------------------------------------------

@router.get("/memory/graph", tags=["memory"])
async def get_memory_graph(
    card_id: str = Query(..., description="tcgdex_id of the focal card"),
    depth: int = Query(2, ge=1, le=3),
) -> dict:
    """Return a synergy graph centred on ``card_id`` up to ``depth`` hops.

    Returns ``{nodes, edges}`` capped at 100 nodes (top by edge weight).
    Nodes: ``{id, name, category, games_observed, win_rate}``.
    Edges: ``{source, target, weight, games_observed}``.
    """
    try:
        async with graph_session() as session:
            # Variable-length path ranges cannot use parameters in Cypher —
            # depth is validated (ge=1, le=3) so inlining as a literal is safe.
            result = await session.run(
                f"""
                MATCH (focal:Card {{tcgdex_id: $card_id}})
                MATCH path = (focal)-[:SYNERGIZES_WITH*1..{depth}]-(neighbor:Card)
                WITH focal, neighbor,
                     [(focal)-[r:SYNERGIZES_WITH]-(neighbor) | r][0] AS direct_edge
                RETURN DISTINCT
                    neighbor.tcgdex_id AS id,
                    neighbor.name AS name,
                    neighbor.category AS category,
                    direct_edge.weight AS weight,
                    direct_edge.games_observed AS games_observed
                ORDER BY direct_edge.weight DESC
                LIMIT 99
                """,
                card_id=card_id,
            )
            neighbor_records = [r.data() async for r in result]

            # Fetch the focal card itself.
            focal_result = await session.run(
                "MATCH (c:Card {tcgdex_id: $id}) RETURN c.name AS name, c.category AS category",
                id=card_id,
            )
            focal_data = await focal_result.single()

            # Collect all node IDs to fetch edges between them.
            all_ids = [card_id] + [r["id"] for r in neighbor_records if r["id"]]
            edge_result = await session.run(
                """
                MATCH (a:Card)-[r:SYNERGIZES_WITH]-(b:Card)
                WHERE a.tcgdex_id IN $ids AND b.tcgdex_id IN $ids
                  AND a.tcgdex_id < b.tcgdex_id
                RETURN a.tcgdex_id AS source, b.tcgdex_id AS target,
                       r.weight AS weight, r.games_observed AS games_observed
                """,
                ids=all_ids,
            )
            edge_records = [r.data() async for r in edge_result]

    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Graph query failed: {exc}")

    focal_name = focal_data["name"] if focal_data else card_id
    focal_category = focal_data["category"] if focal_data else None

    nodes = [{"id": card_id, "name": focal_name, "category": focal_category, "weight": None, "games_observed": None}]
    nodes += [
        {
            "id": r["id"],
            "name": r["name"] or r["id"],
            "category": r["category"],
            "weight": r["weight"],
            "games_observed": r["games_observed"],
        }
        for r in neighbor_records
        if r.get("id")
    ]

    edges = [
        {
            "source": r["source"],
            "target": r["target"],
            "weight": r["weight"],
            "games_observed": r["games_observed"],
        }
        for r in edge_records
    ]

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# GET /api/memory/card/{card_id}/decisions
# ---------------------------------------------------------------------------

@router.get("/memory/card/{card_id}/decisions", tags=["memory"])
async def get_card_decisions(
    card_id: str,
    offset: int = 0,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent AI decisions that involved ``card_id``.

    Filtered by ``card_def_id`` (populated for all decisions made after the
    Phase 11 migration). Existing decisions with NULL card_def_id are excluded.
    """
    total = (await db.execute(
        select(func.count()).select_from(Decision)
        .where(Decision.card_def_id == card_id)
    )).scalar() or 0

    rows = (await db.execute(
        select(Decision)
        .where(Decision.card_def_id == card_id)
        .order_by(Decision.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    decisions = [
        {
            "id": str(d.id),
            "match_id": str(d.match_id) if d.match_id else None,
            "turn_number": d.turn_number,
            "player_id": d.player_id,
            "action_type": d.action_type,
            "card_def_id": d.card_def_id,
            "reasoning": d.reasoning,
            "legal_action_count": d.legal_action_count,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]

    return {"decisions": decisions, "total": total, "offset": offset, "limit": limit}

