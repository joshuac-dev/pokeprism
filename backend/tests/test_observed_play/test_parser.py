"""Tests for the PTCGL battle log parser."""

from __future__ import annotations

import pytest

from app.observed_play.parser import parse_log, ParsedObservedLog
from app.observed_play.constants import (
    PARSER_VERSION,
    ET_TURN_START as EVENT_TURN_START,
    ET_DRAW as EVENT_DRAW,
    ET_ATTACH_ENERGY as EVENT_ATTACH_ENERGY,
    ET_ATTACK_USED as EVENT_ATTACK,
    ET_KNOCKOUT as EVENT_KNOCK_OUT,
    ET_PRIZE_TAKEN as EVENT_PRIZE_TAKEN,
    ET_MULLIGAN as EVENT_MULLIGAN,
    PHASE_SETUP,
    PHASE_TURN,
    PHASE_COMBAT,
)


FIXTURES_DIR = "tests/fixtures/observed_play"


def _read_fixture(name: str) -> str:
    with open(f"{FIXTURES_DIR}/{name}") as fh:
        return fh.read()


# ── Smoke tests ────────────────────────────────────────────────────────────────

class TestParseLogNeverThrows:
    def test_empty_string(self):
        result = parse_log("")
        assert isinstance(result, ParsedObservedLog)

    def test_garbage_input(self):
        result = parse_log("aaaaaaa\x00\x01\x02\xff junk data !!!")
        assert isinstance(result, ParsedObservedLog)

    def test_none_like_string(self):
        result = parse_log("None")
        assert isinstance(result, ParsedObservedLog)

    def test_very_long_input(self):
        result = parse_log("Alice's Turn 1\n" + "junk line\n" * 5000)
        assert isinstance(result, ParsedObservedLog)


# ── Parser version ─────────────────────────────────────────────────────────────

class TestParserVersion:
    def test_version_set(self):
        result = parse_log("Alice's Turn 1\n")
        assert result.parser_version == PARSER_VERSION


# ── Basic fixture: turns and draws ────────────────────────────────────────────

class TestBasicSetupAndTurns:
    @pytest.fixture(autouse=True)
    def parsed(self):
        content = _read_fixture("basic_setup_and_turns.md")
        self.result = parse_log(content)

    def test_no_errors(self):
        assert self.result.errors == []

    def test_players_detected(self):
        assert self.result.player_1_name_raw is not None
        assert self.result.player_2_name_raw is not None

    def test_turn_count(self):
        assert self.result.turn_count >= 2

    def test_event_count_positive(self):
        assert self.result.event_count > 0

    def test_turn_start_events_exist(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_TURN_START in types

    def test_draw_events_exist(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_DRAW in types

    def test_attack_event_exists(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_ATTACK in types

    def test_ko_event_exists(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_KNOCK_OUT in types

    def test_prize_taken_event_exists(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_PRIZE_TAKEN in types

    def test_event_indices_sequential(self):
        indices = [e.event_index for e in self.result.events]
        assert indices == list(range(len(indices)))

    def test_confidence_non_negative(self):
        for e in self.result.events:
            assert e.confidence_score >= 0.0

    def test_phase_transitions(self):
        phases = {e.phase for e in self.result.events}
        assert PHASE_TURN in phases

    def test_player_aliases_assigned(self):
        aliased = [e for e in self.result.events if e.player_raw is not None]
        for e in aliased:
            assert e.player_alias in {"player_1", "player_2"}

    def test_confidence_score_positive(self):
        assert self.result.confidence_score is not None
        assert self.result.confidence_score > 0.0


# ── Mulligan / KO / Prize fixture ─────────────────────────────────────────────

class TestMulliganAttackKoPrize:
    @pytest.fixture(autouse=True)
    def parsed(self):
        content = _read_fixture("mulligan_attack_ko_prize.md")
        self.result = parse_log(content)

    def test_no_errors(self):
        assert self.result.errors == []

    def test_mulligan_events_exist(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_MULLIGAN in types

    def test_ko_event_exists(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_KNOCK_OUT in types

    def test_prize_taken_event_exists(self):
        types = [e.event_type for e in self.result.events]
        assert EVENT_PRIZE_TAKEN in types

    def test_prize_count_set_on_prize_event(self):
        prize_events = [e for e in self.result.events if e.event_type == EVENT_PRIZE_TAKEN]
        for e in prize_events:
            assert e.prize_count_delta is not None and e.prize_count_delta > 0


# ── Confidence scoring ─────────────────────────────────────────────────────────

class TestConfidenceScoring:
    def test_known_event_types_score_high(self):
        content = "Alice's Turn 1\nAlice drew 1 card.\n"
        result = parse_log(content)
        for e in result.events:
            if e.event_type == EVENT_DRAW:
                assert e.confidence_score >= 0.7

    def test_unknown_line_has_low_confidence(self):
        content = "Alice's Turn 1\nsome completely unknown line\n"
        result = parse_log(content)
        low = [e for e in result.events if e.event_type == "unknown"]
        if low:
            assert low[0].confidence_score < 0.7

    def test_log_confidence_is_average(self):
        content = _read_fixture("basic_setup_and_turns.md")
        result = parse_log(content)
        if result.events:
            avg = sum(e.confidence_score for e in result.events) / len(result.events)
            assert abs(result.confidence_score - avg) < 1e-6


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_bom_stripped(self):
        result = parse_log("\ufeffAlice's Turn 1\nAlice drew 1 card.\n")
        assert result.errors == []
        assert result.event_count > 0

    def test_windows_line_endings(self):
        result = parse_log("Alice's Turn 1\r\nAlice drew 1 card.\r\n")
        assert result.event_count > 0

    def test_curly_apostrophe_in_turn(self):
        result = parse_log("Alice\u2019s Turn 1\nAlice drew 1 card.\n")
        assert result.event_count > 0

    def test_only_whitespace(self):
        result = parse_log("   \n\n\t  \n")
        assert isinstance(result, ParsedObservedLog)

    def test_player_1_alias_first_seen(self):
        content = "Alice's Turn 1\nAlice drew 1 card.\nBob's Turn 1\nBob drew 1 card.\n"
        result = parse_log(content)
        assert result.player_1_alias == "player_1"
        assert result.player_2_alias == "player_2"

    def test_single_player_log(self):
        content = "Alice's Turn 1\nAlice drew 1 card.\nAlice's Turn 2\nAlice drew 1 card.\n"
        result = parse_log(content)
        assert result.player_1_name_raw is not None
        assert result.player_2_name_raw is None
