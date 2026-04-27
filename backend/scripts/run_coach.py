#!/usr/bin/env python3
"""CLI entry point for the Coach/Analyst end-to-end pipeline.

Runs N AI/H games with the Dragapult deck, then feeds results to CoachAnalyst
(Gemma 4 E4B) to generate 0–4 card swap proposals with reasoning.

Run from the backend/ directory:
    python3 -m scripts.run_coach [options]

Examples:
    python3 -m scripts.run_coach --num-games 5
    python3 -m scripts.run_coach --num-games 10 --max-swaps 2
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cards.loader import CardListLoader, SET_CODE_MAP  # noqa: E402
from app.cards import registry as card_registry            # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Deck lists (mirrors run_hh.py / tests/conftest.py) ───────────────────────

DRAGAPULT_DECK_LIST: list[tuple[str, str, int]] = [
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

TR_MEWTWO_DECK_LIST: list[tuple[str, str, int]] = [
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


def _load_fixture(set_abbrev: str, card_number: str) -> dict | None:
    tcgdex_set_id = SET_CODE_MAP.get(set_abbrev.upper())
    if not tcgdex_set_id:
        return None
    card_id = f"{tcgdex_set_id}-{int(card_number):03d}"
    path = FIXTURE_DIR / f"{card_id}.json"
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _load_deck(deck_list: list[tuple[str, str, int]]):
    loader = CardListLoader()
    cards = []
    for set_abbrev, number, copies in deck_list:
        raw = _load_fixture(set_abbrev, number)
        if raw is None:
            print(f"  WARNING: fixture missing for {set_abbrev} {number}", file=sys.stderr)
            continue
        cdef = loader._transform(raw, {"set_abbrev": set_abbrev, "number": number,
                                        "name": raw.get("name", "")})
        cards.extend([cdef] * copies)
    return cards


async def _run(args: argparse.Namespace) -> None:
    from app.players.ai_player import AIPlayer
    from app.players.heuristic import HeuristicPlayer
    from app.engine.batch import run_hh_batch
    from app.db.session import AsyncSessionLocal
    from app.coach.analyst import CoachAnalyst

    print("Loading decks …")
    p1_defs = _load_deck(DRAGAPULT_DECK_LIST)
    p2_defs = _load_deck(TR_MEWTWO_DECK_LIST)

    if not p1_defs or not p2_defs:
        print("ERROR: deck loading failed — run capture_fixtures.py first.", file=sys.stderr)
        sys.exit(1)

    for cdef in {c.tcgdex_id: c for c in p1_defs + p2_defs}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)

    print(f"P1 deck: {len(p1_defs)} cards  |  P2 deck: {len(p2_defs)} cards")

    simulation_id = uuid.uuid4()
    print(f"Simulation ID: {simulation_id}")

    print(f"\nRunning {args.num_games} AI/H game(s) …")
    batch = await run_hh_batch(
        p1_deck=p1_defs,
        p2_deck=p2_defs,
        p1_deck_name="Dragapult",
        p2_deck_name="TR-Mewtwo",
        p1_player_class=AIPlayer,
        p2_player_class=HeuristicPlayer,
        num_games=args.num_games,
        persist=True,
        simulation_id=simulation_id,
        verbose=True,
    )
    results = batch.results

    wins = batch.p1_wins
    print(f"\nRound complete: {wins}/{len(results)} wins ({wins/len(results):.1%})")
    print(f"Average turns: {batch.avg_turns:.1f}")

    if args.skip_coach:
        print("\n--skip-coach: not running CoachAnalyst.")
        return

    print(f"\nRunning CoachAnalyst (model={args.model or 'from env'}, max_swaps={args.max_swaps}) …")
    async with AsyncSessionLocal() as db:
        analyst = CoachAnalyst(
            db=db,
            model=args.model or None,
            max_swaps=args.max_swaps,
        )
        mutations = await analyst.analyze_and_mutate(
            current_deck=p1_defs,
            round_results=results,
            simulation_id=simulation_id,
            round_number=1,
        )
        await db.commit()

    if not mutations:
        print("\nCoach proposes 0 swaps (deck performing well or insufficient data).")
    else:
        print(f"\nCoach proposes {len(mutations)} swap(s):")
        for i, m in enumerate(mutations, 1):
            print(f"  [{i}] REMOVE {m['card_removed']}  →  ADD {m['card_added']}")
            print(f"      Reasoning: {m['reasoning']}")

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Coach/Analyst pipeline")
    parser.add_argument("--num-games", type=int, default=5,
                        help="Number of AI/H games to play before analyzing (default: 5)")
    parser.add_argument("--max-swaps", type=int, default=4,
                        help="Maximum swaps the Coach may propose (default: 4)")
    parser.add_argument("--model", type=str, default=None,
                        help="Override OLLAMA_COACH_MODEL (default: read from env)")
    parser.add_argument("--skip-coach", action="store_true",
                        help="Run games only, skip CoachAnalyst inference")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
