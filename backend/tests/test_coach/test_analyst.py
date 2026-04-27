"""Unit tests for CoachAnalyst."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coach.analyst import CoachAnalyst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyst(**kwargs) -> CoachAnalyst:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add_all = MagicMock()
    analyst = CoachAnalyst(db=db, **kwargs)
    return analyst


def _match_result(winner: str = "p1", turns: int = 20) -> MagicMock:
    r = MagicMock()
    r.winner = winner
    r.total_turns = turns
    r.end_condition = "prize"
    return r


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_clean_json(self):
        analyst = _make_analyst()
        payload = {"swaps": [], "analysis": "Deck is fine."}
        result = analyst._parse_response(json.dumps(payload))
        assert result == payload

    def test_markdown_fenced(self):
        analyst = _make_analyst()
        payload = {"swaps": [{"remove": "a", "add": "b", "reasoning": "test"}], "analysis": "ok"}
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = analyst._parse_response(raw)
        assert result == payload

    def test_markdown_fenced_no_lang(self):
        analyst = _make_analyst()
        payload = {"swaps": [], "analysis": "ok"}
        raw = f"```\n{json.dumps(payload)}\n```"
        result = analyst._parse_response(raw)
        assert result == payload

    def test_malformed_returns_none(self):
        analyst = _make_analyst()
        result = analyst._parse_response("this is not JSON at all")
        assert result is None

    def test_regex_fallback_truncated(self):
        """Even with surrounding text, the inner JSON block should be extracted."""
        analyst = _make_analyst()
        payload = {"swaps": [], "analysis": "ok"}
        raw = f'Some preamble text.\n{json.dumps(payload)}\nMore text.'
        result = analyst._parse_response(raw)
        assert result == payload

    def test_empty_string_returns_none(self):
        analyst = _make_analyst()
        assert analyst._parse_response("") is None


# ---------------------------------------------------------------------------
# analyze_and_mutate
# ---------------------------------------------------------------------------

class TestAnalyzeAndMutate:
    @pytest.mark.asyncio
    async def test_zero_swap_response_valid(self):
        """If coach returns 0 swaps, no mutations are written."""
        analyst = _make_analyst()
        card = MagicMock()
        card.tcgdex_id = "set-001"
        card.name = "Pikachu"

        analyst._card_perf.get_card_performance = AsyncMock(return_value={})
        analyst._graph.get_synergies = AsyncMock(return_value={"top": [], "weak": []})
        analyst._similar.find_similar = AsyncMock(return_value=[])
        analyst._card_perf.get_top_performing_cards = AsyncMock(return_value=[])
        analyst._call_ollama = AsyncMock(return_value=json.dumps({"swaps": [], "analysis": "Good deck."}))

        results = [_match_result("p1") for _ in range(5)]
        mutations = await analyst.analyze_and_mutate(
            current_deck=[card],
            round_results=results,
            simulation_id=uuid.uuid4(),
            round_number=1,
        )
        assert mutations == []
        analyst._db.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_swaps_clamped_to_max(self):
        """Swaps in excess of max_swaps are silently dropped."""
        analyst = _make_analyst(max_swaps=2)

        card = MagicMock()
        card.tcgdex_id = "set-001"
        card.name = "Pikachu"

        analyst._card_perf.get_card_performance = AsyncMock(return_value={})
        analyst._graph.get_synergies = AsyncMock(return_value={"top": [], "weak": []})
        analyst._similar.find_similar = AsyncMock(return_value=[])
        analyst._card_perf.get_top_performing_cards = AsyncMock(return_value=[])

        # Propose 4 swaps but max is 2
        proposed_swaps = [
            {"remove": f"set-{i:03d}", "add": f"new-{i:03d}", "reasoning": f"swap {i}"}
            for i in range(4)
        ]
        analyst._call_ollama = AsyncMock(
            return_value=json.dumps({"swaps": proposed_swaps, "analysis": "Lots to change."})
        )
        analyst._graph.record_swap = AsyncMock()

        results = [_match_result("p2") for _ in range(5)]  # all losses
        mutations = await analyst.analyze_and_mutate(
            current_deck=[card],
            round_results=results,
            simulation_id=uuid.uuid4(),
            round_number=1,
        )
        assert len(mutations) == 2

    @pytest.mark.asyncio
    async def test_ollama_failure_returns_empty(self):
        """If all Ollama retries fail to parse, return [] without crashing."""
        analyst = _make_analyst()
        card = MagicMock()
        card.tcgdex_id = "set-001"
        card.name = "Pikachu"

        analyst._card_perf.get_card_performance = AsyncMock(return_value={})
        analyst._graph.get_synergies = AsyncMock(return_value={"top": [], "weak": []})
        analyst._similar.find_similar = AsyncMock(return_value=[])
        analyst._card_perf.get_top_performing_cards = AsyncMock(return_value=[])
        analyst._call_ollama = AsyncMock(return_value="<garbled output>")

        results = [_match_result("p2") for _ in range(3)]
        mutations = await analyst.analyze_and_mutate(
            current_deck=[card],
            round_results=results,
            simulation_id=uuid.uuid4(),
            round_number=1,
        )
        assert mutations == []

    @pytest.mark.asyncio
    async def test_analyze_empty_results_returns_empty(self):
        """analyze_and_mutate with no results returns immediately."""
        analyst = _make_analyst()
        card = MagicMock()
        card.tcgdex_id = "set-001"
        mutations = await analyst.analyze_and_mutate(
            current_deck=[card],
            round_results=[],
            simulation_id=uuid.uuid4(),
            round_number=1,
        )
        assert mutations == []
