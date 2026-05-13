"""Tests for backend/scripts/validate_card_audit_report.py (audit-quality-v4).

Covers:
- risky no-issue behavioral-proof requirements
- behavioral evidence proof-type validation
- top-level behavioral coverage accounting
- completion-status gating with behavioral-unverified rows
- retained v3 structural/evidence rejection behavior
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.validate_card_audit_report import validate


RISKY_FLAGS = {"deck-search", "draw", "discard", "energy-attach", "energy-move", "switch", "gust",
               "force-switch", "status-condition", "damage-modifier-pre-wr", "damage-modifier-post-wr",
               "bench-damage", "prize-manipulation", "once-per-turn", "evolution-trigger",
               "on-play-trigger", "passive-tool", "passive-stadium", "passive-ability", "attack-lock",
               "next-turn-effect", "choice-request", "explicit-empty-selection", "coin-flip",
               "zone-update", "heal", "bench-effect"}


def _existing_test_ev() -> dict:
    return {
        "effect_name": "Search Effect",
        "proof_type": "existing-test",
        "test_file": "backend/tests/test_engine/test_audit_fixes.py",
        "test_name": "test_search_effect",
        "probe_name": None,
        "assertions": ["searches deck", "updates state"],
        "passed": True,
    }


def _generated_probe_ev() -> dict:
    return {
        "effect_name": "Search Effect",
        "proof_type": "generated-probe",
        "test_file": None,
        "test_name": None,
        "probe_name": "probe_search_effect",
        "assertions": ["searches deck", "updates state"],
        "passed": True,
    }


def _not_required_ev() -> dict:
    return {
        "effect_name": "flat-damage",
        "proof_type": "not-required",
        "test_file": None,
        "test_name": None,
        "probe_name": None,
        "assertions": [],
        "passed": None,
    }


def _behavioral_unverified_ev() -> dict:
    return {
        "effect_name": "Search Effect",
        "proof_type": "behavioral-unverified",
        "test_file": None,
        "test_name": None,
        "probe_name": None,
        "assertions": [],
        "passed": None,
    }


def _risky_entry(**overrides) -> dict:
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
                "handler_symbol": "_nest_ball",
                "handler_file": "backend/app/engine/effects/trainers.py",
                "handler_found": True,
                "source_evidence": "registry._trainer_effects['sv06-175']",
                "semantic_checks": ["deck-search", "bench-effect", "shuffle-after-search"],
            }
        ],
        "mechanic_flags": ["deck-search", "bench-effect"],
        "behavioral_evidence": [_existing_test_ev()],
        "result": "no-issue",
        "finding_counted": False,
        "confidence": "medium",
        "notes": "Nest Ball handler and behavior validated by focused test.",
    }
    entry.update(overrides)
    return entry


def _flat_entry(**overrides) -> dict:
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
        "tcgdex_effects_extracted": [
            {
                "kind": "attack",
                "name": "Tackle",
                "raw_text": "",
                "cost": "Colorless",
                "damage": "10",
                "requires_handler": False,
                "reason": "flat-damage attack",
            }
        ],
        "implementation_evidence": [],
        "mechanic_flags": [],
        "behavioral_evidence": [_not_required_ev()],
        "result": "no-issue",
        "finding_counted": False,
        "confidence": "high",
        "notes": "Flat damage only; no behavior proof required.",
    }
    entry.update(overrides)
    return entry


def _compute_behavioral_totals(entries: list[dict]) -> tuple[int, int, int, float]:
    required = 0
    verified = 0
    unverified = 0
    for entry in entries:
        flags = {str(f).lower().replace("_", "-") for f in entry.get("mechanic_flags") or []}
        risky = bool(flags & RISKY_FLAGS)
        result = entry.get("result")
        if risky and result in {"no-issue", "behavioral-unverified"}:
            required += 1
            ev = entry.get("behavioral_evidence") or []
            has_verified = any(
                isinstance(item, dict)
                and item.get("proof_type") in {"existing-test", "generated-probe"}
                and item.get("passed") is True
                and item.get("assertions")
                for item in ev
            )
            if has_verified:
                verified += 1
            elif result == "behavioral-unverified":
                unverified += 1
    coverage = 100.0 if required == 0 else round((verified / required) * 100.0, 2)
    return required, verified, unverified, coverage


def _report(entries: list[dict], **overrides) -> dict:
    required, verified, unverified, coverage = _compute_behavioral_totals(entries)
    report = {
        "run_date_utc": "2026-05-20",
        "completion_status": "DB_EXHAUSTED",
        "target_findings": 25,
        "fixes_implemented": 0,
        "engine_gaps_documented": 0,
        "total_findings": 0,
        "cards_audited": len(entries),
        "db_card_count": len(entries),
        "full_cycle_completed": True,
        "continuation_required": False,
        "start_cursor_used": "START_OF_DATABASE_CARD_LIST",
        "first_card_audited": "Nest Ball | OBF | 175 | sv06-175",
        "last_card_fully_audited": "Nest Ball | OBF | 175 | sv06-175",
        "next_resume_cursor": "START_OF_DATABASE_CARD_LIST",
        "traversal_wrapped": False,
        "behavioral_rows_required": required,
        "behavioral_rows_verified": verified,
        "behavioral_rows_unverified": unverified,
        "behavioral_coverage_percent": coverage,
        "audit_ledger": entries,
    }
    report.update(overrides)
    return report


def test_risky_no_issue_registry_only_fails():
    report = _report([_risky_entry(behavioral_evidence=[])])
    errors = validate(report)
    assert any("risky no-issue rows require behavioral evidence" in e for e in errors)


def test_risky_no_issue_existing_test_passes():
    report = _report([_risky_entry()])
    assert validate(report) == []


def test_risky_no_issue_generated_probe_passes():
    report = _report([_risky_entry(behavioral_evidence=[_generated_probe_ev()])])
    assert validate(report) == []


def test_flat_no_effect_not_required_passes():
    report = _report([_flat_entry()])
    assert validate(report) == []


def test_passive_tool_no_issue_without_behavioral_fails():
    report = _report([_risky_entry(mechanic_flags=["passive Tool"], behavioral_evidence=[])])
    errors = validate(report)
    assert any("risky no-issue rows require behavioral evidence" in e for e in errors)


def test_passive_stadium_no_issue_without_behavioral_fails():
    report = _report([_risky_entry(mechanic_flags=["passive_stadium"], behavioral_evidence=[])])
    errors = validate(report)
    assert any("risky no-issue rows require behavioral evidence" in e for e in errors)


def test_passive_ability_no_issue_without_behavioral_fails():
    report = _report([_risky_entry(mechanic_flags=["passive ability"], behavioral_evidence=[])])
    errors = validate(report)
    assert any("risky no-issue rows require behavioral evidence" in e for e in errors)


def test_continuation_required_behavioral_unverified_accounted_passes():
    row = _risky_entry(
        result="behavioral-unverified",
        confidence="medium",
        behavioral_evidence=[_behavioral_unverified_ev()],
    )
    report = _report(
        [row],
        completion_status="CONTINUATION_REQUIRED",
        full_cycle_completed=False,
        continuation_required=True,
        db_card_count=1607,
    )
    assert validate(report) == []


def test_db_exhausted_with_behavioral_unverified_fails():
    row = _risky_entry(
        result="behavioral-unverified",
        confidence="medium",
        behavioral_evidence=[_behavioral_unverified_ev()],
    )
    report = _report([row], completion_status="DB_EXHAUSTED")
    errors = validate(report)
    assert any("DB_EXHAUSTED is not allowed" in e for e in errors)


def test_missing_behavioral_top_level_counts_fails():
    report = _report([_risky_entry()])
    del report["behavioral_rows_required"]
    errors = validate(report)
    assert any("behavioral_rows_required" in e for e in errors)


def test_mismatched_behavioral_counts_fail():
    report = _report([_risky_entry()], behavioral_rows_verified=0)
    errors = validate(report)
    assert any("behavioral_rows_verified does not match" in e for e in errors)


def test_incorrect_behavioral_coverage_percent_fails():
    report = _report([_risky_entry()], behavioral_coverage_percent=0.0)
    errors = validate(report)
    assert any("behavioral_coverage_percent does not match" in e for e in errors)


def test_existing_v3_style_risky_no_issue_without_behavioral_fails():
    entry = _risky_entry()
    del entry["behavioral_evidence"]
    report = _report([entry])
    errors = validate(report)
    assert any("risky no-issue rows require behavioral evidence" in e for e in errors)


def test_existing_v3_style_flat_no_effect_can_pass():
    entry = _flat_entry()
    del entry["behavioral_evidence"]
    report = _report([entry])
    assert validate(report) == []


def test_existing_test_passed_false_fails():
    bad_ev = _existing_test_ev()
    bad_ev["passed"] = False
    report = _report([_risky_entry(behavioral_evidence=[bad_ev])])
    errors = validate(report)
    assert any("existing-test evidence requires passed=true" in e for e in errors)


def test_existing_test_empty_assertions_fails():
    bad_ev = _existing_test_ev()
    bad_ev["assertions"] = []
    report = _report([_risky_entry(behavioral_evidence=[bad_ev])])
    errors = validate(report)
    assert any("existing-test evidence requires non-empty assertions" in e for e in errors)


def test_generated_probe_missing_probe_name_fails():
    bad_ev = _generated_probe_ev()
    bad_ev["probe_name"] = None
    report = _report([_risky_entry(behavioral_evidence=[bad_ev])])
    errors = validate(report)
    assert any("generated-probe evidence requires probe_name" in e for e in errors)


def test_manual_reviewed_gap_cannot_support_no_issue():
    manual_gap = {
        "effect_name": "Search Effect",
        "proof_type": "manual-reviewed-gap",
        "test_file": None,
        "test_name": None,
        "probe_name": None,
        "assertions": [],
        "passed": None,
    }
    report = _report([_risky_entry(behavioral_evidence=[manual_gap])])
    errors = validate(report)
    assert any("manual-reviewed-gap is only valid" in e for e in errors)


def test_generic_no_issue_note_still_fails():
    report = _report([_risky_entry(notes="handler coverage was verified")])
    errors = validate(report)
    assert any("generic" in e.lower() for e in errors)


def test_handler_not_found_no_issue_still_fails():
    row = copy.deepcopy(_risky_entry())
    row["implementation_evidence"][0]["handler_found"] = False
    report = _report([row])
    errors = validate(report)
    assert any("handler_found=false" in e for e in errors)
