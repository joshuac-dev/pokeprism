#!/usr/bin/env python3
"""Nightly card implementation audit.

This script audits PokéPrism card effect implementations against fresh TCGDex
data, using GitHub Models as the reasoning layer for semantic comparison.

It intentionally:
- reads docs/CARD_EXPANSION_RULES.md for implementation rules,
- parses docs/CARDLIST.md,
- sorts cards alphabetically,
- fetches fresh TCGDex data for every audited card,
- inspects registered effect handlers in EffectRegistry,
- asks the configured GitHub Models model to compare source behavior against
  TCGDex text,
- stops after --max-findings findings or the end of the card list,
- writes a Markdown report and JSON metadata for the workflow.

Usage:
    cd repo-root
    python backend/scripts/audit_card_implementations.py \
      --max-findings 25 \
      --model openai/gpt-5.3-codex \
      --report audit-report.md \
      --metadata audit-metadata.json
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.cards.loader import CardListLoader, SET_CODE_MAP  # noqa: E402
from app.cards.tcgdex import TCGDexClient  # noqa: E402
from app.engine.effects.registry import EffectRegistry  # noqa: E402

# Importing this module registers handlers into EffectRegistry.
import app.engine.effects  # noqa: F401,E402


DEFAULT_MODEL = "openai/gpt-5.3-codex"
DEFAULT_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"


@dataclass
class AuditFinding:
    severity: str
    category: str
    card_name: str
    card_ref: str
    tcgdex_id: str
    component: str
    summary: str
    tcgdex_text: str = ""
    implementation_evidence: str = ""
    recommendation: str = ""


@dataclass
class AuditWarning:
    card_name: str
    card_ref: str
    tcgdex_id: str
    message: str


@dataclass
class AuditStats:
    cards_audited: int = 0
    cards_with_no_issues: int = 0
    skipped_cards: int = 0
    audit_warning_count: int = 0
    alphabetical_start: str = ""
    alphabetical_end: str = ""


@dataclass
class AuditResult:
    findings: list[AuditFinding] = field(default_factory=list)
    warnings: list[AuditWarning] = field(default_factory=list)
    stats: AuditStats = field(default_factory=AuditStats)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-findings", type=int, default=25)
    parser.add_argument("--model", default=os.environ.get("GITHUB_MODELS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--report", default="audit-report.md")
    parser.add_argument("--metadata", default="audit-metadata.json")
    parser.add_argument("--cardlist", default=str(REPO_ROOT / "docs" / "CARDLIST.md"))
    parser.add_argument(
        "--rules",
        default=str(REPO_ROOT / "docs" / "CARD_EXPANSION_RULES.md"),
    )
    parser.add_argument(
        "--github-models-endpoint",
        default=os.environ.get("GITHUB_MODELS_ENDPOINT", DEFAULT_MODELS_ENDPOINT),
    )
    return parser.parse_args()


def card_sort_key(entry: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(entry.get("name", "")).lower(),
        str(entry.get("set_abbrev", "")).lower(),
        int(entry.get("number", 0)),
    )


def card_ref(entry: dict[str, Any]) -> str:
    return f"{entry['set_abbrev']} #{entry['number']}"


def tcgdex_id_for_entry(entry: dict[str, Any]) -> str | None:
    set_id = SET_CODE_MAP.get(entry["set_abbrev"])
    if not set_id:
        return None
    return f"{set_id}-{int(entry['number']):03d}"


def serialize_handler(handler: Any) -> dict[str, str]:
    if handler is None:
        return {
            "registered": "false",
            "name": "",
            "docstring": "",
            "source": "",
        }

    try:
        source = inspect.getsource(handler)
    except Exception as exc:
        source = f"<source unavailable: {exc}>"

    return {
        "registered": "true",
        "name": getattr(handler, "__name__", repr(handler)),
        "docstring": inspect.getdoc(handler) or "",
        "source": source[:8000],
    }


def registry_snapshot_for_card(registry: EffectRegistry, card_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    attack_handlers = []
    for index, attack in enumerate(raw.get("attacks") or []):
        key = f"{card_id}:{index}"
        handler = registry._attack_effects.get(key)  # intentional audit introspection
        attack_handlers.append(
            {
                "index": index,
                "name": attack.get("name", ""),
                "damage": attack.get("damage", ""),
                "effect": attack.get("effect", ""),
                "handler_key": key,
                "handler": serialize_handler(handler),
            }
        )

    ability_handlers = []
    for ability in raw.get("abilities") or []:
        name = ability.get("name", "")
        key = f"{card_id}:{name}"
        handler = registry._ability_effects.get(key)  # intentional audit introspection
        passive = key in registry._passive_abilities
        ability_handlers.append(
            {
                "name": name,
                "type": ability.get("type", ""),
                "effect": ability.get("effect", ""),
                "handler_key": key,
                "registered_active": handler is not None,
                "registered_passive": passive,
                "handler": serialize_handler(handler),
            }
        )

    trainer_handler = registry._trainer_effects.get(card_id)
    energy_handler = registry._energy_effects.get(card_id)

    return {
        "attacks": attack_handlers,
        "abilities": ability_handlers,
        "trainer_handler": serialize_handler(trainer_handler),
        "energy_handler": serialize_handler(energy_handler),
    }


def deterministic_coverage_findings(
    entry: dict[str, Any],
    raw: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    card_name = raw.get("name") or entry["name"]
    ref = card_ref(entry)
    tcgdex_id = raw.get("id", tcgdex_id_for_entry(entry) or "")

    category = (raw.get("category") or "").lower()
    energy_type = (raw.get("energyType") or "").lower()
    trainer_type = raw.get("trainerType") or raw.get("stage") or ""

    if category == "pokemon":
        for attack in snapshot["attacks"]:
            effect_text = (attack.get("effect") or "").strip()
            if effect_text and attack["handler"]["registered"] != "true":
                findings.append(
                    AuditFinding(
                        severity="ERROR",
                        category="missing_attack_handler",
                        card_name=card_name,
                        card_ref=ref,
                        tcgdex_id=tcgdex_id,
                        component=f"attack `{attack['name']}`",
                        summary=(
                            f"Attack `{attack['name']}` has TCGDex effect text "
                            "but no registered EffectRegistry attack handler."
                        ),
                        tcgdex_text=effect_text,
                        implementation_evidence=f"Missing handler key `{attack['handler_key']}`.",
                        recommendation="Register and test an explicit attack effect handler.",
                    )
                )

        for ability in snapshot["abilities"]:
            effect_text = (ability.get("effect") or "").strip()
            if effect_text and not ability["registered_active"] and not ability["registered_passive"]:
                findings.append(
                    AuditFinding(
                        severity="ERROR",
                        category="missing_ability_handler",
                        card_name=card_name,
                        card_ref=ref,
                        tcgdex_id=tcgdex_id,
                        component=f"ability `{ability['name']}`",
                        summary=(
                            f"Ability `{ability['name']}` has TCGDex effect text "
                            "but is not registered as active or passive."
                        ),
                        tcgdex_text=effect_text,
                        implementation_evidence=f"Missing handler/passive key `{ability['handler_key']}`.",
                        recommendation="Register the ability as active or passive and add tests.",
                    )
                )

    elif category == "trainer":
        if snapshot["trainer_handler"]["registered"] != "true":
            findings.append(
                AuditFinding(
                    severity="ERROR",
                    category="missing_trainer_handler",
                    card_name=card_name,
                    card_ref=ref,
                    tcgdex_id=tcgdex_id,
                    component=f"trainer `{trainer_type}`",
                    summary="Trainer card has no registered trainer handler.",
                    tcgdex_text=raw.get("effect", ""),
                    implementation_evidence=f"Missing trainer handler key `{tcgdex_id}`.",
                    recommendation="Register and test a trainer effect handler.",
                )
            )

    elif category == "energy":
        is_special = energy_type == "special"
        name_lower = card_name.lower()
        basic_types = {
            "grass", "fire", "water", "lightning", "psychic",
            "fighting", "darkness", "metal", "dragon", "fairy",
        }
        if energy_type == "normal" and not any(t in name_lower for t in basic_types):
            is_special = True

        if is_special and snapshot["energy_handler"]["registered"] != "true":
            findings.append(
                AuditFinding(
                    severity="ERROR",
                    category="missing_energy_handler",
                    card_name=card_name,
                    card_ref=ref,
                    tcgdex_id=tcgdex_id,
                    component="special energy",
                    summary="Special Energy card has no registered energy handler.",
                    tcgdex_text=raw.get("effect", ""),
                    implementation_evidence=f"Missing energy handler key `{tcgdex_id}`.",
                    recommendation="Register and test a special energy effect handler.",
                )
            )

    return findings


async def call_github_model(
    *,
    endpoint: str,
    token: str,
    model: str,
    rules_text: str,
    entry: dict[str, Any],
    raw: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[AuditFinding]:
    card_name = raw.get("name") or entry["name"]
    ref = card_ref(entry)
    tcgdex_id = raw.get("id", tcgdex_id_for_entry(entry) or "")

    prompt = {
        "task": "Audit card effect implementation against TCGDex source data.",
        "rules": rules_text[:12000],
        "card": {
            "name": card_name,
            "ref": ref,
            "tcgdex_id": tcgdex_id,
            "tcgdex_raw": raw,
        },
        "implementation_snapshot": snapshot,
        "instructions": [
            "Only report factual implementation bugs, errors, or quality concerns.",
            "Do not invent bugs.",
            "If implementation appears correct, return an empty findings array.",
            "Classify missing engine support as ENGINE_GAP.",
            "Use ERROR for clear mismatches, WARNING for ambiguous concerns, ENGINE_GAP for required missing mechanics.",
            "Check attacks, abilities, trainers, and special energy behavior.",
            "Pay attention to damage values, targets, conditions, coin flips, discard effects, draw/search effects, status conditions, and categories.",
        ],
        "required_json_schema": {
            "findings": [
                {
                    "severity": "ERROR | WARNING | ENGINE_GAP",
                    "category": "short_machine_readable_category",
                    "component": "attack/ability/trainer/energy name",
                    "summary": "one sentence factual finding",
                    "tcgdex_text": "relevant TCGDex text",
                    "implementation_evidence": "specific evidence from handler source/docstring/registration",
                    "recommendation": "suggested next step",
                }
            ]
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise code auditor for a Pokémon TCG simulation engine. "
                    "Return only valid JSON. Do not use markdown."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()

    content = payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    model_findings = parsed.get("findings") or []

    findings: list[AuditFinding] = []
    for item in model_findings:
        severity = str(item.get("severity", "WARNING")).upper()
        if severity not in {"ERROR", "WARNING", "ENGINE_GAP"}:
            severity = "WARNING"

        findings.append(
            AuditFinding(
                severity=severity,
                category=str(item.get("category", "model_finding")),
                card_name=card_name,
                card_ref=ref,
                tcgdex_id=tcgdex_id,
                component=str(item.get("component", "")),
                summary=str(item.get("summary", "")).strip(),
                tcgdex_text=str(item.get("tcgdex_text", "")).strip(),
                implementation_evidence=str(item.get("implementation_evidence", "")).strip(),
                recommendation=str(item.get("recommendation", "")).strip(),
            )
        )

    return [f for f in findings if f.summary]


async def run_audit(args: argparse.Namespace) -> AuditResult:
    result = AuditResult()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to call GitHub Models.")

    cardlist_path = Path(args.cardlist)
    rules_path = Path(args.rules)
    rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

    loader = CardListLoader()
    entries = loader.parse_cardlist(cardlist_path)
    entries = sorted(entries, key=card_sort_key)

    registry = EffectRegistry.instance()

    if entries:
        result.stats.alphabetical_start = entries[0]["name"]

    async with TCGDexClient() as tcgdex:
        for entry in entries:
            if len(result.findings) >= args.max_findings:
                break

            result.stats.cards_audited += 1
            result.stats.alphabetical_end = entry["name"]

            set_id = SET_CODE_MAP.get(entry["set_abbrev"])
            if not set_id:
                result.stats.skipped_cards += 1
                result.warnings.append(
                    AuditWarning(
                        card_name=entry["name"],
                        card_ref=card_ref(entry),
                        tcgdex_id="",
                        message=f"Unknown set abbreviation `{entry['set_abbrev']}`.",
                    )
                )
                continue

            try:
                raw = await tcgdex.get_card(set_id, entry["number"])
            except Exception as exc:
                result.stats.skipped_cards += 1
                result.warnings.append(
                    AuditWarning(
                        card_name=entry["name"],
                        card_ref=card_ref(entry),
                        tcgdex_id=tcgdex_id_for_entry(entry) or "",
                        message=f"Failed to fetch fresh TCGDex data: {exc}",
                    )
                )
                continue

            tcgdex_id = raw.get("id") or tcgdex_id_for_entry(entry) or ""
            snapshot = registry_snapshot_for_card(registry, tcgdex_id, raw)

            card_findings = deterministic_coverage_findings(entry, raw, snapshot)

            # If deterministic coverage already found missing handlers, keep those
            # and skip semantic model comparison only when max findings is reached.
            remaining = args.max_findings - len(result.findings)
            result.findings.extend(card_findings[:remaining])

            if len(result.findings) >= args.max_findings:
                continue

            try:
                model_findings = await call_github_model(
                    endpoint=args.github_models_endpoint,
                    token=token,
                    model=args.model,
                    rules_text=rules_text,
                    entry=entry,
                    raw=raw,
                    snapshot=snapshot,
                )
                remaining = args.max_findings - len(result.findings)
                result.findings.extend(model_findings[:remaining])
            except Exception as exc:
                result.warnings.append(
                    AuditWarning(
                        card_name=raw.get("name") or entry["name"],
                        card_ref=card_ref(entry),
                        tcgdex_id=tcgdex_id,
                        message=f"Model audit failed: {exc}",
                    )
                )

            if not card_findings:
                # Count as no-issue only if the model also did not add a finding
                # for this card.
                if not any(f.tcgdex_id == tcgdex_id for f in result.findings):
                    result.stats.cards_with_no_issues += 1

    result.stats.audit_warning_count = len(result.warnings)
    return result


def render_report(result: AuditResult, model: str) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    errors = [f for f in result.findings if f.severity == "ERROR"]
    warnings = [f for f in result.findings if f.severity == "WARNING"]
    engine_gaps = [f for f in result.findings if f.severity == "ENGINE_GAP"]

    lines: list[str] = [
        "## Summary",
        "",
        f"Generated: {now}",
        f"Model: `{model}`",
        "",
        f"Cards audited: {result.stats.cards_audited}",
        f"Alphabetical range audited: {result.stats.alphabetical_start or 'N/A'} - {result.stats.alphabetical_end or 'N/A'}",
        f"Findings created: {len(result.findings)}",
        f"Cards with no issues: {result.stats.cards_with_no_issues}",
        f"Skipped cards: {result.stats.skipped_cards}",
        f"Audit warnings: {len(result.warnings)}",
        "",
        "The audit fetched fresh card data from TCGDex and compared it with registered PokéPrism effect handlers.",
        "",
    ]

    def render_finding_section(title: str, items: list[AuditFinding]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("None.")
            lines.append("")
            return

        for finding in items:
            lines.extend(
                [
                    f"### {finding.card_name} ({finding.card_ref}, `{finding.tcgdex_id}`)",
                    "",
                    f"- Component: {finding.component}",
                    f"- Category: `{finding.category}`",
                    f"- Finding: {finding.summary}",
                ]
            )
            if finding.tcgdex_text:
                lines.append(f"- TCGDex: {finding.tcgdex_text}")
            if finding.implementation_evidence:
                lines.append(f"- Implementation evidence: {finding.implementation_evidence}")
            if finding.recommendation:
                lines.append(f"- Recommendation: {finding.recommendation}")
            lines.append("")

    render_finding_section("Errors Found", errors)
    render_finding_section("Warnings", warnings)
    render_finding_section("Engine Gaps", engine_gaps)

    lines.append("## Audit Warnings")
    lines.append("")
    if result.warnings:
        for warning in result.warnings:
            lines.append(
                f"- {warning.card_name} ({warning.card_ref}, `{warning.tcgdex_id or 'unknown'}`): {warning.message}"
            )
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Cards With No Issues")
    lines.append("")
    lines.append(f"Count: {result.stats.cards_with_no_issues}")
    lines.append("")

    return "\n".join(lines)


def write_metadata(result: AuditResult, path: Path) -> None:
    payload = {
        "finding_count": len(result.findings),
        "audit_warning_count": len(result.warnings),
        "cards_audited": result.stats.cards_audited,
        "cards_with_no_issues": result.stats.cards_with_no_issues,
        "skipped_cards": result.stats.skipped_cards,
        "alphabetical_start": result.stats.alphabetical_start,
        "alphabetical_end": result.stats.alphabetical_end,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def async_main() -> None:
    args = parse_args()
    result = await run_audit(args)

    report = render_report(result, args.model)
    Path(args.report).write_text(report, encoding="utf-8")
    write_metadata(result, Path(args.metadata))

    print(report)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
