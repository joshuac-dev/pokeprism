"""Tests for backend/scripts/validate_card_audit_report.py.

Uses small inline fixture dicts — does not require real DB or TCGDex access.

Test cases:
1.  Valid evidence-bearing DB_EXHAUSTED report passes.
2.  Missing audit_ledger fails.
3.  Generic no-issue note fails.
4.  db_id null without db_identity_gap fails.
5.  no-issue with requires_handler=true but no implementation_evidence fails.
6.  handler_found=false with result=no-issue fails.
7.  cards_audited != ledger length fails.
8.  DB_EXHAUSTED without full_cycle_completed fails.
9.  TARGET_REACHED without enough findings fails.
10. Old shallow report format fails with clear message.
"""

from __future__ import annotations

import copy
import pytest

# Import the validate function directly — no app startup required.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.validate_card_audit_report import validate


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _v3_ledger_entry(**overrides) -> dict:
    """Return a valid v3 ledger entry for a trainer (effect-bearing)."""
    entry = {
        "seq": 1,
        "db_id": "sv06-130",
        "card_name": "Dragapult ex",
        "set_id": "OBF",
        "card_number": "130",
        "tcgdex_id": "sv06-130",
        "tcgdex_fetch": "ok",
        "category": "pokemon",
        "tcgdex_text_hash": "abcdef1234567890",
        "tcgdex_effects_extracted": [
            {
                "kind": "attack",
                "name": "Phantom Dive",
                "raw_text": "Put 6 damage counters on your opponent's Pokémon in any way you like.",
                "cost": "Psychic Dragon",
                "damage": "130",
                "requires_handler": True,
                "reason": "attack has effect text",
            }
        ],
        "implementation_evidence": [
            {
                "effect_name": "Phantom Dive",
                "registry_key": "sv06-130:1",
                "handler_symbol": "phantom_dive",
                "handler_file": "backend/app/engine/effects/attacks.py",
                "handler_found": True,
                "source_evidence": "registry._attack_effects['sv06-130:1']",
                "semantic_checks": ["zone-update", "damage-counter", "bench-spread"],
            }
        ],
        "mechanic_flags": ["damage-counter", "bench-effect"],
        "result": "no-issue",
        "finding_counted": False,
        "confidence": "high",
        "notes": "Phantom Dive handler sv06-130:1 registered; bench damage counter placement verified.",
    }
    entry.update(overrides)
    return entry


def _valid_exhausted_report(**overrides) -> dict:
    """Return a valid DB_EXHAUSTED report with a single evidence-bearing entry."""
    report = {
        "run_date_utc": "2026-05-20",
        "completion_status": "DB_EXHAUSTED",
        "target_findings": 25,
        "fixes_implemented": 0,
        "engine_gaps_documented": 0,
        "total_findings": 0,
        "cards_audited": 1,
        "db_card_count": 1,
        "full_cycle_completed": True,
        "continuation_required": False,
        "start_cursor_used": "START_OF_DATABASE_CARD_LIST",
        "first_card_audited": "Dragapult ex | OBF | 130 | sv06-130",
        "last_card_fully_audited": "Dragapult ex | OBF | 130 | sv06-130",
        "next_resume_cursor": "START_OF_DATABASE_CARD_LIST",
        "traversal_wrapped": False,
        "audit_ledger": [_v3_ledger_entry()],
    }
    report.update(overrides)
    return report


