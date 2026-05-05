import { useEffect, useState, useMemo } from 'react';
import PageShell from '../components/layout/PageShell';
import { CheckCircle, Zap, AlertCircle, ArrowUpDown } from 'lucide-react';
import CardImageLightbox from '../components/cards/CardImageLightbox';

interface CardCoverage {
  tcgdex_id: string;
  name: string;
  set_abbrev: string;
  set_number: string;
  category: string | null;
  subcategory: string | null;
  status: 'implemented' | 'flat_only' | 'missing';
  missing_effects: string[];
  image_url?: string | null;
}

interface CoverageData {
  total: number;
  implemented: number;
  flat_only: number;
  missing: number;
  coverage_pct: number;
  cards: CardCoverage[];
}

type SortKey = 'name' | 'set_abbrev' | 'category' | 'status';
type Filter = 'all' | 'implemented' | 'flat_only' | 'missing';

const STATUS_ORDER: Record<string, number> = { missing: 0, implemented: 1, flat_only: 2 };

const STATUS_LABEL: Record<string, string> = {
  implemented: '✅ Implemented',
  flat_only:   '⚡ Flat Damage Only',
  missing:     '❌ Missing',
};

interface StatTileProps { label: string; value: number; sub?: string; accent?: string }
function StatTile({ label, value, sub, accent = 'text-slate-800 dark:text-slate-100' }: StatTileProps) {
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4">
      <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent}`}>{value.toLocaleString()}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function Coverage() {
  const [data, setData] = useState<CoverageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [search, setSearch] = useState('');
  const [selectedCard, setSelectedCard] = useState<CardCoverage | null>(null);

  useEffect(() => {
    fetch('/api/coverage')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d: CoverageData) => { setData(d); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    let list = data.cards;
    if (filter !== 'all') list = list.filter(c => c.status === filter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(c =>
        c.name.toLowerCase().includes(q) ||
        (c.tcgdex_id || '').toLowerCase().includes(q) ||
        (c.set_abbrev || '').toLowerCase().includes(q),
      );
    }
    return [...list].sort((a, b) => {
      let va: string | number;
      let vb: string | number;
      if (sortKey === 'status') {
        va = STATUS_ORDER[a.status] ?? 9;
        vb = STATUS_ORDER[b.status] ?? 9;
      } else {
        va = (a[sortKey] ?? '').toLowerCase();
        vb = (b[sortKey] ?? '').toLowerCase();
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ?  1 : -1;
      return 0;
    });
  }, [data, filter, sortKey, sortDir, search]);

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('asc'); }
  }

  const SortButton = ({ k, label }: { k: SortKey; label: string }) => (
    <button
      onClick={() => handleSort(k)}
      className="flex items-center gap-1 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
    >
      {label}
      <ArrowUpDown size={12} className={sortKey === k ? 'text-blue-400' : 'opacity-40'} />
    </button>
  );

  if (loading) {
    return (
      <PageShell title="Card Coverage">
        <p className="text-slate-500 text-sm">Loading coverage data…</p>
      </PageShell>
    );
  }

  if (error || !data) {
    return (
      <PageShell title="Card Coverage">
        <p className="text-red-500 text-sm">{error || 'Failed to load coverage data.'}</p>
      </PageShell>
    );
  }

  const FILTERS: { value: Filter; label: string }[] = [
    { value: 'all',         label: `All (${data.total})` },
    { value: 'implemented', label: `✅ Implemented (${data.implemented})` },
    { value: 'flat_only',   label: `⚡ Flat Only (${data.flat_only})` },
    { value: 'missing',     label: `❌ Missing (${data.missing})` },
  ];

  return (
    <PageShell title="Card Coverage">
      {/* Summary tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
        <StatTile label="Total Cards" value={data.total} />
        <StatTile
          label="Implemented"
          value={data.implemented}
          accent="text-green-600 dark:text-green-400"
        />
        <StatTile
          label="Flat Damage Only"
          value={data.flat_only}
          accent="text-yellow-600 dark:text-yellow-400"
          sub="No effect text — no handler needed"
        />
        <StatTile
          label="Missing Handlers"
          value={data.missing}
          accent="text-red-600 dark:text-red-400"
        />
      </div>

      {/* Coverage bar */}
      <div
        className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 mb-6 flex items-center gap-4"
        data-testid="coverage-summary"
      >
        <div className="flex-1">
          <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
            <span>Coverage</span>
            <span className="font-semibold text-slate-800 dark:text-slate-100">
              {data.coverage_pct}% &mdash; {data.implemented + data.flat_only}/{data.total} cards ready
            </span>
          </div>
          <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 rounded-full transition-all"
              style={{ width: `${data.coverage_pct}%` }}
            />
          </div>
        </div>
        <div className="flex gap-3 text-xs text-slate-500 dark:text-slate-400">
          <span className="flex items-center gap-1"><CheckCircle size={12} className="text-green-500" /> Impl.</span>
          <span className="flex items-center gap-1"><Zap size={12} className="text-yellow-500" /> Flat</span>
          <span className="flex items-center gap-1"><AlertCircle size={12} className="text-red-500" /> Missing</span>
        </div>
      </div>

      {/* Filter + search bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex gap-1">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                filter === value
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search by name or set…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="ml-auto px-3 py-1.5 text-xs rounded-md bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Table */}
      <div
        className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden"
        data-testid="coverage-table"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <SortButton k="name" label="Card Name" />
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <SortButton k="set_abbrev" label="Set" />
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <SortButton k="category" label="Category" />
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <SortButton k="status" label="Status" />
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Missing Effects
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-slate-400 text-sm">
                    No cards match the current filter.
                  </td>
                </tr>
              ) : rows.map(card => (
                <tr key={card.tcgdex_id} className="hover:bg-slate-50 dark:hover:bg-slate-700/40 transition-colors">
                  <td className="px-4 py-2.5 font-medium text-slate-800 dark:text-slate-200">
                    <button
                      onClick={() => setSelectedCard(card)}
                      aria-label={`View ${card.name} card image`}
                      className="text-left hover:underline hover:text-blue-600 dark:hover:text-blue-400 cursor-pointer transition-colors"
                      data-testid="coverage-card-name-btn"
                    >
                      {card.name}
                    </button>
                    <span className="ml-1.5 text-xs text-slate-400 font-mono">{card.tcgdex_id}</span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400 font-mono text-xs whitespace-nowrap">
                    {card.set_abbrev} {card.set_number}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400 capitalize text-xs">
                    {card.category}{card.subcategory ? ` / ${card.subcategory}` : ''}
                  </td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                    <span className={
                      card.status === 'implemented' ? 'text-green-600 dark:text-green-400' :
                      card.status === 'flat_only'   ? 'text-yellow-600 dark:text-yellow-400' :
                                                      'text-red-600 dark:text-red-400'
                    }>
                      {STATUS_LABEL[card.status]}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-400 dark:text-slate-500">
                    {card.missing_effects.length > 0
                      ? card.missing_effects.join(', ')
                      : <span className="opacity-40">—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > 0 && (
          <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-700 text-xs text-slate-400">
            Showing {rows.length} of {data.total} cards
          </div>
        )}
      </div>
      {selectedCard && (
        <CardImageLightbox card={selectedCard} onClose={() => setSelectedCard(null)} />
      )}
    </PageShell>
  );
}
