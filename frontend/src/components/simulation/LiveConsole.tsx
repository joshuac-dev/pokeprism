import { useEffect, useRef } from 'react';
import type { NormalisedEvent } from '../../types/simulation';

// ---------------------------------------------------------------------------
// Line formatting — returns { text, cls } for DOM rendering
// ---------------------------------------------------------------------------

const WIN_COND_LABELS: Record<string, string> = {
  prizes:     'prizes',
  deck_out:   'deck-out',
  no_bench:   'no-bench',
  turn_limit: 'turn-limit',
};

interface FmtResult {
  text: string;
  /** Tailwind text-color class(es) */
  cls: string;
  /** When true, the event row is not rendered */
  skip?: boolean;
}

function fmt(ev: NormalisedEvent): FmtResult {
  const t  = ev.type ?? '';
  const et = ev.eventType ?? '';
  const turn = ev.turn != null ? `T${ev.turn} ` : '';
  const who  = ev.player ? `[${ev.player}] ` : '';

  // ── Top-level lifecycle ──────────────────────────────────────────────────
  if (t === 'round_start') {
    return { text: `━━━ Round ${ev.round_number ?? '?'} start ━━━`, cls: 'text-cyan-400 font-semibold' };
  }
  if (t === 'round_end') {
    const wr = ev.data?.win_rate != null
      ? ` | win rate: ${Math.round((ev.data.win_rate as number) * 100)}%`
      : '';
    return { text: `━━━ Round ${ev.round_number ?? '?'} end${wr} ━━━`, cls: 'text-cyan-400 font-semibold' };
  }
  if (t === 'match_start') {
    const n  = ev.data?.match_number as number | undefined;
    const p1 = ev.p1_deck_name ?? (ev.data?.p1_deck as string) ?? (ev.data?.p1 as string) ?? 'P1';
    const p2 = ev.p2_deck_name ?? (ev.data?.p2_deck as string) ?? (ev.data?.p2 as string) ?? 'P2';
    const label = n != null ? `Match ${n}` : 'Match';
    return { text: `╌╌╌ ${label}: ${p1} vs ${p2} ╌╌╌`, cls: 'text-cyan-300' };
  }
  if (t === 'match_end') {
    const n = ev.data?.match_number as number | undefined;
    return fmtMatchEnd(ev.data?.winner as string, ev.data?.condition as string, n);
  }
  if (t === 'deck_mutation') {
    const ci = (ev.data?.card_in  as string) ?? '?';
    const co = (ev.data?.card_out as string) ?? '?';
    return { text: `⟳ Deck swap: −${co} / +${ci}`, cls: 'text-yellow-400 font-semibold' };
  }
  if (t === 'deck_reverted') {
    const wr = ev.data?.reverted_to_win_rate != null ? ` (best was ${ev.data.reverted_to_win_rate}%)` : '';
    return { text: `⟲ Deck reverted to best-known state${wr}`, cls: 'text-orange-400 font-semibold' };
  }
  if (t === 'coach_skipped') {
    const reason = (ev.data?.reason as string) ?? 'consecutive regressions';
    return { text: `⊘ Coach skipped — ${reason}`, cls: 'text-yellow-600' };
  }
  if (t === 'target_reached') {
    const hits   = (ev.data?.consecutive_hits as number) ?? 1;
    const suffix = hits > 1 ? ` (${hits} consecutive)` : '';
    return { text: `★ Target win rate reached!${suffix}`, cls: 'text-yellow-300 font-semibold' };
  }
  if (t === 'simulation_complete') {
    const wr = ev.data?.final_win_rate != null
      ? ` | final win rate: ${Math.round((ev.data.final_win_rate as number) * 100)}%`
      : '';
    return { text: `✓ Simulation complete${wr}`, cls: 'text-green-400 font-semibold' };
  }
  if (t === 'simulation_cancelled') {
    return { text: '⊘ Simulation cancelled', cls: 'text-yellow-400' };
  }
  if (t === 'simulation_error') {
    const msg = (ev.data?.error as string) ?? 'unknown error';
    return { text: `✗ Simulation error: ${msg}`, cls: 'text-red-400 font-semibold' };
  }

  // ── match_event discriminated by event_type ──────────────────────────────
  if (t === 'match_event') {
    if (et === 'game_start') {
      const p1 = (ev.data?.p1_deck as string) ?? 'P1';
      const p2 = (ev.data?.p2_deck as string) ?? 'P2';
      return { text: `╌╌╌ Match start: ${p1} vs ${p2} ╌╌╌`, cls: 'text-cyan-300' };
    }
    if (et === 'game_over') {
      return fmtMatchEnd(ev.data?.winner as string, ev.data?.condition as string);
    }
    // attack_declared is redundant — attack_damage carries all the info
    if (et === 'attack_declared' || et === 'attack') {
      return { text: '', cls: '', skip: true };
    }
    if (et === 'attack_damage') {
      const dmg      = (ev.data?.final_damage as number) ?? (ev.data?.base_damage as number) ?? '?';
      const attacker = (ev.data?.attacker     as string) ?? '';
      const atkName  = ((ev.data?.attack_name  as string) ?? attacker) || 'attack';
      const atkLabel = attacker ? `${atkName} (${attacker})` : atkName;
      return { text: `${turn}${who}⚔ ${atkLabel} → ${dmg} dmg`, cls: 'text-white' };
    }
    if (et === 'attack_no_damage') {
      const attacker = (ev.data?.attacker    as string) ?? '';
      const atkName  = ((ev.data?.attack_name as string) ?? attacker) || 'attack';
      const atkLabel = attacker ? `${atkName} (${attacker})` : atkName;
      return { text: `${turn}${who}⚔ ${atkLabel} → no damage`, cls: 'text-slate-500' };
    }
    if (et === 'ko') {
      const card     = (ev.data?.card_name as string) || (ev.data?.card as string) || 'Pokémon';
      const attacker = (ev.data?.attacker  as string) ?? '';
      const byStr    = attacker ? ` (by ${attacker})` : '';
      return { text: `${turn}${who}★ KO — ${card}${byStr}`, cls: 'text-green-400 font-semibold' };
    }
    if (et === 'prizes_taken' || et === 'prize_taken') {
      const cnt = (ev.data?.count as number) ?? 1;
      const rem = ev.data?.remaining != null ? ` (${ev.data.remaining} left)` : '';
      return { text: `${turn}${who}◆ Prize ×${cnt}${rem}`, cls: 'text-yellow-400' };
    }
    if (et === 'energy_attached') {
      const card   = (ev.data?.card   as string) || (ev.data?.energy as string) || 'energy';
      const target = (ev.data?.target as string) ?? '';
      const tgt    = target ? ` → ${target}` : '';
      return { text: `${turn}${who}⚡ ${card}${tgt}`, cls: 'text-blue-400' };
    }
    if (et === 'play_basic' || et === 'bench_played') {
      const card = (ev.data?.card as string) || 'Pokémon';
      return { text: `${turn}${who}+ Bench ${card}`, cls: 'text-slate-300' };
    }
    if (et === 'play_supporter' || et === 'play_item' || et === 'trainer_played') {
      const card = (ev.data?.card as string) || 'card';
      return { text: `${turn}${who}▷ ${card}`, cls: 'text-slate-300' };
    }
    if (et === 'play_stadium' || et === 'stadium_played') {
      const card = (ev.data?.card as string) || 'Stadium';
      return { text: `${turn}${who}▷ ${card} (Stadium)`, cls: 'text-slate-300' };
    }
    if (et === 'play_tool' || et === 'tool_played') {
      const card   = (ev.data?.card   as string) || 'Tool';
      const target = (ev.data?.target as string) ?? '';
      const tgt    = target ? ` → ${target}` : '';
      return { text: `${turn}${who}▷ ${card} (Tool)${tgt}`, cls: 'text-slate-300' };
    }
    if (et === 'evolve' || et === 'rare_candy_evolve') {
      const from = (ev.data?.from_card as string) || (ev.data?.from as string) || '?';
      const to   = (ev.data?.to_card   as string) || (ev.data?.to   as string) || '?';
      return { text: `${turn}${who}↑ ${from} → ${to}`, cls: 'text-slate-300' };
    }
    if (et === 'retreat') {
      const from = (ev.data?.from_card as string) || (ev.data?.from as string) || '?';
      const to   = (ev.data?.to_card   as string) || (ev.data?.to   as string) || '?';
      return { text: `${turn}${who}↔ Retreat ${from} → ${to}`, cls: 'text-slate-500' };
    }
    if (et === 'switch_active') {
      const card = (ev.data?.card as string) || '?';
      return { text: `${turn}${who}↑ Promote: ${card}`, cls: 'text-slate-300' };
    }
    if (et === 'draw') {
      const count = (ev.data?.count as number) ?? 1;
      return { text: `${turn}${who}↓ Draw ×${count}`, cls: 'text-slate-500' };
    }
    // skip noise events
    if (et === 'turn_start' || et === 'prizes_set') {
      return { text: '', cls: '', skip: true };
    }
    if (et === 'pass') {
      return { text: `${turn}${who}· Pass`, cls: 'text-slate-500' };
    }
    if (et === 'end_turn') {
      return { text: `${turn}${who}· End turn`, cls: 'text-slate-500' };
    }
    // ai_decision events are hidden from the console but kept in the events array
    // so EventDetail can correlate them to the visible action events they precede.
    if (et === 'ai_decision') {
      return { text: '', cls: '', skip: true };
    }
    // fallback
    return { text: `${turn}${who}${et}`, cls: 'text-slate-600' };
  }

  // Unknown top-level
  return { text: t, cls: 'text-slate-600' };
}

