"""TCGDex REST API client.

DEVIATION FROM BLUEPRINT (§7.2):
  The blueprint specifies endpoint /cards/{setCode}/{cardNumber}.
  The actual TCGDex API only accepts /cards/{setId}-{localId} (full card ID).
  Example: /cards/sv06-130  (NOT /cards/sv06/130)
  Verified live: curl https://api.tcgdex.net/v2/en/cards/sv06-130 → Dragapult ex
  The /cards/{setId}/{localId} path returns ERROR for all tested values.
"""

from __future__ import annotations

import logging
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TCGDexClient:
    """Async client for the TCGDex REST API (https://api.tcgdex.net/v2/en).

    All card data originates here — nothing is hardcoded.
    Card numbers are zero-padded to 3 digits (e.g. "11" → "011").
    """

    def __init__(self, base_url: str | None = None):
        self._base_url = (base_url or settings.TCGDEX_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=30.0,
                headers={"User-Agent": "PokePrism/1.0"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "TCGDexClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Core fetch methods
    # ──────────────────────────────────────────────────────────────────────────

    async def get_card(self, tcgdex_set_id: str, card_number: str | int) -> dict:
        """Fetch a single card by TCGDex set ID and local number.

        Args:
            tcgdex_set_id: e.g. "sv06", "me01", "mee"
            card_number:   e.g. 130, "130", "11" — zero-padded internally to 3 digits

        Returns:
            Raw TCGDex card dict.

        Raises:
            httpx.HTTPStatusError: on non-2xx response (caller should handle).
        """
        local_id = str(card_number).zfill(3)
        card_id = f"{tcgdex_set_id}-{local_id}"
        response = await self.client.get(f"/cards/{card_id}")
        response.raise_for_status()
        return response.json()

    async def get_set(self, tcgdex_set_id: str) -> dict:
        """Fetch set metadata including the full card list."""
        response = await self.client.get(f"/sets/{tcgdex_set_id}")
        response.raise_for_status()
        return response.json()

    async def search_cards(self, name: str) -> list[dict]:
        """Search cards by exact name. Useful as a fallback when direct fetch fails."""
        response = await self.client.get("/cards", params={"name": name})
        response.raise_for_status()
        return response.json()

    async def get_card_raw(
        self, tcgdex_set_id: str, card_number: str | int
    ) -> dict | None:
        """Like get_card but returns None instead of raising on 404."""
        try:
            return await self.get_card(tcgdex_set_id, card_number)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def list_sets(self) -> list[dict]:
        """Return all sets known to TCGDex."""
        response = await self.client.get("/sets")
        response.raise_for_status()
        return response.json()
