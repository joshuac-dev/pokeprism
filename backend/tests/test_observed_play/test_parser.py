"""Tests for the PTCGL battle log parser."""

from __future__ import annotations

import pytest

from app.observed_play.parser import parse_log, ParsedObservedLog
from app.observed_play.constants import (
    PARSER_VERSION,
    ET_TURN_START as EVENT_TURN_START,
    ET_DRAW as EVENT_DRAW,
    ET_DRAW_HIDDEN as EVENT_DRAW_HIDDEN,
    ET_ATTACH_ENERGY as EVENT_ATTACH_ENERGY,
    ET_ATTACH_CARD as EVENT_ATTACH_CARD,
    ET_PLAY_TRAINER as EVENT_PLAY_TRAINER,
    ET_PLAY_TO_BENCH_HIDDEN as EVENT_PLAY_TO_BENCH_HIDDEN,
    ET_ATTACK_USED as EVENT_ATTACK,
    ET_KNOCKOUT as EVENT_KNOCK_OUT,
    ET_PRIZE_TAKEN as EVENT_PRIZE_TAKEN,
    ET_MULLIGAN as EVENT_MULLIGAN,
    ET_EVOLVE as EVENT_EVOLVE,
    ET_ABILITY_USED as EVENT_ABILITY_USED,
    ET_SWITCH_ACTIVE as EVENT_SWITCH_ACTIVE,
    ET_UNKNOWN as EVENT_UNKNOWN,
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
        # "drew Pikachu." → known card draw (ET_DRAW), should score high
        content = "Alice's Turn 1\nAlice drew Pikachu.\n"
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


# ── Phase 2.1: Parser hardening tests ─────────────────────────────────────────

class TestDrawHidden:
    """Bug 2: 'drew a card.' should be draw_hidden, not known draw."""

    def test_drew_a_card_is_draw_hidden(self):
        result = parse_log("Alice's Turn 1\nAlice drew a card.\n")
        draw_hidden = [e for e in result.events if e.event_type == EVENT_DRAW_HIDDEN]
        assert len(draw_hidden) == 1
        assert draw_hidden[0].amount == 1
        assert draw_hidden[0].card_name_raw is None

    def test_drew_a_card_is_not_known_draw(self):
        result = parse_log("Alice's Turn 1\nAlice drew a card.\n")
        known_draws = [e for e in result.events if e.event_type == EVENT_DRAW]
        assert len(known_draws) == 0

    def test_drew_n_cards_is_draw_hidden(self):
        result = parse_log("Alice's Turn 1\nAlice drew 2 cards.\n")
        draw_hidden = [e for e in result.events if e.event_type == EVENT_DRAW_HIDDEN]
        assert len(draw_hidden) == 1
        assert draw_hidden[0].amount == 2

    def test_drew_1_card_is_draw_hidden(self):
        result = parse_log("Alice's Turn 1\nAlice drew 1 card.\n")
        draw_hidden = [e for e in result.events if e.event_type == EVENT_DRAW_HIDDEN]
        assert len(draw_hidden) == 1
        assert draw_hidden[0].amount == 1

    def test_drew_named_card_is_known_draw(self):
        result = parse_log("Alice's Turn 1\nAlice drew Charizard ex.\n")
        known_draws = [e for e in result.events if e.event_type == EVENT_DRAW]
        assert len(known_draws) == 1
        assert known_draws[0].card_name_raw == "Charizard ex"


class TestGenericTrainerPlay:
    """Bug 1: generic 'played CARD.' without subtype should parse as play_trainer."""

    def test_item_suffix_is_play_item(self):
        result = parse_log("Alice's Turn 1\nAlice played Rare Candy (Item).\n")
        types = [e.event_type for e in result.events]
        assert "play_item" in types

    def test_supporter_suffix_is_play_supporter(self):
        result = parse_log("Alice's Turn 1\nAlice played Professor's Research (Supporter).\n")
        types = [e.event_type for e in result.events]
        assert "play_supporter" in types

    def test_generic_item_no_suffix_is_play_trainer(self):
        result = parse_log("Alice's Turn 1\ngehejo played Buddy-Buddy Poffin.\n")
        events = [e for e in result.events if e.event_type not in (EVENT_UNKNOWN, "turn_start")]
        assert any(e.event_type == EVENT_PLAY_TRAINER for e in events)
        trainer = [e for e in events if e.event_type == EVENT_PLAY_TRAINER][0]
        assert trainer.card_name_raw == "Buddy-Buddy Poffin"

    def test_generic_supporter_no_suffix_is_play_trainer(self):
        result = parse_log("DAVIDELIRIUM's Turn 1\nDAVIDELIRIUM played Hilda.\n")
        trainer = [e for e in result.events if e.event_type == EVENT_PLAY_TRAINER]
        assert len(trainer) == 1
        assert trainer[0].card_name_raw == "Hilda"

    def test_generic_supporter_with_apostrophe(self):
        result = parse_log("Alice's Turn 1\ngehejo played Team Rocket's Petrel.\n")
        trainer = [e for e in result.events if e.event_type == EVENT_PLAY_TRAINER]
        assert len(trainer) == 1
        assert trainer[0].card_name_raw == "Team Rocket's Petrel"


class TestAttachment:
    """Bug 3: non-energy attachment should not be attach_energy."""

    def test_energy_attachment_is_attach_energy(self):
        result = parse_log("Alice's Turn 1\nAlice attached Psychic Energy to Jynx.\n")
        energy_events = [e for e in result.events if e.event_type == EVENT_ATTACH_ENERGY]
        assert len(energy_events) == 1

    def test_tool_attachment_is_attach_card(self):
        result = parse_log(
            "DAVIDELIRIUM's Turn 1\n"
            "DAVIDELIRIUM attached Maximum Belt to Riolu in the Active Spot.\n"
        )
        attach_card = [e for e in result.events if e.event_type == EVENT_ATTACH_CARD]
        assert len(attach_card) == 1
        ev = attach_card[0]
        assert ev.card_name_raw == "Maximum Belt"
        assert ev.target_card_name_raw == "Riolu"
        assert ev.zone == "active"

    def test_tool_attachment_not_attach_energy(self):
        result = parse_log(
            "DAVIDELIRIUM's Turn 1\n"
            "DAVIDELIRIUM attached Maximum Belt to Riolu in the Active Spot.\n"
        )
        energy_events = [e for e in result.events if e.event_type == EVENT_ATTACH_ENERGY]
        assert len(energy_events) == 0

    def test_general_energy_attachment_with_zone(self):
        result = parse_log("Alice's Turn 1\nAlice attached Fire Energy to Charizard ex.\n")
        energy_events = [e for e in result.events if e.event_type == EVENT_ATTACH_ENERGY]
        assert len(energy_events) == 1


class TestEvolve:
    """Bug 4: 'PLAYER evolved FROM to TO [in ZONE].' should be evolve."""

    def test_evolve_direct_active_spot(self):
        result = parse_log(
            "DAVIDELIRIUM's Turn 1\n"
            "DAVIDELIRIUM evolved Riolu to Mega Lucario ex in the Active Spot.\n"
        )
        evolve = [e for e in result.events if e.event_type == EVENT_EVOLVE]
        assert len(evolve) == 1
        ev = evolve[0]
        assert ev.player_raw == "DAVIDELIRIUM"
        assert ev.target_card_name_raw == "Riolu"
        assert ev.card_name_raw == "Mega Lucario ex"
        assert ev.zone == "active"

    def test_evolve_direct_bench(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "Alice evolved Makuhita to Hariyama on the Bench.\n"
        )
        evolve = [e for e in result.events if e.event_type == EVENT_EVOLVE]
        assert len(evolve) == 1
        ev = evolve[0]
        assert ev.card_name_raw == "Hariyama"
        assert ev.target_card_name_raw == "Makuhita"
        assert ev.zone == "bench"

    def test_evolve_possessive_still_works(self):
        result = parse_log("Alice's Turn 1\nAlice's Charmander evolved into Charizard ex.\n")
        evolve = [e for e in result.events if e.event_type == EVENT_EVOLVE]
        assert len(evolve) == 1


class TestAbilityUsed:
    """Bug 5: 'PLAYER's CARD used ABILITY.' should be ability_used."""

    def test_ability_straight_apostrophe(self):
        result = parse_log("Alice's Turn 1\nDAVIDELIRIUM's Hariyama used Heave-Ho Catcher.\n")
        ability = [e for e in result.events if e.event_type == EVENT_ABILITY_USED]
        assert len(ability) == 1
        ev = ability[0]
        assert ev.card_name_raw == "Hariyama"
        assert ev.event_payload.get("ability_name") == "Heave-Ho Catcher"

    def test_ability_curly_apostrophe(self):
        result = parse_log("Alice\u2019s Turn 1\nDAVIDELIRIUM\u2019s Hariyama used Heave-Ho Catcher.\n")
        ability = [e for e in result.events if e.event_type == EVENT_ABILITY_USED]
        assert len(ability) == 1


class TestAttackNoDamage:
    """Bug 6: 'PLAYER's CARD used ATTACK on TARGET.' without damage should be attack_used."""

    def test_attack_no_damage_has_target(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "gehejo's Dwebble used Shell Smash on DAVIDELIRIUM's Hariyama.\n"
        )
        attacks = [e for e in result.events if e.event_type == EVENT_ATTACK]
        assert len(attacks) == 1
        ev = attacks[0]
        assert ev.damage is None
        assert ev.card_name_raw == "Dwebble"

    def test_ability_no_target_is_ability(self):
        # No-target form should be ability_used, not attack_used
        result = parse_log("Alice's Turn 1\ngehejo's Dwebble used Ascension.\n")
        ability = [e for e in result.events if e.event_type == EVENT_ABILITY_USED]
        assert len(ability) == 1
        attacks = [e for e in result.events if e.event_type == EVENT_ATTACK]
        assert len(attacks) == 0


class TestPrizeTaken:
    """Bug 7: 'took a Prize card.' (singular) should be prize_taken amount 1."""

    def test_singular_prize(self):
        result = parse_log("Alice's Turn 1\nDAVIDELIRIUM took a Prize card.\n")
        prizes = [e for e in result.events if e.event_type == EVENT_PRIZE_TAKEN]
        assert len(prizes) == 1
        assert prizes[0].prize_count_delta == 1

    def test_plural_prize_still_works(self):
        result = parse_log("Alice's Turn 1\nAlice took 2 Prize cards.\n")
        prizes = [e for e in result.events if e.event_type == EVENT_PRIZE_TAKEN]
        assert len(prizes) == 1
        assert prizes[0].prize_count_delta == 2


class TestBenchFromDeckHidden:
    """Bug 8: '- PLAYER drew N cards and played them to the Bench.' should not set card_name_raw='them'."""

    def test_bench_from_deck_type(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench_hidden = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert len(bench_hidden) == 1

    def test_bench_from_deck_amount(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench_hidden = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert bench_hidden[0].amount == 2

    def test_bench_from_deck_no_card_name(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench_hidden = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert bench_hidden[0].card_name_raw != "them"
        assert bench_hidden[0].card_name_raw is None

    def test_bench_from_deck_target_zone(self):
        result = parse_log(
            "Alice's Turn 1\n"
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench_hidden = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert bench_hidden[0].target_zone == "bench"


class TestSwitchActive:
    """Bug 9: 'PLAYER's CARD is now in the Active Spot.' should be switch_active."""

    def test_now_in_active_spot_straight_apostrophe(self):
        result = parse_log("Alice's Turn 1\ngehejo's Dwebble is now in the Active Spot.\n")
        switch = [e for e in result.events if e.event_type == EVENT_SWITCH_ACTIVE]
        assert len(switch) == 1
        ev = switch[0]
        assert ev.card_name_raw == "Dwebble"
        assert ev.player_raw == "gehejo"

    def test_now_in_active_spot_curly_apostrophe(self):
        result = parse_log("Alice\u2019s Turn 1\ngehejo\u2019s Dwebble is now in the Active Spot.\n")
        switch = [e for e in result.events if e.event_type == EVENT_SWITCH_ACTIVE]
        assert len(switch) == 1

    def test_switched_in_still_works(self):
        result = parse_log("Alice's Turn 1\nBob switched in Misdreavus to the Active Spot.\n")
        switch = [e for e in result.events if e.event_type == EVENT_SWITCH_ACTIVE]
        assert len(switch) == 1


class TestParserDiagnostics:
    """Parser diagnostics should be in metadata."""

    def test_diagnostics_in_metadata(self):
        result = parse_log("Alice's Turn 1\nAlice drew a card.\n")
        assert result.metadata is not None
        assert "parser_diagnostics" in result.metadata

    def test_diagnostics_has_required_keys(self):
        result = parse_log("Alice's Turn 1\nsome unknown line\n")
        diag = result.metadata["parser_diagnostics"]
        assert "unknown_count" in diag
        assert "unknown_ratio" in diag
        assert "low_confidence_count" in diag
        assert "event_type_counts" in diag
        assert "top_unknown_raw_lines" in diag

    def test_unknown_count_accurate(self):
        result = parse_log("Alice's Turn 1\nunknown line 1\nunknown line 2\n")
        diag = result.metadata["parser_diagnostics"]
        assert diag["unknown_count"] == 2

    def test_unknown_ratio_calculated(self):
        result = parse_log("Alice's Turn 1\nunknown line\n")
        diag = result.metadata["parser_diagnostics"]
        total = result.event_count
        expected = 1 / total
        assert abs(diag["unknown_ratio"] - expected) < 1e-3

    def test_event_type_counts_map(self):
        result = parse_log("Alice's Turn 1\nAlice drew a card.\n")
        diag = result.metadata["parser_diagnostics"]
        counts = diag["event_type_counts"]
        assert isinstance(counts, dict)
        assert counts.get("turn_start", 0) >= 1
        assert counts.get("draw_hidden", 0) >= 1

    def test_top_unknown_raw_lines_capped(self):
        lines = "\n".join(f"unknown line {i}" for i in range(30))
        result = parse_log(f"Alice's Turn 1\n{lines}\n")
        diag = result.metadata["parser_diagnostics"]
        assert len(diag["top_unknown_raw_lines"]) <= 20

    def test_no_unknown_ratio_zero(self):
        result = parse_log("Alice's Turn 1\nAlice drew a card.\n")
        diag = result.metadata["parser_diagnostics"]
        assert diag["unknown_ratio"] == 0.0
        assert diag["unknown_count"] == 0


class TestRealLogSampleFixture:
    """Test 19-21: real_log_sample.md fixture should have low unknown ratio."""

    @pytest.fixture(autouse=True)
    def parsed(self):
        content = _read_fixture("real_log_sample.md")
        self.result = parse_log(content)

    def test_never_throws(self):
        assert isinstance(self.result, ParsedObservedLog)

    def test_low_unknown_ratio(self):
        diag = self.result.metadata["parser_diagnostics"]
        # After hardening, unknown ratio should be materially below 0.20
        assert diag["unknown_ratio"] < 0.20, (
            f"unknown_ratio={diag['unknown_ratio']} too high; "
            f"top unknown lines: {diag['top_unknown_raw_lines']}"
        )

    def test_raw_line_preservation(self):
        for e in self.result.events:
            assert e.raw_line is not None


class TestDashChildLineAttribution:
    """Phase 2.2: dash-prefixed child lines must preserve player alias."""

    def _parse_with_players(self, body: str) -> "ParsedObservedLog":
        """Wrap body with turn headers to register player aliases first."""
        log = f"gehejo's Turn 1\n\n{body}\nDAVIDELIRIUM's Turn 1\n"
        return parse_log(log)

    def test_dash_shuffle_assigns_player_alias(self):
        result = self._parse_with_players("- gehejo shuffled their deck.\n")
        shuffles = [e for e in result.events if e.event_type == "shuffle_deck"]
        assert len(shuffles) >= 1
        s = shuffles[0]
        assert s.player_raw == "gehejo"
        assert s.player_alias == "player_1"

    def test_dash_shuffle_raw_line_preserved_with_dash(self):
        result = self._parse_with_players("- gehejo shuffled their deck.\n")
        shuffles = [e for e in result.events if e.event_type == "shuffle_deck"]
        assert len(shuffles) >= 1
        assert shuffles[0].raw_line == "- gehejo shuffled their deck."

    def test_dash_known_draw_assigns_player_alias(self):
        result = self._parse_with_players("- gehejo drew Hero's Cape.\n")
        draws = [e for e in result.events if e.event_type == EVENT_DRAW]
        assert len(draws) >= 1
        d = draws[0]
        assert d.player_raw == "gehejo"
        assert d.player_alias == "player_1"
        assert d.card_name_raw == "Hero's Cape"

    def test_dash_known_draw_raw_line_preserved(self):
        result = self._parse_with_players("- gehejo drew Hero's Cape.\n")
        draws = [e for e in result.events if e.event_type == EVENT_DRAW]
        assert len(draws) >= 1
        assert draws[0].raw_line == "- gehejo drew Hero's Cape."

    def test_dash_hidden_draw_assigns_player_alias(self):
        result = self._parse_with_players("- DAVIDELIRIUM drew 2 cards.\n")
        draws = [e for e in result.events if e.event_type == EVENT_DRAW_HIDDEN]
        assert len(draws) >= 1
        d = draws[0]
        assert d.player_raw == "DAVIDELIRIUM"
        assert d.player_alias == "player_2"
        assert d.amount == 2

    def test_dash_hidden_draw_raw_line_preserved(self):
        result = self._parse_with_players("- DAVIDELIRIUM drew 2 cards.\n")
        draws = [e for e in result.events if e.event_type == EVENT_DRAW_HIDDEN]
        assert len(draws) >= 1
        assert draws[0].raw_line == "- DAVIDELIRIUM drew 2 cards."

    def test_dash_evolve_assigns_player_alias(self):
        result = self._parse_with_players(
            "- gehejo evolved Dwebble to Crustle in the Active Spot.\n"
        )
        evolves = [e for e in result.events if e.event_type == EVENT_EVOLVE]
        assert len(evolves) >= 1
        ev = evolves[0]
        assert ev.player_raw == "gehejo"
        assert ev.player_alias == "player_1"
        assert ev.target_card_name_raw == "Dwebble"
        assert ev.card_name_raw == "Crustle"

    def test_dash_bench_from_deck_assigns_player_alias(self):
        result = self._parse_with_players(
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert len(bench) >= 1
        b = bench[0]
        assert b.player_raw == "gehejo"
        assert b.player_alias == "player_1"
        assert b.amount == 2
        assert b.card_name_raw is None

    def test_dash_bench_from_deck_raw_line_preserved(self):
        result = self._parse_with_players(
            "- gehejo drew 2 cards and played them to the Bench.\n"
        )
        bench = [e for e in result.events if e.event_type == EVENT_PLAY_TO_BENCH_HIDDEN]
        assert len(bench) >= 1
        assert bench[0].raw_line == "- gehejo drew 2 cards and played them to the Bench."

    def test_non_dash_line_unaffected(self):
        result = parse_log("Alice's Turn 1\nAlice shuffled their deck.\n")
        shuffles = [e for e in result.events if e.event_type == "shuffle_deck"]
        assert len(shuffles) >= 1
        s = shuffles[0]
        assert s.player_alias == "player_1"
        assert s.raw_line == "Alice shuffled their deck."

    def test_dwebble_ascension_remains_ability_used(self):
        """Owner clarification: 'used Ascension.' with no target = ability_used."""
        result = parse_log("gehejo's Turn 1\ngehejo's Dwebble used Ascension.\n")
        abilities = [e for e in result.events if e.event_type == EVENT_ABILITY_USED]
        assert len(abilities) >= 1
        a = abilities[0]
        assert a.card_name_raw == "Dwebble"
        assert a.event_payload.get("ability_name") == "Ascension"

    def test_targeted_no_damage_attack_remains_attack_used(self):
        """'used ATTACK on OPPONENT's TARGET.' (no damage) = attack_used."""
        result = parse_log(
            "Alice's Turn 1\nBob's Turn 1\n"
            "Alice's Charizard used Flame Charge on Bob's Squirtle.\n"
        )
        attacks = [e for e in result.events if e.event_type == EVENT_ATTACK]
        assert len(attacks) >= 1
        a = attacks[0]
        assert a.card_name_raw == "Charizard"
        assert a.event_payload.get("attack_name") == "Flame Charge"

    def test_real_log_dash_lines_have_correct_aliases(self):
        """Dash-prefixed lines in real_log_sample.md must not have unknown alias."""
        import os
        fixture_path = os.path.join(
            os.path.dirname(__file__), "..", "fixtures", "observed_play", "real_log_sample.md"
        )
        with open(fixture_path) as f:
            content = f.read()
        result = parse_log(content)
        dash_events = [e for e in result.events if e.raw_line and e.raw_line.startswith("- ")]
        for e in dash_events:
            if e.player_raw is not None:
                assert e.player_alias in {"player_1", "player_2"}, (
                    f"Dash-line event has unknown alias: {e.raw_line!r}, alias={e.player_alias!r}"
                )

    def test_diagnostics_still_present_after_dash_changes(self):
        """parser_diagnostics keys should still exist in metadata after Phase 2.2."""
        result = self._parse_with_players("- gehejo shuffled their deck.\n")
        diag = result.metadata["parser_diagnostics"]
        assert "unknown_count" in diag
        assert "unknown_ratio" in diag
        assert "event_type_counts" in diag
        assert "top_unknown_raw_lines" in diag
