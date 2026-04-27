"""Stub router for memory/embeddings API (Phase 11)."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/memory/", tags=["memory"])
async def list_memory():
    raise HTTPException(status_code=501, detail="Not implemented until Phase 11")


@router.get("/memory/similar", tags=["memory"])
async def find_similar():
    raise HTTPException(status_code=501, detail="Not implemented until Phase 11")
