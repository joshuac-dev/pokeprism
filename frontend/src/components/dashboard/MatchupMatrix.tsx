import type { MatchRow, RoundRow } from '../../types/dashboard';

interface Props {
  matches: MatchRow[];
  rounds: RoundRow[];
}

function cellColor(winRate: number): string {
  if (winRate > 0.6) return 'bg-green-800';
  if (winRate >= 0.4) return 'bg-yellow-800';
  return 'bg-red-800';
}

export default function MatchupMatrix({ matches, rounds }: Props) {
  if (!matches.length) {
    return (
      <div className="flex items-center justify-center h-48 text-app-text-subtle text-sm">
        No match data
      </div>
    );
  }

  const roundNumbers = [...new Set(rounds.map((r) => r.round_number))].sort((a, b) => a - b);
  const opponentNames = [
    ...new Set(matches.map((m) => m.p2_deck_name ?? 'Unknown')),
  ].sort();

  // Build a map: (round, opponent) → { wins, total }
  const statsMap = new Map<string, { wins: number; total: number }>();
  for (const m of matches) {
    const key = `${m.round_number}::${m.p2_deck_name ?? 'Unknown'}`;
    const cur = statsMap.get(key) ?? { wins: 0, total: 0 };
    statsMap.set(key, {
      wins: cur.wins + (m.winner === 'p1' ? 1 : 0),
      total: cur.total + 1,
    });
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-xs min-w-max">
        <thead>
          <tr>
            <th className="text-app-text-muted font-medium text-left px-2 py-1 border border-app-border bg-slate-50 dark:bg-slate-900">
              Round
            </th>
            {opponentNames.map((name) => (
              <th
                key={name}
                className="text-app-text-muted font-medium px-2 py-1 border border-app-border bg-slate-50 dark:bg-slate-900 max-w-[120px] truncate"
                title={name}
              >
                <span className="block max-w-[100px] truncate">{name}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roundNumbers.map((rn) => (
            <tr key={rn}>
              <td className="text-app-text-muted px-2 py-1 border border-app-border text-center font-mono">
                {rn}
              </td>
              {opponentNames.map((opp) => {
                const key = `${rn}::${opp}`;
                const s = statsMap.get(key);
                if (!s) {
                  return (
                    <td key={opp} className="px-2 py-1 border border-app-border text-center text-app-text-subtle dark:text-slate-600">
                      —
                    </td>
                  );
                }
                const wr = s.total ? s.wins / s.total : 0;
                return (
                  <td
                    key={opp}
                    className={`px-2 py-1 border border-app-border text-center text-ctp-base ${cellColor(wr)}`}
                    title={`${s.wins}/${s.total}`}
                  >
                    {Math.round(wr * 100)}%
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
