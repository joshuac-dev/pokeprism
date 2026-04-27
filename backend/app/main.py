"""FastAPI application factory.

The socket.io ASGI app wraps FastAPI so socket.io handles /socket.io/* paths
and falls through to FastAPI for everything else. Connect clients to /socket.io.
Call ``create_app()`` to get the ASGI application instance.
"""

from __future__ import annotations

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.ws import sio


def create_app() -> socketio.ASGIApp:
    fastapi_app = FastAPI(
        title="PokéPrism API",
        description="Self-hosted Pokémon TCG simulation and deck evolution engine.",
        version="0.7.0",
    )

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(api_router, prefix="/api")

    # Health check (no prefix, no auth)
    @fastapi_app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok"}

    # socket.io ASGI app wraps FastAPI so /socket.io/* is handled by socket.io
    # and all other paths fall through to FastAPI.
    asgi_app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
    # Expose FastAPI app for dependency_overrides in tests
    asgi_app.fastapi_app = fastapi_app  # type: ignore[attr-defined]
    return asgi_app


# ASGI entry point for uvicorn (e.g. `uvicorn app.main:app`)
app = create_app()