def _valid_trainer_entry(**overrides) -> dict:
    """Trainer card ledger entry with full v3 evidence."""
    entry = {
        "seq": 1,
        "db_id": "sv06-175",
        "card_name": "Nest Ball",
        "set_id": "OBF",
        "card_number": "175",
        "tcgdex_id": "sv06-175",
        "tcgdex_fetch": "ok",
        "category": "trainer",
        "tcgdex_text_hash": "aaaa1111bbbb2222",
        "tcgdex_effects_extracted": [
            {
                "kind": "trainer",
                "name": "Nest Ball",
                "raw_text": "Search your deck for a Basic Pokémon and put it onto your Bench.",
                "cost": "",
                "damage": "",
                "requires_handler": True,
                "reason": "trainer card always requires a handler",
            }
        ],
        "implementation_evidence": [
            {
                "effect_name": "trainer",
                "registry_key": "sv06-175",
                "handler_symbol": "nest_ball",
                "handler_file": "backend/app/engine/effects/trainers.py",
                "handler_found": True,
                "source_evidence": "registry._trainer_effects['sv06-175']",
                "semantic_checks": ["deck-search", "bench-effect", "shuffle-after-search"],
            }
        ],
        "mechanic_flags": ["deck-search"],
        "result": "no-issue",
        "finding_counted": False,
        "confidence": "high",
        "notes": "Nest Ball handler sv06-175 registered; deck-search and bench placement verified.",
    }
    entry.update(overrides)
    return entry


# ── Case 1: Valid evidence-bearing DB_EXHAUSTED report passes ─────────────────

def test_valid_exhausted_report_passes():
    report = _valid_exhausted_report()
    errors = validate(report)
    assert errors == [], f"Expected no errors but got: {errors}"


def test_valid_target_reached_report_passes():
    report = _valid_exhausted_report(
        completion_status="TARGET_REACHED",
        fixes_implemented=5,
        engine_gaps_documented=0,
        total_findings=5,
        target_findings=5,
        full_cycle_completed=False,
    )
    errors = validate(report)
    assert errors == [], f"Expected no errors but got: {errors}"


# ── Case 2: Missing audit_ledger fails ────────────────────────────────────────

def test_missing_audit_ledger_fails():
    report = _valid_exhausted_report()
    del report["audit_ledger"]
    errors = validate(report)
    assert any("audit_ledger" in e for e in errors), f"Expected audit_ledger error, got: {errors}"


def test_missing_required_field_fails():
    report = _valid_exhausted_report()
    del report["completion_status"]
    errors = validate(report)
    assert any("completion_status" in e for e in errors)


# ── Case 3: Generic no-issue note fails ───────────────────────────────────────

def test_generic_note_fails():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["notes"] = (
        "TCGDex text fetched and compared to current handler coverage; "
        "no missing required effect handlers detected."
    )
    errors = validate(report)
    assert any("generic" in e.lower() for e in errors), f"Expected generic note error, got: {errors}"


def test_generic_note_handler_coverage_fails():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["notes"] = "handler coverage was verified"
    errors = validate(report)
    assert any("generic" in e.lower() for e in errors)


def test_nongeneric_specific_note_passes():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["notes"] = (
        "Phantom Dive handler sv06-130:1 registered; bench damage counter placement verified."
    )
    errors = validate(report)
    assert errors == [], f"Expected no errors, got: {errors}"


# ── Case 4: db_id null without db_identity_gap fails ─────────────────────────

def test_db_id_null_without_identity_gap_fails():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["db_id"] = None
    errors = validate(report)
    assert any("db_id" in e for e in errors), f"Expected db_id error, got: {errors}"


def test_db_id_null_with_identity_gap_passes():
    report = _valid_exhausted_report()
    entry = _v3_ledger_entry(db_id=None, result="db-identity-gap")
    report["audit_ledger"] = [entry]
    report["cards_audited"] = 1
    errors = validate(report)
    # db-identity-gap skips deep checks; no db_id error
    assert not any("db_id" in e for e in errors), f"Should not have db_id error, got: {errors}"


# ── Case 5: no-issue with requires_handler=true but no implementation_evidence fails ──

def test_no_implementation_evidence_for_effect_bearing_fails():
    report = _valid_exhausted_report()
    entry = _v3_ledger_entry(implementation_evidence=[])
    report["audit_ledger"] = [entry]
    errors = validate(report)
    assert any("implementation_evidence" in e for e in errors), f"Expected impl_evidence error, got: {errors}"


def test_no_impl_evidence_trainer_fails():
    report = _valid_exhausted_report(
        audit_ledger=[_valid_trainer_entry(implementation_evidence=[])]
    )
    errors = validate(report)
    assert any("implementation_evidence" in e for e in errors)


