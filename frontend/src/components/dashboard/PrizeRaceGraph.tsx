import { useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { PrizeRaceData } from '../../types/dashboard';

interface Props {
  prizeRace: PrizeRaceData;
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; name: string }>;
  label?: number;
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const p1 = payload.find((p) => p.name.startsWith('P1'));
  const p2 = payload.find((p) => p.name.startsWith('P2'));
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded px-3 py-2 text-xs text-slate-900 dark:text-white">
      <p className="font-medium mb-1">Turn {label}</p>
      {p1 && <p>P1: {p1.value} prizes</p>}
      {p2 && <p>P2: {p2.value} prizes</p>}
    </div>
  );
}

export default function PrizeRaceGraph({ prizeRace }: Props) {
  const [selectedMatch, setSelectedMatch] = useState<string>('__avg__');

  if (!prizeRace.average.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm text-center px-4">
        No prize race data — all games ended by deck-out with no KOs.
      </div>
    );
  }

  const isAvg = selectedMatch === '__avg__';

  let chartData: Array<{ turn: number; p1: number; p2: number }> = [];
  if (isAvg) {
    chartData = prizeRace.average.map((pt) => ({
      turn: pt.turn,
      p1: pt.p1_avg,
      p2: pt.p2_avg,
    }));
  } else {
    const match = prizeRace.matches.find((m) => m.match_id === selectedMatch);
    chartData = (match?.turns ?? []).map((pt) => ({
      turn: pt.turn,
      p1: pt.p1_cumulative,
      p2: pt.p2_cumulative,
    }));
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <select
          value={selectedMatch}
          onChange={(e) => setSelectedMatch(e.target.value)}
          className="text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 rounded px-2 py-1"
        >
          <option value="__avg__">Average (all matches)</option>
          {prizeRace.matches.map((m) => (
            <option key={m.match_id} value={m.match_id}>
              Match {m.match_id.slice(0, 8)} — Round {m.round_number}
            </option>
          ))}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={chartData} margin={{ left: 0, right: 8 }}>
          <XAxis
            dataKey="turn"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            label={{ value: 'Turn', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 11 }}
          />
          <YAxis
            domain={[0, 6]}
            ticks={[0, 1, 2, 3, 4, 5, 6]}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={24}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
            formatter={(value) =>
              value === 'p1' ? 'P1 (Your Deck)' : 'P2 (Opponent)'
            }
          />
          <Line
            type="monotone"
            dataKey="p1"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={false}
            name="p1"
          />
          <Line
            type="monotone"
            dataKey="p2"
            stroke="#f87171"
            strokeWidth={2}
            dot={false}
            name="p2"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
