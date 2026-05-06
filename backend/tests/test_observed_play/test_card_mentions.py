"""Tests for Phase 3 card mention extraction and resolution.

Tests extraction from each relevant event type, resolution strategies
(exact match, energy alias, ambiguous, unresolved), idempotency of the
extraction/resolution pipeline, and edge cases.

Does NOT test card DB connectivity — card lookup is mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.observed_play.card_mentions import (
    _is_meaningful,
    clean_extracted_card_name,
    extract_mentions_from_event,
    normalize_card_name,
)
from app.observed_play.card_resolution import (
    RESOLVER_VERSION,
    RS_AMBIGUOUS,
    RS_IGNORED,
    RS_RESOLVED,
    RS_UNRESOLVED,
    CardResolutionSummary,
    _derive_log_resolution_status,
    _resolve_one,
)
from app.observed_play.constants import (
    ET_ABILITY_USED,
    ET_ATTACK_USED,
    ET_CARD_ADDED_TO_HAND,
    ET_CARD_EFFECT_ACTIVATED,
    ET_DISCARD_FROM_POKEMON,
    ET_DRAW,
    ET_EVOLVE,
    ET_ATTACH_CARD,
    ET_ATTACH_ENERGY,
    ET_OPENING_HAND_DRAW_KNOWN,
    ET_PLAY_ITEM,
    ET_PLAY_SUPPORTER,
    ET_PLAY_TRAINER,
    ET_RETREAT,
    ET_SWITCH_ACTIVE,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _event(event_type: str, **kwargs) -> Any:
    """Build a minimal fake event object."""
    return SimpleNamespace(
        event_type=event_type,
        card_name_raw=kwargs.get("card_name_raw"),
        target_card_name_raw=kwargs.get("target_card_name_raw"),
        event_payload_json=kwargs.get("event_payload_json", {}),
        id=1,
    )


def _empty_cards() -> dict:
    return {}


def _empty_rules() -> dict:
    return {}


def _cards(names: list[str]) -> dict:
    """Build a cards_by_norm dict from a list of canonical card names."""
    result: dict[str, list[dict]] = {}
    for name in names:
        from app.observed_play.card_mentions import normalize_card_name as norm
        key = norm(name)
        result.setdefault(key, []).append({
            "tcgdex_id": f"tcg-{key.replace(' ', '-')}",
            "name": name,
            "set_abbrev": "sv01",
            "set_number": "001",
            "image_url": None,
        })
    return result


# ── normalize_card_name ────────────────────────────────────────────────────────

class TestNormalizeCardName:
    def test_lowercases(self):
        assert normalize_card_name("Pikachu") == "pikachu"

    def test_trims_whitespace(self):
        assert normalize_card_name("  Pikachu  ") == "pikachu"

    def test_collapses_internal_whitespace(self):
        assert normalize_card_name("Mega  Lucario  ex") == "mega lucario ex"

    def test_strips_trailing_punctuation(self):
        assert normalize_card_name("Pikachu.") == "pikachu"
        assert normalize_card_name("Pikachu,") == "pikachu"

    def test_curly_apostrophe(self):
        assert normalize_card_name("Team Rocket\u2019s Petrel") == "team rocket's petrel"

    def test_empty_string(self):
        assert normalize_card_name("") == ""

    def test_none_safe(self):
        assert normalize_card_name(None) == ""  # type: ignore[arg-type]


# ── _is_meaningful ─────────────────────────────────────────────────────────────

class TestIsMeaningful:
    def test_normal_name(self):
        assert _is_meaningful("Pikachu") is True

    def test_hidden_a_card(self):
        assert _is_meaningful("A card") is False
        assert _is_meaningful("a card") is False

    def test_empty(self):
        assert _is_meaningful("") is False
        assert _is_meaningful(None) is False  # type: ignore[arg-type]

    def test_single_char(self):
        assert _is_meaningful("a") is False


# ── extract_mentions_from_event ────────────────────────────────────────────────

class TestExtractMentionsFromEvent:
    def test_attack_extracts_actor_and_target(self):
        evt = _event(ET_ATTACK_USED, card_name_raw="Lucario ex", target_card_name_raw="Pikachu")
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert "actor_card" in roles
        assert "target_card" in roles
        names = {m["raw_name"] for m in mentions}
        assert "Lucario ex" in names
        assert "Pikachu" in names

    def test_attack_does_not_extract_attack_name(self):
        evt = _event(ET_ATTACK_USED, card_name_raw="Lucario ex")
        evt.event_payload_json = {"attack_name": "Power Blast"}
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Power Blast" not in names

    def test_ability_used_does_not_extract_ability_name(self):
        evt = _event(ET_ABILITY_USED, card_name_raw="Dwebble")
        evt.event_payload_json = {"ability_name": "Ascension"}
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Ascension" not in names
        assert "Dwebble" in names

    def test_evolve_extracts_from_and_to(self):
        evt = _event(ET_EVOLVE,
                     card_name_raw="Mega Lucario ex",
                     target_card_name_raw="Riolu")
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert "evolution_from" in roles
        assert "evolution_to" in roles
        names = {m["raw_name"] for m in mentions}
        assert "Mega Lucario ex" in names
        assert "Riolu" in names

    def test_attach_energy_extracts_energy_card(self):
        evt = _event(ET_ATTACH_ENERGY, card_name_raw="Basic Fighting Energy", target_card_name_raw="Hariyama")
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert "energy_card" in roles
        assert "target_card" in roles

    def test_attach_card_extracts_tool_role_for_belt(self):
        evt = _event(ET_ATTACH_CARD, card_name_raw="Maximum Belt", target_card_name_raw="Riolu")
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert "tool_card" in roles
        assert "target_card" in roles

    def test_play_trainer_extracts_trainer_card(self):
        evt = _event(ET_PLAY_TRAINER, card_name_raw="Buddy-Buddy Poffin")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "trainer_card"
        assert mentions[0]["raw_name"] == "Buddy-Buddy Poffin"

    def test_play_item_extracts_trainer_card(self):
        evt = _event(ET_PLAY_ITEM, card_name_raw="Rare Candy")
        mentions = extract_mentions_from_event(evt)
        assert mentions[0]["mention_role"] == "trainer_card"

    def test_play_supporter_extracts_trainer_card(self):
        evt = _event(ET_PLAY_SUPPORTER, card_name_raw="Hilda")
        mentions = extract_mentions_from_event(evt)
        assert mentions[0]["mention_role"] == "trainer_card"

    def test_discard_from_pokemon_extracts_both(self):
        evt = _event(ET_DISCARD_FROM_POKEMON,
                     card_name_raw="Basic Fighting Energy",
                     target_card_name_raw="Solrock")
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert "discarded_card" in roles
        assert "target_card" in roles

    def test_card_added_to_hand_extracts_card(self):
        evt = _event(ET_CARD_ADDED_TO_HAND, card_name_raw="Growing Grass Energy")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "added_to_hand_card"

    def test_card_added_to_hand_hidden_is_ignored(self):
        """'A card' should not produce a mention (hidden placeholder)."""
        evt = _event(ET_CARD_ADDED_TO_HAND, card_name_raw=None)
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 0

    def test_card_effect_activated_extracts_effect_card(self):
        evt = _event(ET_CARD_EFFECT_ACTIVATED, card_name_raw="Spiky Energy")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "effect_card"
        assert mentions[0]["raw_name"] == "Spiky Energy"

    def test_retreat_extracts_actor_card(self):
        evt = _event(ET_RETREAT, card_name_raw="Hariyama")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "actor_card"

    def test_deduplication_same_role_and_name(self):
        """Same role+name+field should not produce duplicate mentions."""
        evt = _event(ET_ATTACK_USED, card_name_raw="Lucario ex", target_card_name_raw="Lucario ex")
        mentions = extract_mentions_from_event(evt)
        # actor_card and target_card are different roles → both kept
        roles = [m["mention_role"] for m in mentions]
        assert len(roles) == len(set(zip(roles, [m["raw_name"] for m in mentions])))

    def test_raw_line_not_extracted(self):
        """raw_line is not a source for card mentions."""
        evt = _event(ET_PLAY_TRAINER, card_name_raw="Hilda")
        evt.raw_line = "DAVIDELIRIUM played Hilda."
        mentions = extract_mentions_from_event(evt)
        # Should only get one mention for the card, not the raw_line text
        assert all(m["raw_name"] != "DAVIDELIRIUM played Hilda." for m in mentions)


# ── _resolve_one ───────────────────────────────────────────────────────────────

class TestResolveOne:
    def test_exact_unique_resolves(self):
        cards = _cards(["Pikachu"])
        result = _resolve_one("pikachu", cards, _empty_rules())
        assert result["resolution_status"] == RS_RESOLVED
        assert result["resolution_confidence"] == pytest.approx(0.98)
        assert result["resolution_method"] == "exact_name_unique"
        assert result["resolved_card_name"] == "Pikachu"

    def test_exact_ambiguous_multiple_cards(self):
        cards = _cards(["Pikachu", "Pikachu"])
        # Force two distinct entries with same normalized name
        norm = normalize_card_name("Pikachu")
        cards[norm] = [
            {"tcgdex_id": "sv01-001", "name": "Pikachu", "set_abbrev": "sv01", "set_number": "001", "image_url": None},
            {"tcgdex_id": "sv02-001", "name": "Pikachu", "set_abbrev": "sv02", "set_number": "001", "image_url": None},
        ]
        result = _resolve_one("pikachu", cards, _empty_rules())
        assert result["resolution_status"] == RS_AMBIGUOUS
        assert result["candidate_count"] == 2

    def test_unresolved_when_no_match(self):
        result = _resolve_one("nonexistent card", _empty_cards(), _empty_rules())
        assert result["resolution_status"] == RS_UNRESOLVED
        assert result["resolution_confidence"] == pytest.approx(0.0)

    def test_basic_energy_alias_resolves(self):
        cards = _cards(["Basic Fighting Energy"])
        # Mention uses short form "fighting energy" → should resolve via alias
        result = _resolve_one("fighting energy", cards, _empty_rules())
        assert result["resolution_status"] == RS_RESOLVED
        assert result["resolution_method"] == "basic_energy_alias"
        assert result["resolution_confidence"] == pytest.approx(0.95)

    def test_manual_rule_ignore(self):
        rules = {"spiky energy": {"action": "ignore", "target_card_def_id": None, "target_card_name": None}}
        result = _resolve_one("spiky energy", _empty_cards(), rules)
        assert result["resolution_status"] == RS_IGNORED
        assert result["resolution_method"] == "manual_rule_ignore"

    def test_manual_rule_resolve(self):
        rules = {
            "my card": {
                "action": "resolve",
                "target_card_def_id": "sv01-999",
                "target_card_name": "My Card",
            }
        }
        result = _resolve_one("my card", _empty_cards(), rules)
        assert result["resolution_status"] == RS_RESOLVED
        assert result["resolved_card_def_id"] == "sv01-999"
        assert result["resolution_confidence"] == pytest.approx(1.0)


# ── _derive_log_resolution_status ─────────────────────────────────────────────

class TestDeriveLogResolutionStatus:
    def _summary(self, **kwargs) -> CardResolutionSummary:
        s = CardResolutionSummary(log_id="test-log")
        for k, v in kwargs.items():
            setattr(s, k, v)
        return s

    def test_no_mentions_is_not_resolved(self):
        s = self._summary(card_mention_count=0)
        assert _derive_log_resolution_status(s) == "not_resolved"

    def test_all_resolved(self):
        s = self._summary(card_mention_count=5, resolved_card_count=5)
        assert _derive_log_resolution_status(s) == "resolved"

    def test_has_unresolved_takes_priority(self):
        s = self._summary(
            card_mention_count=5,
            resolved_card_count=3,
            ambiguous_card_count=1,
            unresolved_card_count=1,
        )
        assert _derive_log_resolution_status(s) == "has_unresolved"

    def test_has_ambiguous_when_no_unresolved(self):
        s = self._summary(
            card_mention_count=5,
            resolved_card_count=4,
            ambiguous_card_count=1,
        )
        assert _derive_log_resolution_status(s) == "has_ambiguous"

# ── clean_extracted_card_name ──────────────────────────────────────────────────

class TestCleanExtractedCardName:
    def test_dreepy_in_active_spot(self):
        assert clean_extracted_card_name("Dreepy in the Active Spot") == "Dreepy"

    def test_munkidori_on_bench(self):
        assert clean_extracted_card_name("Munkidori on the Bench") == "Munkidori"

    def test_dunsparce_on_bench(self):
        assert clean_extracted_card_name("Dunsparce on the Bench") == "Dunsparce"

    def test_drakloak_on_bench(self):
        assert clean_extracted_card_name("Drakloak on the Bench") == "Drakloak"

    def test_multiword_name_in_active_spot(self):
        assert (
            clean_extracted_card_name("Cornerstone Mask Ogerpon ex in the Active Spot")
            == "Cornerstone Mask Ogerpon ex"
        )

    def test_apostrophe_name_on_bench(self):
        assert (
            clean_extracted_card_name("Team Rocket's Mewtwo ex on the Bench")
            == "Team Rocket's Mewtwo ex"
        )

    def test_no_suffix_unchanged(self):
        assert clean_extracted_card_name("Pikachu") == "Pikachu"
        assert clean_extracted_card_name("Lucario ex") == "Lucario ex"
        assert clean_extracted_card_name("Basic Fighting Energy") == "Basic Fighting Energy"

    def test_no_internal_stripping(self):
        # "Bench" does not appear at end with the right prefix → unchanged
        assert clean_extracted_card_name("Bench Press Energy") == "Bench Press Energy"

    def test_empty_string(self):
        assert clean_extracted_card_name("") == ""

    def test_to_active_spot(self):
        assert clean_extracted_card_name("Riolu to the Active Spot") == "Riolu"

    def test_from_bench(self):
        assert clean_extracted_card_name("Pikachu from the Bench") == "Pikachu"

    def test_from_active_spot(self):
        assert clean_extracted_card_name("Hariyama from the Active Spot") == "Hariyama"

    def test_case_insensitive(self):
        # Suffix check is case-insensitive
        assert clean_extracted_card_name("Pikachu ON THE BENCH") == "Pikachu"


# ── Phase 3.1: zone-suffix cleaning in extraction ─────────────────────────────

class TestZoneSuffixCleaningInExtraction:
    def test_attack_target_zone_suffix_stripped(self):
        """target_card_name_raw with zone suffix should produce cleaned raw_name."""
        evt = _event(ET_ATTACK_USED,
                     card_name_raw="Lucario ex",
                     target_card_name_raw="Dreepy in the Active Spot")
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Dreepy in the Active Spot" not in names
        assert "Dreepy" in names

    def test_attack_target_bench_suffix_stripped(self):
        evt = _event(ET_ATTACK_USED,
                     card_name_raw="Lucario ex",
                     target_card_name_raw="Munkidori on the Bench")
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Munkidori on the Bench" not in names
        assert "Munkidori" in names

    def test_no_suffix_name_unchanged(self):
        evt = _event(ET_ATTACK_USED,
                     card_name_raw="Lucario ex",
                     target_card_name_raw="Pikachu")
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Pikachu" in names

    def test_multiword_zone_suffix_stripped(self):
        evt = _event(ET_ATTACK_USED,
                     card_name_raw="Lucario ex",
                     target_card_name_raw="Cornerstone Mask Ogerpon ex in the Active Spot")
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Cornerstone Mask Ogerpon ex in the Active Spot" not in names
        assert "Cornerstone Mask Ogerpon ex" in names


# ── Phase 3.1: improved mention roles ─────────────────────────────────────────

class TestImprovedMentionRoles:
    def test_draw_event_uses_drawn_card_role(self):
        evt = _event(ET_DRAW, card_name_raw="Pikachu")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "drawn_card"
        assert mentions[0]["raw_name"] == "Pikachu"

    def test_draw_hidden_produces_no_mention(self):
        """draw_hidden has no card_name_raw so nothing should be extracted."""
        evt = _event("draw_hidden", card_name_raw=None)
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 0

    def test_switch_active_uses_actor_card_role(self):
        evt = _event(ET_SWITCH_ACTIVE, card_name_raw="Hariyama")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "actor_card"
        assert mentions[0]["raw_name"] == "Hariyama"

    def test_opening_hand_draw_known_uses_revealed_card_role(self):
        evt = _event(ET_OPENING_HAND_DRAW_KNOWN, card_name_raw=None,
                     event_payload_json={"cards": ["Pikachu", "Lucario"]})
        mentions = extract_mentions_from_event(evt)
        roles = {m["mention_role"] for m in mentions}
        assert roles == {"revealed_card"}
        names = {m["raw_name"] for m in mentions}
        assert "Pikachu" in names
        assert "Lucario" in names

    def test_opening_hand_payload_zone_suffix_stripped(self):
        """Zone suffixes in payload card lists should be cleaned."""
        evt = _event(ET_OPENING_HAND_DRAW_KNOWN, card_name_raw=None,
                     event_payload_json={"cards": ["Pikachu on the Bench"]})
        mentions = extract_mentions_from_event(evt)
        names = {m["raw_name"] for m in mentions}
        assert "Pikachu on the Bench" not in names
        assert "Pikachu" in names

    def test_card_added_to_hand_role(self):
        evt = _event(ET_CARD_ADDED_TO_HAND, card_name_raw="Growing Grass Energy")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "added_to_hand_card"

    def test_card_effect_activated_role(self):
        evt = _event(ET_CARD_EFFECT_ACTIVATED, card_name_raw="Spiky Energy")
        mentions = extract_mentions_from_event(evt)
        assert len(mentions) == 1
        assert mentions[0]["mention_role"] == "effect_card"

    def test_non_card_strings_not_extracted(self):
        """Zone-only or generic strings should not become mentions."""
        for bad_name in ("a card", "card", "them", "", "2 cards"):
            evt = _event(ET_ATTACH_ENERGY, card_name_raw=bad_name)
            mentions = extract_mentions_from_event(evt)
            assert all(m["raw_name"] != bad_name for m in mentions), (
                f"Should not extract '{bad_name}'"
            )

    def test_false_unresolved_becomes_resolvable(self):
        """After cleaning, a zone-suffixed name that matches a card DB entry
        should become ambiguous/resolved rather than unresolved."""
        from app.observed_play.card_resolution import _resolve_one
        # Simulate: before cleaning "Dreepy in the Active Spot" → unresolved
        # After cleaning → "Dreepy" → ambiguous (2 prints)
        cards = {
            "dreepy": [
                {"tcgdex_id": "sv01-001", "name": "Dreepy",
                 "set_abbrev": "sv01", "set_number": "001", "image_url": None},
                {"tcgdex_id": "sv02-001", "name": "Dreepy",
                 "set_abbrev": "sv02", "set_number": "001", "image_url": None},
            ]
        }
        # Uncleaned → unresolved
        result_bad = _resolve_one("dreepy in the active spot", cards, {})
        assert result_bad["resolution_status"] == "unresolved"
        # Cleaned → ambiguous
        result_good = _resolve_one("dreepy", cards, {})
        assert result_good["resolution_status"] == "ambiguous"

    def test_ambiguous_same_name_stays_ambiguous(self):
        """Multiple prints of same name must remain ambiguous."""
        from app.observed_play.card_resolution import _resolve_one
        cards = {
            "pikachu": [
                {"tcgdex_id": "sv01-001", "name": "Pikachu",
                 "set_abbrev": "sv01", "set_number": "001", "image_url": None},
                {"tcgdex_id": "sv02-001", "name": "Pikachu",
                 "set_abbrev": "sv02", "set_number": "001", "image_url": None},
            ]
        }
        result = _resolve_one("pikachu", cards, {})
        assert result["resolution_status"] == "ambiguous"
        assert result["candidate_count"] == 2
