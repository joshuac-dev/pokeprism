import { useEffect, useState } from 'react';
import { getSimulationDecisions } from '../../api/simulations';
import type { DecisionRow } from '../../types/simulation';

interface Props {
  simulationId: string;
  open: boolean;
  onClose: () => void;
}

const ACTION_COLOR: Record<string, string> = {
  attack: 'text-orange-400',
  bench:  'text-blue-400',
  energy: 'text-yellow-400',
  retreat: 'text-slate-400',
  trainer: 'text-purple-400',
};

function ActionBadge({ type }: { type: string }) {
  const key = Object.keys(ACTION_COLOR).find((k) => type.toLowerCase().includes(k)) ?? '';
  const cls = ACTION_COLOR[key] ?? 'text-slate-300';
  return (
    <span className={`${cls} font-mono text-xs uppercase px-1.5 py-0.5 bg-slate-100 dark:bg-slate-900 rounded`}>
      {type}
    </span>
  );
}

export default function DecisionDetail({ simulationId, open, onClose }: Props) {
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const limit = 50;

  useEffect(() => {
    if (!open) return;
    setDecisions([]);
    setOffset(0);
    fetchPage(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, simulationId]);

  const fetchPage = async (off: number) => {
    setLoading(true);
    try {
      const resp = await getSimulationDecisions(simulationId, { limit, offset: off });
      setDecisions((prev) => off === 0 ? resp.decisions : [...prev, ...resp.decisions]);
      setTotal(resp.total);
    } finally {
      setLoading(false);
    }
  };

  const loadMore = () => {
    const next = offset + limit;
    setOffset(next);
    fetchPage(next);
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full max-w-lg bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
          <div>
            <h2 className="text-slate-900 dark:text-slate-100 font-semibold">AI Decisions</h2>
            <p className="text-xs text-slate-500">{total} total decisions</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 transition-colors text-xl leading-none"
          >
            ✕
          </button>
        </div>

        {/* Decision list */}
        <div className="flex-1 overflow-y-auto">
          {decisions.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
              <span className="text-3xl">🤖</span>
              <p className="text-sm">No AI decisions recorded.</p>
              <p className="text-xs text-slate-600">Only ai_h and ai_ai modes generate decisions.</p>
            </div>
          )}

          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {decisions.map((d) => (
              <li key={d.id} className="px-4 py-3 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-slate-500 font-mono">T{d.turn_number}</span>
                  <span className="text-xs text-slate-500">{d.player_id}</span>
                  <ActionBadge type={d.action_type} />
                  {d.card_played && (
                    <span className="text-xs text-slate-700 dark:text-slate-300 font-mono truncate max-w-[160px]">
                      {d.card_played}
                    </span>
                  )}
                  {d.legal_action_count != null && (
                    <span className="text-xs text-slate-600 ml-auto">
                      {d.legal_action_count} legal actions
                    </span>
                  )}
                </div>

                {d.reasoning && (
                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">
                    {d.reasoning}
                  </p>
                )}

                {d.game_state_summary && (
                  <p className="text-xs text-slate-600 font-mono truncate">
                    {d.game_state_summary}
                  </p>
                )}
              </li>
            ))}
          </ul>

          {/* Load more */}
          {decisions.length < total && (
            <div className="px-4 py-4">
              <button
                onClick={loadMore}
                disabled={loading}
                className="w-full py-2 text-sm text-blue-400 border border-slate-200 dark:border-slate-700 rounded
                           hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
              >
                {loading ? 'Loading…' : `Load more (${total - decisions.length} remaining)`}
              </button>
            </div>
          )}

          {loading && decisions.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
