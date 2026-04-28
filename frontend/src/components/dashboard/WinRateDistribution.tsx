import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import type { MatchRow, OpponentStat } from '../../types/dashboard';

interface Props {
  matches: MatchRow[];
  opponents: OpponentStat[];
}

export default function WinRateDistribution({ matches, opponents }: Props) {
  const [selected, setSelected] = useState<string>('__all__');

  if (!matches.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        No match data
      </div>
    );
  }

  const opponentNames = opponents.map((o) => o.name);

  const filtered =
    selected === '__all__'
      ? matches
      : matches.filter((m) => (m.p2_deck_name ?? 'Unknown') === selected);

  // Group by opponent name, count wins and losses
  const grouped = new Map<string, { wins: number; losses: number }>();
  for (const m of filtered) {
    const name = m.p2_deck_name ?? 'Unknown';
    const cur = grouped.get(name) ?? { wins: 0, losses: 0 };
    if (m.winner === 'p1') cur.wins += 1;
    else cur.losses += 1;
    grouped.set(name, cur);
  }

  const data = [...grouped.entries()].map(([name, { wins, losses }]) => ({
    name,
    Wins: wins,
    Losses: losses,
  }));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 rounded px-2 py-1"
        >
          <option value="__all__">All opponents</option>
          {opponentNames.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ left: 0, right: 8 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
          <Bar dataKey="Wins" fill="#3b82f6" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Losses" fill="#f87171" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
