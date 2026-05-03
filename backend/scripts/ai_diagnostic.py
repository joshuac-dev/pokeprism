"""Section 2C diagnostic: run 1 AI/AI game and report decision quality."""
import asyncio
import logging
import sys

# Capture AI player decisions at debug level; suppress engine noise
logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
_ai_log = logging.getLogger("app.players.ai_player")
_ai_log.setLevel(logging.DEBUG)

# Collect log records for analysis
_decision_log: list[str] = []


class _Capture(logging.Handler):
    def emit(self, record):
        _decision_log.append(self.format(record))


_capture_handler = _Capture()
_capture_handler.setLevel(logging.DEBUG)
_ai_log.addHandler(_capture_handler)


async def main() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from app.config import settings
    from app.db.models import Deck
    from app.tasks.simulation import _deck_text_to_card_defs
    from app.engine.batch import run_hh_batch
    from app.players.ai_player import AIPlayer

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import uuid as _uuid
    _D1_ID = _uuid.UUID("4b2509d2-3e96-4df2-afd8-5990c41ac073")
    _D2_ID = _uuid.UUID("cd0a00c6-8251-4831-8dd9-8141921b52ff")
    async with SessionFactory() as db:
        r1 = await db.execute(select(Deck).where(Deck.id == _D1_ID))
        d1 = r1.scalar_one_or_none()
        r2 = await db.execute(select(Deck).where(Deck.id == _D2_ID))
        d2 = r2.scalar_one_or_none()

    if not d1 or not d2:
        print("ERROR: Required decks not found in DB")
        return

    p1_cards = await _deck_text_to_card_defs(d1.deck_text, SessionFactory)
    p2_cards = await _deck_text_to_card_defs(d2.deck_text, SessionFactory)
    print(f"P1: {d1.name} ({len(p1_cards)} cards)")
    print(f"P2: {d2.name} ({len(p2_cards)} cards)")

    game_events: list[dict] = []

    def cb(event: dict) -> None:
        game_events.append(event)
        if event.get("event_type") == "game_over":
            print(
                f"  → Game over: winner={event.get('winner')}, "
                f"condition={event.get('condition')}, turn={event.get('turn')}"
            )

    print("\nRunning 1 AI/AI game (may take several minutes)...")
    sys.stdout.flush()

    batch = await run_hh_batch(
        p1_deck=p1_cards,
        p2_deck=p2_cards,
        num_games=1,
        p1_deck_name=d1.name,
        p2_deck_name=d2.name,
        p1_player_class=AIPlayer,
        p2_player_class=AIPlayer,
        event_callback=cb,
        verbose=False,
    )

    result = batch.results[0]
    print(f"\n=== RESULT ===")
    print(f"  Winner:    {result.winner}")
    print(f"  Turns:     {result.total_turns}")
    end_cond = getattr(result, "end_condition", getattr(result, "win_condition", "?"))
    print(f"  Condition: {end_cond}")

    decisions = batch.decisions_per_game[0] if batch.decisions_per_game else []
    print(f"  Decisions logged: {len(decisions)}")

    print(f"\n=== SAMPLE DECISIONS (first 8) ===")
    for i, d in enumerate(decisions[:8]):
        print(f"\n  [{i+1}] player={d.get('player','?')} type={d.get('action_type','?')}")
        reasoning = d.get("reasoning", "")
        if reasoning:
            print(f"      reasoning: {reasoning[:300]}")

    print(f"\n=== AI LOG ENTRIES ({len(_decision_log)} total) ===")
    for line in _decision_log[:30]:
        print(f"  {line}")

    # Check for any illegal-action warnings from the validator
    illegal = [e for e in game_events if "illegal" in str(e).lower() or "invalid" in str(e).lower()]
    if illegal:
        print(f"\n=== POTENTIAL ILLEGAL ACTIONS ({len(illegal)}) ===")
        for e in illegal[:5]:
            print(f"  {e}")
    else:
        print("\n  No illegal-action events detected.")

    await engine.dispose()


asyncio.run(main())
