"""Cards API endpoints — list, search, and single-card detail."""

from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card
from app.db.session import AsyncSessionLocal

router = APIRouter()


def card_image_url(raw: str | None) -> str | None:
    """Return a browser-renderable image URL.

    The DB stores bare TCGDex asset paths (e.g. ``.../sv06/130``) which
    serve ``text/html`` without a format suffix.  Appending ``/high.webp``
    returns ``image/webp`` and renders correctly in browsers.
    """
    if not raw:
        return None
    if raw.endswith(".webp") or raw.endswith(".png") or raw.endswith(".jpg"):
        return raw
    return raw + "/high.webp"


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/cards/search", tags=["cards"])
async def search_cards(
    q: str = Query(..., min_length=1, description="Card name search query"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Search cards by name using pg_trgm fuzzy matching."""
    stmt = (
        select(Card.tcgdex_id, Card.name, Card.set_abbrev, Card.set_number, Card.category, Card.image_url)
        .where(Card.name.ilike(f"%{q}%"))
        .order_by(func.similarity(Card.name, q).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "tcgdex_id": r.tcgdex_id,
            "name": r.name,
            "set_abbrev": r.set_abbrev,
            "set_number": r.set_number,
            "category": r.category,
            "image_url": card_image_url(r.image_url),
        }
        for r in rows
    ]


@router.get("/cards", tags=["cards"])
async def list_cards(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = Query(None, description="Filter by category: pokemon/trainer/energy"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all cards, paginated and optionally filtered by category."""
    base_filter = Card.category == category if category else True
    stmt = (
        select(Card)
        .where(base_filter)
        .order_by(Card.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    count_stmt = select(func.count(Card.tcgdex_id)).where(base_filter)
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "cards": [_card_summary(c) for c in rows],
    }


@router.get("/cards/{card_id}", tags=["cards"])
async def get_card(card_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Get full card details by tcgdex_id."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card '{card_id}' not found")
    return _card_detail(card)


# ── helpers ────────────────────────────────────────────────────────────────────

def _card_summary(card: Card) -> dict:
    return {
        "tcgdex_id": card.tcgdex_id,
        "name": card.name,
        "set_abbrev": card.set_abbrev,
        "set_number": card.set_number,
        "category": card.category,
        "subcategory": card.subcategory,
        "hp": card.hp,
        "types": card.types,
        "image_url": card_image_url(card.image_url),
    }


def _card_detail(card: Card) -> dict:
    return {
        **_card_summary(card),
        "evolve_from": card.evolve_from,
        "stage": card.stage,
        "attacks": card.attacks,
        "abilities": card.abilities,
        "weaknesses": card.weaknesses,
        "resistances": card.resistances,
        "retreat_cost": card.retreat_cost,
        "regulation_mark": card.regulation_mark,
        "rarity": card.rarity,
    }
