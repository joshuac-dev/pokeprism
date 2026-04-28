import type { MutationRow } from '../../types/dashboard';

interface Props {
  mutations: MutationRow[];
  numRounds: number;
}

type CellState = 'added' | 'removed' | 'both' | 'none';

function cellClass(state: CellState): string {
  switch (state) {
    case 'added': return 'bg-green-800 text-green-100';
    case 'removed': return 'bg-red-800 text-red-100';
    case 'both': return 'bg-yellow-800 text-yellow-100';
    default: return 'bg-transparent text-slate-600';
  }
}

function cellLabel(state: CellState): string {
  switch (state) {
    case 'added': return '+';
    case 'removed': return '−';
    case 'both': return '±';
    default: return '';
  }
}

export default function CardSwapHeatMap({ mutations, numRounds }: Props) {
  if (!mutations.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm text-center px-4">
        No deck mutations — either deck was locked or no rounds completed.
      </div>
    );
  }

  const roundNumbers = [...new Set(mutations.map((m) => m.round_number))].sort((a, b) => a - b);
  const cardNames = [
    ...new Set([
      ...mutations.map((m) => m.card_added),
      ...mutations.map((m) => m.card_removed),
    ].filter(Boolean)),
  ].sort();

  // map: (card, round) → CellState
  const cellMap = new Map<string, CellState>();
  for (const m of mutations) {
    const addKey = `${m.card_added}::${m.round_number}`;
    const remKey = `${m.card_removed}::${m.round_number}`;

    const prevAdd = cellMap.get(addKey);
    cellMap.set(addKey, prevAdd === 'removed' ? 'both' : 'added');

    const prevRem = cellMap.get(remKey);
    cellMap.set(remKey, prevRem === 'added' ? 'both' : 'removed');
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto">
        <table className="border-collapse text-xs min-w-max">
          <thead>
            <tr>
              <th className="text-slate-500 dark:text-slate-400 font-medium text-left px-2 py-1 border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 min-w-[200px]">
                Card
              </th>
              {roundNumbers.map((rn) => (
                <th
                  key={rn}
                  className="text-slate-500 dark:text-slate-400 font-medium px-2 py-1 border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-center"
                >
                  R{rn}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cardNames.map((card) => (
              <tr key={card}>
                <td
                  className="text-slate-700 dark:text-slate-300 px-2 py-1 border border-slate-200 dark:border-slate-700"
                  title={card}
                >
                  <span className="block whitespace-normal break-words max-w-[240px]">{card}</span>
                </td>
                {roundNumbers.map((rn) => {
                  const state: CellState = cellMap.get(`${card}::${rn}`) ?? 'none';
                  return (
                    <td
                      key={rn}
                      className={`px-2 py-1 border border-slate-200 dark:border-slate-700 text-center font-bold ${cellClass(state)}`}
                    >
                      {cellLabel(state)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-4 text-xs text-slate-400 flex-wrap">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded bg-green-800 inline-block" />
          Added (Coach swapped in)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded bg-red-800 inline-block" />
          Removed (Coach swapped out)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded bg-yellow-800 inline-block" />
          Both (added &amp; removed in same round)
        </span>
      </div>
      <p className="text-xs text-slate-600">Showing {numRounds} round(s)</p>
    </div>
  );
}
