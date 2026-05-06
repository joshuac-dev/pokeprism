import { useCallback, useEffect, useState } from 'react';
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
} from '../api/observedPlay';
import type {
  CardMentionItem,
  EventSummary,
  ObservedPlayBatch,
  ObservedPlayLog,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
  PaginatedEvents,
  ParserDiagnostics,
  UnresolvedCardItem,
} from '../types/observedPlay';

const ACCEPTED_EXTS = '.md,.markdown,.txt,.zip';

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
    completed: 'bg-green-100 text-green-800',
    completed_with_warnings: 'bg-yellow-100 text-yellow-800',
    failed: 'bg-red-100 text-red-800',
    running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-600',
    imported: 'bg-green-100 text-green-800',
    duplicate: 'bg-yellow-100 text-yellow-700',
    skipped: 'bg-gray-100 text-gray-500',
    raw_archived: 'bg-blue-100 text-blue-700',
    not_ingested: 'bg-gray-100 text-gray-500',
  };
  const cls = palette[status] ?? 'bg-gray-100 text-gray-600';
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
        className="relative mx-4 max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <h2 className="mb-3 text-lg font-semibold">Raw Log</h2>
        {loading && <p className="text-sm text-gray-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {detail && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="font-medium text-gray-600">File</span>
              <span>{detail.original_filename}</span>
              <span className="font-medium text-gray-600">SHA-256</span>
              <span className="font-mono text-xs">{detail.sha256_hash}</span>
              <span className="font-medium text-gray-600">Size</span>
              <span>{fmtBytes(detail.file_size_bytes)}</span>
              <span className="font-medium text-gray-600">Parse status</span>
              <StatusChip status={detail.parse_status} />
              <span className="font-medium text-gray-600">Memory status</span>
              <StatusChip status={detail.memory_status} />
              <span className="font-medium text-gray-600">Imported</span>
              <span>{fmtDate(detail.created_at)}</span>
            </div>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-gray-200 bg-gray-50 p-3 text-xs font-mono">
              {detail.raw_content ?? '(no raw content stored)'}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}

function ConfidenceBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-xs text-gray-400">—</span>;
  const pct = Math.round(score * 100);
  const cls =
    pct >= 80
      ? 'bg-green-100 text-green-800'
      : pct >= 50
        ? 'bg-yellow-100 text-yellow-800'
        : 'bg-red-100 text-red-700';
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {pct}%
    </span>
  );
}

// ── Events viewer modal ───────────────────────────────────────────────────────

