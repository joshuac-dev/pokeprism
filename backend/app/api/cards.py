"""Stub router for cards API (Phase 8)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/cards/", tags=["cards"])
async def list_cards():
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")


@router.get("/cards/{card_id}", tags=["cards"])
async def get_card(card_id: str):
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")
