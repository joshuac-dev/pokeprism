"""Stub router for match history API (Phase 11)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/history/", tags=["history"])
async def list_history():
    raise HTTPException(status_code=501, detail="Not implemented until Phase 11")


@router.get("/history/{match_id}", tags=["history"])
async def get_match(match_id: str):
    raise HTTPException(status_code=501, detail="Not implemented until Phase 11")
