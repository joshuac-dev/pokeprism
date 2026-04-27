#!/usr/bin/env python3
"""Phase 6 end-to-end validation script.

Verifies:
  1. Deck sizes (60 cards each)
  2. Coach inference (raw Gemma response, model name, no-prefill)
  3. deck_mutations table rows
  4. CardPerformanceQueries top 5
  5. GraphQueries top 5 synergy pairs
  6. SimilarSituationFinder one vector search result
  7. Embeddings table count / source_type breakdown
  8. Deck legality after applying Coach swaps

Run from backend/:
    python3 -m scripts.validate_phase6
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import time
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cards.loader import CardListLoader, SET_CODE_MAP  # noqa: E402
from app.cards import registry as card_registry            # noqa: E402

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "cards"

# ── Deck lists ────────────────────────────────────────────────────────────────

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


def _load_fixture(set_abbrev: str, card_number: str) -> dict | None:
    tcgdex_set_id = SET_CODE_MAP.get(set_abbrev.upper())
    if not tcgdex_set_id:
        return None
    card_id = f"{tcgdex_set_id}-{int(card_number):03d}"
    path = FIXTURE_DIR / f"{card_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


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


# ── Section helpers ───────────────────────────────────────────────────────────

def header(text: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {text}")
    print('='*60)


async def main() -> None:
    from app.players.ai_player import AIPlayer
    from app.players.heuristic import HeuristicPlayer
    from app.engine.batch import run_hh_batch
    from app.db.session import AsyncSessionLocal
    from app.coach.analyst import CoachAnalyst
    from app.memory.postgres import CardPerformanceQueries
    from app.memory.graph import GraphQueries
    from app.memory.embeddings import SimilarSituationFinder
    from sqlalchemy import text, select, func
    from app.db.models import DeckMutation, Embedding

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 0: DECK SIZES
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 0 — DECK SIZES")
    p1_defs = _load_deck(DRAGAPULT_DECK_LIST)
    p2_defs = _load_deck(TR_MEWTWO_DECK_LIST)

    for cdef in {c.tcgdex_id: c for c in p1_defs + p2_defs}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)

    print(f"  Dragapult deck:  {len(p1_defs)} cards  {'✅' if len(p1_defs)==60 else '❌ FAIL'}")
    print(f"  TR Mewtwo deck:  {len(p2_defs)} cards  {'✅' if len(p2_defs)==60 else '❌ FAIL'}")

    # Verify fix: ASC-39 appears exactly once in Dragapult
    psyduck_copies = sum(1 for c in p1_defs if c.set_abbrev == "ASC" and c.set_number == "39")
    print(f"  Dragapult ASC-39 (Psyduck) copies: {psyduck_copies}  {'✅ (was 2, fixed to 1)' if psyduck_copies==1 else '❌'}")
    assert len(p1_defs) == 60, f"Dragapult deck has {len(p1_defs)} cards!"
    assert len(p2_defs) == 60, f"TR Mewtwo deck has {len(p2_defs)} cards!"

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: RUN 5 AI/H GAMES
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 1 — 5 AI/H GAMES")
    simulation_id = uuid.uuid4()
    print(f"  Simulation ID: {simulation_id}")

    t_start = time.monotonic()
    batch = await run_hh_batch(
        p1_deck=p1_defs,
        p2_deck=p2_defs,
        p1_deck_name="Dragapult",
        p2_deck_name="TR-Mewtwo",
        p1_player_class=AIPlayer,
        p2_player_class=HeuristicPlayer,
        num_games=5,
        persist=True,
        simulation_id=simulation_id,
        verbose=True,
    )
    results = batch.results
    elapsed = time.monotonic() - t_start

    wins = sum(1 for r in results if r.winner == "p1")
    avg_turns = sum(r.total_turns for r in results) / len(results)
    print(f"  Completed: {len(results)}/5  |  P1 wins: {wins}/5  |  "
          f"avg turns: {avg_turns:.1f}  |  wall time: {elapsed:.1f}s")
    print(f"  Win conditions: {[r.win_condition for r in results]}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: COACH INFERENCE (raw Gemma response captured)
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 2 — COACH INFERENCE (raw Gemma response)")

    raw_response_captured: list[str] = []
    model_used: list[str] = []

    async with AsyncSessionLocal() as db:
        analyst = CoachAnalyst(db=db, max_swaps=4)
        model_used.append(analyst._model)

        # Patch _call_ollama to capture the raw response while still calling the real model
        original_call = analyst._call_ollama
        async def capturing_call(prompt: str) -> str:
            raw = await original_call(prompt)
            raw_response_captured.append(raw)
            return raw
        analyst._call_ollama = capturing_call  # type: ignore[method-assign]

        mutations = await analyst.analyze_and_mutate(
            current_deck=p1_defs,
            round_results=results,
            simulation_id=simulation_id,
            round_number=1,
        )
        await db.commit()

    print(f"  Model used: {model_used[0]}")
    print(f"  Expected:   gemma4-E4B-it-Q6_K:latest  "
          f"{'✅' if 'gemma4' in model_used[0].lower() else '❌ WRONG MODEL'}")
    print()
    print("  --- RAW GEMMA RESPONSE (first call) ---")
    if raw_response_captured:
        print(textwrap.indent(raw_response_captured[0][:2000], "  "))
    else:
        print("  (no response captured)")
    print()
    print(f"  Swaps proposed: {len(mutations)}")
    for m in mutations:
        print(f"    REMOVE {m['card_removed']}  →  ADD {m['card_added']}")
        print(f"    Reasoning: {m['reasoning']}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: DECK MUTATIONS TABLE
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 3 — deck_mutations TABLE")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(DeckMutation)
            .where(DeckMutation.simulation_id == simulation_id)
            .order_by(DeckMutation.created_at)
        )).scalars().all()

    if not rows:
        print("  (no mutations written for this simulation — Coach proposed 0 swaps)")
    else:
        print(f"  {'id':<38}  {'card_removed':<20}  {'card_added':<20}  reasoning")
        print(f"  {'-'*38}  {'-'*20}  {'-'*20}  {'-'*40}")
        for r in rows:
            reasoning_short = (r.reasoning or "")[:60]
            print(f"  {str(r.id):<38}  {r.card_removed:<20}  {r.card_added:<20}  {reasoning_short}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: MEMORY QUERIES
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 4 — MEMORY QUERIES")

    # 4a: CardPerformanceQueries — top 5 by win rate
    print("  4a. CardPerformanceQueries — top 5 cards by win rate (min 5 games):")
    async with AsyncSessionLocal() as db:
        cpq = CardPerformanceQueries(db)
        total_games = await cpq.get_total_historical_games()
        top5 = await cpq.get_top_performing_cards(exclude_ids=[], limit=5)
    print(f"      Total matches in DB: {total_games}")
    if top5:
        print(f"      {'tcgdex_id':<22}  {'name':<30}  {'games':<8}  win_rate")
        for c in top5:
            print(f"      {c['tcgdex_id']:<22}  {c['name']:<30}  {c['games_included']:<8}  {c['win_rate']:.1%}")
    else:
        print("      (no cards with ≥5 games yet — expected after only 5 games)")

    # 4b: GraphQueries — top 5 synergy pairs
    print()
    print("  4b. GraphQueries — top 5 SYNERGIZES_WITH pairs:")
    gq = GraphQueries()
    all_card_ids = list({c.tcgdex_id for c in p1_defs + p2_defs})
    synergies = await gq.get_synergies(all_card_ids, top_n=5)
    top_pairs = synergies.get("top", [])
    if top_pairs:
        print(f"      {'card_a':<22}  {'card_b':<22}  weight")
        for id_a, name_a, id_b, name_b, weight in top_pairs:
            print(f"      {id_a:<22}  {id_b:<22}  {weight}")
    else:
        print("      (no synergy edges between these cards in Neo4j)")

    # 4c: SimilarSituationFinder — one vector search
    print()
    print("  4c. SimilarSituationFinder — nearest past decision to a sample state:")
    sample_text = (
        "Turn 5. Active: Dragapult ex (200/320 HP). "
        "Bench: Dreepy, Duskull. Hand size: 4. Prizes left: 5. "
        "Opponent active: Team Rocket's Mewtwo ex (180/230 HP). "
        "Opponent bench size: 2. Opponent prizes: 5."
    )
    print(f"      Query: \"{sample_text[:80]}…\"")
    async with AsyncSessionLocal() as db:
        emb_count = (await db.execute(
            select(func.count()).select_from(Embedding).where(Embedding.source_type == "decision")
        )).scalar()
        ssf = SimilarSituationFinder(db)
        similar = await ssf.find_similar(sample_text, k=3)
    print(f"      (visible embeddings in this session: {emb_count})")
    if similar:
        for i, s in enumerate(similar, 1):
            print(f"      [{i}] dist={s['distance']:.4f}  source_id={s['source_id'][:16]}…")
            print(f"          text: \"{(s['content_text'] or '')[:100]}…\"")
    else:
        print("      (no decision embeddings found — check embeddings pipeline)")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: EMBEDDINGS TABLE
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 5 — EMBEDDINGS TABLE")
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(
            select(Embedding.source_type, func.count(Embedding.id).label("n"))
            .group_by(Embedding.source_type)
        )
        counts = count_result.all()

        dim_result = await db.execute(
            text("SELECT vector_dims(embedding) AS dims FROM embeddings WHERE source_type = 'decision' LIMIT 1")
        )
        dim_row = dim_result.first()

    total_emb = sum(c.n for c in counts)
    print(f"  Total rows: {total_emb}")
    print(f"  By source_type:")
    for c in sorted(counts, key=lambda x: x.n, reverse=True):
        print(f"    {c.source_type:<20}  {c.n} rows")
    if dim_row:
        dims = dim_row.dims
        print(f"  Decision embedding dims: {dims}  "
              f"{'✅' if dims == 768 else '❌ WRONG'}")
    else:
        print("  No decision embeddings found ❌")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: DECK LEGALITY AFTER SWAPS
    # ─────────────────────────────────────────────────────────────────────────
    header("SECTION 6 — DECK LEGALITY AFTER APPLYING SWAPS")
    if not mutations:
        print("  Coach proposed 0 swaps — original 60-card deck unchanged ✅")
    else:
        from collections import Counter
        updated_ids = [c.tcgdex_id for c in p1_defs]
        for m in mutations:
            removed = m["card_removed"]
            added = m["card_added"]
            if removed in updated_ids:
                updated_ids.remove(removed)
                updated_ids.append(added)
            else:
                print(f"  WARNING: tried to remove {removed} but not in deck!")

        counts = Counter(updated_ids)
        max_copies = max(counts.values()) if counts else 0
        over_4 = [(cid, n) for cid, n in counts.items() if n > 4]

        print(f"  Cards after swaps: {len(updated_ids)}  {'✅' if len(updated_ids)==60 else '❌'}")
        print(f"  Max copies of any card: {max_copies}  {'✅' if max_copies<=4 else '❌'}")
        if over_4:
            print(f"  ILLEGAL — exceeds 4 copies: {over_4}")
        else:
            print("  No card exceeds 4 copies ✅")

        # Check if added cards exist in card pool (were loaded from fixtures)
        all_known_ids = {c.tcgdex_id for c in p1_defs + p2_defs}
        for m in mutations:
            added = m["card_added"]
            known = added in all_known_ids
            print(f"  Card {added} in known fixture pool: {'✅' if known else '❌ POSSIBLE HALLUCINATION'}")

    # ─────────────────────────────────────────────────────────────────────────
    header("VALIDATION COMPLETE")
    print("  Review outputs above. Phase 6 is verified if all ✅ pass.")


if __name__ == "__main__":
    asyncio.run(main())
