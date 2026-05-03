"""CoachAnalyst: analyzes round results and proposes deck mutations via Gemma 4."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.coach.prompts import (
    COACH_EVOLUTION_SYSTEM_PROMPT,
    COACH_EVOLUTION_USER_PROMPT,
    COACH_REPAIR_PROMPT,
)
from sqlalchemy import select

from app.db.models import Card, DeckMutation
from app.memory.embeddings import SimilarSituationFinder
from app.memory.graph import GraphQueries
from app.memory.postgres import CardPerformanceQueries

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.engine.batch import MatchResult
    from app.cards.models import CardDefinition

logger = logging.getLogger(__name__)

_TCGDEX_ID_RE = re.compile(r"^[a-z][a-z0-9.]*-[0-9]+[a-z]*$")


class CoachAnalyst:
    """Post-round Coach that queries memory and proposes 0–N card swaps.

    Uses Gemma 4 E4B (OLLAMA_COACH_MODEL) for reasoning.
    Each instance is tied to an async DB session and Neo4j driver.
    """

    def __init__(
        self,
        db: AsyncSession,
        model: str | None = None,
        max_swaps: int = 4,
    ) -> None:
        self._db = db
        self._model = model or settings.OLLAMA_COACH_MODEL
        self._max_swaps = max_swaps
        self._card_perf = CardPerformanceQueries(db)
        self._similar = SimilarSituationFinder(db)
        self._graph = GraphQueries()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_and_mutate(
        self,
        current_deck: list[CardDefinition],
        round_results: list[MatchResult],
        simulation_id: uuid.UUID,
        round_number: int,
        candidate_card_ids: list[str] | None = None,
        excluded_ids: list[str] | None = None,
        regression_info: dict | None = None,
    ) -> list[dict]:
        """Analyze *round_results* and return a list of applied swap dicts.

        Each swap dict: {remove, add, reasoning, round_number, simulation_id}.
        Mutations are written to the DB before returning.

        Args:
            excluded_ids: Card IDs that must never be suggested as additions
                (e.g., opponent deck cards). Enforced at both query level and
                prompt level for belt-and-suspenders safety.
            regression_info: Optional dict with keys: consecutive_regressions,
                prev_win_rate, current_win_rate, best_win_rate, reverted.
                Used to add regression warnings/revert notices to the prompt.
        """
        if not round_results:
            return []

        excluded = list(excluded_ids or [])
        deck_ids = list(dict.fromkeys(c.tcgdex_id for c in current_deck))  # deduplicated, order preserved
        card_stats = await self._card_perf.get_card_performance(deck_ids)
        synergies = await self._graph.get_synergies(deck_ids)
        summary_text = self._summarize_round(card_stats, round_results)
        similar = await self._similar.find_similar(summary_text, k=5)

        # Merge deck_ids + excluded_ids so neither set appears as candidates
        all_excluded = list(dict.fromkeys(deck_ids + excluded))

        if candidate_card_ids is None:
            top_cards = await self._card_perf.get_top_performing_cards(
                exclude_ids=all_excluded, limit=20
            )
        else:
            perf = await self._card_perf.get_card_performance(candidate_card_ids)
            top_cards = [
                {"tcgdex_id": k, "name": k, **v}
                for k, v in perf.items()
                if k not in all_excluded
            ]
        top_cards = await self._enrich_candidate_cards(top_cards)

        # Compute evolution line tiers for this round
        primary_ids = self._identify_primary_line(round_results, current_deck)
        tiers = self._classify_deck_tiers(current_deck, primary_ids)

        prompt_messages = self._build_prompt_messages(
            deck=current_deck,
            excluded_ids=excluded,
            round_results=round_results,
            card_stats=card_stats,
            top_cards=top_cards,
            synergies=synergies,
            similar=similar,
            tiers=tiers,
            regression_info=regression_info,
        )

        raw_swaps = await self._get_swap_decisions(prompt_messages)

        # Enforce tier protection rules (blocks tier1; requires full-line for tier2)
        all_deck_id_set = set(deck_ids)
        candidate_by_id = {c.get("tcgdex_id"): c for c in top_cards if c.get("tcgdex_id")}
        candidate_ids = set(candidate_by_id)
        candidate_filtered_swaps = [
            swap for swap in raw_swaps
            if swap.get("add") in candidate_ids and swap.get("add") not in all_excluded
        ]
        skipped = len(raw_swaps) - len(candidate_filtered_swaps)
        if skipped:
            logger.warning("Coach proposed %d swaps with non-candidate or excluded additions; skipped.", skipped)
        valid_swaps = self._validate_and_filter_swaps(
            candidate_filtered_swaps, tiers, all_deck_id_set
        )

        mutations = []
        for swap in valid_swaps:
            removed = swap.get("remove", "")
            added = swap.get("add", "")
            reasoning = self._format_reasoning_with_evidence(
                swap.get("reasoning", ""),
                swap.get("evidence", []),
            )
            if not removed or not added:
                continue
            mutation = {
                "round_number": round_number,
                "card_removed": removed,
                "card_added": added,
                "card_added_def": self._candidate_to_card_definition(candidate_by_id.get(added)),
                "reasoning": reasoning,
                "evidence": swap.get("evidence", []),
            }
            mutations.append(mutation)
            await self._graph.record_swap(removed, added, round_number, reasoning)

        if mutations:
            await self._write_mutations(mutations, simulation_id)

        return mutations

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt_messages(
        self,
        deck: list[CardDefinition],
        round_results: list[MatchResult],
        card_stats: dict,
        top_cards: list[dict],
        synergies: dict,
        similar: list[dict],
        excluded_ids: list[str] | None = None,
        tiers: dict | None = None,
        regression_info: dict | None = None,
    ) -> str:
        wins = sum(1 for r in round_results if r.winner == "p1")
        total = len(round_results)
        win_rate = wins / total if total else 0.0
        avg_turns = (
            sum(r.total_turns for r in round_results) / total if total else 0.0
        )

        loss_reasons = self._extract_loss_reasons(round_results)
        deck_list = "\n".join(self._format_card_definition(c) for c in deck)
        card_stats_text = self._format_card_stats(card_stats)
        candidate_text = self._format_candidates(top_cards)
        top_syn_text = ", ".join(
            f"{a_name}+{b_name}" for _, a_name, _, b_name, _ in synergies.get("top", [])[:5]
        ) or "none recorded"
        weak_syn_text = ", ".join(
            f"{a_name}+{b_name}" for _, a_name, _, b_name, _ in synergies.get("weak", [])[:5]
        ) or "none"
        similar_text = self._format_similar(similar)

        excluded_cards_text = (
            "\n".join(f"  - {eid}" for eid in excluded_ids)
            if excluded_ids else "  (none)"
        )

        card_tiers_text = self._format_card_tiers(tiers, deck) if tiers else "  (not computed)"
        performance_history_text = self._format_performance_history(regression_info)

        system_prompt = COACH_EVOLUTION_SYSTEM_PROMPT.format(max_swaps=self._max_swaps)
        user_prompt = COACH_EVOLUTION_USER_PROMPT.format(
            max_swaps=self._max_swaps,
            deck_list=deck_list,
            win_rate=win_rate,
            wins=wins,
            total_games=total,
            avg_turns=avg_turns,
            loss_reasons=loss_reasons,
            card_stats=card_stats_text,
            candidate_cards=candidate_text,
            top_synergies=top_syn_text,
            weak_synergies=weak_syn_text,
            similar_situations=similar_text,
            excluded_cards=excluded_cards_text,
            card_tiers=card_tiers_text,
            performance_history=performance_history_text,
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_prompt(self, *args, **kwargs) -> str:
        """Compatibility helper for tests/callers that inspect the user prompt."""
        return self._build_prompt_messages(*args, **kwargs)[1]["content"]

    async def _get_swap_decisions(self, messages: list[dict] | str, retries: int = 2) -> list[dict]:
        if isinstance(messages, str):
            messages = [
                {"role": "system", "content": COACH_EVOLUTION_SYSTEM_PROMPT.format(max_swaps=self._max_swaps)},
                {"role": "user", "content": messages},
            ]
        for attempt in range(retries):
            raw = await self._call_ollama(messages)
            parsed, parse_error = self._parse_response(raw)
            swaps, validation_error = self._validate_swap_response(parsed)
            if swaps is not None:
                return swaps
            error = parse_error or validation_error or "unknown schema failure"
            logger.warning(
                "Coach response validation failed (attempt %d/%d): %s",
                attempt + 1, retries, error,
            )
            messages = [
                messages[0],
                {
                    "role": "user",
                    "content": COACH_REPAIR_PROMPT.format(validation_error=error),
                },
            ]
        logger.error("Coach gave invalid response after %d retries", retries)
        return []

    async def _call_ollama(self, messages: list[dict]) -> str:
        """Call Ollama /api/chat with up to 3 connection retries (exponential backoff)."""
        import asyncio as _asyncio

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 768},
        }
        _CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        f"{settings.OLLAMA_BASE_URL}/api/chat",
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json().get("message", {}).get("content", "")
            except _CONNECT_ERRORS as exc:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    "Coach Ollama connection error (attempt %d/3): %s — retrying in %ds",
                    attempt + 1, exc, wait,
                )
                await _asyncio.sleep(wait)

    def _parse_response(self, raw: str) -> tuple[dict | None, str | None]:
        """Parse Gemma 4 response: strip markdown fences, then JSON parse.

        Gemma 4 does NOT produce <think> tags or require prefill.
        """
        cleaned = raw.strip()
        # Strip ```json ... ``` or ``` ... ``` fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return None, f"invalid_json: {exc}"
        if not isinstance(parsed, dict):
            return None, "top-level response must be a JSON object"
        return parsed, None

    def _validate_swap_response(self, parsed: dict | None) -> tuple[list[dict] | None, str | None]:
        """Validate model JSON before applying deck-mutation rules."""
        if not isinstance(parsed, dict):
            return None, "response is not an object"
        swaps = parsed.get("swaps", [])
        if swaps is None:
            swaps = []
        if not isinstance(swaps, list):
            return None, "swaps must be a list"
        swaps = swaps[:self._max_swaps]

        valid: list[dict] = []
        for swap in swaps:
            if not isinstance(swap, dict):
                return None, "swap entries must be objects"
            remove = swap.get("remove")
            add = swap.get("add")
            reasoning = swap.get("reasoning", "")
            evidence = swap.get("evidence", [])
            if not isinstance(remove, str) or not isinstance(add, str):
                return None, "remove/add must be strings"
            if not _TCGDEX_ID_RE.match(remove) or not _TCGDEX_ID_RE.match(add):
                return None, "remove/add must be valid tcgdex IDs"
            if not isinstance(reasoning, str):
                return None, "reasoning must be a string"
            if not isinstance(evidence, list) or not evidence:
                return None, "each swap must include at least one evidence entry"
            bounded_evidence: list[dict] = []
            for item in evidence[:3]:
                if not isinstance(item, dict):
                    return None, "evidence entries must be objects"
                kind = item.get("kind")
                ref = item.get("ref")
                value = item.get("value")
                if kind not in {"card_performance", "synergy", "round_result", "candidate_metric"}:
                    return None, "invalid evidence kind"
                if not isinstance(ref, str) or not isinstance(value, str):
                    return None, "evidence ref/value must be strings"
                bounded_evidence.append({
                    "kind": kind,
                    "ref": ref[:80],
                    "value": value[:160],
                })
            valid.append({
                "remove": remove,
                "add": add,
                "reasoning": reasoning[:500],
                "evidence": bounded_evidence,
            })
        return valid, None

    def _format_reasoning_with_evidence(self, reasoning: str, evidence: list[dict]) -> str:
        """Persist a compact provenance trail in the existing reasoning field."""
        reasoning = (reasoning or "").strip()[:500]
        if not evidence:
            return reasoning
        parts = []
        for item in evidence[:3]:
            kind = item.get("kind", "?")
            ref = item.get("ref", "?")
            value = item.get("value", "?")
            parts.append(f"{kind}:{ref}={value}")
        suffix = "; ".join(parts)
        return f"{reasoning} Evidence: {suffix}"[:1000]

    def _summarize_round(
        self, card_stats: dict, round_results: list[MatchResult]
    ) -> str:
        wins = sum(1 for r in round_results if r.winner == "p1")
        total = len(round_results)
        win_rate = wins / total if total else 0.0
        avg_turns = (
            sum(r.total_turns for r in round_results) / total if total else 0.0
        )
        bottom_cards = sorted(
            card_stats.items(), key=lambda kv: kv[1].get("win_rate", 0)
        )[:3]
        bottom_text = ", ".join(k for k, _ in bottom_cards)
        return (
            f"Win rate {win_rate:.1%} over {total} games, "
            f"avg {avg_turns:.1f} turns. "
            f"Lowest performing cards: {bottom_text}."
        )

    def _extract_loss_reasons(self, results: list[MatchResult]) -> str:
        losses = [r for r in results if r.winner != "p1"]
        if not losses:
            return "none (all wins)"
        reasons = Counter(
            getattr(r, "win_condition", "unknown") for r in losses
        )
        return ", ".join(f"{k} ({v}x)" for k, v in reasons.most_common(3))

    def _format_card_stats(self, stats: dict) -> str:
        lines = []
        for cid, s in sorted(stats.items(), key=lambda kv: kv[1].get("win_rate", 0)):
            lines.append(
                f"  {cid}: win_rate={s['win_rate']:.1%}, "
                f"games={s['games_included']}"
            )
        return "\n".join(lines) or "  (no data yet)"

    def _format_candidates(self, top_cards: list[dict]) -> str:
        if not top_cards:
            return "  (insufficient historical data)"
        lines = [
            f"  {c['tcgdex_id']} ({c.get('name', '')}): "
            f"win_rate={c.get('win_rate', 0):.1%}, "
            f"games={c.get('games_included', 0)}"
            f"{self._format_candidate_rules_suffix(c)}"
            for c in top_cards[:10]
        ]
        return "\n".join(lines)

    async def _enrich_candidate_cards(self, cards: list[dict]) -> list[dict]:
        ids = [c.get("tcgdex_id") for c in cards if c.get("tcgdex_id")]
        if not ids:
            return cards
        rows = (await self._db.execute(
            select(Card).where(Card.tcgdex_id.in_(ids))
        )).scalars().all()
        by_id = {row.tcgdex_id: row for row in rows}
        enriched: list[dict] = []
        for card in cards:
            row = by_id.get(card.get("tcgdex_id"))
            if row is None:
                enriched.append(card)
                continue
            next_card = dict(card)
            next_card.update({
                "name": row.name,
                "category": row.category,
                "subcategory": row.subcategory,
                "set_abbrev": row.set_abbrev,
                "set_number": row.set_number,
                "hp": row.hp,
                "types": row.types or [],
                "stage": row.stage,
                "evolve_from": row.evolve_from,
                "attacks": row.attacks or [],
                "abilities": row.abilities or [],
                "retreat_cost": row.retreat_cost,
                "raw_tcgdex": row.raw_tcgdex or {},
            })
            enriched.append(next_card)
        return enriched

    def _candidate_to_card_definition(self, card: dict | None):
        if not card:
            return None
        if not card.get("category"):
            return None
        from app.cards.models import CardDefinition
        parts = str(card.get("tcgdex_id", "")).rsplit("-", 1)
        return CardDefinition(
            tcgdex_id=card.get("tcgdex_id", ""),
            name=card.get("name") or card.get("tcgdex_id", ""),
            set_abbrev=card.get("set_abbrev") or (parts[0] if len(parts) == 2 else ""),
            set_number=card.get("set_number") or (parts[1] if len(parts) == 2 else ""),
            category=card.get("category") or "",
            subcategory=card.get("subcategory") or "",
            hp=card.get("hp"),
            types=card.get("types") or [],
            evolve_from=card.get("evolve_from"),
            stage=card.get("stage") or "",
            attacks=card.get("attacks") or [],
            abilities=card.get("abilities") or [],
            retreat_cost=card.get("retreat_cost") or 0,
            raw_tcgdex=card.get("raw_tcgdex") or {},
        )

    def _format_candidate_rules_suffix(self, card: dict) -> str:
        parts: list[str] = []
        category = str(card.get("category") or "").strip()
        subcategory = str(card.get("subcategory") or "").strip()
        if category:
            parts.append(f"type={category}{('/' + subcategory) if subcategory else ''}")
        if card.get("stage"):
            parts.append(f"stage={card.get('stage')}")
        if card.get("evolve_from"):
            parts.append(f"evolves_from={card.get('evolve_from')}")
        if card.get("hp"):
            parts.append(f"hp={card.get('hp')}")
        if card.get("types"):
            parts.append(f"pokemon_type={', '.join(card.get('types') or [])}")
        rules = self._format_raw_rules(
            attacks=card.get("attacks") or [],
            abilities=card.get("abilities") or [],
            raw=card.get("raw_tcgdex") or {},
        )
        if rules:
            parts.append(rules)
        return " | " + " | ".join(parts) if parts else ""

    def _format_card_definition(self, card: CardDefinition) -> str:
        parts = [
            f"- {card.tcgdex_id} ({card.name})",
            f"type={card.category}{('/' + card.subcategory) if card.subcategory else ''}",
        ]
        if card.stage:
            parts.append(f"stage={card.stage}")
        if card.evolve_from:
            parts.append(f"evolves_from={card.evolve_from}")
        if card.hp:
            parts.append(f"hp={card.hp}")
        if card.types:
            parts.append(f"pokemon_type={', '.join(card.types)}")
        rules = self._format_raw_rules(
            attacks=[a.model_dump() for a in card.attacks],
            abilities=[a.model_dump() for a in card.abilities],
            raw=card.raw_tcgdex or {},
        )
        if rules:
            parts.append(rules)
        return " | ".join(parts)

    def _format_raw_rules(self, attacks: list, abilities: list, raw: dict) -> str:
        pieces: list[str] = []
        if attacks:
            attack_parts = []
            for attack in attacks:
                attack_parts.append(
                    f"{attack.get('name', '')} "
                    f"[cost={', '.join(attack.get('cost') or []) or 'none'}; "
                    f"damage={attack.get('damage') or '0'}; "
                    f"effect={self._clean_prompt_text(attack.get('effect') or 'none')}]"
                )
            pieces.append("attacks=" + " / ".join(attack_parts))
        if abilities:
            ability_parts = []
            for ability in abilities:
                ability_parts.append(
                    f"{ability.get('name', '')}: "
                    f"{self._clean_prompt_text(ability.get('effect') or '')}"
                )
            pieces.append("abilities=" + " / ".join(ability_parts))
        effect = self._clean_prompt_text((raw or {}).get("effect", ""))
        if effect:
            pieces.append(f"effect={effect}")
        return " | ".join(pieces)

    def _clean_prompt_text(self, text: str) -> str:
        return " ".join(str(text).split())

    def _format_similar(self, similar: list[dict]) -> str:
        if not similar:
            return "  (no similar situations found)"
        lines = [
            f"  [{i+1}] (dist={s['distance']:.3f}): {s['content_text'][:100]}"
            for i, s in enumerate(similar)
        ]
        return "\n".join(lines)

    def _identify_primary_line(
        self,
        round_results: list[MatchResult],
        current_deck: list[CardDefinition],
    ) -> set[str]:
        """Identify the primary attacker's evolution line from round data.

        Scans attack_damage and ko events across all matches to score each
        attacker Pokémon (damage dealt + prizes taken × 100).  The top scorer's
        full evolution chain is returned as a set of tcgdex_ids.

        Falls back to the highest-HP ex Pokémon in the deck when no attack
        events exist (e.g. all games ended by deck-out before combat).
        """
        damage_by_name: dict[str, int] = defaultdict(int)
        prizes_by_name: dict[str, int] = defaultdict(int)

        for result in round_results:
            for event in (result.events or []):
                etype = event.get("event_type", "")
                attacker = event.get("attacker")
                if not attacker:
                    continue
                if etype == "attack_damage":
                    damage_by_name[attacker] += event.get("final_damage", 0)
                elif etype == "ko":
                    prizes_by_name[attacker] += event.get("prizes_to_take", 1)

        name_to_def: dict[str, CardDefinition] = {}
        for cdef in current_deck:
            if cdef.name not in name_to_def:
                name_to_def[cdef.name] = cdef

        all_attacker_names = set(damage_by_name) | set(prizes_by_name)

        if all_attacker_names:
            def _score(name: str) -> float:
                return damage_by_name.get(name, 0) + prizes_by_name.get(name, 0) * 100

            top_name = max(all_attacker_names, key=_score)
            if top_name in name_to_def:
                chain_names = self._get_evolution_chain_names(top_name, name_to_def)
                return {
                    cdef.tcgdex_id
                    for name in chain_names
                    for cdef in [name_to_def.get(name)]
                    if cdef is not None
                }

        # Fallback: protect the ex Pokémon with the highest HP (longest chain wins)
        best_ex: CardDefinition | None = None
        for cdef in current_deck:
            if cdef.is_ex:
                if best_ex is None or (cdef.hp or 0) > (best_ex.hp or 0):
                    best_ex = cdef
        if best_ex and best_ex.name in name_to_def:
            chain_names = self._get_evolution_chain_names(best_ex.name, name_to_def)
            return {
                cdef.tcgdex_id
                for name in chain_names
                for cdef in [name_to_def.get(name)]
                if cdef is not None
            }

        return set()

    def _get_evolution_chain_names(
        self,
        card_name: str,
        name_to_def: dict[str, CardDefinition],
    ) -> set[str]:
        """Return all card names in the complete evolution chain for card_name.

        Walks backward to the Basic root via evolve_from, then forward to find
        all cards in the deck that evolve from any chain member.
        """
        chain: set[str] = set()

        # Walk backward to root
        current = card_name
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            chain.add(current)
            cdef = name_to_def.get(current)
            if cdef is None:
                break
            parent = cdef.evolve_from
            if parent and parent in name_to_def:
                current = parent
            else:
                break

        # Walk forward: find all cards in the deck that evolve from a chain member
        changed = True
        while changed:
            changed = False
            for cdef in name_to_def.values():
                if cdef.evolve_from in chain and cdef.name not in chain:
                    chain.add(cdef.name)
                    changed = True

        return chain

    def _classify_deck_tiers(
        self,
        current_deck: list[CardDefinition],
        primary_ids: set[str],
    ) -> dict:
        """Classify deck cards into three protection tiers.

        Returns:
            {
              "tier1": set[tcgdex_id]  — primary attacker line (hard protected),
              "tier2": dict[family_root_name → set[tcgdex_id]]  — support evolution
                       lines (swappable only as complete families),
              "tier3": set[tcgdex_id]  — trainers, energies, standalone basics
                       (freely swappable),
            }
        """
        name_to_def: dict[str, CardDefinition] = {}
        for cdef in current_deck:
            if cdef.name not in name_to_def:
                name_to_def[cdef.name] = cdef

        # Names that something else evolves FROM (i.e. they have a Stage1/Stage2 child)
        evolved_from_names: set[str] = {
            cdef.evolve_from
            for cdef in current_deck
            if cdef.evolve_from
        }

        tier2_families: dict[str, set[str]] = {}
        processed_names: set[str] = set()

        for cdef in current_deck:
            if not cdef.is_pokemon:
                continue
            if cdef.tcgdex_id in primary_ids:
                continue
            if cdef.name in processed_names:
                continue

            # A card belongs to a multi-stage family if it has a parent or a child
            has_parent = bool(cdef.evolve_from and cdef.evolve_from in name_to_def)
            has_child = cdef.name in evolved_from_names

            if not has_parent and not has_child:
                continue  # standalone basic → tier3

            family_names = self._get_evolution_chain_names(cdef.name, name_to_def)
            family_ids = {
                name_to_def[n].tcgdex_id
                for n in family_names
                if n in name_to_def
            } - primary_ids

            if not family_ids:
                continue

            # Find the root name (the Basic in this family that's in the deck)
            root_name = None
            for n in family_names:
                nd = name_to_def.get(n)
                if nd and (not nd.evolve_from or nd.evolve_from not in name_to_def):
                    root_name = n
                    break
            root_name = root_name or next(iter(family_names))

            if root_name not in tier2_families:
                tier2_families[root_name] = family_ids

            processed_names.update(family_names)

        all_tier2_ids: set[str] = set().union(*tier2_families.values()) if tier2_families else set()
        tier3 = {
            cdef.tcgdex_id
            for cdef in current_deck
            if cdef.tcgdex_id not in primary_ids
            and cdef.tcgdex_id not in all_tier2_ids
        }

        return {"tier1": primary_ids, "tier2": tier2_families, "tier3": tier3}

    def _validate_and_filter_swaps(
        self,
        swaps: list[dict],
        tiers: dict,
        deck_ids: set[str],
    ) -> list[dict]:
        """Apply tier protection rules to Coach-proposed swaps.

        Rules:
        - Tier 1 (primary line): any swap removing a tier1 card is rejected.
        - Tier 2 (support lines): removing any card in a family requires ALL
          deck members of that family to be removed in the same batch.
          Incomplete line removals are rejected.  A complete line removal counts
          as ONE swap unit toward max_swaps regardless of family size.
        - Tier 3: each swap counts as one unit toward max_swaps.

        Returns a filtered, max_swaps-capped list of valid swaps.
        """
        tier1 = tiers.get("tier1", set())
        tier2_families: dict[str, set[str]] = tiers.get("tier2", {})

        # Build reverse map: tcgdex_id → family root name
        id_to_family: dict[str, str] = {
            cid: root
            for root, ids in tier2_families.items()
            for cid in ids
        }

        removed_ids = {s.get("remove", "") for s in swaps}

        t2_by_family: dict[str, list[dict]] = defaultdict(list)
        t3_swaps: list[dict] = []

        for swap in swaps:
            removed = swap.get("remove", "")
            if removed in tier1:
                logger.warning(
                    "Coach proposed removing %s from the PRIMARY attacker line — blocked.",
                    removed,
                )
                continue
            if removed in id_to_family:
                t2_by_family[id_to_family[removed]].append(swap)
            else:
                t3_swaps.append(swap)

        # Validate each tier2 family: all deck members must be removed together
        valid_t2_groups: list[list[dict]] = []
        for root, group_swaps in t2_by_family.items():
            family_ids_in_deck = tier2_families[root] & deck_ids
            missing = family_ids_in_deck - removed_ids
            if missing:
                logger.warning(
                    "Coach proposed partial removal of '%s' line (missing: %s). "
                    "Full-line swap required — rejecting this family's swaps.",
                    root, missing,
                )
            else:
                valid_t2_groups.append(group_swaps)

        # Build final list: each complete line swap = 1 unit; each t3 swap = 1 unit
        final: list[dict] = []
        units = 0

        for group in valid_t2_groups:
            if units < self._max_swaps:
                final.extend(group)
                units += 1  # whole family counts as one unit

        for swap in t3_swaps:
            if units < self._max_swaps:
                final.append(swap)
                units += 1

        return final

    def _format_card_tiers(
        self,
        tiers: dict,
        deck: list[CardDefinition],
    ) -> str:
        """Format tier classification for inclusion in the Coach prompt."""
        id_to_name: dict[str, str] = {c.tcgdex_id: c.name for c in deck}

        tier1 = tiers.get("tier1", set())
        tier2_families = tiers.get("tier2", {})
        tier3 = tiers.get("tier3", set())

        lines: list[str] = []

        if tier1:
            names = " → ".join(
                dict.fromkeys(id_to_name.get(cid, cid) for cid in tier1)
            )
            lines.append(f"  PRIMARY (HARD PROTECTED — never remove these): {names}")
        else:
            lines.append("  PRIMARY (HARD PROTECTED): (could not be identified this round)")

        if tier2_families:
            lines.append("  SUPPORT (swap as complete lines only):")
            for root, ids in tier2_families.items():
                chain_names = " → ".join(
                    dict.fromkeys(id_to_name.get(cid, cid) for cid in ids)
                )
                lines.append(f"    {root} line: {chain_names}")
        else:
            lines.append("  SUPPORT (swap as complete lines only): (none identified)")

        if tier3:
            t3_names = ", ".join(
                dict.fromkeys(id_to_name.get(cid, cid) for cid in sorted(tier3))
            )
            lines.append(f"  UNPROTECTED (free to swap): {t3_names}")
        else:
            lines.append("  UNPROTECTED (free to swap): (none)")

        return "\n".join(lines)

    def _format_performance_history(self, regression_info: dict | None) -> str:
        """Format win-rate trend, last-swap impact, and stability status for the prompt."""
        if not regression_info:
            return (
                "  Win rate trend: (first round — no prior history)\n"
                "  Last mutations: (none)\n"
                "  Status: ✓ First round — proceed with full analysis."
            )

        history: list[int] = regression_info.get("win_rate_history", [])
        last_muts: list[dict] = regression_info.get("last_mutations", [])
        reverted: bool = regression_info.get("reverted", False)
        consecutive: int = regression_info.get("consecutive_regressions", 0)
        current: int | None = regression_info.get("current_win_rate")
        best: int | None = regression_info.get("best_win_rate")

        # ── Trend line ──────────────────────────────────────────────────────
        if history:
            trend_parts = [f"R{i+1}: {r}%" for i, r in enumerate(history)]
            trend_line = " → ".join(trend_parts) + " ← current"
        else:
            trend_line = "(no prior rounds)"

        # ── Last-mutation impact ────────────────────────────────────────────
        if last_muts and len(history) >= 2:
            delta = history[-1] - history[-2]
            direction = f"▲ +{delta}%" if delta > 0 else (f"▼ {delta}%" if delta < 0 else "→ no change")
            mut_lines = "; ".join(
                f"{m.get('remove', '?')} → {m.get('add', '?')}"
                for m in last_muts
            )
            last_mut_line = f"  Last mutations: {mut_lines} [{direction}]"
        elif not last_muts:
            last_mut_line = "  Last mutations: (none — Coach made no changes last round)"
        else:
            last_mut_line = "  Last mutations: (first round with mutations)"

        # ── Status message ──────────────────────────────────────────────────
        if reverted:
            status = (
                f"  ⚠️ DECK REVERTED: Win rate declined 2 consecutive rounds. "
                f"Deck reset to best known state ({best}%). "
                f"Make only ONE small, well-reasoned improvement."
            )
        elif consecutive >= 2:
            status = (
                f"  ⚠️ CRITICAL REGRESSION: {consecutive} consecutive drops. "
                f"Deck will be auto-reverted next round if this continues. "
                f"If win rate has been declining, prioritize stability — make no changes this round."
            )
        elif consecutive == 1:
            status = (
                f"  ⚠️ REGRESSION: Last swap hurt win rate (now {current}%, best was {best}%). "
                f"If win rate has been declining, prioritize stability. "
                f"Make fewer changes or no changes this round."
            )
        else:
            status = "  ✓ Win rate is stable or improving — proceed with normal analysis."

        return (
            f"  Win rate trend (all rounds): {trend_line}\n"
            f"{last_mut_line}\n"
            f"{status}"
        )

    async def _write_mutations(
        self, mutations: list[dict], simulation_id: uuid.UUID
    ) -> None:
        self._db.add_all(
            DeckMutation(
                simulation_id=simulation_id,
                round_number=m["round_number"],
                card_removed=m["card_removed"],
                card_added=m["card_added"],
                reasoning=m.get("reasoning"),
                evidence=m.get("evidence"),
            )
            for m in mutations
        )
        await self._db.flush()
