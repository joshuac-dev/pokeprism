import { useEffect, useState } from 'react';
import type { SimulationRow, CompareStats } from '../../types/history';
import { getCompareStats } from '../../api/history';
import ModeBadge from './ModeBadge';

interface Props {
  sims: SimulationRow[];
  onClose: () => void;
}

const METRICS: { key: keyof CompareStats; label: string; format: (v: unknown) => string }[] = [
  { key: 'deck_name',       label: 'Deck Name',       format: v => (v as string | null) ?? '—' },
  { key: 'game_mode',       label: 'Mode',             format: v => (v as string) },
  { key: 'rounds_completed',label: 'Rounds',           format: v => String(v) },
  { key: 'total_matches',   label: 'Total Matches',    format: v => String(v) },
  { key: 'final_win_rate',  label: 'Win Rate',         format: v => v != null ? `${((v as number) * 100).toFixed(1)}%` : '—' },
  { key: 'target_win_rate', label: 'Target Win Rate',  format: v => v != null ? `${((v as number) * 100).toFixed(0)}%` : '—' },
  { key: 'target_met',      label: 'Target Met?',      format: v => v ? '✅' : '❌' },
  { key: 'avg_turns',       label: 'Avg Turns',        format: v => v != null ? String(v as number) : '—' },
  { key: 'deck_out_pct',    label: 'Deck-out %',       format: v => v != null ? `${((v as number) * 100).toFixed(1)}%` : '—' },
];

export default function CompareModal({ sims, onClose }: Props) {
  const [stats, setStats] = useState<(CompareStats | null)[]>(sims.map(() => null));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all(sims.map(s => getCompareStats(s.id)))
      .then(results => {
        setStats(results);
        setLoading(false);
      })
      .catch(err => {
        setError(err?.message ?? 'Failed to load comparison data.');
        setLoading(false);
      });
  }, [sims]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl w-full max-w-3xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Compare Simulations</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-900 dark:hover:text-white text-xl leading-none"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-x-auto">
          {loading && (
            <p className="text-slate-400 text-sm">Loading comparison data…</p>
          )}
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}
          {!loading && !error && (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left text-slate-500 dark:text-slate-400 font-medium py-2 pr-4 min-w-[140px]">Metric</th>
                  {sims.map((s, i) => (
                    <th key={s.id} className="text-left text-slate-900 dark:text-white font-semibold py-2 pr-4">
                      <div className="flex flex-col gap-1">
                        <span>{s.user_deck_name ?? `Sim ${i + 1}`}</span>
                        <ModeBadge mode={s.game_mode} />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {METRICS.map(metric => (
                  <tr key={metric.key} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="text-slate-500 dark:text-slate-400 py-2 pr-4">{metric.label}</td>
                    {stats.map((s, i) => (
                      <td key={i} className="text-slate-900 dark:text-white py-2 pr-4">
                        {s ? metric.format(s[metric.key]) : '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 pb-5 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-900 dark:text-white text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
