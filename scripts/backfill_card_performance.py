#!/usr/bin/env python3
"""Rebuild historical card_performance aggregates from persisted matches."""

from __future__ import annotations

import asyncio

from app.db.session import AsyncSessionLocal
from app.memory.backfill import backfill_card_performance


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await backfill_card_performance(db)
        await db.commit()
    print(
        "Backfilled card_performance: "
        f"{result.deck_cards_inserted} deck_cards inserted, "
        f"{result.matches_processed} matches processed, "
        f"{result.card_performance_rows} card rows rebuilt."
    )


if __name__ == "__main__":
    asyncio.run(main())
