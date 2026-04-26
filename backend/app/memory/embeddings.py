"""Embedding generation via Ollama and storage in pgvector."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.db.models import Embedding
from app.db.session import AsyncSessionLocal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