# ── Case 6: handler_found=false with result=no-issue fails ───────────────────

def test_handler_not_found_no_issue_fails():
    report = _valid_exhausted_report()
    entry = copy.deepcopy(report["audit_ledger"][0])
    entry["implementation_evidence"][0]["handler_found"] = False
    report["audit_ledger"] = [entry]
    errors = validate(report)
    assert any("handler_found" in e for e in errors), f"Expected handler_found error, got: {errors}"


# ── Case 7: cards_audited != ledger length fails ──────────────────────────────

def test_cards_audited_mismatch_fails():
    report = _valid_exhausted_report(cards_audited=5)
    # ledger has 1 entry but cards_audited=5
    errors = validate(report)
    assert any("cards_audited" in e for e in errors), f"Expected mismatch error, got: {errors}"


def test_cards_audited_matches_ledger_passes():
    report = _valid_exhausted_report(
        cards_audited=1,
        db_card_count=1,
        audit_ledger=[_v3_ledger_entry()],
    )
    errors = validate(report)
    assert errors == [], f"Expected no errors, got: {errors}"


# ── Case 8: DB_EXHAUSTED without full_cycle_completed fails ──────────────────

def test_db_exhausted_without_full_cycle_fails():
    report = _valid_exhausted_report(full_cycle_completed=False)
    errors = validate(report)
    assert any("full_cycle_completed" in e for e in errors), f"Expected full_cycle error, got: {errors}"


def test_db_exhausted_cards_lt_db_count_fails():
    report = _valid_exhausted_report(
        full_cycle_completed=True,
        cards_audited=5,
        db_card_count=100,
        audit_ledger=[_v3_ledger_entry(seq=i) for i in range(1, 6)],
    )
    errors = validate(report)
    assert any("cards_audited" in e and "db_card_count" in e for e in errors), (
        f"Expected cards_audited < db_card_count error, got: {errors}"
    )


# ── Case 9: TARGET_REACHED without enough findings fails ─────────────────────

def test_target_reached_insufficient_findings_fails():
    report = _valid_exhausted_report(
        completion_status="TARGET_REACHED",
        fixes_implemented=2,
        engine_gaps_documented=1,
        total_findings=3,
        target_findings=25,
        full_cycle_completed=False,
    )
    errors = validate(report)
    assert any("TARGET_REACHED" in e for e in errors), f"Expected TARGET_REACHED error, got: {errors}"


def test_target_reached_exactly_at_target_passes():
    entry = _v3_ledger_entry(result="fixed", finding_counted=True)
    report = _valid_exhausted_report(
        completion_status="TARGET_REACHED",
        fixes_implemented=5,
        engine_gaps_documented=0,
        total_findings=5,
        target_findings=5,
        full_cycle_completed=False,
        audit_ledger=[entry],
        cards_audited=1,
        db_card_count=100,
    )
    errors = validate(report)
    assert errors == [], f"Expected no errors, got: {errors}"


# ── Case 10: Old shallow report format fails with clear message ───────────────

def test_old_shallow_format_fails():
    """Legacy entry with effects_checked but no v3 evidence fields must fail."""
    report = _valid_exhausted_report()
    report["audit_ledger"] = [
        {
            "seq": 1,
            "db_id": 42,
            "card_name": "Dragapult ex",
            "tcgdex_id": "sv06-130",
            "tcgdex_fetch": "ok",
            "effects_checked": ["attacks:2"],
            "result": "no-issue",
            "finding_counted": False,
            "notes": "Phantom Dive reviewed and implementation looks correct.",
        }
    ]
    errors = validate(report)
    assert errors, "Expected errors for old shallow format"
    # Should mention legacy/shallow
    assert any(
        "legacy" in e.lower() or "shallow" in e.lower() for e in errors
    ), f"Expected legacy/shallow mention in errors: {errors}"


