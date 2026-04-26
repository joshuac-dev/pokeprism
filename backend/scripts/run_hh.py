#!/usr/bin/env python3
"""CLI entry point for H/H (and H/G) batch simulation.

Run from the backend/ directory:
    python3 -m scripts.run_hh [options]

Examples:
    # 100-game H/H benchmark (default decks)
    python3 -m scripts.run_hh --num-games 100

    # H/G comparison: HeuristicPlayer (P1) vs GreedyPlayer (P2)
    python3 -m scripts.run_hh --num-games 100 --p2-greedy

    # G/G baseline
    python3 -m scripts.run_hh --num-games 100 --greedy
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the backend package root is on the path when called directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cards.loader import CardListLoader, SET_CODE_MAP  # noqa: E402
from app.cards import registry as card_registry            # noqa: E402
from app.engine.batch import run_hh_batch                 # noqa: E402

logging.basicConfig(level=logging.WARNING)

# ── Canonical deck lists (mirrors tests/conftest.py) ─────────────────────────

DRAGAPULT_DECK_LIST: list[tuple[str, str, int]] = [
    ("TWM", "128", 4), ("TWM", "129", 3), ("TWM", "130", 3),
    ("PRE", "35",  4), ("PRE", "36",  2), ("PRE", "37",  2),
    ("TWM", "96",  1), ("ASC", "142", 1), ("TWM", "95",  1),
    ("ASC", "39",  2),
    ("TEF", "144", 4), ("MEG", "131", 3), ("MEG", "125", 3),
    ("ASC", "196", 2), ("TEF", "157", 2), ("MEG", "114", 2),
    ("TEF", "154", 2), ("TWM", "167", 2), ("TEF", "155", 2),
    ("TEF", "146", 2), ("TWM", "163", 2), ("TWM", "143", 1),
    ("TWM", "148", 1), ("PRE", "95",  1), ("PRE", "112", 1),
    ("MEE", "5",   4), ("TEF", "161", 2), ("ASC", "216", 2),
]

TR_MEWTWO_DECK_LIST: list[tuple[str, str, int]] = [
    # Pokémon (18)
    ("DRI", "81",  3), ("DRI", "87",  3), ("DRI", "128", 2),
    ("DRI", "51",  2), ("DRI", "10",  2), ("ASC", "39",  2),
    ("MEG", "88",  2), ("MEG", "86",  1), ("MEG", "74",  1),
    # Trainers (33)
    ("DRI", "178", 3), ("DRI", "174", 3), ("DRI", "173", 3),
    ("DRI", "177", 2), ("DRI", "170", 2), ("DRI", "171", 2),
    ("DRI", "176", 2), ("DRI", "180", 2), ("DRI", "169", 2),
    ("DRI", "168", 2), ("DRI", "164", 2), ("MEG", "131", 2),
    ("MEG", "114", 2), ("MEG", "119", 1), ("MEG", "115", 1),
    ("SVI", "186", 1), ("SFA", "57",  1),
    # Energy (9)
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
    from app.players.heuristic import HeuristicPlayer
    from app.players.base import GreedyPlayer

    print("Loading decks …")
    p1_defs = _load_deck(DRAGAPULT_DECK_LIST)
    p2_defs = _load_deck(TR_MEWTWO_DECK_LIST)

    if len(p1_defs) == 0 or len(p2_defs) == 0:
        print("ERROR: deck loading failed — run capture_fixtures.py first.", file=sys.stderr)
        sys.exit(1)

    # Register all unique card definitions so the engine can look them up.
    for cdef in {c.tcgdex_id: c for c in p1_defs + p2_defs}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)

    p1_deck = p1_defs
    p2_deck = p2_defs

    if args.swap:
        p1_deck, p2_deck = p2_deck, p1_deck
        p1_name, p2_name = "TR-Mewtwo", "Dragapult"
    else:
        p1_name, p2_name = "Dragapult", "TR-Mewtwo"

    if args.greedy:
        p1_cls, p2_cls = GreedyPlayer, GreedyPlayer
        mode = "G/G"
    elif args.p2_greedy:
        p1_cls, p2_cls = HeuristicPlayer, GreedyPlayer
        mode = "H/G"
    else:
        p1_cls, p2_cls = HeuristicPlayer, HeuristicPlayer
        mode = "H/H"

    swap_label = " (swapped)" if args.swap else ""
    print(f"Running {args.num_games} × {mode} games "
          f"({p1_name} vs {p2_name}){swap_label} …\n")

    result = await run_hh_batch(
        p1_deck=p1_deck,
        p2_deck=p2_deck,
        num_games=args.num_games,
        p1_deck_name=p1_name,
        p2_deck_name=p2_name,
        p1_player_class=p1_cls,
        p2_player_class=p2_cls,
        verbose=True,
    )

    print(f"\n{'─' * 40}")
    print(f"  Mode: {mode}  |  {args.num_games} games")
    print(f"{'─' * 40}")
    print(result.summary())
    print(f"{'─' * 40}")


def main() -> None:
    parser = argparse.ArgumentParser(description="PokéPrism batch simulator")
    parser.add_argument("--num-games", type=int, default=100,
                        help="Number of games to simulate (default: 100)")
    parser.add_argument("--greedy", action="store_true",
                        help="G/G mode: both players use GreedyPlayer")
    parser.add_argument("--p2-greedy", action="store_true",
                        help="H/G mode: P1=Heuristic, P2=Greedy")
    parser.add_argument("--swap", action="store_true",
                        help="Swap decks: P1=TR Mewtwo, P2=Dragapult")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
