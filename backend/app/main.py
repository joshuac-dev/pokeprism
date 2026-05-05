"""FastAPI application factory.

The socket.io ASGI app wraps FastAPI so socket.io handles /socket.io/* paths
and falls through to FastAPI for everything else. Connect clients to /socket.io.
Call ``create_app()`` to get the ASGI application instance.
"""

from __future__ import annotations

import logging

import httpx
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.ws import sio
from app.config import settings

logger = logging.getLogger(__name__)


def _warn_if_log_root_not_writable() -> None:
    """Warn at startup if the ptcgl_logs directory is missing or not writable."""
    import os
    from app.observed_play.storage import OBSERVED_PLAY_ROOT, ensure_observed_play_dirs
    try:
        ensure_observed_play_dirs()
        # Quick write-permission probe
        probe = OBSERVED_PLAY_ROOT / ".write_probe"
        probe.write_bytes(b"")
        probe.unlink()
    except Exception as exc:
        logger.warning(
            "Observed Play log root %s is not writable: %s — "
            "uploads will fail until permissions are fixed (chown -R app:app %s).",
            OBSERVED_PLAY_ROOT, exc, OBSERVED_PLAY_ROOT,
        )


def create_app() -> socketio.ASGIApp:
    fastapi_app = FastAPI(
        title="PokéPrism API",
        description="Self-hosted Pokémon TCG simulation and deck evolution engine.",
        version="0.7.0",
    )

    _warn_if_log_root_not_writable()

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.cors_origins_list == "*" else settings.cors_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(api_router, prefix="/api")

    # Health check (no prefix, no auth)
    @fastapi_app.get("/health", tags=["meta"])
    async def health() -> dict:
        checks: dict[str, object] = {}

        # Postgres
        try:
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import text
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
                row = await db.execute(text("SELECT count(*) FROM simulations WHERE status='running'"))
                active_sims = row.scalar_one()
                row2 = await db.execute(text("SELECT count(*) FROM matches"))
                total_matches = row2.scalar_one()
            checks["postgres"] = "ok"
            checks["active_simulations"] = active_sims
            checks["total_matches"] = total_matches
        except Exception as exc:
            logger.warning("Health: postgres check failed: %s", exc)
            checks["postgres"] = f"error: {exc}"
            checks["active_simulations"] = -1
            checks["total_matches"] = -1

        # Neo4j
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            await driver.verify_connectivity()
            await driver.close()
            checks["neo4j"] = "ok"
        except Exception as exc:
            logger.warning("Health: neo4j check failed: %s", exc)
            checks["neo4j"] = f"error: {exc}"

        # Redis
        try:
            import redis as _redis
            r = _redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
            r.ping()
            r.close()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning("Health: redis check failed: %s", exc)
            checks["redis"] = f"error: {exc}"

        # Ollama connectivity + available models
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
            checks["ollama"] = "ok"
            checks["ollama_models"] = models
        except Exception as exc:
            logger.warning("Health: ollama check failed: %s", exc)
            checks["ollama"] = f"error: {exc}"
            checks["ollama_models"] = []

        # Celery workers
        try:
            from app.tasks.celery_app import celery_app
            i = celery_app.control.inspect(timeout=2)
            ping = i.ping()
            worker_count = len(ping) if ping else 0
            checks["celery_workers"] = worker_count
        except Exception as exc:
            logger.warning("Health: celery check failed: %s", exc)
            checks["celery_workers"] = -1

        overall = "ok" if all(
            v == "ok" for k, v in checks.items()
            if k in ("postgres", "neo4j", "redis", "ollama")
        ) else "degraded"
        return {"status": overall, **checks}

    # socket.io ASGI app wraps FastAPI so /socket.io/* is handled by socket.io
    # and all other paths fall through to FastAPI.
    asgi_app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
    # Expose FastAPI app for dependency_overrides in tests
    asgi_app.fastapi_app = fastapi_app  # type: ignore[attr-defined]
    return asgi_app


# ASGI entry point for uvicorn (e.g. `uvicorn app.main:app`)
app = create_app()
