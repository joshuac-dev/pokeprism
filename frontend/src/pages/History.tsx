import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import PageShell from '../components/layout/PageShell';
import StatusBadge from '../components/history/StatusBadge';
import ModeBadge from '../components/history/ModeBadge';
import FilterBar from '../components/history/FilterBar';
import CompareModal from '../components/history/CompareModal';
import { listSimulations, starSimulation, deleteSimulation } from '../api/history';
import type { SimulationRow } from '../types/history';

const col = createColumnHelper<SimulationRow>();

const MAX_COMPARE = 3;

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtWinRate(v: number | null): string {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—';
}

export default function History() {
  const navigate = useNavigate();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [starred, setStarred] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [minWinRate, setMinWinRate] = useState('');
  const [maxWinRate, setMaxWinRate] = useState('');

  const [page, setPage] = useState(1);
  const PER_PAGE = 25;

  const [data, setData] = useState<SimulationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sorting, setSorting] = useState<SortingState>([]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparing, setComparing] = useState(false);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchData = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, unknown> = { page: p, per_page: PER_PAGE };
      if (status) params.status = status;
      if (search) params.search = search;
      if (starred) params.starred = true;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (minWinRate) params.min_win_rate = Number(minWinRate) / 100;
      if (maxWinRate) params.max_win_rate = Number(maxWinRate) / 100;

      const result = await listSimulations(params as Parameters<typeof listSimulations>[0]);
      setData(result.items ?? []);
      setTotal(result.total ?? 0);
    } catch (err: unknown) {
      setError((err as Error)?.message ?? 'Failed to load simulations.');
    } finally {
      setLoading(false);
    }
  }, [search, status, starred, dateFrom, dateTo, minWinRate, maxWinRate]);

  useEffect(() => {
    setPage(1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchData(1), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [search, status, starred, dateFrom, dateTo, minWinRate, maxWinRate, fetchData]);

  useEffect(() => { fetchData(page); }, [page, fetchData]);

  function handleReset() {
    setSearch(''); setStatus(''); setStarred(false);
    setDateFrom(''); setDateTo(''); setMinWinRate(''); setMaxWinRate('');
    setPage(1);
  }

  function toggleSelect(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_COMPARE) next.add(id);
      return next;
    });
  }

  async function handleStar(id: string) {
    await starSimulation(id);
    fetchData(page);
  }

  async function handleDelete() {
    if (!deleteId) return;
    setDeleting(true);
    try {
      await deleteSimulation(deleteId);
      setDeleteId(null);
      fetchData(page);
    } finally {
      setDeleting(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
  const compareList = data.filter(s => selected.has(s.id));

  const columns = [
    col.display({
      id: 'select',
      header: () => <span className="text-slate-500 text-xs">CMP</span>,
      cell: ({ row }) => {
        const id = row.original.id;
        const checked = selected.has(id);
        const disabled = !checked && selected.size >= MAX_COMPARE;
        return (
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={() => toggleSelect(id)}
            className="accent-blue-500 disabled:opacity-30"
          />
        );
      },
    }),
    col.accessor('starred', {
      header: '*',
      enableSorting: true,
      cell: ({ row }) => (
        <button
          onClick={() => handleStar(row.original.id)}
          className={`text-lg leading-none ${row.original.starred ? 'text-yellow-400' : 'text-slate-600 hover:text-yellow-400'}`}
        >
          {row.original.starred ? '\u2605' : '\u2606'}
        </button>
      ),
    }),
    col.accessor('status', {
      header: 'Status',
      enableSorting: true,
      cell: ({ getValue }) => <StatusBadge status={getValue()} />,
    }),
    col.accessor('created_at', {
      header: 'Created',
      enableSorting: true,
      cell: ({ getValue }) => <span className="text-slate-700 dark:text-slate-300 text-xs">{fmtDate(getValue())}</span>,
    }),
    col.accessor('user_deck_name', {
      header: 'Your Deck',
      enableSorting: true,
      cell: ({ getValue }) => <span className="text-slate-900 dark:text-white">{getValue() ?? '\u2014'}</span>,
    }),
    col.accessor('opponents', {
      header: 'Opponent(s)',
      enableSorting: false,
      cell: ({ getValue }) => {
        const ops = getValue() as string[];
        return <span className="text-slate-600 dark:text-slate-300 text-xs">{ops.length > 0 ? ops.join(', ') : '\u2014'}</span>;
      },
    }),
    col.accessor('game_mode', {
      header: 'Mode',
      enableSorting: true,
      cell: ({ getValue }) => <ModeBadge mode={getValue()} />,
    }),
    col.accessor('rounds_completed', {
      header: 'Rounds',
      enableSorting: true,
      cell: ({ row }) => `${row.original.rounds_completed} / ${row.original.num_rounds}`,
    }),
    col.accessor('final_win_rate', {
      header: 'Win Rate',
      enableSorting: true,
      cell: ({ getValue }) => (
        <span className={(getValue() as number | null) != null && (getValue() as number) >= 0.5 ? 'text-green-600 dark:text-green-400' : 'text-slate-600 dark:text-slate-300'}>
          {fmtWinRate(getValue() as number | null)}
        </span>
      ),
    }),
    col.display({
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const sim = row.original;
        return (
          <div className="flex gap-2">
            <button
              onClick={() => navigate(`/dashboard/${sim.id}`)}
              disabled={sim.status !== 'complete'}
              className="px-2 py-1 rounded text-xs bg-blue-700 hover:bg-blue-600 text-white disabled:opacity-30 disabled:cursor-not-allowed"
            >
              View
            </button>
            <button
              onClick={() => setDeleteId(sim.id)}
              className="px-2 py-1 rounded text-xs bg-red-900 hover:bg-red-700 text-white"
            >
              Delete
            </button>
          </div>
        );
      },
    }),
  ];

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    manualPagination: true,
    pageCount: totalPages,
  });

  return (
    <PageShell title="History">
      <div className="max-w-full">
        <FilterBar
          search={search} status={status} starred={starred}
          dateFrom={dateFrom} dateTo={dateTo}
          minWinRate={minWinRate} maxWinRate={maxWinRate}
          onSearch={setSearch} onStatus={setStatus} onStarred={setStarred}
          onDateFrom={setDateFrom} onDateTo={setDateTo}
          onMinWinRate={setMinWinRate} onMaxWinRate={setMaxWinRate}
          onReset={handleReset}
        />

        {selected.size > 0 && (
          <div className="mb-4 flex items-center gap-3 bg-blue-950 border border-blue-800 rounded-xl px-4 py-2">
            <span className="text-blue-300 text-sm">{selected.size} selected</span>
            <button
              onClick={() => setComparing(true)}
              disabled={selected.size < 2}
              className="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm disabled:opacity-40"
            >
              Compare
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="text-blue-400 hover:text-blue-200 text-sm"
            >
              Clear
            </button>
          </div>
        )}

        {loading && <p className="text-slate-400 text-sm mb-4">Loading...</p>}
        {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

        {!loading && !error && (
          <>
            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 dark:bg-slate-800">
                  {table.getHeaderGroups().map(hg => (
                    <tr key={hg.id}>
                      {hg.headers.map(header => (
                        <th
                          key={header.id}
                          onClick={header.column.getToggleSortingHandler()}
                          className={`px-4 py-3 text-left text-slate-500 dark:text-slate-400 font-medium whitespace-nowrap ${header.column.getCanSort() ? 'cursor-pointer select-none hover:text-slate-900 dark:hover:text-white' : ''}`}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getIsSorted() === 'asc' && ' \u2191'}
                          {header.column.getIsSorted() === 'desc' && ' \u2193'}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                  {table.getRowModel().rows.length === 0 ? (
                    <tr>
                      <td colSpan={columns.length} className="px-4 py-10 text-center text-slate-500">
                        No simulations found.
                      </td>
                    </tr>
                  ) : (
                    table.getRowModel().rows.map(row => (
                      <tr key={row.id} className="bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800/60">
                        {row.getVisibleCells().map(cell => (
                          <td key={cell.id} className="px-4 py-3 whitespace-nowrap">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
              <span>{total} simulation{total !== 1 ? 's' : ''}</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                >
                  Prev
                </button>
                <span>Page {page} of {totalPages}</span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}

        {deleteId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl">
              <h3 className="text-slate-900 dark:text-white font-semibold mb-2">Delete simulation?</h3>
              <p className="text-slate-500 dark:text-slate-400 text-sm mb-5">
                This will permanently delete the simulation and all associated matches, events,
                decisions, mutations, and embeddings. This cannot be undone.
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setDeleteId(null)}
                  className="px-4 py-2 rounded-lg bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-900 dark:text-white text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 text-white text-sm disabled:opacity-50"
                >
                  {deleting ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        )}

        {comparing && compareList.length >= 2 && (
          <CompareModal sims={compareList} onClose={() => setComparing(false)} />
        )}
      </div>
    </PageShell>
  );
}
