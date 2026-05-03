import { useEffect, useRef, useState } from 'react';
import { getSimulationDecisions } from '../../api/simulations';
import type { DecisionRow, NormalisedEvent } from '../../types/simulation';

interface Props {
  simulationId: string;
  event: NormalisedEvent | null;
  isAiMode: boolean;
  onClose: () => void;
}

const SKIP_KEYS = new Set(['event_type', 'active_player', 'phase']);

// Map engine event_type strings (lowercase) to Decision action_type enum names (UPPERCASE).
// Engine events that don't correspond to AI decisions are left unmapped (return undefined).
const EVENT_TO_ACTION: Record<string, string> = {
  attack: 'ATTACK',
  attack_declared: 'ATTACK',
  attack_damage: 'ATTACK',
  attack_no_damage: 'ATTACK',
  energy_attached: 'ATTACH_ENERGY',
  attach_energy: 'ATTACH_ENERGY',
  play_item: 'PLAY_ITEM',
  play_supporter: 'PLAY_SUPPORTER',
  play_basic: 'PLAY_BASIC',
  play_stadium: 'PLAY_STADIUM',
  evolve: 'EVOLVE',
  pass: 'PASS',
  end_turn: 'END_TURN',
  retreat: 'RETREAT',
  switch_active: 'SWITCH_ACTIVE',
  use_ability: 'USE_ABILITY',
};

function toActionType(eventType: string | undefined): string | undefined {
  if (!eventType) return undefined;
  return EVENT_TO_ACTION[eventType.toLowerCase()] ?? eventType.toUpperCase();
}

function DataRow({ k, v }: { k: string; v: unknown }) {
  if (v == null || v === '') return null;
  return (
    <div className="flex gap-2 py-0.5">
      <span className="text-slate-500 shrink-0 w-32 truncate">{k}</span>
      <span className="text-slate-100 font-mono text-xs break-all">{String(v)}</span>
    </div>
  );
}

export default function EventDetail({ simulationId, event, isAiMode, onClose }: Props) {
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Fetch matching AI decisions when event changes
  useEffect(() => {
    setDecisions([]);
    if (!event || !isAiMode || !event.match_id || event.turn == null) return;
    const matchId = event.match_id;
    const turn = event.turn as number;
    const player = event.player ?? undefined;
    // Map the engine event_type (lowercase) to the Decision action_type (UPPERCASE enum name).
    const actionType = toActionType(event.eventType);

    let cancelled = false;
    setLoading(true);
    getSimulationDecisions(simulationId, {
      match_id: matchId,
      turn_number: turn,
      player_id: player,
      action_type: actionType,
      limit: 3,
    })
      .then((r) => { if (!cancelled) setDecisions(r.decisions); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [simulationId, event, isAiMode]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  if (!event) return null;

  const et   = event.eventType ?? event.type ?? '';
  const turn = event.turn != null ? `T${event.turn}` : '';
  const who  = event.player ? ` [${event.player}]` : '';

  const dataEntries = Object.entries(event.data ?? {}).filter(
    ([k]) => !SKIP_KEYS.has(k)
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Panel */}
      <div
        ref={panelRef}
        className="relative z-10 w-full max-w-md bg-slate-900 border border-slate-700 rounded-xl
                   shadow-2xl flex flex-col max-h-[80vh] overflow-hidden"
        data-testid="event-detail-overlay"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <div>
            <span className="font-mono text-sm text-slate-200 font-semibold">{et}</span>
            {(turn || who) && (
              <span className="text-slate-500 text-xs ml-2 font-mono">{turn}{who}</span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-200 text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Event data */}
          {dataEntries.length > 0 && (
            <section>
              <h3 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Event Data</h3>
              <div className="text-xs space-y-0.5">
                {dataEntries.map(([k, v]) => (
                  <DataRow key={k} k={k} v={v} />
                ))}
              </div>
            </section>
          )}

          {/* AI Reasoning */}
          {isAiMode && (
            <section data-testid="event-detail-ai-reasoning">
              <h3 className="text-xs text-slate-500 uppercase tracking-wider mb-1">AI Reasoning</h3>
              {loading && (
                <p className="text-xs text-slate-600 italic">Loading…</p>
              )}
              {!loading && decisions.length === 0 && (
                <p className="text-xs text-slate-600 italic">
                  No AI decision recorded for this event.
                </p>
              )}
              {decisions.map((d) => (
                <div key={d.id} className="bg-slate-800/60 rounded-lg p-3 mb-2 space-y-2" data-testid="event-detail-reasoning-block">
                  <div className="flex gap-2 flex-wrap">
                    <span className="text-xs text-orange-400 font-semibold">{d.action_type}</span>
                    {d.card_played && (
                      <span className="text-xs text-slate-300">{d.card_played}</span>
                    )}
                    {d.target && (
                      <span className="text-xs text-slate-500">→ {d.target}</span>
                    )}
                  </div>
                  {d.reasoning && (
                    <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
                      {d.reasoning}
                    </p>
                  )}
                  {d.game_state_summary && (
                    <p className="text-xs text-slate-500 italic">
                      {d.game_state_summary}
                    </p>
                  )}
                </div>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
