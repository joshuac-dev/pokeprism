#!/usr/bin/env python3
"""Validate a card-effect audit report for evidence quality (schema v4).

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
import unicodedata
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
    "continuation-required", "behavioral-unverified",
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
    "behavioral_rows_required", "behavioral_rows_verified",
    "behavioral_rows_unverified", "behavioral_coverage_percent",
]

# Fields that indicate a v3 evidence-bearing ledger entry
_V3_EVIDENCE_FIELDS = frozenset({
    "tcgdex_effects_extracted", "implementation_evidence", "confidence",
    "mechanic_flags", "tcgdex_text_hash",
})

# Fields that indicate a legacy shallow ledger entry (old format)
_LEGACY_FIELDS = frozenset({"effects_checked"})

_ALLOWED_BEHAVIORAL_PROOF_TYPES = frozenset({
    "existing-test", "generated-probe", "manual-reviewed-gap",
    "not-required", "behavioral-unverified",
})

# Canonical risky mechanic flags (audit-quality-v4)
_RISKY_MECHANICS = frozenset({
    "deck-search", "draw", "discard", "energy-attach", "energy-move",
    "switch", "bench-effect", "gust", "force-switch", "status-condition",
    "damage-modifier-pre-wr", "damage-modifier-post-wr", "bench-damage",
    "prize-manipulation", "once-per-turn", "evolution-trigger",
    "on-play-trigger", "passive-tool", "passive-stadium", "passive-ability",
    "attack-lock", "next-turn-effect", "choice-request",
    "explicit-empty-selection", "coin-flip", "zone-update", "heal",
})

_MECHANIC_ALIASES = {
    "force switch": "force-switch",
    "force_switch": "force-switch",
    "forced-switch": "force-switch",
    "forced_switch": "force-switch",
    "passive tool": "passive-tool",
    "passive_tool": "passive-tool",
    "passive stadium": "passive-stadium",
    "passive_stadium": "passive-stadium",
    "passive ability": "passive-ability",
    "passive_ability": "passive-ability",
}


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


def _normalize_flag(flag: str) -> str:
    norm = (flag or "").strip().lower().replace("_", "-")
    # Support aliases entered with either dashes or spaces.
    norm = _MECHANIC_ALIASES.get(norm, _MECHANIC_ALIASES.get(norm.replace("-", " "), norm))
    return norm


def _normalize_effect_text(raw_text: str) -> str:
    normalized = unicodedata.normalize("NFKD", raw_text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _infer_risky_mechanics_from_effect_text(entry: dict) -> set[str]:
    inferred: set[str] = set()

    extracted = entry.get("tcgdex_effects_extracted") or []
    impl_ev = entry.get("implementation_evidence") or []

    def add(flag: str) -> None:
        if flag in _RISKY_MECHANICS:
            inferred.add(flag)

    def has_any(text: str, needles: tuple[str, ...]) -> bool:
        return any(n in text for n in needles)

    # Infer from semantic checks when auditors already recorded mechanics there.
    for ev in impl_ev:
        if not isinstance(ev, dict):
            continue
        for raw in ev.get("semantic_checks") or []:
            if not isinstance(raw, str):
                continue
            norm = _normalize_flag(raw)
            if norm in _RISKY_MECHANICS:
                inferred.add(norm)

    # Infer from extracted effect text and kinds.
    for fx in extracted:
        if not isinstance(fx, dict):
            continue
        kind = (fx.get("kind") or "").strip().lower()
        raw_text = (fx.get("raw_text") or "")
        text = _normalize_effect_text(raw_text)

        if "search your deck" in text:
            add("deck-search")
        if "draw" in text:
            add("draw")
        if "discard" in text:
            add("discard")
        if "attach" in text and "energy" in text:
            add("energy-attach")
        if "move" in text and "energy" in text:
            add("energy-move")

        if "switch" in text:
            add("switch")
            if "your opponent" in text:
                add("force-switch")
                add("gust")
        if has_any(
            text,
            (
                "benched pokemon with their active pokemon",
                "switch their benched pokemon with their active pokemon",
            ),
        ):
            add("switch")
            add("force-switch")
            add("gust")

        if has_any(text, ("bench", "benched")):
            add("bench-effect")

        if has_any(text, ("burned", "confused", "poisoned", "paralyzed", "asleep")):
            add("status-condition")

        if "before applying weakness and resistance" in text:
            add("damage-modifier-pre-wr")
        if "after applying weakness and resistance" in text:
            add("damage-modifier-post-wr")

        if "benched pokemon" in text and has_any(
            text, ("damage", "damage counter", "damage counters", "put ")
        ):
            add("bench-damage")

        if "prize card" in text or "prize cards" in text:
            add("prize-manipulation")

        if has_any(
            text,
            (
                "once during your turn",
                "once during each player's turn",
                "once during each of your turns",
                "once per turn",
            ),
        ):
            add("once-per-turn")

        if "when you play this pokemon from your hand to evolve" in text:
            add("evolution-trigger")
            add("on-play-trigger")
        elif "when you play this pokemon from your hand" in text:
            add("on-play-trigger")

        if kind == "tool" or (kind == "trainer" and "attached to" in text):
            add("passive-tool")
        if kind == "stadium":
            add("passive-stadium")
        if kind in {"ability", "passive"} and has_any(
            text, ("as long as", "prevent", "can't", "cannot", "each of your", "all of your")
        ):
            add("passive-ability")

        if has_any(text, ("can't attack", "cannot attack", "can't use", "cannot use")):
            add("attack-lock")

        if has_any(text, ("during your opponent's next turn", "during your next turn")):
            add("next-turn-effect")

        if "choose" in text:
            add("choice-request")

        if "flip a coin" in text:
            add("coin-flip")

        if has_any(text, ("heal", "remove damage")):
            add("heal")

        zone_terms = ("deck", "hand", "discard", "bench", "active", "prize")
        zones_present = [z for z in zone_terms if z in text]
        has_zone_move_verb = bool(re.search(r"\b(move|switch|attach|discard|return|put|take)\b", text))
        has_from_to_zone = bool(
            re.search(
                r"\bfrom (?:your |the )?(deck|hand|discard|bench|active|prize)\b.*\bto (?:your |the )?(deck|hand|discard|bench|active|prize)\b",
                text,
            )
        )
        if has_zone_move_verb and (len(zones_present) >= 2 or has_from_to_zone):
            add("zone-update")

    # Infer passive mechanics from passive handler evidence.
    has_passive_handler = any(
        isinstance(ev, dict) and ev.get("handler_symbol") == "passive"
        for ev in impl_ev
    )
    if has_passive_handler:
        kinds = {
            (fx.get("kind") or "").strip().lower()
            for fx in extracted
            if isinstance(fx, dict)
        }
        if "tool" in kinds:
            add("passive-tool")
        elif "stadium" in kinds:
            add("passive-stadium")
        else:
            add("passive-ability")

    return inferred


def _entry_risky_mechanics(entry: dict) -> set[str]:
    risky: set[str] = set()
    for flag in entry.get("mechanic_flags") or []:
        if not isinstance(flag, str):
            continue
        norm = _normalize_flag(flag)
        if norm in _RISKY_MECHANICS:
            risky.add(norm)

    risky.update(_infer_risky_mechanics_from_effect_text(entry))

    return risky


def _has_non_empty_assertions(assertions: Any) -> bool:
    return isinstance(assertions, list) and any(str(a).strip() for a in assertions)


def _validate_behavioral_evidence(
    *,
    entry: dict,
    label: str,
    risky_mechanics: set[str],
    errors: list[str],
) -> tuple[bool, bool, bool]:
    behavioral = entry.get("behavioral_evidence")
    result = entry.get("result")
    requires_handler = _entry_requires_handler(entry)
    flat_no_effect = (
        not requires_handler
        and not risky_mechanics
        and result == "no-issue"
    )

    if behavioral is None:
        behavioral = []
    if not isinstance(behavioral, list):
        errors.append(f"{label}: behavioral_evidence must be a list when present.")
        return False, False, False

    has_verified = False
    has_unverified_marker = False
    has_not_required = False

    for j, ev in enumerate(behavioral):
        if not isinstance(ev, dict):
            errors.append(f"{label}: behavioral_evidence[{j}] must be an object.")
            continue

        proof_type = ev.get("proof_type")
        if proof_type not in _ALLOWED_BEHAVIORAL_PROOF_TYPES:
            errors.append(
                f"{label}: behavioral_evidence[{j}] has unknown proof_type={proof_type!r}."
            )
            continue

        assertions = ev.get("assertions")
        passed = ev.get("passed")

        if proof_type == "existing-test":
            valid = True
            if not ev.get("test_file"):
                errors.append(f"{label}: existing-test evidence requires test_file.")
                valid = False
            if not ev.get("test_name"):
                errors.append(f"{label}: existing-test evidence requires test_name.")
                valid = False
            if not _has_non_empty_assertions(assertions):
                errors.append(f"{label}: existing-test evidence requires non-empty assertions.")
                valid = False
            if passed is not True:
                errors.append(f"{label}: existing-test evidence requires passed=true.")
                valid = False
            if valid:
                has_verified = True

        elif proof_type == "generated-probe":
            valid = True
            if not ev.get("probe_name"):
                errors.append(f"{label}: generated-probe evidence requires probe_name.")
                valid = False
            if not _has_non_empty_assertions(assertions):
                errors.append(f"{label}: generated-probe evidence requires non-empty assertions.")
                valid = False
            if passed is not True:
                errors.append(f"{label}: generated-probe evidence requires passed=true.")
                valid = False
            if valid:
                has_verified = True

        elif proof_type == "manual-reviewed-gap":
            if result not in ("engine-gap", "behavioral-unverified"):
                errors.append(
                    f"{label}: manual-reviewed-gap is only valid with result=engine-gap "
                    "or result=behavioral-unverified."
                )

        elif proof_type == "not-required":
            if not flat_no_effect:
                errors.append(
                    f"{label}: not-required is only valid for flat/no-effect no-issue rows "
                    "without risky mechanics."
                )
            else:
                has_not_required = True

        elif proof_type == "behavioral-unverified":
            if result != "behavioral-unverified":
                errors.append(
                    f"{label}: proof_type behavioral-unverified requires "
                    "result=behavioral-unverified."
                )
            else:
                has_unverified_marker = True

    return has_verified, has_unverified_marker, has_not_required


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
    declared_behavioral_required = int(data.get("behavioral_rows_required", 0))
    declared_behavioral_verified = int(data.get("behavioral_rows_verified", 0))
    declared_behavioral_unverified = int(data.get("behavioral_rows_unverified", 0))
    declared_behavioral_coverage = float(data.get("behavioral_coverage_percent", 0.0))
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
    computed_behavioral_required = 0
    computed_behavioral_verified = 0
    computed_behavioral_unverified = 0

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
        flagged_risky: set[str] = set()
        for raw_flag in (entry.get("mechanic_flags") or []):
            if not isinstance(raw_flag, str):
                continue
            normalized = _normalize_flag(raw_flag)
            if normalized in _RISKY_MECHANICS:
                flagged_risky.add(normalized)
        inferred_risky = _infer_risky_mechanics_from_effect_text(entry)
        risky_mechanics = flagged_risky | inferred_risky
        has_verified_behavior, has_unverified_marker, has_not_required = _validate_behavioral_evidence(
            entry=entry,
            label=label,
            risky_mechanics=risky_mechanics,
            errors=errors,
        )

        if result in ("no-issue", "behavioral-unverified") and risky_mechanics:
            computed_behavioral_required += 1
            if has_verified_behavior:
                computed_behavioral_verified += 1
            elif result == "behavioral-unverified":
                computed_behavioral_unverified += 1

        if result == "behavioral-unverified":
            if not risky_mechanics:
                fail(
                    f"{label}: result=behavioral-unverified requires at least one risky mechanic flag."
                )
            if not (has_unverified_marker or any(
                isinstance(ev, dict) and ev.get("proof_type") == "manual-reviewed-gap"
                for ev in (entry.get("behavioral_evidence") or [])
            )):
                fail(
                    f"{label}: behavioral-unverified row must include proof_type "
                    "behavioral-unverified or manual-reviewed-gap."
                )
            if entry.get("confidence") == "high":
                fail(
                    f"{label}: result=behavioral-unverified cannot have confidence='high'."
                )
            continue

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

        if risky_mechanics and not has_verified_behavior:
            missing_flags = sorted(inferred_risky - flagged_risky)
            missing_flag_hint = (
                f" Inferred risky mechanics missing from mechanic_flags: {', '.join(missing_flags)}."
                if missing_flags else ""
            )
            fail(
                f"{label}: risky no-issue rows require behavioral evidence with "
                "proof_type existing-test or generated-probe (passed=true). "
                "Registry evidence alone is not behavioral proof."
                f"{missing_flag_hint}"
            )

        _ = has_not_required  # explicit not-required is optional for flat/no-effect rows.

    # ── Overall legacy format check ────────────────────────────────────────────
    if has_any_legacy and not has_any_v3:
        fail(
            "Audit report uses legacy shallow ledger format. "
            "Re-run audit with evidence-bearing ledger schema."
        )

    # ── Behavioral coverage totals (audit-quality-v4) ─────────────────────────
    if declared_behavioral_required != computed_behavioral_required:
        fail(
            "behavioral_rows_required does not match ledger-derived value: "
            f"declared={declared_behavioral_required}, computed={computed_behavioral_required}."
        )
    if declared_behavioral_verified != computed_behavioral_verified:
        fail(
            "behavioral_rows_verified does not match ledger-derived value: "
            f"declared={declared_behavioral_verified}, computed={computed_behavioral_verified}."
        )
    if declared_behavioral_unverified != computed_behavioral_unverified:
        fail(
            "behavioral_rows_unverified does not match ledger-derived value: "
            f"declared={declared_behavioral_unverified}, computed={computed_behavioral_unverified}."
        )

    if computed_behavioral_required == 0:
        expected_coverage = 100.0
    else:
        expected_coverage = round((computed_behavioral_verified / computed_behavioral_required) * 100.0, 2)

    if abs(declared_behavioral_coverage - expected_coverage) > 0.01:
        fail(
            "behavioral_coverage_percent does not match ledger-derived coverage: "
            f"declared={declared_behavioral_coverage}, expected={expected_coverage}."
        )

    if status in ("DB_EXHAUSTED", "FULL_CYCLE_COMPLETE") and computed_behavioral_unverified > 0:
        fail(
            f"{status} is not allowed when behavioral_rows_unverified > 0. "
            "Risky no-issue rows must be behaviorally verified before claiming cycle completion."
        )

    if status == "CONTINUATION_REQUIRED" and computed_behavioral_unverified > 0:
        if continuation is not True:
            fail(
                "CONTINUATION_REQUIRED with behavioral-unverified rows requires "
                "continuation_required=true."
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
