"""Embedding generation via Ollama and storage in pgvector."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Embedding
from app.db.session import AsyncSessionLocal


class EmbeddingService:
    """Generate text embeddings via Ollama and persist to pgvector.

    Uses nomic-embed-text (768 dimensions) by default.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model or settings.OLLAMA_EMBED_MODEL

    async def embed(self, text: str) -> list[float]:
        """Return a 768-dimensional embedding vector for *text*."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            response.raise_for_status()
            return response.json()["embedding"]

    async def embed_and_store(
        self,
        text: str,
        source_type: str,
        source_id: str,
        db: AsyncSession,
    ) -> uuid.UUID:
        """Embed *text*, persist to the embeddings table, return the row UUID."""
        vector = await self.embed(text)
        emb = Embedding(
            source_type=source_type,
            source_id=source_id,
            content_text=text,
            embedding=vector,
        )
        db.add(emb)
        await db.flush()
        return emb.id

    def game_state_text(
        self,
        match_id: str,
        turn: int,
        player_active: str,
        player_active_hp: int,
        player_active_max_hp: int,
        bench_names: list[str],
        hand_size: int,
        prizes_remaining: int,
        opp_active: str,
        opp_active_hp: int,
        opp_bench_count: int,
        opp_prizes_remaining: int,
    ) -> str:
        """Build a human-readable game-state string suitable for embedding."""
        return (
            f"Turn {turn}. "
            f"Active: {player_active} ({player_active_hp}/{player_active_max_hp} HP). "
            f"Bench: {', '.join(bench_names) or 'none'}. "
            f"Hand size: {hand_size}. Prizes left: {prizes_remaining}. "
            f"Opponent active: {opp_active} ({opp_active_hp} HP). "
            f"Opponent bench size: {opp_bench_count}. "
            f"Opponent prizes: {opp_prizes_remaining}."
        )


class SimilarSituationFinder:
    """Find past AI decisions with similar game states using pgvector cosine search."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._embed_svc = EmbeddingService()

    async def find_similar(
        self,
        text: str,
        k: int = 5,
        source_type: str = "decision",
    ) -> list[dict]:
        """Embed *text* and return the k nearest stored embeddings.

        Returns list of {source_id, content_text, distance}.
        Returns empty list if no embeddings exist for the given source_type.
        """
        query_vector = await self._embed_svc.embed(text)

        # Increase IVFFlat probes so small datasets are fully scanned.
        # Default probes=1 misses most results when lists >> sqrt(n).
        await self._db.execute(sa_text("SET LOCAL ivfflat.probes = 20"))

        rows = (await self._db.execute(
            select(
                Embedding.source_id,
                Embedding.content_text,
                Embedding.embedding.cosine_distance(query_vector).label("distance"),
            )
            .where(Embedding.source_type == source_type)
            .order_by(Embedding.embedding.cosine_distance(query_vector))
            .limit(k)
        )).all()

        return [
            {
                "source_id": row.source_id,
                "content_text": row.content_text,
                "distance": float(row.distance),
            }
            for row in rows
        ]
