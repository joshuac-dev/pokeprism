#!/usr/bin/env python3
"""Validate a card-effect audit report for evidence quality (schema v3).

Rejects shallow/generic audit reports that do not contain per-card implementation
evidence. Designed to run standalone (local debug) or inside the PR gate.

Usage:
    python3 backend/scripts/validate_card_audit_report.py <report.json>
    python3 -m scripts.validate_card_audit_report <report.json>

Exit codes:
    0 = valid
    1 = invalid (prints actionable error messages)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ── Generic note phrases that fail quality validation ─────────────────────────
# Matches sub-strings of notes that indicate no real implementation inspection.

_GENERIC_NOTE_PATTERNS: list[re.Pattern] = [
    re.compile(r"TCGDex text fetched and compared to current handler coverage", re.IGNORECASE),
    re.compile(r"no missing required effect handlers detected", re.IGNORECASE),
    re.compile(r"handler coverage", re.IGNORECASE),
    re.compile(r"compared to current handler", re.IGNORECASE),
    re.compile(r"compared to handler coverage", re.IGNORECASE),
    re.compile(r"TCGDex compared", re.IGNORECASE),
    re.compile(r"no issues? found", re.IGNORECASE),
    re.compile(r"no issues? detected", re.IGNORECASE),
    re.compile(r"all handlers? (present|found|registered|correct|in place)", re.IGNORECASE),
    re.compile(r"implementation (is |looks |seems )?(correct|fine|ok|good)", re.IGNORECASE),
    re.compile(r"handler (present|found|registered|correct|verified)", re.IGNORECASE),
]

# Result values that are valid for individual ledger entries
_ALLOWED_LEDGER_RESULTS = frozenset({
    "fixed", "engine-gap", "no-issue", "tcgdex-unresolved",
    "db-identity-gap", "blocked-tcgdex", "blocked-db-access",
    "continuation-required",
})

# Result values that are terminal statuses for the whole run
_ALLOWED_COMPLETION_STATUSES = frozenset({
    "TARGET_REACHED", "DB_EXHAUSTED", "FULL_CYCLE_COMPLETE",
    "BLOCKED_TCGDEX", "BLOCKED_DB_ACCESS", "CONTINUATION_REQUIRED",
})

# Categories that always require effect handlers (hence always need evidence)
_ALWAYS_EFFECT_BEARING_CATEGORIES = {"trainer"}

# Top-level required fields (structural)
_REQUIRED_TOP_LEVEL = [
    "run_date_utc", "completion_status", "target_findings",
    "fixes_implemented", "engine_gaps_documented", "total_findings",
    "cards_audited", "db_card_count", "full_cycle_completed",
    "continuation_required", "start_cursor_used",
    "first_card_audited", "last_card_fully_audited",
    "next_resume_cursor", "traversal_wrapped", "audit_ledger",
]

# Fields that indicate a v3 evidence-bearing ledger entry
_V3_EVIDENCE_FIELDS = frozenset({
    "tcgdex_effects_extracted", "implementation_evidence", "confidence",
    "mechanic_flags", "tcgdex_text_hash",
})

# Fields that indicate a legacy shallow ledger entry (old format)
_LEGACY_FIELDS = frozenset({"effects_checked"})


def _entry_label(entry: dict) -> str:
    seq = entry.get("seq", "?")
    tid = entry.get("tcgdex_id") or entry.get("db_id") or "unknown"
    name = entry.get("card_name", "")
    return f"seq={seq} tcgdex_id={tid!r} ({name})"


def _note_is_generic(note: str) -> bool:
    if not note:
        return False
    for pat in _GENERIC_NOTE_PATTERNS:
        if pat.search(note):
            return True
    return False


def _entry_requires_handler(entry: dict) -> bool:
    """Return True when the card requires at least one implementation handler."""
    category = (entry.get("category") or "").lower()
    if category in _ALWAYS_EFFECT_BEARING_CATEGORIES:
        return True
    # Special energy
    if category == "energy" and (entry.get("subcategory") or "").lower() == "special":
        return True
    # Any extracted effect with requires_handler=True
    for fx in entry.get("tcgdex_effects_extracted") or []:
        if isinstance(fx, dict) and fx.get("requires_handler"):
            return True
    return False


def validate(data: dict) -> list[str]:
    """Validate an audit report dict. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    # ── 1. Required top-level fields ──────────────────────────────────────────
    for field in _REQUIRED_TOP_LEVEL:
        if field not in data:
            fail(f"Missing required top-level field: {field!r}")

    if errors:
        return errors  # Can't continue without structure

    status = data["completion_status"]
    fixes = int(data.get("fixes_implemented", 0))
    gaps = int(data.get("engine_gaps_documented", 0))
    total = fixes + gaps
    target = int(data.get("target_findings", 0))
    cards_audited = int(data.get("cards_audited", 0))
    db_card_count = int(data.get("db_card_count", 0))
    full_cycle = bool(data.get("full_cycle_completed", False))
    continuation = bool(data.get("continuation_required", False))
    ledger = data.get("audit_ledger", [])

    # ── 2. completion_status validity ─────────────────────────────────────────
    if status == "PARTIAL_TIME_BUDGET":
        fail(
            "completion_status PARTIAL_TIME_BUDGET is not valid under robust-audit-v2. "
            "Use CONTINUATION_REQUIRED instead."
        )
    elif status not in _ALLOWED_COMPLETION_STATUSES:
        fail(
            f"Unknown completion_status: {status!r}. "
            f"Must be one of: {', '.join(sorted(_ALLOWED_COMPLETION_STATUSES))}"
        )

    # ── 3. TARGET_REACHED requires sufficient findings ─────────────────────────
    if status == "TARGET_REACHED":
        if total < target:
            fail(
                f"TARGET_REACHED requires fixes_implemented + engine_gaps_documented >= "
                f"target_findings. Got {total} ({fixes} fixes + {gaps} gaps) < {target}."
            )

    # ── 4. DB_EXHAUSTED / FULL_CYCLE_COMPLETE require full_cycle_completed ───
    if status in ("DB_EXHAUSTED", "FULL_CYCLE_COMPLETE"):
        if not full_cycle:
            fail(
                f"{status} requires full_cycle_completed=true in the audit report."
            )
        if db_card_count > 0 and cards_audited < db_card_count:
            fail(
                f"{status} requires cards_audited >= db_card_count. "
                f"Got {cards_audited} < {db_card_count}."
            )

    # ── 5. cards_audited must equal audit_ledger length ───────────────────────
    if cards_audited != len(ledger):
        fail(
            f"cards_audited={cards_audited} does not match audit_ledger length={len(ledger)}. "
            "Every audited card must have exactly one ledger entry."
        )

    # ── Per-entry validation ──────────────────────────────────────────────────
    has_any_legacy = False
    has_any_v3 = False

    for i, entry in enumerate(ledger):
        if not isinstance(entry, dict):
            fail(f"audit_ledger[{i}] is not an object")
            continue

        label = _entry_label(entry)

        # Required per-entry fields
        for ef in ("seq", "card_name", "result"):
            if ef not in entry:
                fail(f"{label}: missing required ledger field: {ef!r}")

        result = entry.get("result", "")
        if result == "partial-time-budget":
            fail(f"{label}: invalid result 'partial-time-budget'. Use 'continuation-required'.")
        elif result not in _ALLOWED_LEDGER_RESULTS:
            fail(f"{label}: unknown result: {result!r}")

        # Detect legacy vs v3 entry format
        entry_fields = set(entry.keys())
        is_legacy = bool(entry_fields & _LEGACY_FIELDS and not (entry_fields & _V3_EVIDENCE_FIELDS))
        is_v3 = bool(entry_fields & _V3_EVIDENCE_FIELDS)

        if is_legacy:
            has_any_legacy = True
        if is_v3:
            has_any_v3 = True

        # Skip deep quality checks for blocked/identity-gap results
        if result in ("blocked-tcgdex", "blocked-db-access", "db-identity-gap",
                      "continuation-required", "tcgdex-unresolved"):
            # ── 7. db_id null without db_identity_gap ─────────────────────────
            # db-identity-gap entries are exempt
            continue

        # ── 7. db_id null without db_identity_gap ─────────────────────────────
        if entry.get("db_id") is None and result != "db-identity-gap":
            fail(f"{label}: db_id is null but result is {result!r} (not 'db-identity-gap').")

        tcgdex_fetch = entry.get("tcgdex_fetch", "")

        if tcgdex_fetch == "ok":
            # ── 8. tcgdex_text_hash must be present ───────────────────────────
            if not entry.get("tcgdex_text_hash"):
                fail(f"{label}: tcgdex_fetch=ok but tcgdex_text_hash is missing.")

            # ── 9. tcgdex_effects_extracted must be present ───────────────────
            if "tcgdex_effects_extracted" not in entry:
                fail(
                    f"{label}: tcgdex_fetch=ok but tcgdex_effects_extracted is missing. "
                    "Provide an empty list [] to prove vanilla/no-effects, "
                    "or populate with extracted effects."
                )

        # ── 12. confidence is required ────────────────────────────────────────
        if "confidence" not in entry:
            fail(f"{label}: confidence field is missing (required: 'high' | 'medium' | 'low').")
        else:
            if entry["confidence"] not in ("high", "medium", "low"):
                fail(
                    f"{label}: confidence must be 'high', 'medium', or 'low'. "
                    f"Got: {entry['confidence']!r}"
                )

        # ── 14. Old shallow format detection ──────────────────────────────────
        if is_legacy and result == "no-issue":
            fail(
                f"{label}: uses legacy shallow ledger format (has 'effects_checked' "
                "but no v3 evidence fields). Re-run audit with evidence-bearing ledger schema."
            )

        # Remaining checks only apply to "no-issue" results
        if result != "no-issue":
            # For fixed/engine-gap, implementation_evidence is encouraged but not mandatory here
            # (the agent may have it for fixed items)
            continue

        # ── 6. no-issue rows must not use generic notes ───────────────────────
        notes = entry.get("notes", "") or ""
        if _note_is_generic(notes):
            fail(
                f"{label}: no-issue note is too generic. "
                f"Note: {notes[:120]!r}. "
                "Provide concrete evidence: handler name, registry key, semantic checks."
            )

        requires_handler = _entry_requires_handler(entry)

        # ── 9 (cont.) tcgdex_effects_extracted required for effect-bearing ───
        if requires_handler and "tcgdex_effects_extracted" not in entry:
            fail(
                f"{label}: result=no-issue for an effect-bearing card "
                "but tcgdex_effects_extracted is missing."
            )

        # ── 10. implementation_evidence required when requires_handler=True ──
        if requires_handler:
            impl_ev = entry.get("implementation_evidence")
            if not impl_ev:
                fail(
                    f"{label}: result=no-issue for an effect-bearing card "
                    "but implementation_evidence is missing or empty. "
                    "Provide registry lookup results and handler symbols."
                )

        impl_ev = entry.get("implementation_evidence") or []

        # ── 11. handler_found=false with result=no-issue ───────────────────
        for ev in impl_ev:
            if isinstance(ev, dict) and ev.get("handler_found") is False:
                fail(
                    f"{label}: implementation_evidence has handler_found=false "
                    "but result=no-issue. Cannot claim no-issue when a handler is missing."
                )

        # ── 13. semantic_checks empty for effect-bearing cards ────────────────
        if requires_handler and impl_ev:
            any_semantic = any(
                bool(ev.get("semantic_checks"))
                for ev in impl_ev
                if isinstance(ev, dict)
            )
            if not any_semantic:
                fail(
                    f"{label}: result=no-issue for an effect-bearing card "
                    "but semantic_checks are empty in all implementation_evidence entries. "
                    "List which mechanics were verified (e.g. 'zone-update', 'choice-request-type')."
                )

    # ── Overall legacy format check ────────────────────────────────────────────
    if has_any_legacy and not has_any_v3:
        fail(
            "Audit report uses legacy shallow ledger format. "
            "Re-run audit with evidence-bearing ledger schema."
        )

    return errors


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <audit-report.json>", file=sys.stderr)
        sys.exit(1)

    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(f"ERROR: File not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data: Any = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in {report_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("ERROR: Audit report must be a JSON object.", file=sys.stderr)
        sys.exit(1)

    errors = validate(data)

    if errors:
        print(f"\nAudit report validation FAILED: {report_path}")
        print(f"{len(errors)} error(s):\n")
        for err in errors:
            print(f"  ERROR: {err}")
        sys.exit(1)

    ledger_len = len(data.get("audit_ledger", []))
    print(f"Audit report validation PASSED: {report_path}")
    print(f"  completion_status: {data.get('completion_status')}")
    print(f"  cards_audited:     {data.get('cards_audited')}")
    print(f"  ledger_entries:    {ledger_len}")
    print(f"  fixes_implemented: {data.get('fixes_implemented')}")
    print(f"  engine_gaps:       {data.get('engine_gaps_documented')}")


if __name__ == "__main__":
    main()
