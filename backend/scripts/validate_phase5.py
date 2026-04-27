#!/usr/bin/env python3
"""Phase 5 validation script.

Runs 10 AI/H games and reports:
  1. Completion rate
  2. Fallback rate (LLM parse failures vs total decisions)
  3. Decision quality (3 full prompt/response/action samples)
  4. Reasoning storage (SELECT 5 rows from decisions table)
  5. Performance (avg Ollama inference time, total game wall-clock time)

Run from backend/:
    python3 -m scripts.validate_phase5
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from sqlalchemy import text

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.cards import registry as card_registry
from app.config import settings
from app.engine.actions import Action, ActionType
from app.engine.batch import run_hh_batch
from app.players.ai_player import AIPlayer
from app.players.heuristic import HeuristicPlayer

logging.basicConfig(level=logging.ERROR)  # suppress engine noise

# ── Deck lists (mirrors run_hh.py) ────────────────────────────────────────────

DRAGAPULT_DECK_LIST = [
    ("TWM", "128", 4), ("TWM", "129", 3), ("TWM", "130", 3),
    ("PRE", "35",  4), ("PRE", "36",  2), ("PRE", "37",  2),
    ("TWM", "96",  1), ("ASC", "142", 1), ("TWM", "95",  1),
    ("ASC", "39",  1),
    ("TEF", "144", 4), ("MEG", "131", 3), ("MEG", "125", 3),
    ("ASC", "196", 2), ("TEF", "157", 2), ("MEG", "114", 2),
    ("TEF", "154", 2), ("TWM", "167", 2), ("TEF", "155", 2),
    ("TEF", "146", 2), ("TWM", "163", 2), ("TWM", "143", 1),
    ("TWM", "148", 1), ("PRE", "95",  1), ("PRE", "112", 1),
    ("MEE", "5",   4), ("TEF", "161", 2), ("ASC", "216", 2),
]

TR_MEWTWO_DECK_LIST = [
    ("DRI", "81",  3), ("DRI", "87",  3), ("DRI", "128", 2),
    ("DRI", "51",  2), ("DRI", "10",  2), ("ASC", "39",  2),
    ("MEG", "88",  2), ("MEG", "86",  1), ("MEG", "74",  1),
    ("DRI", "178", 3), ("DRI", "174", 3), ("DRI", "173", 3),
    ("DRI", "177", 2), ("DRI", "170", 2), ("DRI", "171", 2),
    ("DRI", "176", 2), ("DRI", "180", 2), ("DRI", "169", 2),
    ("DRI", "168", 2), ("DRI", "164", 2), ("MEG", "131", 2),
    ("MEG", "114", 2), ("MEG", "119", 1), ("MEG", "115", 1),
    ("SVI", "186", 1), ("SFA", "57",  1),
    ("MEE", "5",   3), ("MEE", "7",   3), ("DRI", "182", 2),
    ("ASC", "216", 1),
]

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "cards"

NUM_GAMES = 10


# ── Instrumented AIPlayer ─────────────────────────────────────────────────────

class InstrumentedAIPlayer(AIPlayer):
    """AIPlayer that records timing and captures sample prompts/responses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_llm_calls: int = 0        # times we actually called Ollama
        self.total_fallbacks: int = 0        # times fallback was used
        self.total_llm_ms: list[float] = []  # per-call inference ms
        # First 3 (prompt, raw_response, parsed_action_desc) tuples
        self.decision_samples: list[tuple[str, str, str]] = []

    async def _call_ollama(self, prompt: str, attempt: int) -> str:
        t0 = time.perf_counter()
        raw = await super()._call_ollama(prompt, attempt)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.total_llm_calls += 1
        self.total_llm_ms.append(elapsed_ms)
        return raw

    async def choose_action(self, state, legal_actions: list) -> Action:
        first = legal_actions[0] if legal_actions else None

        # Interrupts skip LLM entirely — don't count them.
        if first and first.action_type in (
            ActionType.CHOOSE_CARDS, ActionType.CHOOSE_TARGET, ActionType.CHOOSE_OPTION
        ):
            return await super().choose_action(state, legal_actions)

        # Build prompt once so we can capture it.
        if not legal_actions:
            return None

        prompt = self._build_prompt(state, legal_actions)
        player_id = legal_actions[0].player_id
        capture_this = len(self.decision_samples) < 3

        chosen_action = None
        used_fallback = False

        for attempt in range(self.max_retries):
            try:
                raw = await self._call_ollama(prompt, attempt)
                action = self._parse_response(raw, legal_actions)
                if action is not None:
                    if capture_this and attempt == 0:
                        desc = self._describe_action(action, state)
                        self.decision_samples.append((prompt, raw, desc))
                        capture_this = False
                    self._record_decision(state, player_id, action, len(legal_actions))
                    chosen_action = action
                    break
            except Exception as exc:
                print(f"  [WARN] Ollama call failed attempt {attempt+1}: {exc}", file=sys.stderr)

            prompt += (
                "\n\nYour previous response could not be parsed. "
                "You MUST respond with ONLY a JSON object like: "
                '{"action_id": <number>, "reasoning": "<your reasoning>"}'
            )

        if chosen_action is None:
            # All retries failed — fallback.
            self.total_fallbacks += 1
            fallback = HeuristicPlayer()
            chosen_action = await fallback.choose_action(state, legal_actions)
            chosen_action.reasoning = "[FALLBACK] AI response unparseable after retries"
            self._record_decision(state, player_id, chosen_action, len(legal_actions))

        return chosen_action


