"""Section 5 — Effect handler spot check.

Loads 50 randomly-sampled cards from the local fixture library and verifies
that each card's attacks/abilities/trainer/energy effects have registered
handlers. This catches unregistered effects that would silently do nothing
in a real game.

Seed is fixed so the sample is deterministic across runs.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import app.engine.effects  # noqa: F401 — register_all via __init__
from app.engine.effects.registry import EffectRegistry

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "cards"
_RNG_SEED = 12345
_SAMPLE_SIZE = 50


def _fixture_to_coverage_dict(raw: dict) -> dict:
    """Convert a raw TCGDex fixture JSON to the format expected by check_card_coverage."""
    card_id = raw.get("id") or ""
    category = (raw.get("category") or "").lower()
    energy_type = raw.get("energyType") or ""
    subcategory = "special" if energy_type.lower() == "special" else ""

    attacks = []
    for atk in (raw.get("attacks") or []):
        attacks.append({
            "name": atk.get("name") or "",
            "effect": atk.get("effect") or "",
        })

    abilities = []
    for abl in (raw.get("abilities") or []):
        abilities.append({
            "name": abl.get("name") or "",
        })

    return {
        "tcgdex_id": card_id,
        "category": category,
        "subcategory": subcategory,
        "attacks": attacks,
        "abilities": abilities,
    }


def _load_sample() -> list[dict]:
    """Load 50 random fixture cards (deterministic seed)."""
    all_paths = list(FIXTURE_DIR.glob("*.json"))
    rng = random.Random(_RNG_SEED)
    sample_paths = rng.sample(all_paths, min(_SAMPLE_SIZE, len(all_paths)))
    cards = []
    for p in sample_paths:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            cards.append(_fixture_to_coverage_dict(raw))
        except Exception:
            pass
    return cards


@pytest.fixture(scope="module")
def sampled_cards() -> list[dict]:
    return _load_sample()


def test_sample_loads_50_cards(sampled_cards):
    assert len(sampled_cards) == _SAMPLE_SIZE, (
        f"Expected {_SAMPLE_SIZE} fixture cards, got {len(sampled_cards)}"
    )


def test_sampled_cards_have_no_unregistered_effects(sampled_cards):
    """Every sampled card must have all its effect handlers registered."""
    reg = EffectRegistry.instance()
    failures: list[str] = []

    for card in sampled_cards:
        card_id = card["tcgdex_id"]
        missing = reg.check_card_coverage(card)
        if missing:
            failures.append(f"{card_id}: missing {missing}")

    assert not failures, (
        f"{len(failures)} cards missing handlers:\n" + "\n".join(failures)
    )
