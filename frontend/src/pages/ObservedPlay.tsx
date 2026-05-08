import { useCallback, useEffect, useRef, useState } from 'react';
import { Upload, X } from 'lucide-react';
import PageShell from '../components/layout/PageShell';
import {
  uploadObservedPlayLog,
  listObservedPlayBatches,
  listObservedPlayLogs,
  getObservedPlayLog,
  getObservedPlayLogEvents,
  reparseObservedPlayLog,
  getCardMentions,
  getUnresolvedCards,
  previewMemoryIngestion,
  ingestMemory,
  getMemoryItems,
  createResolutionRule,
  resolveCards,
  getMemorySummary,
  getMemoryAnalytics,
  getMemoryAnalyticsSourceItems,
  bulkReparseAll,
  bulkPreviewEligible,
  bulkIngestEligible,
  getCorpusReadiness,
  getCoachEvidence,
} from '../api/observedPlay';
import type {
  BulkReparseSummary,
  BulkIngestEligiblePreview,
  BulkIngestEligibleSummary,
  CardCandidateItem,
  CardMentionItem,
  EligibilityReason,
  EventSummary,
  IngestionBlocker,
  IngestionConfig,
  MemoryIngestionPreview,
  MemoryIngestionSummary,
  MemoryItemSummary,
  ObservedPlayBatch,
  ObservedPlayLog,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
  PaginatedEvents,
  PaginatedMemoryItems,
  ParserDiagnostics,
  ResolutionRuleCreate,
  MemorySummary,
  MemoryAnalyticsResponse,
  MemoryAnalyticsGroup,
  MemoryAnalyticsSourceItemsParams,
  UnresolvedCardItem,
  CorpusReadinessReport,
  CoachEvidenceResponse,
  CoachEvidenceItem,
} from '../types/observedPlay';
import { normalizeTcgdexImageUrl } from '../utils/imageUrl';

const ACCEPTED_EXTS = '.md,.markdown,.txt,.zip';

type LogSortKey =
  | 'created_at' | 'filename' | 'parse_status' | 'memory_status'
  | 'event_count' | 'confidence_score' | 'card_mention_count'
  | 'cards' | 'ambiguous_card_count' | 'unresolved_card_count' | 'resolved_card_count'
  | 'memory_item_count' | 'file_size_bytes' | 'sha256_hash';

