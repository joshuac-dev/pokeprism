import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import type { RoundRow } from '../../types/dashboard';

interface Props {
  rounds: RoundRow[];
  targetWinRate: number;
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: number;
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded px-3 py-2 text-xs text-slate-900 dark:text-white">
      Round {label}: {payload[0].value.toFixed(1)}%
    </div>
  );
}

export default function WinRateProgress({ rounds, targetWinRate }: Props) {
  const withData = rounds.filter((r) => r.win_rate !== null);

  if (!withData.length) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-400 text-sm">
        Waiting for round data
      </div>
    );
  }

  const data = withData.map((r) => ({
    round: r.round_number,
    win_rate: Math.round((r.win_rate ?? 0) * 1000) / 10,
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ left: 0, right: 8 }}>
        <XAxis
          dataKey="round"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          label={{ value: 'Round', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 11 }}
        />
        <YAxis
          domain={[0, 100]}
          tickFormatter={(v: number) => `${v}%`}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={40}
        />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine
          y={targetWinRate * 100}
          stroke="#eab308"
          strokeDasharray="4 2"
          label={{ value: 'Target', fill: '#eab308', fontSize: 10, position: 'right' }}
        />
        <Line
          type="monotone"
          dataKey="win_rate"
          stroke="#60a5fa"
          strokeWidth={2}
          dot={{ fill: '#60a5fa', r: 3 }}
          name="Win Rate"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
