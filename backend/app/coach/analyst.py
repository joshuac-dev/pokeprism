"""CoachAnalyst: analyzes round results and proposes deck mutations via Gemma 4."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.coach.prompts import COACH_EVOLUTION_PROMPT
from app.db.models import DeckMutation
from app.memory.embeddings import SimilarSituationFinder
from app.memory.graph import GraphQueries
from app.memory.postgres import CardPerformanceQueries

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.engine.batch import MatchResult
    from app.cards.models import CardDefinition

logger = logging.getLogger(__name__)


class CoachAnalyst:
    """Post-round Coach that queries memory and proposes 0–N card swaps.

    Uses Gemma 4 E4B (OLLAMA_COACH_MODEL) for reasoning.
    Each instance is tied to an async DB session and Neo4j driver.
    """

    def __init__(
        self,
        db: AsyncSession,
        model: str | None = None,
        max_swaps: int = 4,
    ) -> None:
        self._db = db
        self._model = model or settings.OLLAMA_COACH_MODEL
        self._max_swaps = max_swaps
        self._card_perf = CardPerformanceQueries(db)
        self._similar = SimilarSituationFinder(db)
        self._graph = GraphQueries()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_and_mutate(
        self,
        current_deck: list[CardDefinition],
        round_results: list[MatchResult],
        simulation_id: uuid.UUID,
        round_number: int,
        candidate_card_ids: list[str] | None = None,
    ) -> list[dict]:
        """Analyze *round_results* and return a list of applied swap dicts.

        Each swap dict: {remove, add, reasoning, round_number, simulation_id}.
        Mutations are written to the DB before returning.
        """
        if not round_results:
            return []

        deck_ids = list(dict.fromkeys(c.tcgdex_id for c in current_deck))  # deduplicated, order preserved
        card_stats = await self._card_perf.get_card_performance(deck_ids)
        synergies = await self._graph.get_synergies(deck_ids)
        summary_text = self._summarize_round(card_stats, round_results)
        similar = await self._similar.find_similar(summary_text, k=5)

        if candidate_card_ids is None:
            top_cards = await self._card_perf.get_top_performing_cards(
                exclude_ids=deck_ids, limit=20
            )
        else:
            perf = await self._card_perf.get_card_performance(candidate_card_ids)
            top_cards = [
                {"tcgdex_id": k, "name": k, **v}
                for k, v in perf.items()
                if k not in deck_ids
            ]

        prompt = self._build_prompt(
            deck=current_deck,
            round_results=round_results,
            card_stats=card_stats,
            top_cards=top_cards,
            synergies=synergies,
            similar=similar,
        )

        swaps = await self._get_swap_decisions(prompt)
        swaps = swaps[: self._max_swaps]

        mutations = []
        for swap in swaps:
            removed = swap.get("remove", "")
            added = swap.get("add", "")
            reasoning = swap.get("reasoning", "")
            if not removed or not added:
                continue
            mutation = {
                "round_number": round_number,
                "card_removed": removed,
                "card_added": added,
                "reasoning": reasoning,
            }
            mutations.append(mutation)
            await self._graph.record_swap(removed, added, round_number, reasoning)

        if mutations:
            await self._write_mutations(mutations, simulation_id)

        return mutations

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        deck: list[CardDefinition],
        round_results: list[MatchResult],
        card_stats: dict,
        top_cards: list[dict],
        synergies: dict,
        similar: list[dict],
    ) -> str:
        wins = sum(1 for r in round_results if r.winner == "p1")
        total = len(round_results)
        win_rate = wins / total if total else 0.0
        avg_turns = (
            sum(r.total_turns for r in round_results) / total if total else 0.0
        )

        loss_reasons = self._extract_loss_reasons(round_results)
        deck_list = "\n".join(
            f"- {c.tcgdex_id} ({c.name})" for c in deck
        )
        card_stats_text = self._format_card_stats(card_stats)
        candidate_text = self._format_candidates(top_cards)
        top_syn_text = ", ".join(
            f"{a_name}+{b_name}" for _, a_name, _, b_name, _ in synergies.get("top", [])[:5]
        ) or "none recorded"
        weak_syn_text = ", ".join(
            f"{a_name}+{b_name}" for _, a_name, _, b_name, _ in synergies.get("weak", [])[:5]
        ) or "none"
        similar_text = self._format_similar(similar)

        return COACH_EVOLUTION_PROMPT.format(
            max_swaps=self._max_swaps,
            deck_list=deck_list,
            win_rate=win_rate,
            wins=wins,
            total_games=total,
            avg_turns=avg_turns,
            loss_reasons=loss_reasons,
            card_stats=card_stats_text,
            candidate_cards=candidate_text,
            top_synergies=top_syn_text,
            weak_synergies=weak_syn_text,
            similar_situations=similar_text,
        )

    async def _get_swap_decisions(self, prompt: str, retries: int = 3) -> list[dict]:
        for attempt in range(retries):
            raw = await self._call_ollama(prompt)
            parsed = self._parse_response(raw)
            if parsed is not None:
                return parsed.get("swaps", [])
            logger.warning("Coach parse failed (attempt %d/%d)", attempt + 1, retries)
        logger.error("Coach gave unparseable response after %d retries", retries)
        return []

    async def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": -1},
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    def _parse_response(self, raw: str) -> dict | None:
        """Parse Gemma 4 response: strip markdown fences, then JSON parse.

        Gemma 4 does NOT produce <think> tags or require prefill.
        """
        cleaned = raw.strip()
        # Strip ```json ... ``` or ``` ... ``` fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Regex fallback: extract first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _summarize_round(
        self, card_stats: dict, round_results: list[MatchResult]
    ) -> str:
        wins = sum(1 for r in round_results if r.winner == "p1")
        total = len(round_results)
        win_rate = wins / total if total else 0.0
        avg_turns = (
            sum(r.total_turns for r in round_results) / total if total else 0.0
        )
        bottom_cards = sorted(
            card_stats.items(), key=lambda kv: kv[1].get("win_rate", 0)
        )[:3]
        bottom_text = ", ".join(k for k, _ in bottom_cards)
        return (
            f"Win rate {win_rate:.1%} over {total} games, "
            f"avg {avg_turns:.1f} turns. "
            f"Lowest performing cards: {bottom_text}."
        )

    def _extract_loss_reasons(self, results: list[MatchResult]) -> str:
        losses = [r for r in results if r.winner != "p1"]
        if not losses:
            return "none (all wins)"
        reasons = Counter(
            getattr(r, "win_condition", "unknown") for r in losses
        )
        return ", ".join(f"{k} ({v}x)" for k, v in reasons.most_common(3))

    def _format_card_stats(self, stats: dict) -> str:
        lines = []
        for cid, s in sorted(stats.items(), key=lambda kv: kv[1].get("win_rate", 0)):
            lines.append(
                f"  {cid}: win_rate={s['win_rate']:.1%}, "
                f"games={s['games_included']}"
            )
        return "\n".join(lines) or "  (no data yet)"

    def _format_candidates(self, top_cards: list[dict]) -> str:
        if not top_cards:
            return "  (insufficient historical data)"
        lines = [
            f"  {c['tcgdex_id']} ({c.get('name', '')}): "
            f"win_rate={c.get('win_rate', 0):.1%}, "
            f"games={c.get('games_included', 0)}"
            for c in top_cards[:10]
        ]
        return "\n".join(lines)

    def _format_similar(self, similar: list[dict]) -> str:
        if not similar:
            return "  (no similar situations found)"
        lines = [
            f"  [{i+1}] (dist={s['distance']:.3f}): {s['content_text'][:100]}"
            for i, s in enumerate(similar)
        ]
        return "\n".join(lines)

    async def _write_mutations(
        self, mutations: list[dict], simulation_id: uuid.UUID
    ) -> None:
        self._db.add_all(
            DeckMutation(
                simulation_id=simulation_id,
                round_number=m["round_number"],
                card_removed=m["card_removed"],
                card_added=m["card_added"],
                reasoning=m.get("reasoning"),
            )
            for m in mutations
        )
        await self._db.flush()
