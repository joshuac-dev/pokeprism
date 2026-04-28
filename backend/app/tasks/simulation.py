"""Celery task: run_simulation — full simulation lifecycle.

Phase 7: wraps the async simulation engine in a synchronous Celery task.
Publishes real-time events to Redis pub/sub for WebSocket forwarding.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import redis  # module-level import so tests can patch `app.tasks.simulation.redis`

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Deck, Round, Simulation, SimulationOpponent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deck text helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PTCGL format regexes
# ---------------------------------------------------------------------------

# Section headers: "Pokémon: 14", "Trainer:", "Energy: 7" — always skipped
_PTCGL_SECTION_RE = re.compile(
    r"^(?:Pok[eé]mon|Trainer|Energy)\s*:", re.IGNORECASE
)

# PTCGL card line: "4 Dreepy PRE 71" or "1 Pecharunt PR-SV 149"
# Groups: (count, card_name, set_abbrev, card_number)
_PTCGL_LINE_RE = re.compile(
    r"^(\d+)\s+(.+?)\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)\s+(\d+)\s*$"
)


def _parse_ptcgl_deck_text(deck_text: str) -> list[dict]:
    """Parse PTCGL export format into structured entries.

    Handles:
      - "4 Dreepy PRE 71"
      - "2 Boss's Orders MEG 114"
      - "1 Pecharunt PR-SV 149"
      - Section headers (Pokémon:, Trainer:, Energy:) — skipped
      - Blank lines and # comments — skipped

    Returns list of dicts: {count, name, set_abbrev, set_number}
    """
    entries: list[dict] = []
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _PTCGL_SECTION_RE.match(line):
            continue
        m = _PTCGL_LINE_RE.match(line)
        if not m:
            continue
        entries.append({
            "count": int(m.group(1)),
            "name": m.group(2).strip(),
            "set_abbrev": m.group(3),
            "set_number": m.group(4),
        })
    return entries


def _parse_deck_text(deck_text: str) -> list[tuple[int, str]]:
    """Parse TCGdex-format deck text into (count, tcgdex_id) pairs.

    Handles:
      - "4 Dragapult ex sv06-130"  → count=4, tcgdex_id="sv06-130"
      - "4 sv06-130"               → count=4, tcgdex_id="sv06-130"
    The last space-separated token on each line is treated as the tcgdex_id
    when it contains a hyphen; otherwise the second token is used.
    """
    entries: list[tuple[int, str]] = []
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        try:
            count = int(tokens[0])
        except ValueError:
            continue
        # Prefer the last token when it looks like a tcgdex_id (e.g. sv06-130)
        last = tokens[-1]
        if "-" in last and any(c.isdigit() for c in last):
            tcgdex_id = last
        elif len(tokens) == 2:
            tcgdex_id = tokens[1]
        else:
            continue
        entries.append((count, tcgdex_id))
    return entries


def count_deck_cards(deck_text: str) -> int:
    """Return the total number of cards described in *deck_text*.

    Handles both TCGdex format (``4 Dragapult ex sv06-130``) and
    PTCGO/PTCGL export format (``4 Dragapult ex SVI 186``).  Any line
    whose first token is a positive integer is counted; section headers
    such as ``Pokémon: 14`` are skipped because their first token is
    not a plain integer.
    """
    total = 0
    for raw_line in deck_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        try:
            count = int(tokens[0])
            if count > 0:
                total += count
        except ValueError:
            continue
    return total


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------

from app.tasks.celery_app import celery_app  # noqa: E402


@celery_app.task(bind=True, name="pokeprism.run_simulation")
def run_simulation(self, simulation_id: str) -> dict:
    """Synchronous Celery entry point — wraps async implementation."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_simulation_async(self, simulation_id))
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------

