from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.observed_play.archetype_labels import (
    CardSignal,
    ObservedCardSignal,
    canonicalize_label_key,
    infer_deck_labels_from_cards,
    infer_observed_log_labels_from_signals,
)
from app.observed_play.schemas import ArchetypeLabel


def _labels_by_key(labels):
    return {label.canonical_key: label for label in labels}


class TestCanonicalizeLabelKey:
    def test_normalizes_spaces_punctuation_and_case(self):
        assert canonicalize_label_key("Dragapult ex") == "dragapult-ex"
        assert canonicalize_label_key("Lillie’s Clefairy ex") == "lillies-clefairy-ex"
        assert canonicalize_label_key("Poison/Burn") == "poison-burn"
        assert canonicalize_label_key("  Fire   toolbox!! ") == "fire-toolbox"


class TestArchetypeLabelSchema:
    def test_accepts_canonical_label_shape(self):
        label = ArchetypeLabel(
            label="Dragapult ex",
            canonical_key="dragapult-ex",
            label_type="archetype",
            source="deck_cards",
            confidence=0.92,
            evidence_card_ids=["sv06-130"],
            evidence_card_names=["Dragapult ex"],
            evidence_counts={"dragapult ex": 3},
        )

        assert label.review_status == "suggested"
        assert label.schema_version == "archetype_label_v1"

    def test_rejects_invalid_confidence(self):
        with pytest.raises(ValidationError):
            ArchetypeLabel(
                label="Dragapult ex",
                canonical_key="dragapult-ex",
                label_type="archetype",
                source="deck_cards",
                confidence=1.2,
            )

    def test_rejects_unknown_label_type_source_and_status(self):
        with pytest.raises(ValidationError):
            ArchetypeLabel(
                label="Dragapult ex",
                canonical_key="dragapult-ex",
                label_type="game_rule",
                source="deck_cards",
                confidence=0.9,
            )
        with pytest.raises(ValidationError):
            ArchetypeLabel(
                label="Dragapult ex",
                canonical_key="dragapult-ex",
                label_type="archetype",
                source="simulator_truth",
                confidence=0.9,
            )
        with pytest.raises(ValidationError):
            ArchetypeLabel(
                label="Dragapult ex",
                canonical_key="dragapult-ex",
                label_type="archetype",
                source="deck_cards",
                review_status="automatic_truth",
                confidence=0.9,
            )


class TestDeckInference:
    def test_dragapult_deck_returns_archetype_and_secondary_labels(self):
        preview = infer_deck_labels_from_cards("deck-1", "Dragapult", [
            CardSignal("sv06-128", "Dreepy", 4, "pokemon"),
            CardSignal("sv06-129", "Drakloak", 3, "pokemon"),
            CardSignal("sv06-130", "Dragapult ex", 3, "pokemon"),
        ])

        labels = _labels_by_key(preview.labels)
        assert labels["dragapult-ex"].confidence == 0.92
        assert labels["dragapult-ex"].source == "deck_cards"
        assert "sv06-130" in labels["dragapult-ex"].evidence_card_ids
        assert labels["stage-2-setup"].label_type == "package"
        assert labels["spread-damage"].label_type == "strategy"
        assert preview.primary_label.canonical_key == "dragapult-ex"
        assert preview.ambiguous is False

    def test_salazzle_deck_returns_poison_burn_strategy(self):
        preview = infer_deck_labels_from_cards("deck-2", "Salazzle", [
            CardSignal("sv10-019", "Salandit", 4, "pokemon"),
            CardSignal("sv10-020", "Salazzle ex", 3, "pokemon"),
        ])

        labels = _labels_by_key(preview.labels)
        assert labels["salazzle-ex"].label_type == "archetype"
        assert labels["poison-burn-strategy"].label_type == "strategy"
        assert labels["poison-burn-strategy"].confidence < labels["salazzle-ex"].confidence

    def test_crustle_deck_returns_crustle_label(self):
        preview = infer_deck_labels_from_cards("deck-3", "Crustle", [
            CardSignal("sv07-075", "Dwebble", 4, "pokemon"),
            CardSignal("sv07-076", "Crustle", 4, "pokemon"),
        ])

        assert _labels_by_key(preview.labels)["crustle"].confidence >= 0.86

    def test_charizard_deck_returns_charizard_label(self):
        preview = infer_deck_labels_from_cards("deck-4", "Charizard", [
            CardSignal("sv03-004", "Charmander", 4, "pokemon", types=("Fire",)),
            CardSignal("sv03-005", "Charmeleon", 2, "pokemon", types=("Fire",)),
            CardSignal("sv03-006", "Charizard ex", 3, "pokemon", types=("Fire",)),
        ])

        labels = _labels_by_key(preview.labels)
        assert labels["charizard-ex"].confidence == 0.92
        assert "stage-2-setup" in labels
        assert "fire-toolbox" not in labels

    def test_gardevoir_deck_returns_psychic_engine_label(self):
        preview = infer_deck_labels_from_cards("deck-5", "Gardevoir", [
            CardSignal("sv01-084", "Ralts", 4, "pokemon", types=("Psychic",)),
            CardSignal("sv01-085", "Kirlia", 4, "pokemon", types=("Psychic",)),
            CardSignal("sv01-086", "Gardevoir ex", 2, "pokemon", types=("Psychic",)),
        ])

        labels = _labels_by_key(preview.labels)
        assert labels["gardevoir-ex"].confidence == 0.92
        assert labels["psychic-engine"].label_type == "package"

    def test_fire_toolbox_returns_lower_confidence_when_no_dominant_archetype(self):
        preview = infer_deck_labels_from_cards("deck-6", "Fire Box", [
            CardSignal("sv01-001", "Armarouge", 2, "pokemon", types=("Fire",)),
            CardSignal("sv01-002", "Entei", 2, "pokemon", types=("Fire",)),
            CardSignal("sv01-003", "Moltres", 2, "pokemon", types=("Fire",)),
        ])

        labels = _labels_by_key(preview.labels)
        assert labels["fire-toolbox"].label_type == "archetype"
        assert labels["fire-toolbox"].confidence == 0.66

    def test_unknown_deck_returns_no_label_reason(self):
        preview = infer_deck_labels_from_cards("deck-7", "Unknown", [
            CardSignal("sv01-200", "Nest Ball", 4, "trainer"),
        ])

        assert preview.labels == []
        assert preview.no_label_reason is not None

    def test_similarly_scored_archetypes_mark_ambiguous(self):
        preview = infer_deck_labels_from_cards("deck-8", "Mixed", [
            CardSignal("sv06-130", "Dragapult ex", 2, "pokemon"),
            CardSignal("sv06-128", "Dreepy", 2, "pokemon"),
            CardSignal("sv10-020", "Salazzle ex", 2, "pokemon"),
            CardSignal("sv10-019", "Salandit", 2, "pokemon"),
        ])

        assert preview.ambiguous is True
        assert len([label for label in preview.labels if label.label_type == "archetype"]) >= 2


