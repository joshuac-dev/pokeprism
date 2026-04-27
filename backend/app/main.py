"""FastAPI application factory.

Mounts the socket.io ASGI app at /ws and includes the REST API router.
Call ``create_app()`` to get the ASGI application instance.
"""

from __future__ import annotations

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.ws import sio


def create_app() -> FastAPI:
    app = FastAPI(
        title="PokéPrism API",
        description="Self-hosted Pokémon TCG simulation and deck evolution engine.",
        version="0.7.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    # Health check (no prefix, no auth)
    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok"}

    # Mount socket.io at /ws
    app.mount("/ws", socketio.ASGIApp(sio))

    return app


# ASGI entry point for uvicorn (e.g. `uvicorn app.main:app`)
app = create_app()