async def _run_simulation_async(task_self: Any, simulation_id: str) -> dict:
    """Full simulation lifecycle."""
    from app.engine.batch import run_hh_batch
    from app.memory.postgres import MatchMemoryWriter

    sim_uuid = uuid.UUID(simulation_id)
    r = redis.Redis.from_url(settings.REDIS_URL)
    channel = f"simulation:{simulation_id}"

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _publish(event: dict) -> None:
        try:
            r.publish(channel, json.dumps(event))
        except Exception as exc:
            logger.warning("Redis publish failed: %s", exc)

    try:
        # ── 1 & 2. Load simulation and set status = running ─────────────────
        async with SessionFactory() as db:
            row = await db.execute(select(Simulation).where(Simulation.id == sim_uuid))
            sim = row.scalar_one_or_none()
            if sim is None:
                raise ValueError(f"Simulation {simulation_id} not found")

            num_rounds = sim.num_rounds
            matches_per_opponent = sim.matches_per_opponent
            target_win_rate = sim.target_win_rate  # integer percentage (e.g. 60)
            deck_locked = sim.deck_locked
            game_mode = sim.game_mode
            user_deck_id = sim.user_deck_id
            user_deck_name = sim.user_deck_name or "User Deck"

            sim.status = "running"
            sim.started_at = datetime.now(timezone.utc)
            await db.commit()

        # ── 3 & 4. Load user deck and opponent decks ────────────────────────
        async with SessionFactory() as db:
            if user_deck_id:
                dr = await db.execute(select(Deck).where(Deck.id == user_deck_id))
                user_deck_row = dr.scalar_one_or_none()
                user_deck_text = user_deck_row.deck_text if user_deck_row else ""
            else:
                user_deck_text = ""

            opp_rows = await db.execute(
                select(SimulationOpponent).where(
                    SimulationOpponent.simulation_id == sim_uuid
                )
            )
            opponents = opp_rows.scalars().all()

            # (deck_id, deck_name, deck_text)
            opponent_decks: list[tuple[uuid.UUID, str, str]] = []
            for opp in opponents:
                dr = await db.execute(select(Deck).where(Deck.id == opp.deck_id))
                deck_row = dr.scalar_one_or_none()
                if deck_row:
                    opponent_decks.append(
                        (opp.deck_id, opp.deck_name or deck_row.name or "", deck_row.deck_text)
                    )

        current_deck_cards = await _deck_text_to_card_defs(user_deck_text, SessionFactory)
        if not current_deck_cards:
            raise ValueError(
                "User deck could not be parsed — no valid card lines found. "
                "Accepted formats: TCGdex ('4 sv06-130'), TCGdex verbose "
                "('4 Dragapult ex sv06-130'), or PTCGL export ('4 Dragapult ex TWM 130')."
            )
        current_deck_text = user_deck_text
        writer = MatchMemoryWriter()
        final_win_rate = 0
        total_round_matches = 0

        # ── 5. Round loop ───────────────────────────────────────────────────
        for round_number in range(1, num_rounds + 1):
            # Check if simulation was cancelled between rounds
            async with SessionFactory() as db:
                status_row = await db.execute(
                    select(Simulation.status).where(Simulation.id == sim_uuid)
                )
                current_status = status_row.scalar_one_or_none()
                if current_status == "cancelled":
                    logger.info("Simulation %s cancelled — stopping at round %d", simulation_id, round_number)
                    _publish({"type": "simulation_cancelled", "simulation_id": simulation_id})
                    return {"status": "cancelled"}

            if task_self is not None and hasattr(task_self, "update_state"):
                task_self.update_state(
                    state="PROGRESS",
                    meta={"round": round_number, "total_rounds": num_rounds},
                )

            deck_snapshot = [
                {"tcgdex_id": c.tcgdex_id, "name": c.name}
                for c in current_deck_cards
            ]

            _publish({
                "type": "round_start",
                "simulation_id": simulation_id,
                "round_number": round_number,
                "deck_snapshot": deck_snapshot,
            })

            round_id = uuid.uuid4()
            async with SessionFactory() as db:
                rnd = Round(
                    id=round_id,
                    simulation_id=sim_uuid,
                    round_number=round_number,
                    deck_snapshot={"cards": deck_snapshot},
                    started_at=datetime.now(timezone.utc),
                    total_matches=0,
                )
                db.add(rnd)
                await db.commit()

            player_classes = _get_player_classes(game_mode)
            all_round_results = []
            p1_wins_round = 0
            p1_total_round = 0

            for opp_deck_id, opp_name, opp_deck_text in opponent_decks:
                opp_cards = await _deck_text_to_card_defs(opp_deck_text, SessionFactory)
                if not opp_cards:
                    continue

                match_counter = {"n": 0}

                def _make_match_event_callback(
                    _sim_id: str,
                    _round_num: int,
                    _counter: dict,
                ) -> None:
                    def _cb(event: dict) -> None:
                        etype = event.get("event_type", "") or event.get("type", "")
                        if etype == "game_start":
                            _counter["n"] += 1
                            _publish({
                                "type": "match_start",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "p1_deck": event.get("p1_deck"),
                                "p2_deck": event.get("p2_deck"),
                            })
                        elif etype == "game_over":
                            _publish({
                                "type": "match_end",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "winner": event.get("winner"),
                                "condition": event.get("condition"),
                            })
                        else:
                            _publish({
                                "type": "match_event",
                                "simulation_id": _sim_id,
                                "round_number": _round_num,
                                "match_number": _counter["n"],
                                "event": etype,
                                "data": {k: v for k, v in event.items() if k != "event_type"},
                            })
                    return _cb

                batch = await run_hh_batch(
                    p1_deck=current_deck_cards,
                    p2_deck=opp_cards,
                    num_games=matches_per_opponent,
                    p1_deck_name=user_deck_name,
                    p2_deck_name=opp_name,
                    p1_player_class=player_classes[0],
                    p2_player_class=player_classes[1],
                    event_callback=_make_match_event_callback(
                        simulation_id, round_number, match_counter
                    ),
                    verbose=False,
                )

                async with SessionFactory() as db:
                    all_card_defs = list(
                        {c.tcgdex_id: c for c in current_deck_cards + opp_cards}.values()
                    )
                    await writer.ensure_cards(all_card_defs, db)
                    p1_deck_db_id = await writer.ensure_deck(
                        user_deck_name, current_deck_cards, db
                    )
                    for idx, result_item in enumerate(batch.results):
                        match_id = await writer.write_match(
                            result=result_item,
                            simulation_id=sim_uuid,
                            round_id=round_id,
                            round_number=round_number,
                            p1_deck_id=p1_deck_db_id,
                            p2_deck_id=opp_deck_id,
                            db=db,
                        )
                        game_decisions = (
                            batch.decisions_per_game[idx]
                            if idx < len(batch.decisions_per_game) else []
                        )
                        if game_decisions:
                            await writer.write_decisions(
                                game_decisions,
                                match_id=match_id,
                                simulation_id=sim_uuid,
                                db=db,
                            )
                    await db.commit()

                all_round_results.extend(batch.results)
                p1_wins_round += batch.p1_wins
                p1_total_round += batch.total_games

            win_rate_pct = (
                int(round(p1_wins_round / p1_total_round * 100))
                if p1_total_round > 0 else 0
            )
            final_win_rate = win_rate_pct
            total_round_matches += p1_total_round

            async with SessionFactory() as db:
                await db.execute(
                    update(Round)
                    .where(Round.id == round_id)
                    .values(
                        win_rate=win_rate_pct,
                        total_matches=p1_total_round,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.execute(
                    update(Simulation)
                    .where(Simulation.id == sim_uuid)
                    .values(
                        rounds_completed=round_number,
                        total_matches=total_round_matches,
                    )
                )
                await db.commit()

            mutations_for_event: list[dict] = []

            if win_rate_pct >= target_win_rate:
                _publish({
                    "type": "target_reached",
                    "simulation_id": simulation_id,
                    "round_number": round_number,
                    "win_rate": win_rate_pct / 100.0,
                })
                _publish({
                    "type": "round_end",
                    "simulation_id": simulation_id,
                    "round_number": round_number,
                    "win_rate": win_rate_pct / 100.0,
                    "wins": p1_wins_round,
                    "total": p1_total_round,
                    "mutations": mutations_for_event,
                })
                break

            if not deck_locked and round_number < num_rounds and current_deck_cards:
                try:
                    async with SessionFactory() as db:
                        from app.coach.analyst import CoachAnalyst
                        analyst = CoachAnalyst(db=db)
                        mutations = await analyst.analyze_and_mutate(
                            current_deck=current_deck_cards,
                            round_results=all_round_results,
                            simulation_id=sim_uuid,
                            round_number=round_number,
                        )
                        await db.commit()

                    current_deck_cards, current_deck_text = _apply_mutations(
                        current_deck_cards, current_deck_text, mutations
                    )
                    mutations_for_event = [
                        {
                            "remove": m.get("card_removed"),
                            "add": m.get("card_added"),
                            "reasoning": m.get("reasoning"),
                        }
                        for m in mutations
                    ]
                    for mut in mutations_for_event:
                        _publish({
                            "type": "deck_mutation",
                            "simulation_id": simulation_id,
                            "round_number": round_number,
                            "remove": mut["remove"],
                            "add": mut["add"],
                            "reasoning": mut["reasoning"],
                        })
                except Exception as exc:
                    logger.warning("Coach mutation failed (round %d): %s", round_number, exc)

            _publish({
                "type": "round_end",
                "simulation_id": simulation_id,
                "round_number": round_number,
                "win_rate": win_rate_pct / 100.0,
                "wins": p1_wins_round,
                "total": p1_total_round,
                "mutations": mutations_for_event,
            })

        # ── 6. Mark complete ────────────────────────────────────────────────
        async with SessionFactory() as db:
            await db.execute(
                update(Simulation)
                .where(Simulation.id == sim_uuid)
                .values(
                    status="complete",
                    final_win_rate=final_win_rate,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        _publish({
            "type": "simulation_complete",
            "simulation_id": simulation_id,
            "final_win_rate": final_win_rate / 100.0,
            "rounds_completed": num_rounds,
        })
        return {"status": "complete", "final_win_rate": final_win_rate}

    except Exception as exc:
        logger.exception("Simulation %s failed: %s", simulation_id, exc)
        try:
            async with SessionFactory() as db:
                await db.execute(
                    update(Simulation)
                    .where(Simulation.id == sim_uuid)
                    .values(
                        status="failed",
                        error_message=str(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
        except Exception:
            pass
        _publish({
            "type": "simulation_error",
            "simulation_id": simulation_id,
            "error": str(exc),
        })
        raise

    finally:
        await engine.dispose()
        try:
            r.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _deck_text_to_card_defs(
    deck_text: str,
    SessionFactory: async_sessionmaker,
) -> list:
    """Convert deck text to ``list[CardDefinition]`` (with duplicates for count).

    Accepts both TCGdex format (e.g. ``4 sv06-130``) and PTCGL export format
    (e.g. ``4 Dreepy PRE 71``).  For PTCGL format, unknown cards are fetched
    on-demand from TCGDex and persisted to the DB before the simulation runs.

    Raises ``ValueError`` if:
      - A PTCGL card's set abbreviation is not in SET_CODE_MAP
      - A PTCGL card is not found in TCGDex (404 or network error)
    """
    if not deck_text.strip():
        return []

    from app.cards.loader import CardListLoader, SET_CODE_MAP
    from app.cards.models import CardDefinition
    from app.cards.tcgdex import TCGDexClient
    from app.db.models import Card
    from app.memory.postgres import MatchMemoryWriter

    # ── 1. Try TCGdex format (existing path: last token contains a hyphen) ───
    tcgdex_entries = _parse_deck_text(deck_text)
    if tcgdex_entries:
        tcgdex_ids = [tid for _, tid in tcgdex_entries]
        async with SessionFactory() as db:
            result = await db.execute(
                select(Card).where(Card.tcgdex_id.in_(tcgdex_ids))
            )
            card_rows = {row.tcgdex_id: row for row in result.scalars().all()}

        defs: list[CardDefinition] = []
        for count, tcgdex_id in tcgdex_entries:
            if tcgdex_id in card_rows:
                row = card_rows[tcgdex_id]
                card_def = CardDefinition(
                    tcgdex_id=row.tcgdex_id,
                    name=row.name,
                    set_abbrev=row.set_abbrev,
                    set_number=row.set_number,
                    category=row.category or "",
                    subcategory=row.subcategory or "",
                    hp=row.hp,
                    types=row.types or [],
                    evolve_from=row.evolve_from,
                    stage=row.stage or "",
                    retreat_cost=row.retreat_cost or 0,
                    regulation_mark=row.regulation_mark,
                    rarity=row.rarity,
                    image_url=row.image_url,
                )
            else:
                parts = tcgdex_id.rsplit("-", 1)
                card_def = CardDefinition(
                    tcgdex_id=tcgdex_id,
                    name=tcgdex_id,
                    set_abbrev=parts[0] if len(parts) == 2 else "",
                    set_number=parts[1] if len(parts) == 2 else "",
                )
            defs.extend([card_def] * count)
        return defs

    # ── 2. Try PTCGL export format ────────────────────────────────────────────
    ptcgl_entries = _parse_ptcgl_deck_text(deck_text)
    if not ptcgl_entries:
        return []

    # ── 2a. Batch DB lookup by (set_abbrev, normalised set_number) ────────────
    abbrevs = list({e["set_abbrev"] for e in ptcgl_entries})
    async with SessionFactory() as db:
        result = await db.execute(
            select(Card).where(Card.set_abbrev.in_(abbrevs))
        )
        db_cards: dict[tuple[str, str], Card] = {}
        for row in result.scalars().all():
            norm = str(int(row.set_number)) if (row.set_number and row.set_number.isdigit()) else (row.set_number or "")
            db_cards[(row.set_abbrev, norm)] = row

    # ── 2b. On-demand TCGDex fetch for DB misses ──────────────────────────────
    loader = CardListLoader()
    writer = MatchMemoryWriter()
    fresh_defs: dict[tuple[str, str], CardDefinition] = {}

    async with TCGDexClient() as tcgdex:
        for entry in ptcgl_entries:
            abbrev = entry["set_abbrev"]
            number = entry["set_number"]
            norm = str(int(number)) if number.isdigit() else number
            key = (abbrev, norm)

            if key in db_cards or key in fresh_defs:
                continue

            set_id = SET_CODE_MAP.get(abbrev)
            if set_id is None:
                raise ValueError(
                    f"Unknown set abbreviation '{abbrev}' for card "
                    f"'{entry['name']} {abbrev} {number}'. "
                    f"Add it to SET_CODE_MAP in loader.py."
                )

            try:
                raw = await tcgdex.get_card(set_id, number)
            except Exception as exc:
                raise ValueError(
                    f"Card not found in TCGDex: {entry['name']} {abbrev} {number} "
                    f"(tried {set_id}-{str(number).zfill(3)}). Error: {exc}"
                ) from exc

            card_def = loader._transform(
                raw,
                {"name": entry["name"], "set_abbrev": abbrev, "number": number},
            )
            fresh_defs[key] = card_def
            logger.info("Fetched new card from TCGDex: %s (%s)", card_def.name, card_def.tcgdex_id)

    # ── 2c. Upsert fresh cards to DB ──────────────────────────────────────────
    if fresh_defs:
        async with SessionFactory() as db:
            await writer.ensure_cards(list(fresh_defs.values()), db)
            await db.commit()
            new_ids = [c.tcgdex_id for c in fresh_defs.values()]
            result = await db.execute(select(Card).where(Card.tcgdex_id.in_(new_ids)))
            for row in result.scalars().all():
                norm = str(int(row.set_number)) if (row.set_number and row.set_number.isdigit()) else (row.set_number or "")
                db_cards[(row.set_abbrev, norm)] = row

    # ── 2d. Build CardDefinition list ─────────────────────────────────────────
    defs_ptcgl: list[CardDefinition] = []
    for entry in ptcgl_entries:
        abbrev = entry["set_abbrev"]
        number = entry["set_number"]
        count = entry["count"]
        norm = str(int(number)) if number.isdigit() else number
        key = (abbrev, norm)

        row = db_cards.get(key)
        if row is not None:
            card_def = CardDefinition(
                tcgdex_id=row.tcgdex_id,
                name=row.name,
                set_abbrev=row.set_abbrev,
                set_number=row.set_number,
                category=row.category or "",
                subcategory=row.subcategory or "",
                hp=row.hp,
                types=row.types or [],
                evolve_from=row.evolve_from,
                stage=row.stage or "",
                retreat_cost=row.retreat_cost or 0,
                regulation_mark=row.regulation_mark,
                rarity=row.rarity,
                image_url=row.image_url,
            )
        else:
            card_def = fresh_defs.get(key)
            if card_def is None:
                raise ValueError(
                    f"Card not found after fetch: {entry['name']} {abbrev} {number}"
                )

        defs_ptcgl.extend([card_def] * count)

    return defs_ptcgl


def _apply_mutations(
    current_deck: list,
    current_deck_text: str,
    mutations: list[dict],
) -> tuple[list, str]:
    """Apply analyst mutations to the in-memory deck and return updated (deck, deck_text)."""
    from app.cards.models import CardDefinition

    new_deck = list(current_deck)
    for mutation in mutations:
        remove_id = mutation.get("card_removed")
        add_id = mutation.get("card_added")
        if not remove_id or not add_id:
            continue
        for i, card in enumerate(new_deck):
            if card.tcgdex_id == remove_id:
                new_deck.pop(i)
                break
        parts = add_id.rsplit("-", 1)
        new_card = CardDefinition(
            tcgdex_id=add_id,
            name=add_id,
            set_abbrev=parts[0] if len(parts) == 2 else "",
            set_number=parts[1] if len(parts) == 2 else "",
        )
        new_deck.append(new_card)

    counts: dict[str, tuple[str, int]] = {}
    for card in new_deck:
        if card.tcgdex_id in counts:
            name, cnt = counts[card.tcgdex_id]
            counts[card.tcgdex_id] = (name, cnt + 1)
        else:
            counts[card.tcgdex_id] = (card.name, 1)

    new_deck_text = "\n".join(
        f"{cnt} {name} {tid}" for tid, (name, cnt) in sorted(counts.items())
    )
    return new_deck, new_deck_text


def _get_player_classes(game_mode: str) -> tuple:
    """Return (P1PlayerClass, P2PlayerClass) for the given game mode."""
    from app.players.heuristic import HeuristicPlayer

    if game_mode == "ai_h":
        try:
            from app.players.ai_player import AIPlayer
            return (AIPlayer, HeuristicPlayer)
        except ImportError:
            pass
    elif game_mode == "ai_ai":
        try:
            from app.players.ai_player import AIPlayer
            return (AIPlayer, AIPlayer)
        except ImportError:
            pass
    return (HeuristicPlayer, HeuristicPlayer)
