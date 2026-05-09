"""Deck API routes."""

from __future__ import annotations

from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.observed_play.archetype_labels import preview_deck_archetype_labels
from app.observed_play.schemas import DeckArchetypeLabelPreview

router = APIRouter()

_NOT_IMPLEMENTED = {"detail": "Not implemented until Phase 8"}


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/decks/", tags=["decks"])
async def list_decks():
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")


@router.get(
    "/decks/{deck_id}/archetype-label-preview",
    response_model=DeckArchetypeLabelPreview,
    tags=["decks"],
)
async def get_deck_archetype_label_preview(
    deck_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    preview = await preview_deck_archetype_labels(db, deck_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    return preview


@router.get("/decks/{deck_id}", tags=["decks"])
async def get_deck(deck_id: str):
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")
