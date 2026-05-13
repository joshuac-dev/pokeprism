#!/usr/bin/env python3
"""Card effect audit probe — generates v3 ledger skeleton rows from live data.

Fetches a card from the DB and TCGDex, inspects the effect registry, and
emits a JSON skeleton ledger entry for use in an audit report.

This script is a scaffolding aid for auditors. It does NOT assess semantic
correctness; the auditor must fill in semantic_checks and set confidence.

Usage:
    cd backend
    python3 -m scripts.card_effect_audit_probe --tcgdex-id sv06-130
    python3 -m scripts.card_effect_audit_probe --list [--limit 20] [--cursor "Dragapult ex"]

Options:
    --tcgdex-id ID        Probe a single card by TCGDex ID (e.g. sv06-130)
    --list                List DB cards with registry coverage status
    --limit N             Limit to first N cards when listing (default: 20)
    --cursor NAME         Start listing from this card name (sorted order)
    --output FILE         Write output JSON to a file instead of stdout
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)
_TEST_NAME_PATTERN = re.compile(r"^\s*(?:async\s+)?def\s+(test_[a-zA-Z0-9_]+)\s*\(", flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Registry inspection helpers (import lazily to avoid heavy app startup)
# ---------------------------------------------------------------------------

def _load_registry():
    """Import and return the populated EffectRegistry singleton."""
    # Force all handler modules to load so the registry is fully populated.
    import app.engine.effects.attacks   # noqa: F401
    import app.engine.effects.abilities  # noqa: F401
    import app.engine.effects.trainers  # noqa: F401
    from app.engine.effects.registry import EffectRegistry
    return EffectRegistry.instance()


def _registry_evidence(registry, card_id: str, category: str,
                        subcategory: str, attacks: list, abilities: list) -> list[dict]:
    """Inspect the registry and return a list of implementation_evidence dicts."""
    evidence: list[dict] = []
    category_lc = (category or "").lower()
    subcat_lc = (subcategory or "").lower()

    if category_lc == "trainer":
        key = card_id
        found = key in registry._trainer_effects
        handler = registry._trainer_effects.get(key)
        evidence.append({
            "effect_name": "trainer",
            "registry_key": key,
            "handler_symbol": getattr(handler, "__name__", None) if found else None,
            "handler_file": (
                _handler_file(handler) if found else None
            ),
            "handler_found": found,
            "source_evidence": f"registry._trainer_effects[{key!r}]",
            "semantic_checks": [],
        })

    elif category_lc == "energy" and subcat_lc == "special":
        key = card_id
        found = key in registry._energy_effects
        handler = registry._energy_effects.get(key)
        evidence.append({
            "effect_name": "energy",
            "registry_key": key,
            "handler_symbol": getattr(handler, "__name__", None) if found else None,
            "handler_file": (_handler_file(handler) if found else None),
            "handler_found": found,
            "source_evidence": f"registry._energy_effects[{key!r}]",
            "semantic_checks": [],
        })

    elif category_lc == "pokemon":
        for i, atk in enumerate(attacks or []):
            name = atk.get("name", f"attack_{i}")
            effect = (atk.get("effect") or "").strip()
            if not effect:
                continue  # flat-damage; no handler needed
            key = f"{card_id}:{i}"
            found = key in registry._attack_effects
            handler = registry._attack_effects.get(key)
            evidence.append({
                "effect_name": name,
                "registry_key": key,
                "handler_symbol": getattr(handler, "__name__", None) if found else None,
                "handler_file": (_handler_file(handler) if found else None),
                "handler_found": found,
                "source_evidence": f"registry._attack_effects[{key!r}]",
                "semantic_checks": [],
            })

        for abl in (abilities or []):
            name = abl.get("name", "")
            if not name:
                continue
            ab_key = f"{card_id}:{name}"
            found_active = ab_key in registry._ability_effects
            found_passive = ab_key in registry._passive_abilities
            handler = registry._ability_effects.get(ab_key)
            evidence.append({
                "effect_name": name,
                "registry_key": ab_key,
                "handler_symbol": (
                    getattr(handler, "__name__", None)
                    if found_active
                    else ("passive" if found_passive else None)
                ),
                "handler_file": (_handler_file(handler) if found_active else None),
                "handler_found": found_active or found_passive,
                "source_evidence": (
                    f"registry._ability_effects[{ab_key!r}]"
                    if found_active
                    else (
                        f"registry._passive_abilities has {ab_key!r}"
                        if found_passive
                        else f"not found in ability_effects or passive_abilities"
                    )
                ),
                "semantic_checks": [],
            })

    return evidence


def _handler_file(handler) -> str | None:
    if handler is None:
        return None
    try:
        import inspect
        src = inspect.getfile(handler)
        # Make relative to backend/
        parts = Path(src).parts
        try:
            idx = list(parts).index("backend")
            return str(Path(*parts[idx:]))
        except ValueError:
            return src
    except (TypeError, OSError):
        return None


def _extract_effects(category: str, subcategory: str,
                     attacks: list, abilities: list,
                     tcgdex_data: dict) -> list[dict]:
    """Extract effect entries for tcgdex_effects_extracted."""
    extracted: list[dict] = []
    cat = (category or "").lower()
    subcat = (subcategory or "").lower()

    if cat == "trainer":
        raw_text = tcgdex_data.get("effect") or tcgdex_data.get("text") or ""
        extracted.append({
            "kind": "trainer",
            "name": tcgdex_data.get("name", ""),
            "raw_text": raw_text,
            "cost": "",
            "damage": "",
            "requires_handler": True,
            "reason": "trainer card always requires a handler",
        })

    elif cat == "energy" and subcat == "special":
        raw_text = tcgdex_data.get("effect") or tcgdex_data.get("text") or ""
        extracted.append({
            "kind": "energy",
            "name": tcgdex_data.get("name", ""),
            "raw_text": raw_text,
            "cost": "",
            "damage": "",
            "requires_handler": True,
            "reason": "special energy always requires a handler",
        })

    elif cat == "pokemon":
        for atk in (attacks or []):
            effect = (atk.get("effect") or "").strip()
            requires = bool(effect)
            extracted.append({
                "kind": "attack",
                "name": atk.get("name", ""),
                "raw_text": effect,
                "cost": " ".join(atk.get("cost") or []),
                "damage": atk.get("damage", ""),
                "requires_handler": requires,
                "reason": "attack has effect text" if requires else "flat-damage attack",
            })

        for abl in (abilities or []):
            effect = (abl.get("effect") or "").strip()
            extracted.append({
                "kind": "ability",
                "name": abl.get("name", ""),
                "raw_text": effect,
                "cost": "",
                "damage": "",
                "requires_handler": True,
                "reason": "ability always requires handler or passive registration",
            })

    return extracted


def _mechanic_flags(tcgdex_effects_extracted: list[dict]) -> list[str]:
    """Derive mechanic_flags from extracted effects (keyword scanning)."""
    flags: set[str] = set()
    sentinel_map = [
        (r"search\b.*(deck|pile)", "deck-search"),
        (r"(choose|choose\s+\d+|choose one|choose an)", "choice-request"),
        (r"(before|prior to).*(weakness|resistance)", "damage-modifier-pre-wr"),
        (r"\bstadium\b", "passive-stadium"),
        (r"(damage counter|put.*counter)", "damage-counter"),
        (r"(shuffle|put.*back.*deck)", "shuffle-after-search"),
        (r"(discard|send.*discard)", "discard"),
        (r"(bench|benched)", "bench-effect"),
        (r"(heal|remove.*damage)", "heal"),
        (r"(switch|retreat)", "switch"),
        (r"(prize|take.*prize)", "prize-manipulation"),
        (r"once (per|during) (each|your) turn", "once-per-turn"),
        (r"(basic energy|special energy)", "energy-type-filter"),
        (r"(status|sleep|poison|paralyz|burn|confus)", "status-condition"),
    ]
    import re
    for fx in tcgdex_effects_extracted:
        text = (fx.get("raw_text") or "").lower()
        for pattern, flag in sentinel_map:
            if re.search(pattern, text, re.IGNORECASE):
                flags.add(flag)
    return sorted(flags)


def _behavioral_evidence_candidates(
    tcgdex_id: str,
    card_name: str,
    effects: list[dict],
    implementation_evidence: list[dict],
    mechanic_flags: list[str],
) -> list[dict]:
    """Best-effort discovery of candidate existing tests for behavioral proof."""
    base = Path(__file__).parent.parent
    search_roots = [
        base / "tests" / "test_engine",
        base / "tests" / "test_scripts",
    ]
    terms = {
        tcgdex_id.lower(),
        (card_name or "").lower(),
        *(str(fx.get("name", "")).lower() for fx in effects if isinstance(fx, dict)),
        *(str(ev.get("handler_symbol", "")).lower() for ev in implementation_evidence if isinstance(ev, dict)),
        *(str(flag).lower() for flag in mechanic_flags),
    }
    terms = {t.strip() for t in terms if t and t.strip()}
    if not terms:
        return []

    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for root in search_roots:
        if not root.exists():
            continue
        for test_file in root.rglob("test_*.py"):
            try:
                raw = test_file.read_text(encoding="utf-8")
            except OSError:
                continue

            raw_lc = raw.lower()
            matched = sorted(t for t in terms if t in raw_lc)
            if not matched:
                continue

            rel_file = str(test_file.relative_to(base))
            test_names = _TEST_NAME_PATTERN.findall(raw)
            if not test_names:
                key = (rel_file, "")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "proof_type": "existing-test",
                    "test_file": rel_file,
                    "test_name": None,
                    "matched_keywords": matched[:8],
                })
                continue

            for test_name in test_names[:12]:
                key = (rel_file, test_name)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "proof_type": "existing-test",
                    "test_file": rel_file,
                    "test_name": test_name,
                    "matched_keywords": matched[:8],
                })
                if len(candidates) >= 40:
                    return candidates

    return candidates


async def _probe_single(tcgdex_id: str) -> dict:
    """Probe one card and return a v3 ledger skeleton."""
    from app.cards.tcgdex import TCGDexClient
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select, text

    # ── 1. DB lookup ──────────────────────────────────────────────────────────
    db_row: dict | None = None
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM cards WHERE tcgdex_id = :tid LIMIT 1"),
            {"tid": tcgdex_id},
        )
        row = result.mappings().first()
        if row:
            db_row = dict(row)

    # ── 2. TCGDex fetch ───────────────────────────────────────────────────────
    tcgdex_data: dict = {}
    tcgdex_fetch = "not-attempted"
    tcgdex_text_hash = ""
    async with TCGDexClient() as client:
        try:
            # tcgdex_id format: "sv06-130" → set_id="sv06", number="130"
            parts = tcgdex_id.rsplit("-", 1)
            if len(parts) == 2:
                card = await client.get_card(parts[0], parts[1])
                tcgdex_data = card or {}
                tcgdex_fetch = "ok"
                # Hash the serialised text for traceability
                text_blob = json.dumps(tcgdex_data, sort_keys=True)
                tcgdex_text_hash = hashlib.sha256(text_blob.encode()).hexdigest()[:16]
            else:
                tcgdex_fetch = "error"
        except Exception as exc:
            tcgdex_fetch = "error"
            logger.warning("TCGDex fetch failed for %s: %s", tcgdex_id, exc)

    # ── 3. Normalise card metadata ────────────────────────────────────────────
    if db_row:
        category = db_row.get("category", "")
        subcategory = db_row.get("subcategory", "") or ""
        attacks = db_row.get("attacks") or []
        abilities = db_row.get("abilities") or []
        card_name = db_row.get("name", tcgdex_id)
        set_abbrev = db_row.get("set_abbrev", "")
        set_number = db_row.get("set_number", "")
        db_id = db_row.get("tcgdex_id") or tcgdex_id
    else:
        # Fallback to TCGDex data
        category = tcgdex_data.get("category", "pokemon")
        subcategory = tcgdex_data.get("subtype", "")
        attacks = tcgdex_data.get("attacks") or []
        abilities = tcgdex_data.get("abilities") or []
        card_name = tcgdex_data.get("name", tcgdex_id)
        set_abbrev = ""
        set_number = ""
        db_id = None

    # ── 4. Extract effects ────────────────────────────────────────────────────
    tcgdex_effects_extracted = _extract_effects(
        category, subcategory, attacks, abilities, tcgdex_data
    ) if tcgdex_fetch == "ok" else []

    # ── 5. Registry inspection ────────────────────────────────────────────────
    registry = _load_registry()
    impl_evidence = _registry_evidence(
        registry, tcgdex_id, category, subcategory, attacks, abilities
    )

    # ── 6. Mechanic flags ─────────────────────────────────────────────────────
    flags = _mechanic_flags(tcgdex_effects_extracted)

    # ── 7. Build skeleton row ─────────────────────────────────────────────────
    has_missing = any(not ev.get("handler_found") for ev in impl_evidence)
    result = "engine-gap" if has_missing else "no-issue"
    confidence = "low"  # Auditor must assess and upgrade
    behavioral_candidates = _behavioral_evidence_candidates(
        tcgdex_id=tcgdex_id,
        card_name=card_name,
        effects=tcgdex_effects_extracted,
        implementation_evidence=impl_evidence,
        mechanic_flags=flags,
    )

    skeleton = {
        "seq": 0,  # Auditor must set correct sequence number
        "db_id": db_id,
        "card_name": card_name,
        "set_id": set_abbrev,
        "card_number": set_number,
        "tcgdex_id": tcgdex_id,
        "tcgdex_fetch": tcgdex_fetch,
        "category": category,
        "tcgdex_text_hash": tcgdex_text_hash,
        "tcgdex_effects_extracted": tcgdex_effects_extracted,
        "implementation_evidence": impl_evidence,
        "mechanic_flags": flags,
        "result": result,
        "finding_counted": has_missing,
        "confidence": confidence,
        "behavioral_evidence_candidates": behavioral_candidates,
        "notes": (
            "PROBE: Registry coverage checked. "
            "Auditor must verify semantic correctness and fill semantic_checks."
        ),
    }
    return skeleton


async def _list_cards(cursor: str | None, limit: int) -> list[dict]:
    """List DB cards with registry coverage summary."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text as sa_text

    registry = _load_registry()

    query = """
        SELECT tcgdex_id, name, set_abbrev, set_number, category, subcategory,
               attacks, abilities
        FROM cards
        ORDER BY name, set_abbrev, set_number, tcgdex_id
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(sa_text(query))
        rows = result.mappings().all()

    # Apply cursor
    if cursor:
        cursor_lc = cursor.lower()
        rows = [r for r in rows if r["name"].lower() >= cursor_lc]

    rows = list(rows)[:limit]

    summary = []
    for row in rows:
        card_id = row["tcgdex_id"]
        category = row["category"] or ""
        subcategory = row["subcategory"] or ""
        attacks = row["attacks"] or []
        abilities = row["abilities"] or []

        evidence = _registry_evidence(
            registry, card_id, category, subcategory, attacks, abilities
        )
        missing = [ev["effect_name"] for ev in evidence if not ev.get("handler_found")]

        summary.append({
            "tcgdex_id": card_id,
            "name": row["name"],
            "set": f"{row['set_abbrev']}/{row['set_number']}",
            "category": category,
            "effects_needing_handlers": len(evidence),
            "missing_handlers": missing,
            "coverage": "full" if not missing else f"missing: {', '.join(missing)}",
        })

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe card registry coverage and generate v3 ledger skeletons."
    )
    parser.add_argument("--tcgdex-id", help="Probe a single card by TCGDex ID (e.g. sv06-130)")
    parser.add_argument("--list", action="store_true", help="List DB cards with registry status")
    parser.add_argument("--limit", type=int, default=20, help="Max cards to list (default: 20)")
    parser.add_argument("--cursor", help="Start listing from this card name")
    parser.add_argument("--output", help="Write output JSON to this file instead of stdout")
    args = parser.parse_args()

    if not args.tcgdex_id and not args.list:
        parser.print_help()
        sys.exit(1)

    if args.list:
        data = asyncio.run(_list_cards(args.cursor, args.limit))
    else:
        data = asyncio.run(_probe_single(args.tcgdex_id))

    output = json.dumps(data, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote output to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
