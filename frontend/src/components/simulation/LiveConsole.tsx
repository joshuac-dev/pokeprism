import { useEffect, useLayoutEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import type { NormalisedEvent } from '../../types/simulation';

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

const RESET  = '\x1b[0m';
const DIM    = '\x1b[2m';
const CYAN   = '\x1b[36m';
const BCYAN  = '\x1b[1;36m';
const WHITE  = '\x1b[37m';
const BGREEN = '\x1b[1;32m';
const YELLOW = '\x1b[33m';
const BYELLOW= '\x1b[1;33m';
const BLUE   = '\x1b[34m';
const BRED   = '\x1b[1;31m';

function fmt(ev: NormalisedEvent): string {
  const t = ev.type ?? '';
  const et = ev.eventType ?? '';

  // Top-level lifecycle events
  if (t === 'round_start') {
    return `${BCYAN}━━━ Round ${ev.round_number ?? '?'} start ━━━${RESET}`;
  }
  if (t === 'round_end') {
    const wr = ev.data?.win_rate != null ? ` | win rate: ${Math.round((ev.data.win_rate as number) * 100)}%` : '';
    return `${BCYAN}━━━ Round ${ev.round_number ?? '?'} end${wr} ━━━${RESET}`;
  }
  if (t === 'match_start') {
    const p1 = ev.p1_deck_name ?? (ev.data?.p1 as string) ?? 'P1';
    const p2 = ev.p2_deck_name ?? (ev.data?.p2 as string) ?? 'P2';
    return `${CYAN}▶ Match start — ${p1} vs ${p2}${RESET}`;
  }
  if (t === 'match_end') {
    const winner = (ev.data?.winner as string) ?? '?';
    return `${DIM}■ Match end — winner: ${winner}${RESET}`;
  }
  if (t === 'deck_mutation') {
    const ci = (ev.data?.card_in as string) ?? '?';
    const co = (ev.data?.card_out as string) ?? '?';
    return `${BYELLOW}⟳ Deck swap: −${co} / +${ci}${RESET}`;
  }
  if (t === 'target_reached') {
    return `${BYELLOW}★ Target win rate reached!${RESET}`;
  }
  if (t === 'simulation_complete') {
    const wr = ev.data?.final_win_rate != null
      ? ` | final win rate: ${Math.round((ev.data.final_win_rate as number) * 100)}%`
      : '';
    return `${BGREEN}✓ Simulation complete${wr}${RESET}`;
  }
  if (t === 'simulation_cancelled') {
    return `${BYELLOW}⊘ Simulation cancelled${RESET}`;
  }
  if (t === 'simulation_error') {
    const msg = (ev.data?.error as string) ?? 'unknown error';
    return `${BRED}✗ Simulation error: ${msg}${RESET}`;
  }

  // match_event discriminated by event_type
  if (t === 'match_event') {
    const turn = ev.turn != null ? `T${ev.turn} ` : '';
    const who  = ev.player ? `[${ev.player}] ` : '';

    if (et === 'attack') {
      const name = (ev.data?.attack_name as string) ?? (ev.data?.move as string) ?? 'attack';
      const dmg  = ev.data?.damage != null ? ` (${ev.data.damage} dmg)` : '';
      return `${WHITE}${turn}${who}⚔ ${name}${dmg}${RESET}`;
    }
    if (et === 'ko') {
      const card = (ev.data?.card as string) ?? (ev.data?.target as string) ?? 'Pokémon';
      return `${BGREEN}${turn}${who}★ KO — ${card}${RESET}`;
    }
    if (et === 'prize_taken') {
      const cnt = (ev.data?.count as number) ?? 1;
      return `${YELLOW}${turn}${who}◆ Prize taken (${cnt})${RESET}`;
    }
    if (et === 'energy_attached') {
      const card = (ev.data?.card as string) ?? (ev.data?.energy as string) ?? 'energy';
      return `${BLUE}${turn}${who}⚡ Attach ${card}${RESET}`;
    }
    if (et === 'trainer_played') {
      const card = (ev.data?.card as string) ?? 'trainer';
      return `${WHITE}${turn}${who}▷ ${card}${RESET}`;
    }
    if (et === 'bench_played') {
      const card = (ev.data?.card as string) ?? 'Pokémon';
      return `${WHITE}${turn}${who}+ Bench ${card}${RESET}`;
    }
    if (et === 'retreat') {
      const from = (ev.data?.from as string) ?? '?';
      const to   = (ev.data?.to as string) ?? '?';
      return `${DIM}${turn}${who}↩ Retreat ${from} → ${to}${RESET}`;
    }
    // fallback for unknown match_event types
    return `${DIM}${turn}${who}${et}${RESET}`;
  }

  // Unknown top-level type
  return `${DIM}${t}${RESET}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  events: NormalisedEvent[];
  totalEvents: number;
  hasMore: boolean;
  onLoadEarlier?: () => Promise<void>;
}

export default function LiveConsole({ events, totalEvents, hasMore, onLoadEarlier }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef      = useRef<Terminal | null>(null);
  const fitRef       = useRef<FitAddon | null>(null);
  const writtenRef   = useRef(0);        // index of last written event in events[]
  const loadingEarlierRef = useRef(false);

  // Initialise xterm once
  useLayoutEffect(() => {
    if (!containerRef.current || termRef.current) return;

    const term = new Terminal({
      theme: {
        background: '#0f172a',  // slate-950
        foreground: '#cbd5e1',  // slate-300
        cursor:     '#3b82f6',  // blue-500
        selectionBackground: '#1e3a5f',
      },
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
      fontSize: 12,
      lineHeight: 1.4,
      scrollback: 10000,
      convertEol: true,
      cursorBlink: false,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current  = fit;

    term.writeln(`\x1b[1;34mPokéPrism live console ready\x1b[0m`);
    term.writeln(`\x1b[2m─────────────────────────────────────────\x1b[0m`);

    const ro = new ResizeObserver(() => fit.fit());
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      term.dispose();
      termRef.current = null;
      fitRef.current  = null;
      writtenRef.current = 0;
    };
  }, []);

  // Diff-write new events (only append new ones, never rewrite whole buffer)
  useEffect(() => {
    const term = termRef.current;
    if (!term) return;

    // If events shrank (prepend caused a reset), rewrite from start
    if (writtenRef.current > events.length) {
      writtenRef.current = 0;
      term.clear();
    }

    const toWrite = events.slice(writtenRef.current);
    for (const ev of toWrite) {
      term.writeln(fmt(ev));
    }
    writtenRef.current = events.length;
  }, [events]);

  const handleLoadEarlier = async () => {
    if (loadingEarlierRef.current || !onLoadEarlier) return;
    loadingEarlierRef.current = true;
    // Mark the terminal before reload
    termRef.current?.writeln(
      `\x1b[2m── Loading earlier events… ──\x1b[0m`
    );
    // Prepending resets writtenRef in the events effect above
    writtenRef.current = 0;
    await onLoadEarlier();
    loadingEarlierRef.current = false;
  };

  const showing = events.length;
  const hidden  = Math.max(0, totalEvents - showing);

  return (
    <div className="flex flex-col h-full bg-slate-950 rounded-lg border border-slate-800 overflow-hidden">
      {/* Load-earlier bar */}
      {hasMore && (
        <button
          onClick={handleLoadEarlier}
          className="w-full py-1.5 px-4 text-xs text-slate-400 hover:text-slate-100
                     bg-slate-900 border-b border-slate-800 hover:bg-slate-800
                     transition-colors text-left"
        >
          ↑ Load earlier events
          {hidden > 0 && (
            <span className="text-slate-600 ml-2">({hidden.toLocaleString()} not shown)</span>
          )}
        </button>
      )}

      {/* Terminal container */}
      <div ref={containerRef} className="flex-1 min-h-0 p-1" />

      {/* Footer */}
      <div className="px-3 py-1 text-xs text-slate-600 border-t border-slate-800 flex justify-between">
        <span>{showing.toLocaleString()} events shown</span>
        {totalEvents > 0 && <span>{totalEvents.toLocaleString()} total</span>}
      </div>
    </div>
  );
}
