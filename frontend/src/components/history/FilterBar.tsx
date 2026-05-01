import { useState } from 'react';

interface Props {
  search: string;
  status: string;
  starred: boolean;
  dateFrom: string;
  dateTo: string;
  minWinRate: string;
  maxWinRate: string;
  onSearch: (v: string) => void;
  onStatus: (v: string) => void;
  onStarred: (v: boolean) => void;
  onDateFrom: (v: string) => void;
  onDateTo: (v: string) => void;
  onMinWinRate: (v: string) => void;
  onMaxWinRate: (v: string) => void;
  onReset: () => void;
}

const STATUSES = ['', 'pending', 'running', 'complete', 'failed', 'cancelled'];
const STATUS_LABEL: Record<string, string> = {
  '': 'All statuses', pending: 'Pending', running: 'Running',
  complete: 'Complete', failed: 'Failed', cancelled: 'Cancelled',
};

export default function FilterBar({
  search, status, starred, dateFrom, dateTo, minWinRate, maxWinRate,
  onSearch, onStatus, onStarred, onDateFrom, onDateTo, onMinWinRate, onMaxWinRate, onReset,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-slate-50 dark:bg-slate-800 border border-app-border rounded-xl p-4 mb-4 space-y-3">
      {/* Row 1: search + status + starred + toggle */}
      <div className="flex flex-wrap gap-3 items-center">
        <input
          type="text"
          placeholder="Search deck name…"
          value={search}
          onChange={e => onSearch(e.target.value)}
          className="flex-1 min-w-[200px] bg-app-bg-secondary border border-app-border rounded-lg px-3 py-1.5 text-sm text-app-text placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:border-app-focus"
        />

        <select
          value={status}
          onChange={e => onStatus(e.target.value)}
          className="bg-app-bg-secondary border border-app-border rounded-lg px-3 py-1.5 text-sm text-app-text focus:outline-none focus:border-app-focus"
        >
          {STATUSES.map(s => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={starred}
            onChange={e => onStarred(e.target.checked)}
            className="accent-yellow-400"
          />
          ★ Starred only
        </label>

        <button
          onClick={() => setExpanded(x => !x)}
          className="text-xs text-app-text-muted hover:text-slate-800 dark:hover:text-slate-200 border border-app-border rounded-lg px-3 py-1.5"
        >
          {expanded ? 'Fewer filters ▲' : 'More filters ▼'}
        </button>

        <button
          onClick={onReset}
          className="text-xs text-app-text-subtle hover:text-ctp-red"
        >
          Reset
        </button>
      </div>

      {/* Row 2: expanded filters */}
      {expanded && (
        <div className="flex flex-wrap gap-3 items-center pt-1 border-t border-app-border">
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <span>From</span>
            <input
              type="date"
              value={dateFrom}
              onChange={e => onDateFrom(e.target.value)}
              className="bg-app-bg-secondary border border-app-border rounded-lg px-2 py-1 text-sm text-app-text focus:outline-none focus:border-app-focus"
            />
            <span>To</span>
            <input
              type="date"
              value={dateTo}
              onChange={e => onDateTo(e.target.value)}
              className="bg-app-bg-secondary border border-app-border rounded-lg px-2 py-1 text-sm text-app-text focus:outline-none focus:border-app-focus"
            />
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <span>Win rate</span>
            <input
              type="number"
              min={0} max={100} step={5}
              placeholder="min %"
              value={minWinRate}
              onChange={e => onMinWinRate(e.target.value)}
              className="w-20 bg-app-bg-secondary border border-app-border rounded-lg px-2 py-1 text-sm text-app-text focus:outline-none focus:border-app-focus"
            />
            <span>–</span>
            <input
              type="number"
              min={0} max={100} step={5}
              placeholder="max %"
              value={maxWinRate}
              onChange={e => onMaxWinRate(e.target.value)}
              className="w-20 bg-app-bg-secondary border border-app-border rounded-lg px-2 py-1 text-sm text-app-text focus:outline-none focus:border-app-focus"
            />
          </div>
        </div>
      )}
    </div>
  );
}
