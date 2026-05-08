#!/usr/bin/env python3
"""Read-only low-confidence audit for observed-play parsed events.

Queries the live DB for events below a confidence threshold and groups
recurring patterns to identify parser improvement candidates.

Usage (inside backend container):
    python scripts/observed_play_low_confidence_audit.py --threshold 0.80 --top 200
    python scripts/observed_play_low_confidence_audit.py --threshold 0.80 --top 200 --output tmp/audit.md

Output containing raw battle-log lines MUST NOT be committed to the repo.
If --output is used, write to a gitignored path (e.g. tmp/).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_PLAYER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]{2,}\b")

_NORMALISE_SUBS: list[tuple[re.Pattern[str], str]] = [
    # Numbers → <N>
    (re.compile(r"\b\d+\b"), "<N>"),
    # heads / tails → <COIN>
    (re.compile(r"\b(heads|tails)\b", re.IGNORECASE), "<COIN>"),
    # Special conditions → <CONDITION>
    (re.compile(r"\b(Burned|Poisoned|Paralyzed|Confused|Asleep)\b", re.IGNORECASE), "<CONDITION>"),
    # Bullet list items "• CARD" → <CARD_LIST>
    (re.compile(r"•\s*.+"), "<CARD_LIST>"),
    # Possessive card references → <CARD>  (after player, apostrophe, then card)
    (re.compile(r"[\u2019']s .+? (was|used|evolved|retreated|is)"), r"'s <CARD> \1"),
    # Energy type words
    (re.compile(r"\b(Fire|Water|Grass|Lightning|Psychic|Fighting|Darkness|Metal|Dragon|Fairy|Colorless)\b"), "<TYPE>"),
]


def normalise(raw_line: str) -> str:
    """Return a normalised version of *raw_line* for pattern grouping."""
    s = raw_line.strip()
    for pat, repl in _NORMALISE_SUBS:
        s = pat.sub(repl, s)
    return s


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

async def run_audit(threshold: float, top_n: int, output_path: str | None) -> None:
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)

    async with AsyncSessionLocal() as session:
        # ── Totals ─────────────────────────────────────────────────────────
        r = await session.execute(text("SELECT COUNT(*) FROM observed_play_logs"))
        total_logs: int = r.scalar()  # type: ignore[assignment]

        r = await session.execute(text("SELECT COUNT(*) FROM observed_play_events"))
        total_events: int = r.scalar()  # type: ignore[assignment]

        r = await session.execute(text(
            "SELECT COUNT(*) FROM observed_play_events WHERE confidence_score < :t"
        ), {"t": threshold})
        below_threshold: int = r.scalar()  # type: ignore[assignment]

        r = await session.execute(text(
            "SELECT COUNT(*) FROM observed_play_events WHERE event_type = 'unknown'"
        ))
        unknown_count: int = r.scalar()  # type: ignore[assignment]

        avg_conf_r = await session.execute(text(
            "SELECT AVG(confidence_score) FROM observed_play_events"
        ))
        avg_conf: float = avg_conf_r.scalar() or 0.0

        emit("# Observed-Play Low-Confidence Audit")
        emit()
        emit("## Overview")
        emit(f"- Total logs:                {total_logs}")
        emit(f"- Total events:              {total_events}")
        emit(f"- Events below {threshold:.0%}:        {below_threshold}  ({below_threshold/total_events:.1%} of total)")
        emit(f"- Unknown events:            {unknown_count}")
        emit(f"- Average corpus confidence: {avg_conf:.4f}")
        emit()

        # ── By event type ──────────────────────────────────────────────────
        r = await session.execute(text("""
            SELECT event_type, COUNT(*) AS cnt,
                   AVG(confidence_score) AS avg_conf,
                   MIN(confidence_score) AS min_conf
            FROM observed_play_events
            WHERE confidence_score < :t
            GROUP BY event_type
            ORDER BY cnt DESC
        """), {"t": threshold})
        rows = r.fetchall()

        emit("## Low-Confidence Events by Event Type")
        if rows:
            for row in rows:
                emit(f"  {row[0]:40s}  count={row[1]:5d}  avg={row[2]:.3f}  min={row[3]:.3f}")
        else:
            emit("  (none)")
        emit()

        # ── By raw line ────────────────────────────────────────────────────
        r = await session.execute(text("""
            SELECT raw_line, COUNT(*) AS cnt,
                   MIN(confidence_score) AS min_conf,
                   MIN(event_type) AS et
            FROM observed_play_events
            WHERE confidence_score < :t
            GROUP BY raw_line
            ORDER BY cnt DESC, min_conf ASC
            LIMIT :n
        """), {"t": threshold, "n": top_n})
        raw_rows = r.fetchall()

        emit(f"## Top {top_n} Low-Confidence Raw Lines (grouped)")
        for row in raw_rows:
            snippet = row[0][:120]
            emit(f"  [{row[1]}x, {row[2]:.2f}, {row[3]}] {snippet!r}")
        emit()

        # ── Normalised groups ──────────────────────────────────────────────
        norm_counter: Counter[str] = Counter()
        norm_examples: defaultdict[str, list[str]] = defaultdict(list)
        for row in raw_rows:
            key = normalise(row[0])
            norm_counter[key] += row[1]
            if len(norm_examples[key]) < 3:
                norm_examples[key].append(row[0][:100])

        emit("## Normalised Pattern Groups (top by count)")
        for norm, cnt in norm_counter.most_common(40):
            emit(f"  [{cnt}x] {norm}")
            for ex in norm_examples[norm][:2]:
                emit(f"         e.g. {ex!r}")
        emit()

        # ── Per-log summary ────────────────────────────────────────────────
        r = await session.execute(text("""
            SELECT l.original_filename,
                   l.confidence_score AS log_conf,
                   COUNT(e.id) AS total_ev,
                   SUM(CASE WHEN e.confidence_score < :t THEN 1 ELSE 0 END) AS low_ev,
                   SUM(CASE WHEN e.event_type = 'unknown' THEN 1 ELSE 0 END) AS unk_ev
            FROM observed_play_logs l
            JOIN observed_play_events e ON e.observed_play_log_id = l.id
            GROUP BY l.id, l.original_filename, l.confidence_score
            ORDER BY low_ev DESC, log_conf ASC
        """), {"t": threshold})
        log_rows = r.fetchall()

        emit("## Per-Log Summary (sorted by low-confidence count)")
        emit(f"  {'filename':<50s}  {'log_conf':>8}  {'events':>6}  {'low':>5}  {'unknown':>7}")
        emit(f"  {'-'*50}  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*7}")
        for row in log_rows:
            fname = (row[0] or "?")[:50]
            emit(f"  {fname:<50s}  {row[1] or 0:8.4f}  {row[2]:6d}  {row[3]:5d}  {row[4]:7d}")
        emit()

        # ── Candidate triage ───────────────────────────────────────────────
        emit("## Candidate Pattern Triage")
        emit("(Manual review required — decide: implement / confidence-only / leave / ignore)")
        emit()
        for norm, cnt in norm_counter.most_common(20):
            emit(f"  [{cnt}x] {norm}")
        emit()

    result = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(result, encoding="utf-8")
        print(f"Report written to {output_path}")
    else:
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Observed-play low-confidence corpus audit.")
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="Confidence threshold (default: 0.80)")
    parser.add_argument("--top", type=int, default=100,
                        help="Max distinct raw lines to show (default: 100)")
    parser.add_argument("--output", type=str, default=None,
                        help="Write report to this path (must be gitignored, e.g. tmp/audit.md)")
    args = parser.parse_args()
    asyncio.run(run_audit(args.threshold, args.top, args.output))


if __name__ == "__main__":
    main()
