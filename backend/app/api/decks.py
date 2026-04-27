"""Stub API routers for Phases 8–11 (not yet implemented)."""

from fastapi import APIRouter

router = APIRouter()

_NOT_IMPLEMENTED = {"detail": "Not implemented until Phase 8"}


@router.get("/decks/", tags=["decks"])
async def list_decks():
    from fastapi import HTTPException
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")


@router.get("/decks/{deck_id}", tags=["decks"])
async def get_deck(deck_id: str):
    from fastapi import HTTPException
    raise HTTPException(status_code=501, detail="Not implemented until Phase 8")