function ParserDiagnosticsPanel({ diag }: { diag: ParserDiagnostics }) {
  return (
    <div className="mb-4 rounded border border-gray-100 bg-gray-50 p-3 text-xs">
      <p className="mb-1 font-medium text-gray-600">Parser diagnostics</p>
      <p>Unknown: {diag.unknown_count} ({(diag.unknown_ratio * 100).toFixed(1)}%)</p>
      <p>Low confidence: {diag.low_confidence_count}</p>
      {diag.top_unknown_raw_lines.length > 0 && (
        <div className="mt-1">
          <p className="font-medium text-gray-600">Top unknown lines:</p>
          <ul className="mt-0.5 space-y-0.5">
            {diag.top_unknown_raw_lines.slice(0, 5).map((line, i) => (
              <li key={i} className="truncate font-mono text-gray-500">{line}</li>
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
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <div className="mb-4 flex items-center gap-4">
          <h2 className="text-lg font-semibold">Parsed Events</h2>
          <button
            onClick={handleReparse}
            disabled={reparsing}
            className="rounded border border-blue-300 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {reparsing ? 'Reparsing…' : 'Reparse'}
          </button>
          {reparseMsg && <span className="text-xs text-gray-600">{reparseMsg}</span>}
        </div>
        {loading && <p className="text-sm text-gray-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {diagnostics && <ParserDiagnosticsPanel diag={diagnostics} />}
        {data && data.total === 0 && (
          <p className="text-sm text-gray-500">
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
            <p className="mb-3 text-xs text-gray-500">{data.total} events total</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-gray-500">
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
                    <tr key={evt.id} className="border-b border-gray-100 last:border-0">
                      <td className="py-0.5 pr-2 text-gray-400">{evt.event_index}</td>
                      <td className="py-0.5 pr-2">{evt.turn_number ?? '—'}</td>
                      <td className="py-0.5 pr-2">{evt.phase}</td>
                      <td className="py-0.5 pr-2">{evt.player_alias ?? evt.player_raw ?? '—'}</td>
                      <td className="py-0.5 pr-2 font-medium">{evt.event_type}</td>
                      <td className="py-0.5 pr-2">{evt.card_name_raw ?? '—'}</td>
                      <td className="py-0.5 pr-2">{evt.damage ?? '—'}</td>
                      <td className="py-0.5 pr-2"><ConfidenceBadge score={evt.confidence_score} /></td>
                      <td className="max-w-xs truncate py-0.5 font-mono text-gray-500">{evt.raw_line}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
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
  if (total === 0) return <span className="text-xs text-gray-400">—</span>;
  const resolved = log.resolved_card_count ?? 0;
  const ambiguous = log.ambiguous_card_count ?? 0;
  const unresolved = log.unresolved_card_count ?? 0;
  return (
    <span className="flex items-center gap-1 text-xs">
      <span className="text-gray-500">{total}</span>
      {resolved > 0 && (
        <span className="rounded bg-green-100 px-1 text-green-700">{resolved}✓</span>
      )}
      {ambiguous > 0 && (
        <span className="rounded bg-yellow-100 px-1 text-yellow-700">{ambiguous}?</span>
      )}
      {unresolved > 0 && (
        <span className="rounded bg-red-100 px-1 text-red-700">{unresolved}✗</span>
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
      resolved: 'bg-green-100 text-green-700',
      ambiguous: 'bg-yellow-100 text-yellow-700',
      unresolved: 'bg-red-100 text-red-700',
      ignored: 'bg-gray-100 text-gray-500',
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
        className="relative mx-4 max-h-[90vh] w-full max-w-5xl overflow-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-gray-500 hover:text-gray-800"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        <div className="mb-4 flex items-center gap-4 flex-wrap">
          <h2 className="text-lg font-semibold">Card Mentions</h2>
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="rounded border border-gray-300 px-2 py-1 text-xs"
          >
            <option value="">All statuses</option>
            <option value="resolved">Resolved</option>
            <option value="ambiguous">Ambiguous</option>
            <option value="unresolved">Unresolved</option>
            <option value="ignored">Ignored</option>
          </select>
          <span className="text-xs text-gray-500">{total} mentions</span>
        </div>
        {loading && <p className="text-sm text-gray-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && items.length === 0 && (
          <p className="text-sm text-gray-400">No card mentions found.</p>
        )}
        {items.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-gray-500">
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
                    <tr key={m.id} className="border-b border-gray-100 last:border-0">
                      <td className="py-0.5 pr-2 text-gray-500">{m.mention_role}</td>
                      <td className="py-0.5 pr-2 font-medium">{m.raw_name}</td>
                      <td className="py-0.5 pr-2">{statusBadge(m.resolution_status)}</td>
                      <td className="py-0.5 pr-2">{m.resolved_card_name ?? '—'}</td>
                      <td className="py-0.5 pr-2">
                        {m.resolution_confidence != null
                          ? `${Math.round(m.resolution_confidence * 100)}%`
                          : '—'}
                      </td>
                      <td className="py-0.5 text-gray-400">{m.resolution_method ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
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

function UnresolvedCardsSection() {
  const [items, setItems] = useState<UnresolvedCardItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getUnresolvedCards({ per_page: 20 })
      .then((data) => { setItems(data.items); setTotal(data.total); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (items.length === 0) return null;

  return (
    <section className="mb-8 rounded-lg border border-yellow-200 bg-yellow-50 p-6 shadow-sm">
      <h2 className="mb-3 text-base font-semibold text-yellow-800">
        Unresolved / Ambiguous Cards
        <span className="ml-2 text-sm font-normal text-yellow-700">({total} unique names)</span>
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-yellow-200 text-left text-yellow-700">
              <th className="pb-1 pr-3">Raw name</th>
              <th className="pb-1 pr-3">Status</th>
              <th className="pb-1 pr-3">Mentions</th>
              <th className="pb-1 pr-3">Logs</th>
              <th className="pb-1">Candidates</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.normalized_name}-${item.status}`} className="border-b border-yellow-100 last:border-0">
                <td className="py-0.5 pr-3 font-medium">{item.raw_name}</td>
                <td className="py-0.5 pr-3">
                  <span className={`rounded px-1 text-xs font-medium ${
                    item.status === 'ambiguous'
                      ? 'bg-yellow-200 text-yellow-800'
                      : 'bg-red-100 text-red-700'
                  }`}>
                    {item.status}
                  </span>
                </td>
                <td className="py-0.5 pr-3 text-center">{item.mention_count}</td>
                <td className="py-0.5 pr-3 text-center">{item.log_count}</td>
                <td className="py-0.5 text-gray-500">
                  {item.candidate_count > 0
                    ? `${item.candidate_count} candidate${item.candidate_count > 1 ? 's' : ''}`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

  const [viewLogId, setViewLogId] = useState<string | null>(null);
  const [viewEventsLogId, setViewEventsLogId] = useState<string | null>(null);
  const [viewCardMentionsLogId, setViewCardMentionsLogId] = useState<string | null>(null);

  const PER_PAGE = 25;

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
      const res = await listObservedPlayLogs({ page: p, per_page: PER_PAGE });
      setLogs(res.items);
      setLogTotal(res.total);
    } catch {
      // keep stale data
    } finally {
      setLogLoading(false);
    }
  }, []);

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

  return (
    <PageShell title="Observed Play">
      {/* Phase banner */}
      <div className="mb-6 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700">
        Phase 3 active — parser running, card resolution enabled. Memory ingestion not yet active.
      </div>

      {/* ── Upload panel ─────────────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Upload Battle Log</h2>
        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 rounded border border-gray-300 bg-gray-50 px-3 py-2 text-sm hover:bg-gray-100">
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
        <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Import Report</h2>
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
              <div key={label as string} className="rounded border border-gray-100 bg-gray-50 p-2 text-center">
                <div className="text-xs text-gray-500">{label}</div>
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
                <p key={i} className="text-xs text-yellow-700">⚑ {w}</p>
              ))}
            </div>
          )}
          {uploadResult.logs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                    <th className="pb-1 pr-3">File</th>
                    <th className="pb-1 pr-3">Status</th>
                    <th className="pb-1 pr-3">Parse</th>
                    <th className="pb-1 pr-3">Hash prefix</th>
                    <th className="pb-1">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadResult.logs.map((l) => (
                    <tr key={l.sha256_hash || l.original_filename} className="border-b border-gray-100 last:border-0">
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
      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Import History</h2>
        {batchLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : batches.length === 0 ? (
          <p className="text-sm text-gray-400">No import batches yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
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
                  <tr key={b.id} className="border-b border-gray-100 last:border-0">
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
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
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

      {/* ── Raw logs table ────────────────────────────────────────────────── */}
      <section className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Raw Logs</h2>
        {logLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : logs.length === 0 ? (
          <p className="text-sm text-gray-400">No logs imported yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                  <th className="pb-1 pr-3">Filename</th>
                  <th className="pb-1 pr-3">Parse</th>
                  <th className="pb-1 pr-3">Memory</th>
                  <th className="pb-1 pr-3">Events</th>
                  <th className="pb-1 pr-3">Confidence</th>
                  <th className="pb-1 pr-3">Cards</th>
                  <th className="pb-1 pr-3">Size</th>
                  <th className="pb-1 pr-3">Imported at</th>
                  <th className="pb-1 pr-3">Hash prefix</th>
                  <th className="pb-1"></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-gray-100 last:border-0">
                    <td className="py-1 pr-3 font-mono text-xs">{log.original_filename}</td>
                    <td className="py-1 pr-3"><StatusChip status={log.parse_status} /></td>
                    <td className="py-1 pr-3"><StatusChip status={log.memory_status} /></td>
                    <td className="py-1 pr-3 text-center text-xs">{(log.event_count ?? 0) || '—'}</td>
                    <td className="py-1 pr-3"><ConfidenceBadge score={log.confidence_score} /></td>
                    <td className="py-1 pr-3"><CardResolutionBadges log={log} /></td>
                    <td className="py-1 pr-3 text-xs">{fmtBytes(log.file_size_bytes)}</td>
                    <td className="py-1 pr-3 text-xs">{fmtDate(log.created_at)}</td>
                    <td className="py-1 pr-3 font-mono text-xs">{log.sha256_hash.slice(0, 8)}</td>
                    <td className="py-1 flex gap-1">
                      <button
                        onClick={() => setViewLogId(log.id)}
                        className="rounded border border-gray-300 px-2 py-0.5 text-xs hover:bg-gray-50"
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
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
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
      <UnresolvedCardsSection />

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
    </PageShell>
  );
}
