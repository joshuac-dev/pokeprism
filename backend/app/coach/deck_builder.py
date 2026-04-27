"""DeckBuilder scaffold — full implementation requires MINIMUM_MATCHES_RECOMMENDED games."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.cards.models import CardDefinition

MINIMUM_MATCHES_RECOMMENDED = 5_000
"""Minimum historical matches before DeckBuilder has sufficient data to operate."""


class DeckBuilder:
    """Builds or completes a deck using historical performance data.

    Not yet implemented — requires at least {n} matches in the database.
    """.format(n=MINIMUM_MATCHES_RECOMMENDED)

    def complete_deck(
        self,
        partial_deck: list[CardDefinition],
        target_size: int = 60,
    ) -> list[CardDefinition]:
        """Fill *partial_deck* up to *target_size* cards using top-performing candidates.

        TODO: implement once MINIMUM_MATCHES_RECOMMENDED matches are available.
        """
        raise NotImplementedError(
            f"DeckBuilder.complete_deck requires {MINIMUM_MATCHES_RECOMMENDED:,} "
            "historical matches. Run more simulations first."
        )

    def build_from_scratch(
        self,
        avoid_meta: bool = True,
    ) -> list[CardDefinition]:
        """Generate a full 60-card deck from historical win-rate data.

        TODO: implement once MINIMUM_MATCHES_RECOMMENDED matches are available.
        """
        raise NotImplementedError(
            f"DeckBuilder.build_from_scratch requires {MINIMUM_MATCHES_RECOMMENDED:,} "
            "historical matches. Run more simulations first."
        )
