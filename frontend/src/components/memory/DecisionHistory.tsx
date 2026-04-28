import { useEffect, useState } from 'react';
import { getCardDecisions } from '../../api/memory';
import type { MemoryDecisionRow } from '../../types/memory';

interface Props {
  cardId: string;
}

const PAGE_SIZE = 20;

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function DecisionHistory({ cardId }: Props) {
  const [rows, setRows] = useState<MemoryDecisionRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setRows([]);
    setOffset(0);
    setTotal(0);
  }, [cardId]);

  useEffect(() => {
    if (!cardId) return;
    setLoading(true);
    getCardDecisions(cardId, { limit: PAGE_SIZE, offset })
      .then(resp => {
        setRows(prev => offset === 0 ? resp.decisions : [...prev, ...resp.decisions]);
        setTotal(resp.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [cardId, offset]);

  const hasMore = rows.length < total;

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl p-5">
      <h3 className="text-slate-900 dark:text-white font-semibold mb-4">Decision History</h3>

      {rows.length === 0 && !loading && (
        <p className="text-slate-500 text-sm">No decisions recorded for this card.</p>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-xs uppercase">
                <th className="text-left pb-2 pr-4">Turn</th>
                <th className="text-left pb-2 pr-4">Action</th>
                <th className="text-left pb-2 pr-4">Reasoning</th>
                <th className="text-left pb-2">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {rows.map(d => (
                <tr key={d.id} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/50">
                  <td className="py-2 pr-4 text-slate-500 dark:text-slate-400">{d.turn_number}</td>
                  <td className="py-2 pr-4">
                    <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-xs">
                      {d.action_type}
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-slate-500 dark:text-slate-300 max-w-xs truncate" title={d.reasoning ?? undefined}>
                    {d.reasoning ? d.reasoning.slice(0, 80) + (d.reasoning.length > 80 ? '\u2026' : '') : '\u2014'}
                  </td>
                  <td className="py-2 text-slate-500 text-xs whitespace-nowrap">{fmtDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading && <p className="text-slate-500 text-sm mt-3">Loading...</p>}

      {hasMore && !loading && (
        <button
          onClick={() => setOffset(rows.length)}
          className="mt-4 px-4 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm"
        >
          Load more ({total - rows.length} remaining)
        </button>
      )}
    </div>
  );
}
