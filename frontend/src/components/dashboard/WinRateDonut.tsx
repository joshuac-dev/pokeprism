import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

interface Props {
  winRate: number | null;
  totalMatches: number;
}

export default function WinRateDonut({ winRate, totalMatches }: Props) {
  if (winRate === null) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        No data available
      </div>
    );
  }

  const winPct = Math.round(winRate * 100);
  const lossPct = 100 - winPct;
  const wins = Math.round(winRate * totalMatches);
  const losses = totalMatches - wins;

  const data = [
    { name: 'Wins', value: winPct },
    { name: 'Losses', value: lossPct },
  ];

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative w-full" style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              dataKey="value"
              startAngle={90}
              endAngle={-270}
            >
              <Cell fill="#3b82f6" />
              <Cell fill="#475569" />
            </Pie>
            <Tooltip formatter={(v) => [`${v}%`]} />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-3xl font-bold text-white">{winPct}%</span>
          <span className="text-xs text-slate-400">win rate</span>
        </div>
      </div>
      <div className="flex gap-6 text-sm text-slate-400">
        <span>
          <span className="inline-block w-3 h-3 rounded-full bg-blue-500 mr-1" />
          Wins ({wins} matches)
        </span>
        <span>
          <span className="inline-block w-3 h-3 rounded-full bg-slate-600 mr-1" />
          Losses ({losses} matches)
        </span>
      </div>
    </div>
  );
}
