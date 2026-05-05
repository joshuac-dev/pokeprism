"""Coverage endpoint — reports effect-handler implementation status for every card in DB."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card
from app.db.session import AsyncSessionLocal
from app.api.cards import card_image_url

router = APIRouter()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _card_needs_handlers(card_def: dict) -> bool:
    """Return True if this card has any effects that require registered handlers."""
    category = (card_def.get("category") or "").lower()
    subcategory = (card_def.get("subcategory") or "").lower()
    if category == "trainer":
        return True
    if category == "energy" and subcategory == "special":
        return True
    if category == "pokemon":
        for atk in card_def.get("attacks") or []:
            if (atk.get("effect") or "").strip():
                return True
        if card_def.get("abilities"):
            return True
    return False


@router.get("")
async def get_coverage(db: AsyncSession = Depends(get_db)) -> dict:
    """Return per-card effect-handler coverage for every card in the database."""
    from app.engine.effects.registry import EffectRegistry

    registry = EffectRegistry.instance()

    result = await db.execute(
        select(Card).order_by(Card.category, Card.name)
    )
    all_cards = result.scalars().all()

    cards_out: list[dict] = []
    total = implemented = flat_only = missing_count = 0

    for row in all_cards:
        if row.tcgdex_id == "test-002":
            continue  # test fixture — skip coverage check

        card_dict = {
            "tcgdex_id": row.tcgdex_id,
            "category": row.category or "",
            "subcategory": row.subcategory or "",
            "attacks": row.attacks or [],
            "abilities": row.abilities or [],
        }

        missing_effects = registry.check_card_coverage(card_dict)
        needs_handlers = _card_needs_handlers(card_dict)

        total += 1
        if missing_effects:
            status = "missing"
            missing_count += 1
        elif needs_handlers:
            status = "implemented"
            implemented += 1
        else:
            status = "flat_only"
            flat_only += 1

        cards_out.append({
            "tcgdex_id": row.tcgdex_id,
            "name": row.name,
            "set_abbrev": row.set_abbrev,
            "set_number": row.set_number,
            "category": row.category,
            "subcategory": row.subcategory,
            "status": status,
            "missing_effects": missing_effects,
            "image_url": card_image_url(row.image_url),
        })

    coverage_pct = round(100.0 * (implemented + flat_only) / max(total, 1), 1)

    return {
        "total": total,
        "implemented": implemented,
        "flat_only": flat_only,
        "missing": missing_count,
        "coverage_pct": coverage_pct,
        "cards": cards_out,
    }
