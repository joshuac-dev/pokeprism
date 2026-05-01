import type { SimulationDetail } from '../../types/simulation';

interface Props {
  detail: Pick<
    SimulationDetail,
    'status' | 'num_rounds' | 'rounds_completed' | 'matches_per_opponent' |
    'total_matches' | 'target_win_rate' | 'final_win_rate' | 'game_mode' |
    'user_deck_name' | 'error_message'
  >;
  onCancel?: () => void;
  cancelling?: boolean;
}

const STATUS_COLOR: Record<string, string> = {
  pending:   'text-app-text-subtle',
  running:   'text-blue-400',
  complete:  'text-ctp-green',
  failed:    'text-ctp-red',
  cancelled: 'text-amber-400',
};

const STATUS_LABEL: Record<string, string> = {
  pending:   'Pending',
  running:   'Running',
  complete:  'Complete',
  failed:    'Failed',
  cancelled: 'Cancelled',
};

function WinRateBar({ value, target }: { value: number | null; target: number }) {
  const pct = value != null ? Math.round(value * 100) : null;
  const targetPct = Math.round(target * 100);
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex-1 h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-visible">
        {/* target line */}
        <div
          className="absolute top-0 h-full w-0.5 bg-amber-400 opacity-70"
          style={{ left: `${targetPct}%` }}
        />
        {/* fill */}
        {pct != null && (
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-700"
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        )}
      </div>
      <span className="text-app-text text-sm tabular-nums w-12 text-right">
        {pct != null ? `${pct}%` : '—'}
      </span>
    </div>
  );
}

export default function SimulationStatus({ detail, onCancel, cancelling }: Props) {
  const canCancel = detail.status === 'running' || detail.status === 'pending';
  const progress = detail.num_rounds > 0
    ? Math.round((detail.rounds_completed / detail.num_rounds) * 100)
    : 0;

  return (
    <div className="bg-app-surface border border-app-border rounded-lg p-4 space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-app-text-muted uppercase tracking-wide">Simulation</p>
          <p className="text-app-text font-semibold truncate max-w-xs">
            {detail.user_deck_name ?? 'Custom Deck'}
          </p>
        </div>
        <span className={`text-sm font-semibold ${STATUS_COLOR[detail.status] ?? 'text-app-text-subtle'}`}>
          {STATUS_LABEL[detail.status] ?? detail.status}
        </span>
      </div>

      {/* Round progress bar */}
      <div>
        <div className="flex justify-between text-xs text-app-text-subtle mb-1">
          <span>Round progress</span>
          <span>{detail.rounds_completed} / {detail.num_rounds}</span>
        </div>
        <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-app-primary rounded-full transition-all duration-700"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Win rate */}
      <div>
        <div className="flex justify-between text-xs text-app-text-subtle mb-1">
          <span>Win rate</span>
          <span className="text-amber-400">target {Math.round(detail.target_win_rate * 100)}%</span>
        </div>
        <WinRateBar value={detail.final_win_rate} target={detail.target_win_rate} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <div className="bg-slate-100 dark:bg-slate-900 rounded p-2">
          <p className="text-app-text-muted">Mode</p>
          <p className="text-app-text font-mono uppercase">{detail.game_mode}</p>
        </div>
        <div className="bg-slate-100 dark:bg-slate-900 rounded p-2">
          <p className="text-app-text-muted">Matches</p>
          <p className="text-app-text font-mono">{detail.total_matches}</p>
        </div>
        <div className="bg-slate-100 dark:bg-slate-900 rounded p-2">
          <p className="text-app-text-muted">Per opp.</p>
          <p className="text-app-text font-mono">{detail.matches_per_opponent}</p>
        </div>
      </div>

      {/* Error message */}
      {detail.error_message && (
        <p className="text-xs text-ctp-red bg-red-950/30 border border-red-800 rounded px-3 py-2">
          {detail.error_message}
        </p>
      )}

      {/* Cancel button */}
      {canCancel && onCancel && (
        <button
          onClick={onCancel}
          disabled={cancelling}
          className="w-full py-1.5 px-4 text-sm rounded border border-red-700 text-ctp-red
                     hover:bg-red-900/30 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          {cancelling ? 'Cancelling…' : 'Cancel Simulation'}
        </button>
      )}
    </div>
  );
}
