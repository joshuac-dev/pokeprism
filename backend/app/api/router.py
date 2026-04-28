"""Central API router — aggregates all sub-routers."""

from fastapi import APIRouter

from app.api import decks, cards, history, memory, coverage
from app.api.simulations import router as simulations_router

api_router = APIRouter()

api_router.include_router(simulations_router, prefix="/simulations", tags=["simulations"])
api_router.include_router(decks.router, prefix="", tags=["decks"])
api_router.include_router(cards.router, prefix="", tags=["cards"])
api_router.include_router(history.router, prefix="", tags=["history"])
api_router.include_router(memory.router, prefix="", tags=["memory"])
api_router.include_router(coverage.router, prefix="/coverage", tags=["coverage"])
