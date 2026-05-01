import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import type { OpponentStat } from '../../types/dashboard';

interface Props {
  opponents: OpponentStat[];
}

function barColor(winRate: number): string {
  if (winRate > 0.6) return '#22c55e';
  if (winRate >= 0.4) return '#eab308';
  return '#ef4444';
}

interface TooltipPayloadItem {
  payload: OpponentStat;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-app-bg-secondary border border-app-border rounded px-3 py-2 text-xs text-app-text">
      <p className="font-medium">{d.name}</p>
      <p>{d.wins} wins / {d.total} total ({Math.round(d.win_rate * 100)}%)</p>
    </div>
  );
}

export default function OpponentWinRateBar({ opponents }: Props) {
  if (!opponents.length) {
    return (
      <div className="flex items-center justify-center h-48 text-app-text-subtle text-sm">
        No opponent data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, opponents.length * 36)}>
      <BarChart data={opponents} layout="vertical" margin={{ left: 8, right: 16 }}>
        <XAxis
          type="number"
          domain={[0, 100]}
          tickFormatter={(v: number) => `${v}%`}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={120}
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<CustomTooltip />} />
        <Bar dataKey="win_rate" name="Win Rate">
          {opponents.map((o, i) => (
            <Cell key={i} fill={barColor(o.win_rate)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