function fmtMatchEnd(winner: string | undefined, cond: string | undefined, matchNum?: number): FmtResult {
  const raw = winner ?? '?';
  const winnerLabel = raw === 'p1' ? 'P1' : raw === 'p2' ? 'P2' : raw;
  const condLabel   = cond ? ` (${WIN_COND_LABELS[cond] ?? cond})` : '';
  const matchLabel  = matchNum != null ? `Match ${matchNum} ` : '';
  return { text: `═══ ${matchLabel}complete — ${winnerLabel} wins${condLabel} ═══`, cls: 'text-slate-400 font-semibold' };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  events: NormalisedEvent[];
  totalEvents: number;
  hasMore: boolean;
  onLoadEarlier?: () => Promise<void>;
  onEventClick?: (ev: NormalisedEvent) => void;
}

export default function LiveConsole({
  events,
  totalEvents,
  hasMore,
  onLoadEarlier,
  onEventClick,
}: Props) {
  const containerRef     = useRef<HTMLDivElement>(null);
  const bottomRef        = useRef<HTMLDivElement>(null);
  const autoScrollRef    = useRef(true);
  const prevLengthRef    = useRef(0);
  const loadingRef       = useRef(false);

  // Scroll to bottom when new events arrive (if user hasn't scrolled up)
  useEffect(() => {
    if (events.length > prevLengthRef.current) {
      prevLengthRef.current = events.length;
      if (autoScrollRef.current) {
        bottomRef.current?.scrollIntoView({ behavior: 'instant' });
      }
    }
  }, [events]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  const handleLoadEarlier = async () => {
    if (loadingRef.current || !onLoadEarlier) return;
    loadingRef.current = true;
    await onLoadEarlier();
    loadingRef.current = false;
  };

  const showing = events.length;
  const hidden  = Math.max(0, totalEvents - showing);

  return (
    <div
      className="flex flex-col h-full bg-slate-950 rounded-lg border border-slate-700 overflow-hidden"
      data-testid="live-console"
    >
      {/* Load-earlier bar */}
      {hasMore && (
        <button
          onClick={handleLoadEarlier}
          className="w-full py-1.5 px-4 text-xs text-slate-400 hover:text-slate-100
                     bg-slate-900 border-b border-slate-800 hover:bg-slate-800
                     transition-colors text-left shrink-0"
        >
          ↑ Load earlier events
          {hidden > 0 && (
            <span className="text-slate-600 ml-2">({hidden.toLocaleString()} not shown)</span>
          )}
        </button>
      )}

      {/* Event list */}
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto py-1"
        onScroll={handleScroll}
        style={{ fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace' }}
        data-testid="live-console-events"
      >
        {events.length === 0 && (
          <p className="text-slate-600 text-xs px-3 py-2">Waiting for events…</p>
        )}
        {events.map((ev, i) => {
          const { text, cls, skip } = fmt(ev);
          if (skip || !text) return null;
          return (
            <div
              key={ev.id ?? i}
              onClick={() => onEventClick?.(ev)}
              className={`px-3 py-px text-xs leading-5 whitespace-pre-wrap break-all select-text
                ${cls}
                ${onEventClick ? 'cursor-pointer hover:bg-slate-900 rounded' : ''}`}
              data-testid="live-console-event"
            >
              {text}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Footer */}
      <div className="px-3 py-1 text-xs text-slate-600 border-t border-slate-800 flex justify-between shrink-0">
        <span>{showing.toLocaleString()} events shown</span>
        {totalEvents > 0 && <span>{totalEvents.toLocaleString()} total</span>}
      </div>
    </div>
  );
}