def test_old_shallow_format_generic_note_fails():
    """Legacy entry with generic note should produce specific error messages."""
    report = _valid_exhausted_report()
    report["audit_ledger"] = [
        {
            "seq": 1,
            "db_id": 42,
            "card_name": "Dragapult ex",
            "tcgdex_id": "sv06-130",
            "tcgdex_fetch": "ok",
            "effects_checked": ["attacks:2"],
            "result": "no-issue",
            "finding_counted": False,
            "notes": (
                "TCGDex text fetched and compared to current handler coverage; "
                "no missing required effect handlers detected."
            ),
        }
    ]
    errors = validate(report)
    assert errors, "Expected errors"
    assert any(
        "legacy" in e.lower() or "shallow" in e.lower() or "generic" in e.lower()
        for e in errors
    )


# ── Additional edge cases ─────────────────────────────────────────────────────

def test_partial_time_budget_status_fails():
    report = _valid_exhausted_report(completion_status="PARTIAL_TIME_BUDGET")
    errors = validate(report)
    assert any("PARTIAL_TIME_BUDGET" in e for e in errors)


def test_unknown_completion_status_fails():
    report = _valid_exhausted_report(completion_status="MADE_UP_STATUS")
    errors = validate(report)
    assert any("MADE_UP_STATUS" in e or "Unknown" in e for e in errors)


def test_missing_confidence_fails():
    report = _valid_exhausted_report()
    del report["audit_ledger"][0]["confidence"]
    errors = validate(report)
    assert any("confidence" in e for e in errors)


def test_invalid_confidence_value_fails():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["confidence"] = "very-high"
    errors = validate(report)
    assert any("confidence" in e for e in errors)


def test_missing_tcgdex_text_hash_fails():
    report = _valid_exhausted_report()
    report["audit_ledger"][0]["tcgdex_text_hash"] = ""
    errors = validate(report)
    assert any("tcgdex_text_hash" in e for e in errors)


def test_missing_tcgdex_effects_extracted_fails():
    report = _valid_exhausted_report()
    del report["audit_ledger"][0]["tcgdex_effects_extracted"]
    errors = validate(report)
    assert any("tcgdex_effects_extracted" in e for e in errors)


def test_empty_semantic_checks_for_effect_bearing_fails():
    report = _valid_exhausted_report()
    entry = copy.deepcopy(report["audit_ledger"][0])
    entry["implementation_evidence"][0]["semantic_checks"] = []
    report["audit_ledger"] = [entry]
    errors = validate(report)
    assert any("semantic_checks" in e for e in errors), f"Expected semantic_checks error, got: {errors}"


def test_vanilla_pokemon_no_effects_passes():
    """Vanilla Pokémon with no effects (empty tcgdex_effects_extracted) passes."""
    entry = {
        "seq": 1,
        "db_id": "sv06-001",
        "card_name": "Bulbasaur",
        "set_id": "OBF",
        "card_number": "001",
        "tcgdex_id": "sv06-001",
        "tcgdex_fetch": "ok",
        "category": "pokemon",
        "tcgdex_text_hash": "1234abcd5678efgh",
        "tcgdex_effects_extracted": [],  # No effects — vanilla
        "implementation_evidence": [],
        "mechanic_flags": [],
        "result": "no-issue",
        "finding_counted": False,
        "confidence": "high",
        "notes": "Bulbasaur has no effect text. Flat damage only. No handler required.",
    }
    report = _valid_exhausted_report(audit_ledger=[entry])
    errors = validate(report)
    assert errors == [], f"Expected no errors for vanilla Pokemon, got: {errors}"


def test_blocked_tcgdex_entry_skips_deep_checks():
    """blocked-tcgdex entries should not trigger evidence checks."""
    entry = {
        "seq": 1,
        "db_id": None,
        "card_name": "Dragapult ex",
        "tcgdex_id": "sv06-130",
        "tcgdex_fetch": "blocked",
        "result": "blocked-tcgdex",
        "confidence": "high",
        "notes": "TCGDex returned 429 rate-limit error.",
    }
    report = _valid_exhausted_report(audit_ledger=[entry])
    errors = validate(report)
    # db_id=None is OK for blocked entries; no evidence required
    assert not any("db_id" in e for e in errors)
    assert not any("tcgdex_effects_extracted" in e for e in errors)
