import type { DeckMutation } from '../../types/simulation';

interface Props {
  mutations: DeckMutation[];
  numRounds: number;
}

function WrBadge({ value }: { value: number | null }) {
  if (value == null) return <span className="text-slate-500">—</span>;
  return <span className="tabular-nums">{Math.round(value * 100)}%</span>;
}

function DeltaBadge({ before, after }: { before: number | null; after: number | null }) {
  if (before == null || after == null) return null;
  const delta = Math.round((after - before) * 100);
  const cls = delta > 0 ? 'text-green-400' : delta < 0 ? 'text-red-400' : 'text-slate-400';
  return (
    <span className={`${cls} text-xs`}>
      {delta > 0 ? '+' : ''}{delta}%
    </span>
  );
}

export default function DeckChangesTile({ mutations, numRounds }: Props) {
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Deck Changes</h3>
        <span className="text-xs text-slate-500">{mutations.length} swap{mutations.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto max-h-64">
        {mutations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-500 text-sm gap-1">
            <span className="text-2xl">🃏</span>
            <span>No deck swaps yet</span>
            {numRounds > 0 && (
              <span className="text-xs text-slate-600">
                Swaps appear after each round if win rate is below target
              </span>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-slate-200/50 dark:divide-slate-700/50">
            {mutations.map((m, i) => (
              <li key={i} className="px-4 py-2.5 flex items-start gap-3 text-xs">
                {/* Round badge */}
                <span className="mt-0.5 shrink-0 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded px-1.5 py-0.5 font-mono text-[11px]">
                  R{m.round}
                </span>

                {/* Swap description */}
                <div className="flex-1 min-w-0">
                  {m.card_out && (
                    <p className="text-red-400 truncate">
                      <span className="opacity-60">−</span> {m.card_out}
                    </p>
                  )}
                  {m.card_in && (
                    <p className="text-green-400 truncate">
                      <span className="opacity-60">+</span> {m.card_in}
                    </p>
                  )}
                  {!m.card_in && !m.card_out && (
                    <p className="text-slate-500 italic">deck mutation</p>
                  )}
                </div>

                {/* Win-rate delta */}
                <div className="shrink-0 text-right space-y-0.5">
                  <p className="text-slate-400">
                    <WrBadge value={m.win_rate_before} />
                    {' → '}
                    <WrBadge value={m.win_rate_after} />
                  </p>
                  <DeltaBadge before={m.win_rate_before} after={m.win_rate_after} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