function SortableTh({
  label, sortKey, currentSortBy, currentSortDir, onSort, defaultDir = 'asc', title,
}: {
  label: string;
  sortKey: LogSortKey;
  currentSortBy: LogSortKey;
  currentSortDir: 'asc' | 'desc';
  onSort: (key: LogSortKey, defaultDir: 'asc' | 'desc') => void;
  defaultDir?: 'asc' | 'desc';
  title?: string;
}) {
  const isActive = sortKey === currentSortBy;
  const icon = isActive ? (currentSortDir === 'asc' ? '▲' : '▼') : '↕';
  const nextDir = isActive ? (currentSortDir === 'asc' ? 'desc' : 'asc') : defaultDir;
  return (
    <th className="pb-1 pr-3">
      <button
        onClick={() => onSort(sortKey, defaultDir)}
        className="flex items-center gap-0.5 text-xs text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-slate-100 whitespace-nowrap"
        aria-label={`Sort by ${label} ${nextDir}ending`}
        title={title}
      >
        {label}
        <span className={`ml-0.5 ${isActive ? 'text-blue-500 dark:text-blue-400' : 'opacity-40'}`}>{icon}</span>
      </button>
    </th>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function StatusChip({ status }: { status: string }) {
  const palette: Record<string, string> = {
    completed: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-300',
    completed_with_warnings: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200',
    failed: 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-300',
    running: 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-300',
    pending: 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-300',
    imported: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-300',
    duplicate: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300',
    skipped: 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-slate-400',
    raw_archived: 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300',
    not_ingested: 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-slate-400',
    ingested: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-300',
    ingestion_failed: 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300',
    ingestion_skipped: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300',
  };
  const cls = palette[status] ?? 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-300';
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

// ── Raw log viewer modal ──────────────────────────────────────────────────────

function RawLogModal({
  logId,
  onClose,
}: {
  logId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ObservedPlayLogDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getObservedPlayLog(logId)
      .then(setDetail)
      .catch(() => setError('Failed to load log.'))
      .finally(() => setLoading(false));
  }, [logId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <h2 className="mb-3 text-lg font-semibold text-slate-900 dark:text-white">Raw Log</h2>
        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {detail && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="font-medium text-gray-600 dark:text-slate-300">File</span>
              <span>{detail.original_filename}</span>
              <span className="font-medium text-gray-600 dark:text-slate-300">SHA-256</span>
              <span className="font-mono text-xs">{detail.sha256_hash}</span>
              <span className="font-medium text-gray-600 dark:text-slate-300">Size</span>
              <span>{fmtBytes(detail.file_size_bytes)}</span>
              <span className="font-medium text-gray-600 dark:text-slate-300">Parse status</span>
              <StatusChip status={detail.parse_status} />
              <span className="font-medium text-gray-600 dark:text-slate-300">Memory status</span>
              <StatusChip status={detail.memory_status} />
              <span className="font-medium text-gray-600 dark:text-slate-300">Imported</span>
              <span>{fmtDate(detail.created_at)}</span>
            </div>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 dark:text-slate-300 p-3 text-xs font-mono">
              {detail.raw_content ?? '(no raw content stored)'}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}

function ConfidenceBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-xs text-gray-400 dark:text-slate-500">—</span>;
  const pct = Math.round(score * 100);
  const cls =
    pct >= 80
      ? 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-300'
      : pct >= 50
        ? 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200'
        : 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300';
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {pct}%
    </span>
  );
}

// ── Events viewer modal ───────────────────────────────────────────────────────

function ParserDiagnosticsPanel({ diag }: { diag: ParserDiagnostics }) {
  return (
    <div className="mb-4 rounded border border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-3 text-xs">
      <p className="mb-1 font-medium text-gray-600 dark:text-slate-300">Parser diagnostics</p>
      <p>Unknown: {diag.unknown_count} ({(diag.unknown_ratio * 100).toFixed(1)}%)</p>
      <p>Low confidence: {diag.low_confidence_count}</p>
      {diag.top_unknown_raw_lines.length > 0 && (
        <div className="mt-1">
          <p className="font-medium text-gray-600 dark:text-slate-300">Top unknown lines:</p>
          <ul className="mt-0.5 space-y-0.5">
            {diag.top_unknown_raw_lines.slice(0, 5).map((line, i) => (
              <li key={i} className="truncate font-mono text-gray-500 dark:text-slate-400">{line}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function EventsModal({
  logId,
  onClose,
  initialDiagnostics,
}: {
  logId: string;
  onClose: () => void;
  initialDiagnostics?: ParserDiagnostics | null;
}) {
  const [data, setData] = useState<PaginatedEvents | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reparsing, setReparsing] = useState(false);
  const [reparseMsg, setReparseMsg] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<ParserDiagnostics | null | undefined>(initialDiagnostics);
  const PER_PAGE = 50;

  const load = useCallback(
    (p: number) => {
      setLoading(true);
      setError(null);
      getObservedPlayLogEvents(logId, { page: p, per_page: PER_PAGE })
        .then(setData)
        .catch(() => setError('Failed to load events.'))
        .finally(() => setLoading(false));
    },
    [logId],
  );

  useEffect(() => { load(page); }, [page, load]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  async function handleReparse() {
    setReparsing(true);
    setReparseMsg(null);
    try {
      const res = await reparseObservedPlayLog(logId);
      setReparseMsg(`Reparsed: ${res.event_count} events, status=${res.parse_status}`);
      if (res.parser_diagnostics) setDiagnostics(res.parser_diagnostics);
      load(1);
    } catch {
      setReparseMsg('Reparse failed.');
    } finally {
      setReparsing(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <div className="mb-4 flex items-center gap-4">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Parsed Events</h2>
          <button
            onClick={handleReparse}
            disabled={reparsing}
            className="rounded border border-blue-300 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {reparsing ? 'Reparsing…' : 'Reparse'}
          </button>
          {reparseMsg && <span className="text-xs text-gray-600 dark:text-slate-300">{reparseMsg}</span>}
        </div>
        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {diagnostics && <ParserDiagnosticsPanel diag={diagnostics} />}
        {data && data.total === 0 && (
          <p className="text-sm text-gray-500 dark:text-slate-400">
            No parsed events found. Try{' '}
            <button
              onClick={handleReparse}
              disabled={reparsing}
              className="text-blue-600 hover:underline disabled:opacity-50"
            >
              Reparse
            </button>
            .
          </p>
        )}
        {data && data.total > 0 && (
          <>
            <p className="mb-3 text-xs text-gray-500 dark:text-slate-400">{data.total} events total</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-gray-500 dark:text-slate-400">
                    <th className="pb-1 pr-2">#</th>
                    <th className="pb-1 pr-2">Turn</th>
                    <th className="pb-1 pr-2">Phase</th>
                    <th className="pb-1 pr-2">Player</th>
                    <th className="pb-1 pr-2">Type</th>
                    <th className="pb-1 pr-2">Card</th>
                    <th className="pb-1 pr-2">Dmg</th>
                    <th className="pb-1 pr-2">Conf</th>
                    <th className="pb-1">Raw line</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.items as EventSummary[]).map((evt) => (
                    <tr key={evt.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                      <td className="py-0.5 pr-2 text-gray-400 dark:text-slate-500">{evt.event_index}</td>
                      <td className="py-0.5 pr-2">{evt.turn_number ?? '—'}</td>
                      <td className="py-0.5 pr-2">{evt.phase}</td>
                      <td className="py-0.5 pr-2">{evt.player_alias ?? evt.player_raw ?? '—'}</td>
                      <td className="py-0.5 pr-2 font-medium">{evt.event_type}</td>
                      <td className="py-0.5 pr-2">{evt.card_name_raw ?? '—'}</td>
                      <td className="py-0.5 pr-2">{evt.damage ?? '—'}</td>
                      <td className="py-0.5 pr-2"><ConfidenceBadge score={evt.confidence_score} /></td>
                      <td className="max-w-xs truncate py-0.5 font-mono text-gray-500 dark:text-slate-400">{evt.raw_line}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  ‹ Prev
                </button>
                <span>Page {page} / {totalPages}</span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  Next ›
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Card resolution badge ─────────────────────────────────────────────────────

function CardResolutionBadges({ log }: { log: ObservedPlayLog }) {
  const total = log.card_mention_count ?? 0;
  if (total === 0) return <span className="text-xs text-gray-400 dark:text-slate-500">—</span>;
  const resolved = log.resolved_card_count ?? 0;
  const ambiguous = log.ambiguous_card_count ?? 0;
  const unresolved = log.unresolved_card_count ?? 0;
  return (
    <span className="flex items-center gap-1 text-xs">
      <span className="text-gray-500 dark:text-slate-400">{total}</span>
      {resolved > 0 && (
        <span className="rounded bg-green-100 dark:bg-green-900 px-1 text-green-700 dark:text-green-300">{resolved}✓</span>
      )}
      {ambiguous > 0 && (
        <span className="rounded bg-yellow-100 dark:bg-yellow-900 px-1 text-yellow-700 dark:text-yellow-300">{ambiguous}?</span>
      )}
      {unresolved > 0 && (
        <span className="rounded bg-red-100 dark:bg-red-900 px-1 text-red-700 dark:text-red-300">{unresolved}✗</span>
      )}
    </span>
  );
}

// ── Card mentions modal ───────────────────────────────────────────────────────

function CardMentionsModal({
  logId,
  onClose,
}: {
  logId: string;
  onClose: () => void;
}) {
  const [items, setItems] = useState<CardMentionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const PER_PAGE = 50;

  const load = useCallback(
    (p: number, status: string) => {
      setLoading(true);
      setError(null);
      getCardMentions(logId, { page: p, per_page: PER_PAGE, resolution_status: status || undefined })
        .then((data) => { setItems(data.items); setTotal(data.total); })
        .catch(() => setError('Failed to load card mentions.'))
        .finally(() => setLoading(false));
    },
    [logId],
  );

  useEffect(() => { load(page, statusFilter); }, [page, statusFilter, load]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const statusBadge = (status: string) => {
    const palette: Record<string, string> = {
      resolved: 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300',
      ambiguous: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300',
      unresolved: 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300',
      ignored: 'bg-gray-100 dark:bg-slate-700 text-gray-500 dark:text-slate-400',
    };
    return (
      <span className={`rounded px-1 py-0.5 text-xs font-medium ${palette[status] ?? 'bg-gray-100'}`}>
        {status}
      </span>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label="Card mentions"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <div className="mb-4 flex items-center gap-4 flex-wrap">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Card Mentions</h2>
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="rounded border border-gray-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 px-2 py-1 text-xs"
          >
            <option value="">All statuses</option>
            <option value="resolved">Resolved</option>
            <option value="ambiguous">Ambiguous</option>
            <option value="unresolved">Unresolved</option>
            <option value="ignored">Ignored</option>
          </select>
          <span className="text-xs text-gray-500 dark:text-slate-400">{total} mentions</span>
        </div>
        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && items.length === 0 && (
          <p className="text-sm text-gray-400 dark:text-slate-500">No card mentions found.</p>
        )}
        {items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-gray-500 dark:text-slate-400">
                    <th className="pb-1 pr-2">Role</th>
                    <th className="pb-1 pr-2">Raw name</th>
                    <th className="pb-1 pr-2">Status</th>
                    <th className="pb-1 pr-2">Resolved as</th>
                    <th className="pb-1 pr-2">Confidence</th>
                    <th className="pb-1">Method</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((m) => (
                    <tr key={m.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                      <td className="py-0.5 pr-2 text-gray-500 dark:text-slate-400">{m.mention_role}</td>
                      <td className="py-0.5 pr-2 font-medium">{m.raw_name}</td>
                      <td className="py-0.5 pr-2">{statusBadge(m.resolution_status)}</td>
                      <td className="py-0.5 pr-2">{m.resolved_card_name ?? '—'}</td>
                      <td className="py-0.5 pr-2">
                        {m.resolution_confidence != null
                          ? `${Math.round(m.resolution_confidence * 100)}%`
                          : '—'}
                      </td>
                      <td className="py-0.5 text-gray-400 dark:text-slate-500">{m.resolution_method ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  ‹ Prev
                </button>
                <span>Page {page} / {totalPages}</span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  Next ›
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Unresolved cards section ──────────────────────────────────────────────────

// ── Resolution rule modal ─────────────────────────────────────────────────────

function ResolutionRuleModal({
  item,
  onClose,
  onResolved,
}: {
  item: UnresolvedCardItem;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [previewImg, setPreviewImg] = useState<string | null>(null);

  const handleClose = () => { onClose(); };

  const handleResolve = async (candidate: CardCandidateItem) => {
    if (!confirm(`Resolve "${item.raw_name}" as "${candidate.name}"?`)) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const body: ResolutionRuleCreate = {
        raw_name: item.raw_name,
        action: 'resolve',
        target_card_def_id: candidate.card_def_id,
        target_card_name: candidate.name,
        notes: 'Manual selected from observed-play review',
      };
      await createResolutionRule(body);
      const affected = item.affected_log_ids ?? [];
      for (const logId of affected) {
        try { await resolveCards(logId); } catch { /* continue on partial failure */ }
      }
      setSuccess(`Rule created: "${item.raw_name}" → "${candidate.name}"`);
      onResolved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to create rule');
    } finally {
      setSubmitting(false);
    }
  };

  const handleIgnore = async () => {
    if (!confirm(`Ignore "${item.raw_name}" in future card resolution? This will suppress it as a non-card/noise name.`)) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const body: ResolutionRuleCreate = {
        raw_name: item.raw_name,
        action: 'ignore',
        notes: 'Manual ignore from observed-play review',
      };
      await createResolutionRule(body);
      const affected = item.affected_log_ids ?? [];
      for (const logId of affected) {
        try { await resolveCards(logId); } catch { /* continue */ }
      }
      setSuccess(`Ignore rule created for "${item.raw_name}"`);
      onResolved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to create ignore rule');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 pt-16"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      <div className="relative mx-4 w-full max-w-2xl rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-xl">
        <button
          className="absolute right-4 top-4 text-gray-400 hover:text-gray-600 dark:text-slate-500 dark:hover:text-slate-300"
          onClick={handleClose}
          aria-label="Close"
        >
          <X size={18} />
        </button>
        <h2 className="mb-1 text-lg font-semibold text-gray-800 dark:text-white">Resolve Card Mention</h2>

        {/* Summary */}
        <div className="mb-4 rounded bg-gray-50 dark:bg-slate-800 px-4 py-3 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span><span className="font-medium">Raw name:</span> {item.raw_name}</span>
            <span><span className="font-medium">Normalized:</span> {item.normalized_name}</span>
            <span>
              <span className="font-medium">Status:</span>{' '}
              <span className={`rounded px-1 font-medium ${item.status === 'ambiguous' ? 'bg-yellow-200 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200' : 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300'}`}>
                {item.status}
              </span>
            </span>
            <span><span className="font-medium">Mentions:</span> {item.mention_count}</span>
            <span><span className="font-medium">Logs:</span> {item.log_count}</span>
          </div>
        </div>

        {/* Error / success messages */}
        {error && <div className="mb-3 rounded bg-red-50 dark:bg-red-950 px-3 py-2 text-sm text-red-700 dark:text-red-300">{error}</div>}
        {success && (
          <div className="mb-3 rounded bg-green-50 dark:bg-green-950 px-3 py-2 text-sm text-green-700 dark:text-green-300">
            {success}
            {(item.affected_log_ids?.length ?? 0) > 0 && (
              <span className="ml-2 text-green-600 dark:text-green-400">
                ({item.affected_log_ids!.length} affected log{item.affected_log_ids!.length > 1 ? 's' : ''} re-resolved)
              </span>
            )}
          </div>
        )}

        {/* Candidates */}
        {item.candidates && item.candidates.length > 0 ? (
          <>
            <h3 className="mb-2 text-sm font-semibold text-gray-700 dark:text-slate-200">Candidates</h3>
            <div className="mb-4 overflow-x-auto rounded border border-gray-200 dark:border-slate-700">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-gray-50 dark:bg-slate-800 text-left text-gray-600 dark:text-slate-300">
                    <th className="px-2 py-1.5"></th>
                    <th className="px-2 py-1.5">Name</th>
                    <th className="px-2 py-1.5">Set</th>
                    <th className="px-2 py-1.5">Number</th>
                    <th className="px-2 py-1.5">Card def ID</th>
                    <th className="px-2 py-1.5">Reason</th>
                    <th className="px-2 py-1.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {item.candidates.map((c) => {
                    const imgUrl = c.image_url ? normalizeTcgdexImageUrl(c.image_url, 'low') : null;
                    return (
                      <tr key={c.card_def_id} className="border-b last:border-0 hover:bg-gray-50 dark:hover:bg-slate-800/60">
                        <td className="px-2 py-1.5">
                          {imgUrl ? (
                            <img
                              src={imgUrl}
                              alt={c.name}
                              className="h-10 w-7 cursor-pointer rounded object-cover"
                              onClick={() => setPreviewImg(imgUrl)}
                            />
                          ) : (
                            <div className="h-10 w-7 rounded bg-gray-100 dark:bg-slate-700" />
                          )}
                        </td>
                        <td className="px-2 py-1.5 font-medium">{c.name}</td>
                        <td className="px-2 py-1.5 text-gray-500 dark:text-slate-400">{c.set_abbrev ?? '—'}</td>
                        <td className="px-2 py-1.5 text-gray-500 dark:text-slate-400">{c.set_number ?? '—'}</td>
                        <td className="px-2 py-1.5 font-mono text-gray-500 dark:text-slate-400">{c.card_def_id}</td>
                        <td className="px-2 py-1.5 text-gray-400 dark:text-slate-500">{c.reason ?? '—'}</td>
                        <td className="px-2 py-1.5">
                          <button
                            className="rounded bg-blue-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                            disabled={submitting || !!success}
                            onClick={() => handleResolve(c)}
                          >
                            Select
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="mb-4 text-sm text-gray-500 dark:text-slate-400">No candidates available for this name.</p>
        )}

        {/* Sample mentions */}
        {item.sample_mentions && item.sample_mentions.length > 0 && (
          <>
            <h3 className="mb-2 text-sm font-semibold text-gray-700 dark:text-slate-200">Sample mentions</h3>
            <div className="mb-4 overflow-x-auto rounded border border-gray-200 dark:border-slate-700">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-gray-50 dark:bg-slate-800 text-left text-gray-600 dark:text-slate-300">
                    <th className="px-2 py-1.5">Role</th>
                    <th className="px-2 py-1.5">Event type</th>
                    <th className="px-2 py-1.5">Turn</th>
                    <th className="px-2 py-1.5">Player</th>
                    <th className="px-2 py-1.5">Source line</th>
                  </tr>
                </thead>
                <tbody>
                  {item.sample_mentions.map((sm) => (
                    <tr key={sm.event_id} className="border-b last:border-0">
                      <td className="px-2 py-1 font-mono text-gray-500 dark:text-slate-400">{sm.mention_role}</td>
                      <td className="px-2 py-1 text-gray-500 dark:text-slate-400">{sm.source_event_type ?? '—'}</td>
                      <td className="px-2 py-1 text-center">{sm.turn_number ?? '—'}</td>
                      <td className="px-2 py-1 text-gray-500 dark:text-slate-400">{sm.player_alias ?? '—'}</td>
                      <td className="px-2 py-1 font-mono text-gray-400 dark:text-slate-500 truncate max-w-xs" title={sm.raw_line ?? ''}>{sm.raw_line ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 border-t pt-3">
          <button
            className="rounded bg-red-100 dark:bg-red-900/50 px-3 py-1.5 text-sm font-medium text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-900 disabled:opacity-50"
            disabled={submitting || !!success}
            onClick={handleIgnore}
          >
            Ignore this name
          </button>
          <button
            className="ml-auto rounded bg-gray-100 dark:bg-slate-800 px-3 py-1.5 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700"
            onClick={handleClose}
          >
            Close
          </button>
        </div>

        {/* Image lightbox */}
        {previewImg && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
            onClick={() => setPreviewImg(null)}
          >
            <img src={previewImg} alt="Card preview" className="max-h-[80vh] rounded shadow-xl" />
          </div>
        )}
      </div>
    </div>
  );
}

function UnresolvedCardsSection({
  onRefreshLogs,
  onRefreshAnalytics,
  refreshRef,
}: {
  onRefreshLogs?: () => void;
  onRefreshAnalytics?: () => void;
  refreshRef?: { current: (() => void) | null };
}) {
  const [items, setItems] = useState<UnresolvedCardItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [modalItem, setModalItem] = useState<UnresolvedCardItem | null>(null);

  const load = useCallback(() => {
    getUnresolvedCards({ per_page: 20 })
      .then((data) => { setItems(data.items); setTotal(data.total); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (refreshRef) refreshRef.current = load;
  });

  const handleResolved = () => {
    load();
    onRefreshLogs?.();
    onRefreshAnalytics?.();
  };

  if (loading) return null;
  if (items.length === 0 && !modalItem) return null;

  return (
    <>
      <section className="mb-8 rounded-lg border border-yellow-200 dark:border-amber-800 bg-yellow-50 dark:bg-amber-950/50 p-6 shadow-sm">
        <h2 className="mb-3 text-base font-semibold text-yellow-800 dark:text-amber-200">
          Unresolved / Ambiguous Cards
          <span className="ml-2 text-sm font-normal text-yellow-700 dark:text-amber-300">({total} unique names)</span>
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-yellow-200 dark:border-amber-800 text-left text-yellow-700 dark:text-amber-300">
                <th className="pb-1 pr-3">Raw name</th>
                <th className="pb-1 pr-3">Status</th>
                <th className="pb-1 pr-3">Mentions</th>
                <th className="pb-1 pr-3">Logs</th>
                <th className="pb-1 pr-3">Candidates</th>
                <th className="pb-1">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.normalized_name}-${item.status}`} className="border-b border-yellow-100 dark:border-amber-900 last:border-0">
                  <td className="py-0.5 pr-3 font-medium">{item.raw_name}</td>
                  <td className="py-0.5 pr-3">
                    <span className={`rounded px-1 text-xs font-medium ${
                      item.status === 'ambiguous'
                        ? 'bg-yellow-200 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200'
                        : 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300'
                    }`}>
                      {item.status}
                    </span>
                  </td>
                  <td className="py-0.5 pr-3 text-center">{item.mention_count}</td>
                  <td className="py-0.5 pr-3 text-center">{item.log_count}</td>
                  <td className="py-0.5 pr-3 text-gray-500 dark:text-slate-400">
                    {item.candidate_count > 0
                      ? `${item.candidate_count} candidate${item.candidate_count > 1 ? 's' : ''}`
                      : '—'}
                  </td>
                  <td className="py-0.5">
                    <button
                      className="rounded bg-blue-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-blue-700"
                      onClick={() => setModalItem(item)}
                      aria-label={`Review ${item.raw_name}`}
                    >
                      Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {modalItem && (
        <ResolutionRuleModal
          item={modalItem}
          onClose={() => setModalItem(null)}
          onResolved={handleResolved}
        />
      )}
    </>
  );
}

// ── Memory preview & ingest modal ─────────────────────────────────────────────

function MemoryPreviewModal({
  logId,
  onClose,
  onIngestSuccess,
}: {
  logId: string;
  onClose: () => void;
  onIngestSuccess: () => void;
}) {
  const [preview, setPreview] = useState<MemoryIngestionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<MemoryIngestionSummary | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [ingestBlockers, setIngestBlockers] = useState<IngestionBlocker[]>([]);
  const [ingestBlockersTruncated, setIngestBlockersTruncated] = useState(false);

  useEffect(() => {
    setLoading(true);
    previewMemoryIngestion(logId)
      .then(setPreview)
      .catch(() => setError('Failed to load preview.'))
      .finally(() => setLoading(false));
  }, [logId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  async function handleIngest(config: IngestionConfig = {}) {
    setIngesting(true);
    setIngestError(null);
    setIngestBlockers([]);
    setIngestBlockersTruncated(false);
    try {
      const result = await ingestMemory(logId, config);
      setIngestResult(result);
      onIngestSuccess();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: { message?: string; blockers?: IngestionBlocker[]; blocker_count?: number; blockers_truncated?: boolean } | string } } })?.response?.data?.detail;
      const msg = typeof detail === 'object' && detail?.message
        ? detail.message
        : (typeof detail === 'string' ? detail : 'Ingestion failed');
      setIngestError(msg);
      if (typeof detail === 'object' && detail?.blockers) {
        setIngestBlockers(detail.blockers);
        setIngestBlockersTruncated(detail.blockers_truncated ?? false);
      }
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-label="Memory Preview"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[90vh] w-full max-w-2xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>

        <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-white">Memory Preview</h2>
        <p className="mb-4 text-xs text-gray-500 dark:text-slate-400">
          Observed memories are stored for review only. They are not used by Coach or AI Player yet.
        </p>

        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading preview…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {preview && !ingestResult && (
          <>
            <div className={`mb-4 rounded border px-3 py-2 text-sm ${preview.eligible ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950 text-green-800 dark:text-green-300' : 'border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 text-red-800 dark:text-red-300'}`}>
              {preview.eligible
                ? `✓ Eligible — estimated ${preview.estimated_memory_item_count} memory items`
                : '✗ Not eligible for ingestion'}
            </div>

            {preview.reasons.length > 0 && (
              <div className="mb-4">
                <p className="mb-1 text-xs font-medium text-gray-600 dark:text-slate-300">Eligibility reasons:</p>
                <ul className="space-y-0.5 text-xs text-gray-600 dark:text-slate-300">
                  {preview.reasons.map((r: EligibilityReason) => (
                    <li key={r.code}>
                      <span className="font-mono text-red-700 dark:text-red-400">{r.code}</span>: {r.detail}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {preview.blockers && preview.blockers.length > 0 && (
              <div className="mb-4">
                <p className="mb-1 text-xs font-medium text-gray-600 dark:text-slate-300">Blocking unresolved mentions:</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-left text-gray-500 dark:text-slate-400">
                        <th className="pb-0.5 pr-2">Raw name</th>
                        <th className="pb-0.5 pr-2">Role</th>
                        <th className="pb-0.5 pr-2">Turn</th>
                        <th className="pb-0.5 pr-2">Player</th>
                        <th className="pb-0.5 pr-2">Event</th>
                        <th className="pb-0.5">Source line</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.blockers.map((b, i) => (
                        <tr key={i} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                          <td className="py-0.5 pr-2 font-medium text-red-700 dark:text-red-400">{b.raw_name ?? '—'}</td>
                          <td className="py-0.5 pr-2 font-mono text-gray-600 dark:text-slate-300">{b.mention_role ?? '—'}</td>
                          <td className="py-0.5 pr-2">{b.turn_number ?? '—'}</td>
                          <td className="py-0.5 pr-2">{b.player_alias ?? '—'}</td>
                          <td className="py-0.5 pr-2 text-gray-500 dark:text-slate-400">{b.source_event_type ?? '—'}</td>
                          <td className="py-0.5 max-w-[200px] truncate text-gray-500 dark:text-slate-400" title={b.raw_line ?? undefined}>{b.raw_line ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {preview.blockers_truncated && (
                  <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">Showing first {preview.blockers.length} blockers.</p>
                )}
              </div>
            )}

            {preview.metrics && (
              <div className="mb-4 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-gray-600 dark:text-slate-300">
                <span className="font-medium">Confidence</span>
                <span>{(preview.metrics.confidence_score * 100).toFixed(1)}%</span>
                <span className="font-medium">Events</span>
                <span>{preview.metrics.event_count}</span>
                <span className="font-medium">Card mentions</span>
                <span>{preview.metrics.card_mention_count}</span>
                <span className="font-medium">Unresolved</span>
                <span>{preview.metrics.unresolved_card_count}</span>
                <span className="font-medium">Ambiguous</span>
                <span>{preview.metrics.ambiguous_card_count}</span>
              </div>
            )}

            {preview.event_type_counts && Object.keys(preview.event_type_counts).length > 0 && (
              <div className="mb-4">
                <p className="mb-1 text-xs font-medium text-gray-600 dark:text-slate-300">Memory types to be created:</p>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(preview.event_type_counts).map(([k, v]) => (
                    <span key={k} className="rounded bg-gray-100 dark:bg-slate-700 px-2 py-0.5 text-xs">
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {preview.sample_items && preview.sample_items.length > 0 && (
              <div className="mb-4">
                <p className="mb-1 text-xs font-medium text-gray-600 dark:text-slate-300">Sample items (first {preview.sample_items.length}):</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-left text-gray-500 dark:text-slate-400">
                        <th className="pb-0.5 pr-2">Turn</th>
                        <th className="pb-0.5 pr-2">Type</th>
                        <th className="pb-0.5 pr-2">Actor</th>
                        <th className="pb-0.5 pr-2">Action</th>
                        <th className="pb-0.5 pr-2">Dmg</th>
                        <th className="pb-0.5">Conf</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.sample_items.map((item) => (
                        <tr key={item.event_id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                          <td className="py-0.5 pr-2">{item.turn_number ?? '—'}</td>
                          <td className="py-0.5 pr-2 text-gray-500 dark:text-slate-400">{item.memory_type}</td>
                          <td className="py-0.5 pr-2 font-medium">{item.actor_card_raw ?? '—'}</td>
                          <td className="py-0.5 pr-2">{item.action_name ?? '—'}</td>
                          <td className="py-0.5 pr-2">{item.damage ?? '—'}</td>
                          <td className="py-0.5">{(item.confidence_score * 100).toFixed(0)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {ingestError && (
              <div className="mb-3">
                <p className="text-sm text-red-600" role="alert">{ingestError}</p>
                {ingestBlockers.length > 0 && (
                  <div className="mt-2 overflow-x-auto">
                    <p className="mb-1 text-xs font-medium text-gray-600 dark:text-slate-300">Blocking unresolved mentions:</p>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b text-left text-gray-500 dark:text-slate-400">
                          <th className="pb-0.5 pr-2">Raw name</th>
                          <th className="pb-0.5 pr-2">Role</th>
                          <th className="pb-0.5 pr-2">Turn</th>
                          <th className="pb-0.5 pr-2">Player</th>
                          <th className="pb-0.5">Event</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ingestBlockers.map((b, i) => (
                          <tr key={i} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                            <td className="py-0.5 pr-2 font-medium text-red-700 dark:text-red-400">{b.raw_name ?? '—'}</td>
                            <td className="py-0.5 pr-2 font-mono text-gray-600 dark:text-slate-300">{b.mention_role ?? '—'}</td>
                            <td className="py-0.5 pr-2">{b.turn_number ?? '—'}</td>
                            <td className="py-0.5 pr-2">{b.player_alias ?? '—'}</td>
                            <td className="py-0.5 text-gray-500 dark:text-slate-400">{b.source_event_type ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {ingestBlockersTruncated && (
                      <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">Showing first {ingestBlockers.length} blockers.</p>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-2">
              {preview.eligible && (
                <button
                  onClick={() => handleIngest()}
                  disabled={ingesting}
                  className="rounded bg-teal-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
                >
                  {ingesting ? 'Ingesting…' : 'Ingest memory'}
                </button>
              )}

              <button
                onClick={onClose}
                className="rounded border border-gray-300 dark:border-slate-600 dark:text-slate-200 px-4 py-1.5 text-sm hover:bg-gray-50 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
            </div>
          </>
        )}

        {ingestResult && (
          <div className="text-sm">
            <p className="mb-2 font-medium text-green-700 dark:text-green-300">
              ✓ Ingestion {ingestResult.status} — {ingestResult.memory_item_count ?? 0} memory items created
            </p>
            <button
              onClick={onClose}
              className="rounded bg-gray-100 dark:bg-slate-800 dark:text-slate-200 px-4 py-1.5 text-sm hover:bg-gray-200 dark:hover:bg-slate-700"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Memory items viewer modal ─────────────────────────────────────────────────

function MemoryItemsModal({
  logId,
  onClose,
}: {
  logId: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<PaginatedMemoryItems | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [memoryTypeFilter, setMemoryTypeFilter] = useState('');
  const PER_PAGE = 50;

  const load = useCallback(
    (p: number) => {
      setLoading(true);
      setError(null);
      getMemoryItems(logId, {
        page: p,
        per_page: PER_PAGE,
        memory_type: memoryTypeFilter || undefined,
      })
        .then(setData)
        .catch(() => setError('Failed to load memory items.'))
        .finally(() => setLoading(false));
    },
    [logId, memoryTypeFilter],
  );

  useEffect(() => { load(page); }, [page, load]);

  useEffect(() => {
    setPage(1);
    load(1);
  }, [memoryTypeFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PER_PAGE)) : 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-label="Memory Items"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>

        <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-white">Memory Items</h2>
        <p className="mb-3 text-xs text-gray-500 dark:text-slate-400">
          Observed memories are stored for review only. They are not used by Coach or AI Player yet.
        </p>

        <div className="mb-3 flex items-center gap-3">
          <label className="text-xs text-gray-600 dark:text-slate-300">Filter by type:</label>
          <input
            type="text"
            value={memoryTypeFilter}
            onChange={(e) => setMemoryTypeFilter(e.target.value)}
            placeholder="e.g. attack_used"
            className="rounded border border-gray-300 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 px-2 py-0.5 text-xs w-36"
          />
          {data && <span className="text-xs text-gray-500 dark:text-slate-400">{data.total} total</span>}
        </div>

        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-gray-500 dark:text-slate-400">
                  <th className="pb-1 pr-2">Turn</th>
                  <th className="pb-1 pr-2">Type</th>
                  <th className="pb-1 pr-2">Player</th>
                  <th className="pb-1 pr-2">Actor</th>
                  <th className="pb-1 pr-2">Action</th>
                  <th className="pb-1 pr-2">Target</th>
                  <th className="pb-1 pr-2">Dmg/Amt</th>
                  <th className="pb-1 pr-2">Conf</th>
                  <th className="pb-1">Source line</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item: MemoryItemSummary) => (
                  <tr key={item.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                    <td className="py-0.5 pr-2">{item.turn_number ?? '—'}</td>
                    <td className="py-0.5 pr-2 text-gray-500 dark:text-slate-400">{item.memory_type}</td>
                    <td className="py-0.5 pr-2">{item.player_alias ?? item.player_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2 font-medium">{item.actor_card_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2">{item.action_name ?? '—'}</td>
                    <td className="py-0.5 pr-2">{item.target_card_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2">
                      {item.damage != null ? `${item.damage} dmg` : item.amount != null ? `${item.amount}` : '—'}
                    </td>
                    <td className="py-0.5 pr-2">
                      <ConfidenceBadge score={item.confidence_score} />
                    </td>
                    <td className="py-0.5 max-w-xs truncate text-gray-400 dark:text-slate-500" title={item.source_raw_line ?? ''}>
                      {item.source_raw_line ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pages > 1 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  ‹ Prev
                </button>
                <span>Page {page} / {pages}</span>
                <button
                  onClick={() => setPage((p) => Math.min(pages, p + 1))}
                  disabled={page >= pages}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                >
                  Next ›
                </button>
              </div>
            )}
          </div>
        )}
        {data && data.items.length === 0 && !loading && (
          <p className="text-sm text-gray-400 dark:text-slate-500">No memory items found.</p>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-3 py-2">
      <p className="text-xs text-gray-500 dark:text-slate-400">{label}</p>
      <p className="text-lg font-semibold text-slate-900 dark:text-white">{String(value)}</p>
    </div>
  );
}

function AnalyticsGroupTable({
  title,
  groups,
  onViewExamples,
  onReview,
}: {
  title: string;
  groups: MemoryAnalyticsGroup[];
  onViewExamples: (g: MemoryAnalyticsGroup) => void;
  onReview?: (g: MemoryAnalyticsGroup) => void;
}) {
  return (
    <div className="mb-4">
      <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full table-fixed text-xs">
          <colgroup>
            <col className="w-[34%]" />
            <col className="w-[7%]" />
            <col className="w-[9%]" />
            <col className="w-[10%]" />
            <col className="w-[8%]" />
            <col className="w-[11%]" />
            <col className="w-[10%]" />
            <col className="w-[11%]" />
          </colgroup>
          <thead className="bg-gray-50 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Label</th>
              <th className="px-2 py-1 text-right font-medium">Count</th>
              <th className="px-2 py-1 text-center font-medium">Avg conf</th>
              <th className="px-2 py-1 text-center font-medium">Resolved</th>
              <th className="px-2 py-1 text-center font-medium">Ambig</th>
              <th className="px-2 py-1 text-center font-medium">Unresolved</th>
              <th className="px-2 py-1 text-center font-medium">Examples</th>
              <th className="px-2 py-1 text-center font-medium">Review</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
            {groups.map((g) => (
              <tr key={g.label} className="hover:bg-gray-50 dark:hover:bg-slate-800">
                <td className="px-2 py-1 text-slate-900 dark:text-slate-100 truncate" title={g.label}>{g.label}</td>
                <td className="px-2 py-1 text-right text-slate-700 dark:text-slate-300">{g.count}</td>
                <td className="px-2 py-1 text-center text-slate-700 dark:text-slate-300">
                  {g.average_confidence != null ? `${(g.average_confidence * 100).toFixed(0)}%` : '—'}
                </td>
                <td className="px-2 py-1 text-center text-green-700 dark:text-green-400">{g.resolved_count}</td>
                <td className="px-2 py-1 text-center text-yellow-700 dark:text-yellow-400">{g.ambiguous_count}</td>
                <td className="px-2 py-1 text-center text-red-700 dark:text-red-400">{g.unresolved_count}</td>
                <td className="px-2 py-1 text-center">
                  <button
                    onClick={() => onViewExamples(g)}
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    Examples
                  </button>
                </td>
                <td className="px-2 py-1 text-center">
                  {onReview && g.can_review_resolution && (g.ambiguous_count + g.unresolved_count) > 0 ? (
                    <button
                      onClick={() => onReview(g)}
                      className="text-yellow-600 dark:text-yellow-400 hover:underline"
                    >
                      Review
                    </button>
                  ) : (
                    <span className="text-gray-300 dark:text-slate-600" aria-label="Not reviewable">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MemoryAnalyticsExamplesModal({
  items,
  total,
  loading,
  onClose,
  filterLabel,
}: {
  items: MemoryItemSummary[];
  total: number;
  loading: boolean;
  onClose: () => void;
  filterLabel?: string;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-label="Memory Examples"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white dark:bg-slate-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-100"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <h2 className="mb-1 text-lg font-semibold text-slate-900 dark:text-white">Memory Examples</h2>
        {filterLabel && <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">Filter: {filterLabel}</p>}
        <p className="mb-3 text-xs text-gray-500 dark:text-slate-400">{total} matching items</p>
        {loading && <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>}
        {!loading && items.length === 0 && (
          <p className="text-sm text-gray-400 dark:text-slate-500">No items found.</p>
        )}
        {!loading && items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-gray-500 dark:text-slate-400">
                  <th className="pb-1 pr-2">Type</th>
                  <th className="pb-1 pr-2">Turn</th>
                  <th className="pb-1 pr-2">Player</th>
                  <th className="pb-1 pr-2">Actor</th>
                  <th className="pb-1 pr-2">Action</th>
                  <th className="pb-1 pr-2">Target</th>
                  <th className="pb-1 pr-2">Dmg/Amt</th>
                  <th className="pb-1 pr-2">Conf</th>
                  <th className="pb-1">Source line</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                    <td className="py-0.5 pr-2 text-gray-500 dark:text-slate-400">{item.memory_type}</td>
                    <td className="py-0.5 pr-2">{item.turn_number ?? '—'}</td>
                    <td className="py-0.5 pr-2">{item.player_alias ?? item.player_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2 font-medium">{item.actor_card_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2">{item.action_name ?? '—'}</td>
                    <td className="py-0.5 pr-2">{item.target_card_raw ?? '—'}</td>
                    <td className="py-0.5 pr-2">
                      {item.damage != null ? `${item.damage} dmg` : item.amount != null ? `${item.amount}` : '—'}
                    </td>
                    <td className="py-0.5 pr-2">
                      <ConfidenceBadge score={item.confidence_score} />
                    </td>
                    <td className="py-0.5 max-w-xs truncate text-gray-400 dark:text-slate-500" title={item.source_raw_line ?? ''}>
                      {item.source_raw_line ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Phase 5.2: Corpus Readiness Scorecard ────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: CorpusReadinessReport['verdict'] }) {
  const cfg = {
    ready: { label: 'Ready for limited downstream experimentation', cls: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 border-green-300 dark:border-green-700' },
    needs_review: { label: 'Needs Review', cls: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 border-yellow-300 dark:border-yellow-700' },
    not_ready: { label: 'Not Ready', cls: 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 border-red-300 dark:border-red-700' },
  }[verdict];
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

function ScorecardStatRow({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <tr className="border-b border-gray-100 dark:border-slate-800 last:border-0">
      <td className="py-0.5 pr-3 text-gray-500 dark:text-slate-400 w-1/2">{label}</td>
      <td className="py-0.5 font-mono font-medium text-gray-900 dark:text-white">{value}</td>
      {note && <td className="py-0.5 pl-2 text-gray-400 dark:text-slate-500 text-xs">{note}</td>}
    </tr>
  );
}

function CorpusScorecardSection() {
  const [report, setReport] = useState<CorpusReadinessReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await getCorpusReadiness());
    } catch {
      setError('Failed to load corpus readiness scorecard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const pct = (n: number, d: number) => d > 0 ? `${Math.round((n / d) * 100)}%` : 'n/a';
  const fmt = (v: number | null | undefined, digits = 4) =>
    v != null ? v.toFixed(digits) : '—';

  return (
    <section
      className="mb-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 shadow-sm"
      data-testid="corpus-scorecard-section"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">
          Observed Play Corpus Quality / Readiness Scorecard
        </h2>
        <button
          onClick={() => load()}
          disabled={loading}
          className="rounded border border-gray-300 dark:border-slate-600 px-2 py-0.5 text-xs text-gray-600 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-800 disabled:opacity-40"
        >
          {loading ? 'Loading…' : 'Refresh scorecard'}
        </button>
      </div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-4" data-testid="scorecard-safety-note">
        Observed memories are still review-only and are not used by Coach, AI Player, simulator
        runtime, deck builder, pgvector, Neo4j, match_events, or card_performance.
      </p>

      {error && (
        <p className="text-sm text-red-600 dark:text-red-400 mb-3" data-testid="scorecard-error">{error}</p>
      )}

      {!loading && !error && report === null && (
        <p className="text-sm text-gray-400 dark:text-slate-500" data-testid="scorecard-empty">
          No observed-play corpus data found. Upload logs before reviewing readiness.
        </p>
      )}

      {report && (
        <>
          {/* Verdict + score bar */}
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <VerdictBadge verdict={report.verdict} />
            <span className="text-xs text-gray-500 dark:text-slate-400">
              Readiness score:&nbsp;
              <span
                className="font-mono font-semibold text-gray-900 dark:text-white"
                data-testid="readiness-score"
              >
                {report.readiness_score.toFixed(1)}&nbsp;/&nbsp;100
              </span>
            </span>
            <span className="text-xs text-gray-400 dark:text-slate-500">
              Generated {new Date(report.generated_at).toLocaleString()}
            </span>
          </div>

          {/* Empty corpus message */}
          {report.corpus.log_count === 0 && (
            <p className="text-sm text-gray-400 dark:text-slate-500 mb-4" data-testid="scorecard-no-logs">
              No observed-play corpus data found. Upload logs before reviewing readiness.
            </p>
          )}

          {/* Stats grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            {/* Corpus coverage */}
            <div>
              <h3 className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wide">
                Corpus Coverage
              </h3>
              <table className="w-full text-xs">
                <tbody>
                  <ScorecardStatRow label="Logs" value={report.corpus.log_count} />
                  <ScorecardStatRow
                    label="Parsed"
                    value={`${report.corpus.parsed_log_count} / ${report.corpus.log_count}`}
                    note={pct(report.corpus.parsed_log_count, report.corpus.log_count)}
                  />
                  <ScorecardStatRow
                    label="Ingested"
                    value={`${report.corpus.ingested_log_count} / ${report.corpus.log_count}`}
                    note={pct(report.corpus.ingested_log_count, report.corpus.log_count)}
                  />
                  <ScorecardStatRow label="Failed logs" value={report.corpus.failed_log_count} />
                  <ScorecardStatRow label="Events" value={report.corpus.event_count.toLocaleString()} />
                  <ScorecardStatRow label="Memory items" value={report.corpus.memory_item_count.toLocaleString()} />
                </tbody>
              </table>
            </div>

            {/* Parser quality */}
            <div>
              <h3 className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wide">
                Parser Quality
              </h3>
              <table className="w-full text-xs">
                <tbody>
                  <ScorecardStatRow label="Unknown events" value={report.parser_quality.unknown_event_count} />
                  <ScorecardStatRow
                    label={`Events below ${(report.parser_quality.low_confidence_threshold * 100).toFixed(0)}%`}
                    value={report.parser_quality.low_confidence_event_count}
                  />
                  <ScorecardStatRow
                    label="Avg event confidence"
                    value={fmt(report.parser_quality.avg_event_confidence)}
                  />
                  <ScorecardStatRow
                    label="Avg log confidence"
                    value={fmt(report.parser_quality.avg_log_confidence)}
                  />
                  <ScorecardStatRow
                    label="Min log confidence"
                    value={fmt(report.parser_quality.min_log_confidence)}
                  />
                  <ScorecardStatRow
                    label="Logs below ingestion threshold"
                    value={report.parser_quality.logs_below_ingestion_threshold}
                  />
                </tbody>
              </table>
            </div>

            {/* Card resolution */}
            <div>
              <h3 className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wide">
                Card Resolution Burden
              </h3>
              <table className="w-full text-xs">
                <tbody>
                  <ScorecardStatRow label="Total card mentions" value={report.card_resolution.card_mention_count.toLocaleString()} />
                  <ScorecardStatRow
                    label="Resolved"
                    value={`${report.card_resolution.resolved_count.toLocaleString()} / ${report.card_resolution.card_mention_count.toLocaleString()}`}
                    note={pct(report.card_resolution.resolved_count, report.card_resolution.card_mention_count)}
                  />
                  <ScorecardStatRow label="Ambiguous" value={report.card_resolution.ambiguous_count} />
                  <ScorecardStatRow label="Unresolved" value={report.card_resolution.unresolved_count} />
                  <ScorecardStatRow label="Critical unresolved" value={report.card_resolution.critical_unresolved_count} />
                </tbody>
              </table>
              {report.card_resolution.top_ambiguous.length > 0 && (
                <div className="mt-1">
                  <span className="text-xs text-gray-400 dark:text-slate-500">Top ambiguous: </span>
                  <span className="text-xs font-mono text-gray-700 dark:text-slate-300">
                    {report.card_resolution.top_ambiguous.slice(0, 5).join(', ')}
                  </span>
                </div>
              )}
              {report.card_resolution.top_unresolved.length > 0 && (
                <div className="mt-0.5">
                  <span className="text-xs text-gray-400 dark:text-slate-500">Top unresolved: </span>
                  <span className="text-xs font-mono text-gray-700 dark:text-slate-300">
                    {report.card_resolution.top_unresolved.slice(0, 5).join(', ')}
                  </span>
                </div>
              )}
            </div>

            {/* Memory quality */}
            <div>
              <h3 className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wide">
                Memory Quality
              </h3>
              <table className="w-full text-xs">
                <tbody>
                  <ScorecardStatRow
                    label="Avg memory confidence"
                    value={fmt(report.memory_quality.avg_memory_confidence)}
                  />
                  <ScorecardStatRow
                    label="Low-confidence items"
                    value={report.memory_quality.low_confidence_memory_item_count}
                  />
                  <ScorecardStatRow
                    label="Ambiguous ref items"
                    value={report.memory_quality.ambiguous_reference_item_count}
                  />
                  <ScorecardStatRow
                    label="Unresolved ref items"
                    value={report.memory_quality.unresolved_reference_item_count}
                  />
                </tbody>
              </table>
              {report.memory_quality.memory_type_counts.length > 0 && (
                <div className="mt-2">
                  <span className="text-xs text-gray-400 dark:text-slate-500 block mb-0.5">Memory types:</span>
                  <div className="flex flex-wrap gap-1">
                    {report.memory_quality.memory_type_counts.slice(0, 6).map((mt) => (
                      <span key={mt.memory_type} className="text-xs rounded bg-gray-100 dark:bg-slate-800 px-1 py-0.5 font-mono">
                        {mt.memory_type}&nbsp;
                        <span className="font-semibold">{mt.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Blockers */}
          {report.blockers.length > 0 && (
            <div className="mb-3 rounded border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 p-3" data-testid="scorecard-blockers">
              <h3 className="text-xs font-semibold text-red-700 dark:text-red-300 mb-1">Blockers</h3>
              <ul className="text-xs text-red-700 dark:text-red-300 list-disc list-inside space-y-0.5">
                {report.blockers.map((b, i) => <li key={i}>{b}</li>)}
              </ul>
            </div>
          )}

          {/* Warnings */}
          {report.warnings.length > 0 && (
            <div className="mb-3 rounded border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950 p-3" data-testid="scorecard-warnings">
              <h3 className="text-xs font-semibold text-yellow-700 dark:text-yellow-300 mb-1">Warnings</h3>
              <ul className="text-xs text-yellow-700 dark:text-yellow-300 list-disc list-inside space-y-0.5">
                {report.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {/* Recommendations */}
          {report.recommendations.length > 0 && (
            <div className="mb-1 rounded border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950 p-3" data-testid="scorecard-recommendations">
              <h3 className="text-xs font-semibold text-blue-700 dark:text-blue-300 mb-1">Recommendations</h3>
              <ul className="text-xs text-blue-700 dark:text-blue-300 list-disc list-inside space-y-0.5">
                {report.recommendations.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

// ── Phase 6.0: Coach Advisory Evidence ───────────────────────────────────────

const COACH_EVIDENCE_DEFAULT_MIN_CONFIDENCE = 0.80;
const COACH_EVIDENCE_DEFAULT_LIMIT = 25;
const COACH_EVIDENCE_MAX_LIMIT = 100;

function CoachEvidenceSection() {
  const [cardName, setCardName] = useState('');
  const [memoryType, setMemoryType] = useState('');
  const [actionName, setActionName] = useState('');
  const [minConfidence, setMinConfidence] = useState(COACH_EVIDENCE_DEFAULT_MIN_CONFIDENCE);
  const [limit, setLimit] = useState(COACH_EVIDENCE_DEFAULT_LIMIT);

  const [response, setResponse] = useState<CoachEvidenceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<string[]>([]);

  const search = useCallback(async () => {
    setLoading(true);
    setError(null);
    setBlockers([]);
    try {
      const data = await getCoachEvidence({
        card_name: cardName || undefined,
        memory_type: memoryType || undefined,
        action_name: actionName || undefined,
        min_confidence: minConfidence,
        limit,
      });
      setResponse(data);
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { message?: string; blockers?: string[] } } };
      if (err?.response?.status === 409) {
        const detail = err?.response?.data;
        setError(detail?.message ?? 'Corpus not ready for evidence retrieval.');
        setBlockers(detail?.blockers ?? []);
      } else {
        setError('Failed to load coach evidence.');
      }
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }, [cardName, memoryType, actionName, minConfidence, limit]);

  return (
    <section className="mt-8 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950/30 p-6">
      <h2 className="text-xl font-bold text-indigo-900 dark:text-indigo-200 mb-1">
        Coach Evidence Preview
      </h2>
      <p className="text-sm text-indigo-700 dark:text-indigo-400 mb-4">
        Review-only advisory evidence. Not used by Coach/AI runtime decisions yet.
      </p>

      {/* Search controls */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-slate-300 mb-1">Card name</label>
          <input
            className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-white px-2 py-1.5 text-sm"
            type="text"
            placeholder="e.g. Dragapult ex"
            value={cardName}
            onChange={(e) => setCardName(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-slate-300 mb-1">Memory type</label>
          <input
            className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-white px-2 py-1.5 text-sm"
            type="text"
            placeholder="e.g. attack_used"
            value={memoryType}
            onChange={(e) => setMemoryType(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-slate-300 mb-1">Action / attack name</label>
          <input
            className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-white px-2 py-1.5 text-sm"
            type="text"
            placeholder="e.g. Phantom Dive"
            value={actionName}
            onChange={(e) => setActionName(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-slate-300 mb-1">Min confidence</label>
          <input
            className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-white px-2 py-1.5 text-sm"
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={minConfidence}
            onChange={(e) => setMinConfidence(parseFloat(e.target.value) || 0)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-slate-300 mb-1">Limit (max {COACH_EVIDENCE_MAX_LIMIT})</label>
          <input
            className="w-full rounded border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-900 dark:text-white px-2 py-1.5 text-sm"
            type="number"
            min="1"
            max={COACH_EVIDENCE_MAX_LIMIT}
            value={limit}
            onChange={(e) => setLimit(parseInt(e.target.value) || COACH_EVIDENCE_DEFAULT_LIMIT)}
          />
        </div>
        <div className="flex items-end">
          <button
            onClick={search}
            disabled={loading}
            className="w-full rounded bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            {loading ? 'Searching…' : 'Search / Refresh'}
          </button>
        </div>
      </div>

      {/* Error / blockers */}
      {error && (
        <div className="rounded bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-700 p-3 mb-4 text-sm text-red-800 dark:text-red-300">
          <strong>Error:</strong> {error}
          {blockers.length > 0 && (
            <ul className="mt-1 list-disc list-inside">
              {blockers.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Warnings */}
      {response && response.warnings.length > 0 && (
        <div className="rounded bg-yellow-50 dark:bg-yellow-950/30 border border-yellow-200 dark:border-yellow-700 p-3 mb-4 text-sm text-yellow-800 dark:text-yellow-300">
          {response.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {/* Summary */}
      {response && (
        <div className="mb-4">
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="rounded bg-indigo-100 dark:bg-indigo-900/50 px-3 py-1 text-indigo-900 dark:text-indigo-200">
              {response.summary.matching_item_count} matching items
            </span>
            {response.summary.avg_confidence != null && (
              <span className="rounded bg-indigo-100 dark:bg-indigo-900/50 px-3 py-1 text-indigo-900 dark:text-indigo-200">
                avg confidence {(response.summary.avg_confidence * 100).toFixed(1)}%
              </span>
            )}
            {response.summary.memory_type_counts.slice(0, 3).map((t) => (
              <span key={t.memory_type} className="rounded bg-slate-100 dark:bg-slate-800 px-3 py-1 text-gray-700 dark:text-slate-300">
                {t.memory_type}: {t.count}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Evidence table */}
      {response && response.evidence.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-slate-400">No matching evidence found.</p>
      )}

      {response && response.evidence.length > 0 && (
        <div className="overflow-x-auto rounded border border-gray-200 dark:border-slate-700">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 dark:bg-slate-800">
              <tr>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Type</th>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Actor</th>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Target</th>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Action</th>
                <th className="text-right px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Conf.</th>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Turn</th>
                <th className="text-left px-2 py-1.5 text-gray-600 dark:text-slate-300 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {response.evidence.map((item: CoachEvidenceItem, i: number) => (
                <tr key={item.memory_item_id} className={i % 2 === 0 ? 'bg-white dark:bg-slate-900' : 'bg-gray-50 dark:bg-slate-800/50'}>
                  <td className="px-2 py-1.5 text-gray-700 dark:text-slate-300 whitespace-nowrap">{item.memory_type}</td>
                  <td className="px-2 py-1.5 text-gray-900 dark:text-white">{item.actor_card_raw ?? '—'}</td>
                  <td className="px-2 py-1.5 text-gray-700 dark:text-slate-300">{item.target_card_raw ?? '—'}</td>
                  <td className="px-2 py-1.5 text-gray-700 dark:text-slate-300">{item.action_name ?? '—'}</td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    <span className={item.confidence_score >= 0.9 ? 'text-green-700 dark:text-green-400' : item.confidence_score >= 0.8 ? 'text-yellow-700 dark:text-yellow-400' : 'text-red-700 dark:text-red-400'}>
                      {(item.confidence_score * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-gray-500 dark:text-slate-400">{item.turn_number ?? '—'}</td>
                  <td className="px-2 py-1.5 max-w-xs">
                    <div className="text-gray-500 dark:text-slate-500 truncate" title={item.filename}>{item.filename}</div>
                    {item.source_raw_line && (
                      <div className="text-gray-400 dark:text-slate-600 font-mono truncate text-xs mt-0.5" title={item.source_raw_line}>{item.source_raw_line}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MemoryAnalyticsSection({
  refreshRef,
  onRefreshLogs,
  onRefreshUnresolved,
}: {
  refreshRef?: { current: (() => void) | null };
  onRefreshLogs?: () => void;
  onRefreshUnresolved?: () => void;
}) {
  const [summary, setSummary] = useState<MemorySummary | null>(null);
  const [analytics, setAnalytics] = useState<MemoryAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [examplesFilter, setExamplesFilter] = useState<MemoryAnalyticsSourceItemsParams | null>(null);
  const [examplesItems, setExamplesItems] = useState<MemoryItemSummary[]>([]);
  const [examplesTotal, setExamplesTotal] = useState(0);
  const [examplesLoading, setExamplesLoading] = useState(false);
  const [qualityFilter, setQualityFilter] = useState<'all' | 'ambiguous' | 'low_confidence' | 'unresolved'>('all');
  const [unresolvedLookup, setUnresolvedLookup] = useState<Record<string, UnresolvedCardItem>>({});
  const [reviewItem, setReviewItem] = useState<UnresolvedCardItem | null>(null);
  const [examplesFilterLabel, setExamplesFilterLabel] = useState<string>('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const analyticsParams = qualityFilter !== 'all' ? { quality_filter: qualityFilter } : {};
      const [s, a, unresolvedData] = await Promise.all([
        getMemorySummary(),
        getMemoryAnalytics(analyticsParams),
        getUnresolvedCards({ per_page: 100 }),
      ]);
      setSummary(s);
      setAnalytics(a);
      const lookup: Record<string, UnresolvedCardItem> = {};
      for (const item of unresolvedData.items) {
        lookup[item.raw_name] = item;
      }
      setUnresolvedLookup(lookup);
    } catch {
      setError('Failed to load memory analytics.');
    } finally {
      setLoading(false);
    }
  }, [qualityFilter]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (refreshRef) refreshRef.current = load;
  });

  async function openExamples(filter: MemoryAnalyticsSourceItemsParams, label?: string) {
    setExamplesFilter(filter);
    setExamplesFilterLabel(label ?? '');
    setExamplesLoading(true);
    try {
      const res = await getMemoryAnalyticsSourceItems({ ...filter, per_page: 20 });
      setExamplesItems(res.items);
      setExamplesTotal(res.total);
    } catch {
      setExamplesItems([]);
      setExamplesTotal(0);
    } finally {
      setExamplesLoading(false);
    }
  }

  function handleReview(g: MemoryAnalyticsGroup) {
    const rawName = g.review_raw_name;
    if (!rawName) return;
    const item = unresolvedLookup[rawName];
    if (item) {
      setReviewItem(item);
    }
  }

  function handleReviewResolved() {
    load();
    onRefreshLogs?.();
    onRefreshUnresolved?.();
  }

  return (
    <section className="mb-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">Memory Analytics</h2>
        <button
          onClick={() => load()}
          disabled={loading}
          className="rounded border border-gray-300 dark:border-slate-600 px-2 py-0.5 text-xs text-gray-600 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-800 disabled:opacity-40"
        >
          {loading ? 'Loading…' : 'Refresh analytics'}
        </button>
      </div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-4">
        Observed memories are for review only. They are not used by Coach or AI Player yet.
      </p>

      {/* Quality filter controls */}
      <div className="flex flex-wrap gap-2 mb-4">
        {(['all', 'ambiguous', 'low_confidence', 'unresolved'] as const).map((f) => {
          const labels = {
            all: 'All',
            ambiguous: 'Ambiguous refs',
            low_confidence: 'Low confidence',
            unresolved: 'Unresolved refs',
          };
          return (
            <button
              key={f}
              onClick={() => setQualityFilter(f)}
              className={`rounded border px-2 py-0.5 text-xs ${
                qualityFilter === f
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 font-medium'
                  : 'border-gray-300 dark:border-slate-600 text-gray-600 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-800'
              }`}
              aria-pressed={qualityFilter === f}
            >
              {labels[f]}
            </button>
          );
        })}
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {summary && summary.memory_item_count === 0 && (
        <p className="text-sm text-gray-500 dark:text-slate-400">
          No observed memories have been ingested yet. Preview and ingest eligible logs above to populate analytics.
        </p>
      )}

      {summary && summary.memory_item_count > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <StatCard label="Ingested logs" value={summary.ingested_log_count} />
          <StatCard label="Memory items" value={summary.memory_item_count} />
          <StatCard
            label="Avg confidence"
            value={summary.average_confidence != null ? `${(summary.average_confidence * 100).toFixed(0)}%` : '—'}
          />
          <StatCard label="Low confidence" value={summary.low_confidence_count} />
          <StatCard label="Ambiguous refs" value={summary.ambiguous_reference_count} />
          <StatCard label="Unresolved refs" value={summary.unresolved_reference_count} />
        </div>
      )}

      {analytics && analytics.top_memory_types.length > 0 && (
        <AnalyticsGroupTable
          title="Memory types"
          groups={analytics.top_memory_types}
          onViewExamples={(g) => openExamples({ memory_type: g.label }, g.label)}
        />
      )}

      {analytics && analytics.top_actions.length > 0 && (
        <AnalyticsGroupTable
          title="Top actions"
          groups={analytics.top_actions}
          onViewExamples={(g) => {
            const [mt, ...rest] = g.label.split(':');
            openExamples({ memory_type: mt, action_name: rest.join(':') }, g.label);
          }}
        />
      )}

      {analytics && analytics.top_actor_cards.length > 0 && (
        <AnalyticsGroupTable
          title="Top actor cards"
          groups={analytics.top_actor_cards}
          onViewExamples={(g) => openExamples({ actor_card_raw: g.label }, g.label)}
          onReview={handleReview}
        />
      )}

      {analytics && analytics.top_target_cards.length > 0 && (
        <AnalyticsGroupTable
          title="Top target cards"
          groups={analytics.top_target_cards}
          onViewExamples={(g) => openExamples({ target_card_raw: g.label }, g.label)}
          onReview={handleReview}
        />
      )}

      {analytics && analytics.top_attacks.length > 0 && (
        <AnalyticsGroupTable
          title="Top attacks"
          groups={analytics.top_attacks}
          onViewExamples={(g) => {
            const [actor, ...rest] = g.label.split(':');
            openExamples({ memory_type: 'attack_used', actor_card_raw: actor, action_name: rest.join(':') }, g.label);
          }}
        />
      )}

      {analytics && analytics.top_abilities.length > 0 && (
        <AnalyticsGroupTable
          title="Top abilities"
          groups={analytics.top_abilities}
          onViewExamples={(g) => {
            const [actor, ...rest] = g.label.split(':');
            openExamples({ memory_type: 'ability_used', actor_card_raw: actor, action_name: rest.join(':') }, g.label);
          }}
        />
      )}

      {analytics && analytics.top_attachments.length > 0 && (
        <AnalyticsGroupTable
          title="Top attachments"
          groups={analytics.top_attachments}
          onViewExamples={(g) => openExamples({ memory_type: 'card_attached', target_card_raw: g.label }, g.label)}
          onReview={handleReview}
        />
      )}

      {analytics && analytics.top_evolutions.length > 0 && (
        <AnalyticsGroupTable
          title="Top evolutions"
          groups={analytics.top_evolutions}
          onViewExamples={(g) => openExamples({ memory_type: 'card_evolved', actor_card_raw: g.label }, g.label)}
          onReview={handleReview}
        />
      )}

      {analytics && analytics.top_knockouts.length > 0 && (
        <AnalyticsGroupTable
          title="Top knockouts"
          groups={analytics.top_knockouts}
          onViewExamples={(g) => openExamples({ memory_type: 'knockout', target_card_raw: g.label }, g.label)}
          onReview={handleReview}
        />
      )}

      {analytics && analytics.quality_flags.length > 0 && (
        <AnalyticsGroupTable
          title="Quality flags"
          groups={analytics.quality_flags}
          onViewExamples={(g) => openExamples({ quality_flag: g.label }, g.label)}
        />
      )}

      <p className="mt-2 text-xs text-gray-400 dark:text-slate-500 italic">
        Resolution rules update parsed card mention metadata. Re-ingest logs to reflect changed resolution details in memory items.
      </p>

      {examplesFilter && (
        <MemoryAnalyticsExamplesModal
          items={examplesItems}
          total={examplesTotal}
          loading={examplesLoading}
          filterLabel={examplesFilterLabel}
          onClose={() => { setExamplesFilter(null); setExamplesFilterLabel(''); }}
        />
      )}

      {reviewItem && (
        <ResolutionRuleModal
          item={reviewItem}
          onClose={() => setReviewItem(null)}
          onResolved={handleReviewResolved}
        />
      )}
    </section>
  );
}

export default function ObservedPlay() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<ObservedPlayUploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [batches, setBatches] = useState<ObservedPlayBatch[]>([]);
  const [batchTotal, setBatchTotal] = useState(0);
  const [batchPage, setBatchPage] = useState(1);
  const [batchLoading, setBatchLoading] = useState(true);

  const [logs, setLogs] = useState<ObservedPlayLog[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [logPage, setLogPage] = useState(1);
  const [logLoading, setLogLoading] = useState(true);
  const [logSortBy, setLogSortBy] = useState<LogSortKey>('created_at');
  const [logSortDir, setLogSortDir] = useState<'asc' | 'desc'>('desc');

  const [viewLogId, setViewLogId] = useState<string | null>(null);
  const [viewEventsLogId, setViewEventsLogId] = useState<string | null>(null);
  const [viewCardMentionsLogId, setViewCardMentionsLogId] = useState<string | null>(null);
  const [memoryPreviewLogId, setMemoryPreviewLogId] = useState<string | null>(null);
  const [memoryItemsLogId, setMemoryItemsLogId] = useState<string | null>(null);

  // Bulk action state
  const [bulkParseOpen, setBulkParseOpen] = useState(false);
  const [bulkParseRunning, setBulkParseRunning] = useState(false);
  const [bulkParseResult, setBulkParseResult] = useState<BulkReparseSummary | null>(null);
  const [bulkParseError, setBulkParseError] = useState<string | null>(null);
  const [bulkIncludeIngested, setBulkIncludeIngested] = useState(false);

  const [bulkIngestOpen, setBulkIngestOpen] = useState(false);
  const [bulkIngestPreviewLoading, setBulkIngestPreviewLoading] = useState(false);
  const [bulkIngestPreview, setBulkIngestPreview] = useState<BulkIngestEligiblePreview | null>(null);
  const [bulkIngestRunning, setBulkIngestRunning] = useState(false);
  const [bulkIngestResult, setBulkIngestResult] = useState<BulkIngestEligibleSummary | null>(null);
  const [bulkIngestError, setBulkIngestError] = useState<string | null>(null);
  const [bulkIncludeAlreadyIngested, setBulkIncludeAlreadyIngested] = useState(false);

  const PER_PAGE = 25;
  const analyticsRefreshRef = useRef<(() => void) | null>(null);
  const unresolvedRefreshRef = useRef<(() => void) | null>(null);

  const fetchBatches = useCallback(async (p: number) => {
    setBatchLoading(true);
    try {
      const res = await listObservedPlayBatches({ page: p, per_page: PER_PAGE });
      setBatches(res.items);
      setBatchTotal(res.total);
    } catch {
      // keep stale data
    } finally {
      setBatchLoading(false);
    }
  }, []);

  const fetchLogs = useCallback(async (p: number) => {
    setLogLoading(true);
    try {
      const res = await listObservedPlayLogs({ page: p, per_page: PER_PAGE, sort_by: logSortBy, sort_dir: logSortDir });
      setLogs(res.items);
      setLogTotal(res.total);
    } catch {
      // keep stale data
    } finally {
      setLogLoading(false);
    }
  }, [logSortBy, logSortDir]);

  useEffect(() => { fetchBatches(batchPage); }, [batchPage, fetchBatches]);
  useEffect(() => { fetchLogs(logPage); }, [logPage, fetchLogs]);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError(null);
    try {
      const result = await uploadObservedPlayLog(file);
      setUploadResult(result);
      setBatchPage(1);
      setLogPage(1);
      await Promise.all([fetchBatches(1), fetchLogs(1)]);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const msg = detail || (err instanceof Error ? err.message : 'Upload failed');
      setUploadError(msg);
    } finally {
      setUploading(false);
    }
  }

  const batchPages = Math.max(1, Math.ceil(batchTotal / PER_PAGE));
  const logPages = Math.max(1, Math.ceil(logTotal / PER_PAGE));

  function handleLogSort(key: LogSortKey, defaultDir: 'asc' | 'desc') {
    if (logSortBy === key) {
      setLogSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setLogSortBy(key);
      setLogSortDir(defaultDir);
    }
    setLogPage(1);
  }

  async function handleBulkParseRun() {
    setBulkParseRunning(true);
    setBulkParseResult(null);
    setBulkParseError(null);
    try {
      const result = await bulkReparseAll({ include_ingested: bulkIncludeIngested });
      setBulkParseResult(result);
      await fetchLogs(logPage);
      unresolvedRefreshRef.current?.();
      analyticsRefreshRef.current?.();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : 'Reparse failed');
      setBulkParseError(msg);
    } finally {
      setBulkParseRunning(false);
    }
  }

  async function refreshBulkIngestPreview(includeAlreadyIngested: boolean) {
    setBulkIngestPreviewLoading(true);
    setBulkIngestPreview(null);
    setBulkIngestError(null);
    try {
      const preview = await bulkPreviewEligible({ include_already_ingested: includeAlreadyIngested });
      setBulkIngestPreview(preview);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : 'Preview failed');
      setBulkIngestError(msg);
    } finally {
      setBulkIngestPreviewLoading(false);
    }
  }

  async function openBulkIngestModal() {
    setBulkIngestOpen(true);
    setBulkIngestPreview(null);
    setBulkIngestResult(null);
    setBulkIngestError(null);
    setBulkIncludeAlreadyIngested(false);
    await refreshBulkIngestPreview(false);
  }

  async function handleBulkIngestRun() {
    setBulkIngestRunning(true);
    setBulkIngestResult(null);
    setBulkIngestError(null);
    try {
      const result = await bulkIngestEligible({ include_already_ingested: bulkIncludeAlreadyIngested });
      setBulkIngestResult(result);
      await fetchLogs(logPage);
      unresolvedRefreshRef.current?.();
      analyticsRefreshRef.current?.();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : 'Ingest failed');
      setBulkIngestError(msg);
    } finally {
      setBulkIngestRunning(false);
    }
  }

  return (
    <PageShell title="Observed Play">
      {/* Phase banner */}
      <div className="mb-6 rounded border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50 px-4 py-2 text-sm text-blue-700 dark:text-blue-300">
        Phase 4 active — memory ingestion enabled. Phase 5.2 adds the Corpus Quality / Readiness Scorecard.
        Observed memories are stored for review only. They are not used by Coach or AI Player yet.
      </div>

      {/* ── Upload panel ─────────────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">Upload Battle Log</h2>
        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 rounded border border-gray-300 dark:border-slate-600 bg-gray-50 dark:bg-slate-800 dark:text-slate-200 px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-slate-700">
            <Upload size={16} />
            <span>{file ? file.name : 'Choose file…'}</span>
            <input
              type="file"
              accept={ACCEPTED_EXTS}
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {uploadError && (
          <p className="mt-3 text-sm text-red-600" role="alert">
            {uploadError}
          </p>
        )}
      </section>

      {/* ── Last import report ────────────────────────────────────────────── */}
      {uploadResult && (
        <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">Import Report</h2>
          <div className="mb-3 flex flex-wrap gap-4 text-sm">
            <span><strong>Batch:</strong> <span className="font-mono text-xs">{uploadResult.batch_id}</span></span>
            <StatusChip status={uploadResult.status} />
          </div>
          <div className="mb-4 grid grid-cols-3 gap-3 sm:grid-cols-6">
            {[
              ['Original', uploadResult.original_file_count],
              ['Accepted', uploadResult.accepted_file_count],
              ['Imported', uploadResult.imported_file_count],
              ['Duplicate', uploadResult.duplicate_file_count],
              ['Skipped', uploadResult.skipped_file_count],
              ['Failed', uploadResult.failed_file_count],
            ].map(([label, val]) => (
              <div key={label as string} className="rounded border border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-2 text-center">
                <div className="text-xs text-gray-500 dark:text-slate-400">{label}</div>
                <div className="text-xl font-bold">{val}</div>
              </div>
            ))}
          </div>
          {uploadResult.errors.length > 0 && (
            <div className="mt-3 space-y-1">
              {uploadResult.errors.map((e, i) => (
                <p key={i} className="text-xs text-red-600" role="alert">⚠ {e}</p>
              ))}
            </div>
          )}
          {uploadResult.warnings.length > 0 && (
            <div className="mt-2 space-y-1">
              {uploadResult.warnings.map((w, i) => (
                <p key={i} className="text-xs text-yellow-700 dark:text-amber-300">⚑ {w}</p>
              ))}
            </div>
          )}
          {uploadResult.logs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-xs text-gray-500 dark:text-slate-400">
                    <th className="pb-1 pr-3">File</th>
                    <th className="pb-1 pr-3">Status</th>
                    <th className="pb-1 pr-3">Parse</th>
                    <th className="pb-1 pr-3">Hash prefix</th>
                    <th className="pb-1">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadResult.logs.map((l) => (
                    <tr key={l.sha256_hash || l.original_filename} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                      <td className="py-1 pr-3 font-mono text-xs">{l.original_filename}</td>
                      <td className="py-1 pr-3"><StatusChip status={l.status} /></td>
                      <td className="py-1 pr-3"><StatusChip status={l.parse_status} /></td>
                      <td className="py-1 pr-3 font-mono text-xs">{l.sha256_hash.slice(0, 8) || '—'}</td>
                      <td className="py-1 text-xs text-red-600">{l.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ── Import history ────────────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">Import History</h2>
        {batchLoading ? (
          <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>
        ) : batches.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-slate-500">No import batches yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-xs text-gray-500 dark:text-slate-400">
                  <th className="pb-1 pr-3">Imported at</th>
                  <th className="pb-1 pr-3">Filename</th>
                  <th className="pb-1 pr-3">Status</th>
                  <th className="pb-1 pr-3">Imported</th>
                  <th className="pb-1 pr-3">Dup</th>
                  <th className="pb-1 pr-3">Failed</th>
                  <th className="pb-1">Skipped</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                    <td className="py-1 pr-3 text-xs">{fmtDate(b.created_at)}</td>
                    <td className="py-1 pr-3 font-mono text-xs">{b.uploaded_filename ?? '—'}</td>
                    <td className="py-1 pr-3"><StatusChip status={b.status} /></td>
                    <td className="py-1 pr-3 text-center">{b.imported_file_count}</td>
                    <td className="py-1 pr-3 text-center">{b.duplicate_file_count}</td>
                    <td className="py-1 pr-3 text-center">{b.failed_file_count}</td>
                    <td className="py-1 text-center">{b.skipped_file_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
              <button
                onClick={() => setBatchPage((p) => Math.max(1, p - 1))}
                disabled={batchPage <= 1}
                className="rounded border px-2 py-0.5 disabled:opacity-40"
              >
                ‹ Prev
              </button>
              <span>Page {batchPage} / {batchPages} ({batchTotal} total)</span>
              <button
                onClick={() => setBatchPage((p) => Math.min(batchPages, p + 1))}
                disabled={batchPage >= batchPages}
                className="rounded border px-2 py-0.5 disabled:opacity-40"
              >
                Next ›
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── Bulk actions panel ───────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-sm">
        <h2 className="mb-1 text-base font-semibold text-slate-900 dark:text-white">Bulk Actions</h2>
        <p className="mb-4 text-xs text-gray-500 dark:text-slate-400">
          Bulk actions only operate on Observed Play logs. Ingest all eligible skips ineligible logs and does not force ingest.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => { setBulkParseOpen(true); setBulkParseResult(null); setBulkParseError(null); }}
            disabled={bulkParseRunning || bulkIngestRunning}
            className="rounded bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 dark:bg-slate-600 dark:hover:bg-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Parse / Reparse all
          </button>
          <button
            onClick={openBulkIngestModal}
            disabled={bulkParseRunning || bulkIngestRunning}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Ingest all eligible
          </button>
        </div>
      </section>

      {/* ── Bulk parse modal ─────────────────────────────────────────────── */}
      {bulkParseOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Bulk parse modal">
          <div className="w-full max-w-lg rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Parse / Reparse all</h3>
              <button onClick={() => setBulkParseOpen(false)} className="text-gray-400 hover:text-gray-600 dark:text-slate-400 dark:hover:text-slate-200" aria-label="Close"><X size={18} /></button>
            </div>
            {!bulkParseResult && (
              <>
                <div className="mb-4 rounded border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
                  <p>This will reparse observed logs with the current parser and refresh parsed events and card mentions.</p>
                  <ul className="mt-2 ml-4 list-disc space-y-1">
                    <li>No memory will be ingested.</li>
                    {!bulkIncludeIngested && <li>Logs that already have ingested memory are <strong>skipped</strong> to avoid stale memory items.</li>}
                    {bulkIncludeIngested && <li className="text-amber-900 dark:text-amber-200">Already-ingested logs will be reparsed, but existing memory items will not be changed. Use Re-ingest already-ingested eligible logs afterward to refresh memory items.</li>}
                  </ul>
                </div>
                <label className="mb-4 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    className="rounded"
                    checked={bulkIncludeIngested}
                    onChange={(e) => setBulkIncludeIngested(e.target.checked)}
                  />
                  Include already-ingested logs
                </label>
              </>
            )}
            {bulkParseError && (
              <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">{bulkParseError}</p>
            )}
            {bulkParseResult && (
              <div className="mb-4">
                <div className="grid grid-cols-4 gap-2 text-center text-sm mb-3">
                  {([
                    ['Considered', bulkParseResult.considered_count],
                    ['Reparsed', bulkParseResult.reparsed_count],
                    ['Skipped', bulkParseResult.skipped_count],
                    ['Failed', bulkParseResult.failed_count],
                  ] as [string, number][]).map(([label, val]) => (
                    <div key={label} className="rounded border border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-2">
                      <div className="text-xs text-gray-500 dark:text-slate-400">{label}</div>
                      <div className="text-xl font-bold">{val}</div>
                    </div>
                  ))}
                </div>
                {bulkParseResult.average_confidence != null && (
                  <p className="text-xs text-gray-500 dark:text-slate-400">Avg confidence (reparsed): {(bulkParseResult.average_confidence * 100).toFixed(1)}%</p>
                )}
                {(bulkParseResult.ingested_reparsed_count ?? 0) > 0 && (
                  <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                    Already-ingested logs reparsed: {bulkParseResult.ingested_reparsed_count} — re-ingest to refresh memory items.
                  </p>
                )}
                {bulkParseResult.failed.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs font-medium text-red-600 dark:text-red-400">Failed logs:</p>
                    {bulkParseResult.failed.map(f => (
                      <p key={f.log_id} className="text-xs text-red-500">{f.filename}: {f.error}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button onClick={() => setBulkParseOpen(false)} className="rounded border border-gray-300 dark:border-slate-600 px-4 py-2 text-sm dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800">Close</button>
              {!bulkParseResult && (
                <button
                  onClick={handleBulkParseRun}
                  disabled={bulkParseRunning}
                  className="rounded bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 dark:bg-slate-600 dark:hover:bg-slate-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {bulkParseRunning ? 'Parsing…' : 'Run parse / reparse'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Bulk ingest eligible modal ────────────────────────────────────── */}
      {bulkIngestOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="dialog" aria-modal="true" aria-label="Bulk ingest eligible modal">
          <div className="w-full max-w-lg rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Ingest all eligible</h3>
              <button onClick={() => setBulkIngestOpen(false)} className="text-gray-400 hover:text-gray-600 dark:text-slate-400 dark:hover:text-slate-200" aria-label="Close"><X size={18} /></button>
            </div>
            {bulkIngestPreviewLoading && (
              <p className="mb-4 text-sm text-gray-500 dark:text-slate-400">Computing eligibility…</p>
            )}
            <label className="mb-3 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                className="rounded"
                checked={bulkIncludeAlreadyIngested}
                disabled={bulkIngestPreviewLoading || !!bulkIngestResult}
                onChange={(e) => {
                  setBulkIncludeAlreadyIngested(e.target.checked);
                  setBulkIngestResult(null);
                  refreshBulkIngestPreview(e.target.checked);
                }}
              />
              Re-ingest already-ingested eligible logs
            </label>
            {bulkIncludeAlreadyIngested && !bulkIngestResult && (
              <p className="mb-3 text-xs text-amber-700 dark:text-amber-400 rounded border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-3 py-2">
                Existing observed memory items for eligible already-ingested logs will be replaced, not duplicated.
              </p>
            )}
            {bulkIngestError && (
              <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">{bulkIngestError}</p>
            )}
            {bulkIngestPreview && !bulkIngestResult && (
              <div className="mb-4">
                <div className="grid grid-cols-4 gap-2 text-center text-sm mb-3">
                  {([
                    ['Eligible', bulkIngestPreview.eligible_count],
                    ['Ineligible', bulkIngestPreview.ineligible_count],
                    ['Already\ningested', bulkIngestPreview.already_ingested_count],
                    ['Not ready', bulkIngestPreview.not_ready_count],
                  ] as [string, number][]).map(([label, val]) => (
                    <div key={label} className="rounded border border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-2">
                      <div className="text-xs text-gray-500 dark:text-slate-400 whitespace-pre-line">{label}</div>
                      <div className="text-xl font-bold">{val}</div>
                    </div>
                  ))}
                </div>
                {(bulkIngestPreview.eligible_for_reingest_count ?? 0) > 0 && (
                  <p className="text-xs text-amber-600 dark:text-amber-400 mb-1">Eligible for re-ingest: {bulkIngestPreview.eligible_for_reingest_count}</p>
                )}
                {bulkIngestPreview.estimated_memory_item_count > 0 && (
                  <p className="text-xs text-gray-500 dark:text-slate-400 mb-2">Estimated memory items: {bulkIngestPreview.estimated_memory_item_count}</p>
                )}
                {bulkIngestPreview.top_blocker_reasons.length > 0 && (
                  <div className="text-xs text-gray-500 dark:text-slate-400">
                    <span className="font-medium">Top blockers: </span>
                    {bulkIngestPreview.top_blocker_reasons.slice(0, 3).map(b => `${b.reason} (${b.count})`).join(', ')}
                  </div>
                )}
              </div>
            )}
            {bulkIngestResult && (
              <div className="mb-4">
                <div className={`grid gap-2 text-center text-sm mb-3 ${(bulkIngestResult.reingested_count ?? 0) > 0 ? 'grid-cols-5' : 'grid-cols-4'}`}>
                  {([
                    ['Ingested', bulkIngestResult.ingested_count],
                    ...((bulkIngestResult.reingested_count ?? 0) > 0 ? [['Re-ingested', bulkIngestResult.reingested_count] as [string, number]] : []),
                    ['Skipped', bulkIngestResult.skipped_count],
                    ['Failed', bulkIngestResult.failed_count],
                    ['Mem items', bulkIngestResult.memory_items_created],
                  ] as [string, number][]).map(([label, val]) => (
                    <div key={label} className="rounded border border-gray-100 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-2">
                      <div className="text-xs text-gray-500 dark:text-slate-400">{label}</div>
                      <div className="text-xl font-bold">{val}</div>
                    </div>
                  ))}
                </div>
                {bulkIngestResult.failed_logs.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs font-medium text-red-600 dark:text-red-400">Failed logs:</p>
                    {bulkIngestResult.failed_logs.map(f => (
                      <p key={f.log_id} className="text-xs text-red-500">{f.filename}: {f.error}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button onClick={() => setBulkIngestOpen(false)} className="rounded border border-gray-300 dark:border-slate-600 px-4 py-2 text-sm dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800">Close</button>
              {!bulkIngestResult && bulkIngestPreview && (bulkIngestPreview.eligible_count > 0 || (bulkIngestPreview.eligible_for_reingest_count ?? 0) > 0) && (
                <button
                  onClick={handleBulkIngestRun}
                  disabled={bulkIngestRunning || bulkIngestPreviewLoading}
                  className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {bulkIngestRunning
                    ? 'Ingesting eligible logs…'
                    : bulkIncludeAlreadyIngested
                      ? `Ingest/re-ingest ${bulkIngestPreview.eligible_count + (bulkIngestPreview.eligible_for_reingest_count ?? 0)} eligible log${(bulkIngestPreview.eligible_count + (bulkIngestPreview.eligible_for_reingest_count ?? 0)) !== 1 ? 's' : ''}`
                      : `Ingest ${bulkIngestPreview.eligible_count} eligible log${bulkIngestPreview.eligible_count !== 1 ? 's' : ''}`
                  }
                </button>
              )}
              {!bulkIngestResult && bulkIngestPreview && bulkIngestPreview.eligible_count === 0 && (bulkIngestPreview.eligible_for_reingest_count ?? 0) === 0 && (
                <span className="text-sm text-gray-500 dark:text-slate-400 self-center">No eligible logs to ingest</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Raw logs table ────────────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">Raw Logs</h2>
        {logLoading ? (
          <p className="text-sm text-gray-500 dark:text-slate-400">Loading…</p>
        ) : logs.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-slate-500">No logs imported yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-slate-700 text-left text-xs text-gray-500 dark:text-slate-400">
                  <SortableTh label="Filename" sortKey="filename" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="asc" />
                  <SortableTh label="Parse" sortKey="parse_status" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="asc" title="Sorts by parse status, then lower-confidence parsed logs." />
                  <SortableTh label="Memory" sortKey="memory_status" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="asc" />
                  <SortableTh label="Events" sortKey="event_count" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" />
                  <SortableTh label="Confidence" sortKey="confidence_score" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" />
                  <SortableTh label="Cards" sortKey="cards" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" title="Sorts by unresolved, ambiguous, then total card mentions." />
                  <SortableTh label="Mem items" sortKey="memory_item_count" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" />
                  <SortableTh label="Size" sortKey="file_size_bytes" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" />
                  <SortableTh label="Imported at" sortKey="created_at" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="desc" />
                  <SortableTh label="Hash prefix" sortKey="sha256_hash" currentSortBy={logSortBy} currentSortDir={logSortDir} onSort={handleLogSort} defaultDir="asc" />
                  <th className="pb-1"></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-gray-100 dark:border-slate-800 last:border-0">
                    <td className="py-1 pr-3 font-mono text-xs">{log.original_filename}</td>
                    <td className="py-1 pr-3"><StatusChip status={log.parse_status} /></td>
                    <td className="py-1 pr-3"><StatusChip status={log.memory_status} /></td>
                    <td className="py-1 pr-3 text-center text-xs">{(log.event_count ?? 0) || '—'}</td>
                    <td className="py-1 pr-3"><ConfidenceBadge score={log.confidence_score} /></td>
                    <td className="py-1 pr-3"><CardResolutionBadges log={log} /></td>
                    <td className="py-1 pr-3 text-center text-xs">
                      {(log.memory_item_count ?? 0) > 0
                        ? <span className="font-medium text-green-700 dark:text-green-400">{log.memory_item_count}</span>
                        : '—'}
                    </td>
                    <td className="py-1 pr-3 text-xs">{fmtBytes(log.file_size_bytes)}</td>
                    <td className="py-1 pr-3 text-xs">{fmtDate(log.created_at)}</td>
                    <td className="py-1 pr-3 font-mono text-xs">{log.sha256_hash.slice(0, 8)}</td>
                    <td className="py-1 flex flex-wrap gap-1">
                      <button
                        onClick={() => setViewLogId(log.id)}
                        className="rounded border border-gray-300 dark:border-slate-600 dark:text-slate-200 px-2 py-0.5 text-xs hover:bg-gray-50 dark:hover:bg-slate-800"
                      >
                        View raw
                      </button>
                      <button
                        onClick={() => setViewEventsLogId(log.id)}
                        className="rounded border border-blue-300 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-50"
                      >
                        View events
                      </button>
                      {(log.card_mention_count ?? 0) > 0 && (
                        <button
                          onClick={() => setViewCardMentionsLogId(log.id)}
                          className="rounded border border-purple-300 px-2 py-0.5 text-xs text-purple-700 hover:bg-purple-50"
                        >
                          View cards
                        </button>
                      )}
                      {log.parse_status === 'parsed' || log.parse_status === 'parsed_with_warnings' ? (
                        <button
                          onClick={() => setMemoryPreviewLogId(log.id)}
                          className="rounded border border-teal-300 px-2 py-0.5 text-xs text-teal-700 hover:bg-teal-50"
                        >
                          {log.memory_status === 'ingested' || (log.memory_item_count ?? 0) > 0 ? 'Re-preview memory' : 'Preview memory'}
                        </button>
                      ) : null}
                      {(log.memory_item_count ?? 0) > 0 && (
                        <button
                          onClick={() => setMemoryItemsLogId(log.id)}
                          className="rounded border border-green-300 dark:border-green-700 px-2 py-0.5 text-xs text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-950"
                        >
                          View memory
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
              <button
                onClick={() => setLogPage((p) => Math.max(1, p - 1))}
                disabled={logPage <= 1}
                className="rounded border px-2 py-0.5 disabled:opacity-40"
              >
                ‹ Prev
              </button>
              <span>Page {logPage} / {logPages} ({logTotal} total)</span>
              <button
                onClick={() => setLogPage((p) => Math.min(logPages, p + 1))}
                disabled={logPage >= logPages}
                className="rounded border px-2 py-0.5 disabled:opacity-40"
              >
                Next ›
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── Unresolved cards section ──────────────────────────────────────── */}
      <UnresolvedCardsSection
        onRefreshLogs={() => fetchLogs(logPage)}
        onRefreshAnalytics={() => analyticsRefreshRef.current?.()}
        refreshRef={unresolvedRefreshRef}
      />

      <MemoryAnalyticsSection
        refreshRef={analyticsRefreshRef}
        onRefreshLogs={() => fetchLogs(logPage)}
        onRefreshUnresolved={() => unresolvedRefreshRef.current?.()}
      />

      <CorpusScorecardSection />

      <CoachEvidenceSection />

      {viewLogId && (
        <RawLogModal logId={viewLogId} onClose={() => setViewLogId(null)} />
      )}
      {viewEventsLogId && (
        <EventsModal
          logId={viewEventsLogId}
          onClose={() => setViewEventsLogId(null)}
          initialDiagnostics={logs.find((l) => l.id === viewEventsLogId)?.parser_diagnostics}
        />
      )}
      {viewCardMentionsLogId && (
        <CardMentionsModal
          logId={viewCardMentionsLogId}
          onClose={() => setViewCardMentionsLogId(null)}
        />
      )}
      {memoryPreviewLogId && (
        <MemoryPreviewModal
          logId={memoryPreviewLogId}
          onClose={() => setMemoryPreviewLogId(null)}
          onIngestSuccess={() => {
            setMemoryPreviewLogId(null);
            fetchLogs(logPage);
            analyticsRefreshRef.current?.();
          }}
        />
      )}
      {memoryItemsLogId && (
        <MemoryItemsModal
          logId={memoryItemsLogId}
          onClose={() => setMemoryItemsLogId(null)}
        />
      )}
    </PageShell>
  );
}