class TestObservedLogInference:
    def test_observed_dragapult_labels_one_player(self):
        preview = infer_observed_log_labels_from_signals("log-1", [
            ObservedCardSignal("player_1", "sv06-130", "Dragapult ex", "resolved", "1", "mem-1"),
            ObservedCardSignal("player_1", "sv06-130", "Dragapult ex", "resolved", "2", "mem-2"),
            ObservedCardSignal("player_1", "sv06-129", "Drakloak", "resolved", "3", "mem-3"),
            ObservedCardSignal("player_2", "sv01-200", "Nest Ball", "resolved", "4", "mem-4"),
        ])

        labels = _labels_by_key(preview.labels_by_player["player_1"])
        assert labels["dragapult-ex"].confidence == 0.78
        assert labels["dragapult-ex"].player_alias == "player_1"
        assert "1" in labels["dragapult-ex"].evidence_event_ids
        assert "mem-1" in labels["dragapult-ex"].evidence_memory_item_ids
        assert "player_2" not in preview.labels_by_player

    def test_observed_salazzle_poison_burn_strategy(self):
        preview = infer_observed_log_labels_from_signals("log-2", [
            ObservedCardSignal("player_1", "sv10-020", "Salazzle ex", "resolved", "1", "mem-1", action_name="Poison Burst"),
            ObservedCardSignal("player_1", "sv10-020", "Salazzle ex", "resolved", "2", "mem-2", memory_type="attack_used"),
            ObservedCardSignal("player_1", "sv10-019", "Salandit", "resolved", "3", "mem-3"),
        ])

        labels = _labels_by_key(preview.labels_by_player["player_1"])
        assert labels["salazzle-ex"].label_type == "archetype"
        assert labels["poison-burn-strategy"].label_type == "strategy"

    def test_same_log_can_label_each_player_separately(self):
        preview = infer_observed_log_labels_from_signals("log-3", [
            ObservedCardSignal("player_1", "sv06-130", "Dragapult ex", "resolved", "1", "mem-1"),
            ObservedCardSignal("player_1", "sv06-130", "Dragapult ex", "resolved", "2", "mem-2"),
            ObservedCardSignal("player_2", "sv07-076", "Crustle", "resolved", "3", "mem-3"),
            ObservedCardSignal("player_2", "sv07-076", "Crustle", "resolved", "4", "mem-4"),
            ObservedCardSignal("player_2", "sv07-075", "Dwebble", "resolved", "5", "mem-5"),
        ])

        assert _labels_by_key(preview.labels_by_player["player_1"])["dragapult-ex"]
        assert _labels_by_key(preview.labels_by_player["player_2"])["crustle"]

    def test_one_off_mention_does_not_create_high_confidence_label(self):
        preview = infer_observed_log_labels_from_signals("log-4", [
            ObservedCardSignal("player_1", "sv06-130", "Dragapult ex", "resolved", "1", "mem-1"),
        ])

        assert preview.labels_by_player == {}
        assert preview.no_label_reason is not None

    def test_unresolved_mentions_do_not_create_high_confidence_labels(self):
        preview = infer_observed_log_labels_from_signals("log-5", [
            ObservedCardSignal("player_1", None, "Dragapult ex", "unresolved", "1", "mem-1"),
            ObservedCardSignal("player_1", None, "Dragapult ex", "unresolved", "2", "mem-2"),
            ObservedCardSignal("player_1", None, "Dreepy", "unresolved", "3", "mem-3"),
        ])

        assert preview.labels_by_player == {}
