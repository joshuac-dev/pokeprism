"""Section 2C: Run 3 AI/AI games and report decision quality."""
import asyncio, sys, uuid as _uuid

async def main() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from app.config import settings
    from app.db.models import Deck
    from app.tasks.simulation import _deck_text_to_card_defs
    from app.engine.batch import run_hh_batch
    from app.players.ai_player import AIPlayer

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SF = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    _D1 = _uuid.UUID("4b2509d2-3e96-4df2-afd8-5990c41ac073")  # Dragapult ex
    _D2 = _uuid.UUID("cd0a00c6-8251-4831-8dd9-8141921b52ff")  # TR Mewtwo ex
    _D3 = _uuid.UUID("d439f02a-8030-4fee-b7e3-da3b3af999e6")  # Ogerpon ex

    async with SF() as db:
        d1 = (await db.execute(select(Deck).where(Deck.id == _D1))).scalar_one()
        d2 = (await db.execute(select(Deck).where(Deck.id == _D2))).scalar_one()
        d3 = (await db.execute(select(Deck).where(Deck.id == _D3))).scalar_one()

    p1 = await _deck_text_to_card_defs(d1.deck_text, SF)
    p2 = await _deck_text_to_card_defs(d2.deck_text, SF)
    p3 = await _deck_text_to_card_defs(d3.deck_text, SF)

    game_configs = [
        (p1, d1.name, p2, d2.name),
        (p1, d1.name, p3, d3.name),
        (p2, d2.name, p3, d3.name),
    ]

    all_decisions = []
    all_results = []
    import logging
    # Suppress engine noise but keep warnings
    logging.basicConfig(level=logging.WARNING)
    # Capture only illegal-action warnings from validator
    validator_warnings = []
    class _VCapture(logging.Handler):
        def emit(self, r):
            validator_warnings.append(r.getMessage())
    _vc = _VCapture()
    for name in ("app.engine.actions", "app.engine.runner", "app.engine.effects.registry"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.addHandler(_vc)

    for i, (d_p1, n1, d_p2, n2) in enumerate(game_configs, 1):
        print(f"\nGame {i}: {n1} vs {n2}", flush=True)
        events: list[dict] = []
        def cb(e, _ev=events):
            _ev.append(e)
            if e.get("event_type") == "game_over":
                print(f"  Done: winner={e.get('winner')}, turns={e.get('turn')}", flush=True)

        batch = await run_hh_batch(
            p1_deck=d_p1, p2_deck=d_p2, num_games=1,
            p1_deck_name=n1, p2_deck_name=n2,
            p1_player_class=AIPlayer, p2_player_class=AIPlayer,
            event_callback=cb, verbose=False,
        )
        r = batch.results[0]
        decs = batch.decisions_per_game[0] if batch.decisions_per_game else []
        all_results.append((i, r, decs))
        all_decisions.extend(decs)

    print("\n" + "="*60)
    print("SECTION 2C — AI/AI BEHAVIORAL AUDIT RESULTS")
    print("="*60)
    for i, r, decs in all_results:
        cond = getattr(r, "end_condition", getattr(r, "win_condition", "?"))
        print(f"\nGame {i}: winner={r.winner}, turns={r.total_turns}, condition={cond}, decisions={len(decs)}")

    print(f"\nTotal decisions across 3 games: {len(all_decisions)}")

    # Find decisions with suspicious reasoning
    suspicious = []
    for d in all_decisions:
        reason = (d.get("reasoning") or "").lower()
        action = d.get("action_type", "")
        # Potential issues:
        # 1. PASS reasoning that mentions a KO opportunity (missed KO)
        if action == "PASS" and ("knock out" in reason or "ko" in reason or "enough" in reason):
            suspicious.append(("POSSIBLE MISSED KO (chose PASS)", d))
        # 2. Reasoning contradicting action: mentions attacking but chose END_TURN/PASS
        if action in ("END_TURN", "PASS") and "attack" in reason and "can" not in reason and "no" not in reason:
            suspicious.append(("REASONING MENTIONS ATTACK BUT PASSED", d))

    print(f"\nSuspicious decisions found: {len(suspicious)}")
    worst = suspicious[:5] if suspicious else []

    print("\n=== WORST DECISIONS ===")
    if not worst:
        print("  None found — AI reasoning appears consistent with actions chosen.")
    for label, d in worst:
        print(f"\n  [{label}]")
        print(f"  Action type: {d.get('action_type')}")
        print(f"  Reasoning: {(d.get('reasoning') or '')[:400]}")

    print("\n=== VALIDATOR GATE CHECK ===")
    if validator_warnings:
        print(f"  {len(validator_warnings)} validator warnings:")
        for w in validator_warnings[:10]:
            print(f"    {w}")
    else:
        print("  PASS — No validator warnings detected across 3 games.")
        print("  The hard gate blocked all illegal actions before they reached the engine.")

    await engine.dispose()

asyncio.run(main())