# ── Deck loader ───────────────────────────────────────────────────────────────

def _load_fixture(set_abbrev: str, card_number: str) -> dict | None:
    tcgdex_set_id = SET_CODE_MAP.get(set_abbrev.upper())
    if not tcgdex_set_id:
        return None
    card_id = f"{tcgdex_set_id}-{int(card_number):03d}"
    path = FIXTURE_DIR / f"{card_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _load_deck(deck_list):
    loader = CardListLoader()
    cards = []
    for set_abbrev, number, copies in deck_list:
        raw = _load_fixture(set_abbrev, number)
        if raw is None:
            print(f"  WARNING: fixture missing {set_abbrev} {number}", file=sys.stderr)
            continue
        cdef = loader._transform(raw, {"set_abbrev": set_abbrev, "number": number,
                                       "name": raw.get("name", "")})
        cards.extend([cdef] * copies)
    return cards


# ── Validation runner ─────────────────────────────────────────────────────────

async def run_validation():
    print("=" * 60)
    print("  PHASE 5 VALIDATION — 10 AI/H GAMES")
    print("=" * 60)

    print("\nLoading decks …")
    p1_defs = _load_deck(DRAGAPULT_DECK_LIST)
    p2_defs = _load_deck(TR_MEWTWO_DECK_LIST)
    if not p1_defs or not p2_defs:
        print("ERROR: deck loading failed.", file=sys.stderr)
        sys.exit(1)
    for cdef in {c.tcgdex_id: c for c in p1_defs + p2_defs}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)
    print(f"  P1 deck: {len(p1_defs)} cards (Dragapult)")
    print(f"  P2 deck: {len(p2_defs)} cards (TR Mewtwo)")

    # ── Per-game loop (not using run_hh_batch so we can time each game) ────────
    from app.engine.runner import MatchRunner
    from app.db.session import AsyncSessionLocal
    from app.memory.postgres import MatchMemoryWriter
    from app.memory.graph import GraphMemoryWriter

    simulation_id = uuid.uuid4()
    round_id = uuid.uuid4()
    pg_writer = MatchMemoryWriter()
    graph_writer = GraphMemoryWriter()

    # Bootstrap DB rows.
    async with AsyncSessionLocal() as db:
        await pg_writer.ensure_cards(
            list({c.tcgdex_id: c for c in p1_defs + p2_defs}.values()), db
        )
        p1_deck_db_id = await pg_writer.ensure_deck("Dragapult", p1_defs, db)
        p2_deck_db_id = await pg_writer.ensure_deck("TR-Mewtwo", p2_defs, db)
        await pg_writer.ensure_simulation(simulation_id, db)
        await pg_writer.ensure_round(
            round_id, simulation_id, 1,
            {"p1": "Dragapult", "p2": "TR-Mewtwo"}, db
        )
        await db.commit()

    ai_player = InstrumentedAIPlayer()
    h_player = HeuristicPlayer()

    crashes = 0
    completions = 0
    game_times: list[float] = []
    match_ids: list[uuid.UUID] = []

    print(f"\nRunning {NUM_GAMES} games …\n")

    for i in range(NUM_GAMES):
        print(f"  Game {i+1}/{NUM_GAMES} … ", end="", flush=True)
        game_t0 = time.perf_counter()
        try:
            runner = MatchRunner(
                p1_player=ai_player,
                p2_player=h_player,
                p1_deck=p1_defs,
                p2_deck=p2_defs,
                p1_deck_name="Dragapult",
                p2_deck_name="TR-Mewtwo",
            )
            result = await runner.run()
            elapsed = time.perf_counter() - game_t0
            game_times.append(elapsed)
            completions += 1
            print(f"done in {elapsed:.1f}s  (winner={result.winner}, "
                  f"turns={result.total_turns}, cond={result.win_condition})")

            # Drain and persist decisions.
            p1_decisions = ai_player.drain_decisions()
            async with AsyncSessionLocal() as db:
                match_id = await pg_writer.write_match(
                    result=result,
                    simulation_id=simulation_id,
                    round_id=round_id,
                    round_number=1,
                    p1_deck_id=p1_deck_db_id,
                    p2_deck_id=p2_deck_db_id,
                    db=db,
                )
                if p1_decisions:
                    await pg_writer.write_decisions(
                        p1_decisions,
                        match_id=match_id,
                        simulation_id=simulation_id,
                        db=db,
                    )
                await db.commit()
            match_ids.append(match_id)

        except Exception as exc:
            elapsed = time.perf_counter() - game_t0
            crashes += 1
            print(f"CRASHED after {elapsed:.1f}s: {exc}")
            import traceback
            traceback.print_exc()

    # ── 1. COMPLETION RATE ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("1. COMPLETION RATE")
    print("=" * 60)
    print(f"  Games attempted : {NUM_GAMES}")
    print(f"  Completed       : {completions}")
    print(f"  Crashed         : {crashes}")
    print(f"  Completion rate : {completions/NUM_GAMES*100:.0f}%")

    # ── 2. FALLBACK RATE ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("2. FALLBACK RATE")
    print("=" * 60)
    total_decisions = ai_player.total_llm_calls + ai_player.total_fallbacks
    fallback_pct = (ai_player.total_fallbacks / total_decisions * 100) if total_decisions else 0
    print(f"  Total LLM decisions attempted : {total_decisions}")
    print(f"  Successful parses             : {total_decisions - ai_player.total_fallbacks}")
    print(f"  Fallbacks (parse failures)    : {ai_player.total_fallbacks}")
    print(f"  Fallback rate                 : {fallback_pct:.2f}%  (target: <1%)")

    # ── 3. DECISION QUALITY ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("3. DECISION QUALITY — 3 SAMPLE DECISIONS")
    print("=" * 60)
    for idx, (prompt, raw_resp, parsed_desc) in enumerate(ai_player.decision_samples, 1):
        print(f"\n--- Sample {idx} ---")
        print("\n[PROMPT SENT TO OLLAMA]")
        print(prompt)
        print("\n[RAW OLLAMA RESPONSE]")
        print(repr(raw_resp))
        print("\n[PARSED ACTION]")
        print(f"  {parsed_desc}")

    if not ai_player.decision_samples:
        print("  WARNING: No decision samples captured (0 LLM calls succeeded?)")

    # ── 4. REASONING STORAGE ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("4. REASONING STORAGE — 5 ROWS FROM decisions TABLE")
    print("=" * 60)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            """
            SELECT
                d.turn_number,
                d.player_id,
                d.action_type,
                d.legal_action_count,
                LEFT(d.reasoning, 120) AS reasoning_preview,
                d.game_state_summary
            FROM decisions d
            WHERE d.simulation_id = :sim_id
            ORDER BY d.turn_number
            LIMIT 5
            """
        ), {"sim_id": str(simulation_id)})).fetchall()

    if rows:
        for row in rows:
            print(f"\n  turn={row.turn_number}  player={row.player_id}  "
                  f"action={row.action_type}  legal_choices={row.legal_action_count}")
            print(f"  state  : {row.game_state_summary}")
            print(f"  reason : {row.reasoning_preview}")
    else:
        print("  WARNING: No rows found in decisions table for this simulation_id.")
        print(f"  simulation_id = {simulation_id}")

    # ── 5. PERFORMANCE ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("5. PERFORMANCE")
    print("=" * 60)
    if ai_player.total_llm_ms:
        avg_ms = sum(ai_player.total_llm_ms) / len(ai_player.total_llm_ms)
        min_ms = min(ai_player.total_llm_ms)
        max_ms = max(ai_player.total_llm_ms)
        print(f"  Ollama inference — avg  : {avg_ms:.0f} ms")
        print(f"  Ollama inference — min  : {min_ms:.0f} ms")
        print(f"  Ollama inference — max  : {max_ms:.0f} ms")
        print(f"  Total LLM calls         : {len(ai_player.total_llm_ms)}")
    else:
        print("  WARNING: No timing data (no LLM calls completed?).")

    if game_times:
        avg_game = sum(game_times) / len(game_times)
        print(f"  Game wall-clock — avg   : {avg_game:.1f} s")
        print(f"  Game wall-clock — min   : {min(game_times):.1f} s")
        print(f"  Game wall-clock — max   : {max(game_times):.1f} s")

    print("\n" + "=" * 60)
    print("  VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_validation())
