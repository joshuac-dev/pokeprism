"""AIPlayer — Qwen3.5-9B-backed player using Ollama for in-game decisions.

KEY DESIGN DECISIONS:
- CHOOSE_CARDS / CHOOSE_TARGET / CHOOSE_OPTION interrupts are handled by
  BasePlayer heuristics (they require card instance IDs, not LLM reasoning).
- Only MAIN/ATTACK phase actions go to the LLM.
- The Qwen 3.5 Modelfile prefills the assistant response with '{"' to suppress
  <think> tags.  Ollama returns the response WITHOUT those two leading chars.
  _parse_response() MUST prepend '{"' before JSON parsing — do NOT rely on
  system prompts or think:false to suppress thinking.
- On parse failure, retry up to max_retries with escalating guidance, then
  fall back to HeuristicPlayer for that single action.
- Each LLM decision is accumulated in pending_decisions for the batch runner
  to persist after the match completes (match_id is not known until then).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from app.config import settings
from app.engine.actions import Action, ActionType
from app.players.base import BasePlayer

logger = logging.getLogger(__name__)

# Action types that are engine interrupts — always handle with heuristics.
_INTERRUPT_TYPES = {ActionType.CHOOSE_CARDS, ActionType.CHOOSE_TARGET, ActionType.CHOOSE_OPTION}


class AIPlayer(BasePlayer):
    """LLM-backed player that uses Ollama/Qwen3.5-9B for decision-making."""

    def __init__(
        self,
        model: str | None = None,
        ollama_url: str | None = None,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> None:
        self.model = model or settings.OLLAMA_PLAYER_MODEL
        self.ollama_url = ollama_url or settings.OLLAMA_BASE_URL
        self.temperature = temperature
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(timeout=120.0)
        # Accumulated per-game decision records; drained by batch.py after each match.
        self.pending_decisions: list[dict] = []

    # ── Main entry point ───────────────────────────────────────────────────────

    async def choose_action(self, state, legal_actions: list) -> Action:
        if not legal_actions:
            return None

        first = legal_actions[0]

        # Engine interrupts: delegate to BasePlayer heuristics.
        if first.action_type == ActionType.CHOOSE_CARDS:
            return self._choose_cards(state, first)
        if first.action_type == ActionType.CHOOSE_TARGET:
            return self._choose_target(state, legal_actions)
        if first.action_type == ActionType.CHOOSE_OPTION:
            return legal_actions[0]

        # LLM decision for main/attack phase actions.
        player_id = first.player_id
        prompt = self._build_prompt(state, legal_actions)

        for attempt in range(self.max_retries):
            try:
                raw = await self._call_ollama(prompt, attempt)
                action = self._parse_response(raw, legal_actions)
                if action is not None:
                    self._record_decision(state, player_id, action, len(legal_actions))
                    return action
            except Exception as exc:
                logger.warning("Ollama call failed (attempt %d): %s", attempt + 1, exc)

            prompt += (
                "\n\nYour previous response could not be parsed. "
                "You MUST respond with ONLY a JSON object like: "
                '{"action_id": <number>, "reasoning": "<your reasoning>"}'
            )

        # All retries failed — fall back to heuristic for this action.
        from app.players.heuristic import HeuristicPlayer
        fallback = HeuristicPlayer()
        action = await fallback.choose_action(state, legal_actions)
        action.reasoning = "[FALLBACK] AI response unparseable after retries"
        self._record_decision(state, player_id, action, len(legal_actions))
        return action

    # ── Prompt construction ────────────────────────────────────────────────────

    def _build_prompt(self, state, legal_actions: list) -> str:
        player_id = legal_actions[0].player_id
        player = state.get_player(player_id)
        opp = state.get_opponent(player_id)

        action_lines = "\n".join(
            f"  {i}: {self._describe_action(a, state)}"
            for i, a in enumerate(legal_actions)
        )

        active_str = (
            f"{player.active.card_name} "
            f"(HP: {player.active.current_hp}/{player.active.max_hp}, "
            f"Energy: {self._format_energy(player.active)})"
            if player.active else "none"
        )
        opp_active_str = (
            f"{opp.active.card_name} "
            f"(HP: {opp.active.current_hp}/{opp.active.max_hp}, "
            f"Energy: {self._format_energy(opp.active)})"
            if opp.active else "none"
        )

        return (
            "You are an expert Pokémon TCG player. Analyze the board state and choose the best action.\n\n"
            "## Current Board State\n\n"
            f"**Turn:** {state.turn_number} | **Phase:** {state.phase.name}\n\n"
            "**Your Side:**\n"
            f"- Active: {active_str}\n"
            f"- Bench: {self._format_bench(player.bench)}\n"
            f"- Hand ({len(player.hand)} cards): "
            f"{', '.join(c.card_name for c in player.hand)}\n"
            f"- Prizes remaining: {player.prizes_remaining}\n"
            f"- Deck: {len(player.deck)} cards remaining\n"
            f"- Supporter played: {'Yes' if player.supporter_played_this_turn else 'No'}\n"
            f"- Energy attached: {'Yes' if player.energy_attached_this_turn else 'No'}\n\n"
            "**Opponent's Side:**\n"
            f"- Active: {opp_active_str}\n"
            f"- Bench: {self._format_bench(opp.bench)}\n"
            f"- Hand: {len(opp.hand)} cards\n"
            f"- Prizes remaining: {opp.prizes_remaining}\n"
            f"- Deck: {len(opp.deck)} cards remaining\n\n"
            "## Legal Actions\n"
            f"{action_lines}\n\n"
            "## Instructions\n"
            "Choose the action that gives you the best chance of winning. Consider:\n"
            "1. Can you take a knockout this turn?\n"
            "2. Are you setting up for a knockout next turn?\n"
            "3. What is your opponent's likely response?\n"
            "4. Board position and prize trade efficiency\n\n"
            'Respond with ONLY a JSON object:\n'
            '{"action_id": <number from the list above>, "reasoning": "<brief explanation>"}'
        )

    # ── Ollama HTTP call ───────────────────────────────────────────────────────

    async def _call_ollama(self, prompt: str, attempt: int) -> str:
        """Call Ollama with up to 3 connection retries (exponential backoff).

        Connection retries are separate from parse-failure retries in choose_action.
        A ConnectError or timeout triggers a retry; parse failures do not.
        """
        import asyncio as _asyncio

        _CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
        for conn_attempt in range(3):
            try:
                response = await self.client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": self.temperature + (attempt * 0.1),
                            "num_predict": 200,
                        },
                    },
                )
                response.raise_for_status()
                return response.json()["response"]
            except _CONNECT_ERRORS as exc:
                if conn_attempt == 2:
                    raise
                wait = 2 ** conn_attempt
                logger.warning(
                    "Ollama connection error (attempt %d/3): %s — retrying in %ds",
                    conn_attempt + 1, exc, wait,
                )
                await _asyncio.sleep(wait)

    # ── Response parsing ───────────────────────────────────────────────────────

    def _parse_response(self, response: str, legal_actions: list) -> Optional[Action]:
        try:
            cleaned = response.strip()

            # Strip markdown code fences if present.
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]

            # CRITICAL: Qwen 3.5 Modelfile prefills with '{"' which Ollama strips.
            # Always prepend it before JSON parsing.
            cleaned = '{"' + cleaned

            # Try to truncate at last "}" to recover from num_predict cutoffs.
            last_brace = cleaned.rfind("}")
            json_str = cleaned[: last_brace + 1] if last_brace != -1 else cleaned

            try:
                data = json.loads(json_str)
                action_id = int(data["action_id"])
                reasoning = data.get("reasoning", "")
            except (json.JSONDecodeError, KeyError, ValueError):
                # Regex fallback for responses truncated mid-string.
                m = re.search(r'"action_id"\s*:\s*(\d+)', cleaned)
                if not m:
                    return None
                action_id = int(m.group(1))
                r_m = re.search(r'"reasoning"\s*:\s*"([^"]*)', cleaned)
                reasoning = r_m.group(1) if r_m else ""

            if 0 <= action_id < len(legal_actions):
                action = legal_actions[action_id]
                action.reasoning = reasoning
                return action
        except (IndexError, TypeError):
            pass
        return None

    # ── Decision recording ─────────────────────────────────────────────────────

    def _record_decision(self, state, player_id: str, action: Action, legal_count: int) -> None:
        self.pending_decisions.append({
            "turn_number": state.turn_number,
            "player_id": player_id,
            "action_type": action.action_type.name,
            "card_played": action.card_instance_id,
            "card_def_id": self._find_card_def_id(state, action.card_instance_id),
            "target": action.target_instance_id,
            "reasoning": getattr(action, "reasoning", None),
            "legal_action_count": legal_count,
            "game_state_summary": self._state_summary(state, player_id),
        })

    def drain_decisions(self) -> list[dict]:
        """Return and clear all pending decisions (called by batch runner per game)."""
        decisions = list(self.pending_decisions)
        self.pending_decisions.clear()
        return decisions

    # ── Formatting helpers ─────────────────────────────────────────────────────

    def _describe_action(self, action: Action, state) -> str:
        at = action.action_type
        if at == ActionType.ATTACK:
            from app.cards import registry as card_registry
            player = state.get_player(action.player_id)
            if player and player.active:
                cdef = card_registry.get(player.active.card_def_id)
                if cdef and cdef.attacks and action.attack_index is not None:
                    idx = action.attack_index
                    if idx < len(cdef.attacks):
                        atk = cdef.attacks[idx]
                        return f"ATTACK: {atk.name} ({atk.damage or '0'} dmg)"
            return "ATTACK"
        if at == ActionType.ATTACH_ENERGY:
            return f"ATTACH ENERGY → {self._find_card_name(state, action.target_instance_id)}"
        if at == ActionType.PLAY_SUPPORTER:
            return f"PLAY SUPPORTER: {self._card_name_from_action(state, action)}"
        if at == ActionType.PLAY_ITEM:
            return f"PLAY ITEM: {self._card_name_from_action(state, action)}"
        if at == ActionType.PLAY_TOOL:
            return f"PLAY TOOL: {self._card_name_from_action(state, action)}"
        if at == ActionType.PLAY_BASIC:
            return f"PLAY BASIC: {self._card_name_from_action(state, action)}"
        if at == ActionType.EVOLVE:
            onto = self._find_card_name(state, action.target_instance_id)
            return f"EVOLVE: {self._card_name_from_action(state, action)} onto {onto}"
        if at == ActionType.RETREAT:
            return f"RETREAT → {self._find_card_name(state, action.target_instance_id)}"
        if at == ActionType.USE_ABILITY:
            return f"USE ABILITY on {self._find_card_name(state, action.card_instance_id)}"
        if at == ActionType.PASS:
            return "PASS (end main phase, move to attack)"
        if at == ActionType.END_TURN:
            return "END TURN (skip attack)"
        return at.name

    def _find_card_name(self, state, instance_id: Optional[str]) -> str:
        if not instance_id:
            return "?"
        for player in (state.p1, state.p2):
            for c in (
                ([player.active] if player.active else [])
                + player.bench
                + player.hand
                + player.discard
            ):
                if c.instance_id == instance_id:
                    return c.card_name
        return instance_id[:8]

    def _find_card_def_id(self, state, instance_id: Optional[str]) -> Optional[str]:
        """Look up the tcgdex card_def_id for a given card instance UUID."""
        if not instance_id:
            return None
        for player in (state.p1, state.p2):
            for c in (
                ([player.active] if player.active else [])
                + player.bench
                + player.hand
                + player.discard
            ):
                if c.instance_id == instance_id:
                    return c.card_def_id or None
        return None

    def _card_name_from_action(self, state, action: Action) -> str:
        if action.card_instance_id:
            return self._find_card_name(state, action.card_instance_id)
        return "?"

    def _format_energy(self, pokemon) -> str:
        if not pokemon or not pokemon.energy_attached:
            return "none"
        return ", ".join(e.energy_type.value for e in pokemon.energy_attached)

    def _format_bench(self, bench: list) -> str:
        if not bench:
            return "empty"
        parts = []
        for p in bench:
            energy = f"+{len(p.energy_attached)}E" if p.energy_attached else ""
            parts.append(f"{p.card_name}({p.current_hp}/{p.max_hp}{energy})")
        return ", ".join(parts)

    def _state_summary(self, state, player_id: str) -> str:
        player = state.get_player(player_id)
        opp = state.get_opponent(player_id)
        active = (
            f"{player.active.card_name}({player.active.current_hp}/{player.active.max_hp})"
            if player.active else "none"
        )
        opp_active = (
            f"{opp.active.card_name}({opp.active.current_hp}/{opp.active.max_hp})"
            if opp.active else "none"
        )
        return (
            f"T{state.turn_number} | {player_id} | "
            f"Active:{active} | Bench:{len(player.bench)} | Prizes:{player.prizes_remaining} | "
            f"Opp:{opp_active} | OppPrizes:{opp.prizes_remaining}"
        )
