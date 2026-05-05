import { useCallback, useEffect, useState } from 'react';
import { Upload, X } from 'lucide-react';
import PageShell from '../components/layout/PageShell';
import {
  uploadObservedPlayLog,
  listObservedPlayBatches,
  listObservedPlayLogs,
  getObservedPlayLog,
} from '../api/observedPlay';
import type {
  ObservedPlayBatch,
  ObservedPlayLog,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
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

// ── Main page ─────────────────────────────────────────────────────────────────

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
      const msg = err instanceof Error ? err.message : 'Upload failed';
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
        Raw archive only. Parser and memory ingestion are not active yet.
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
                    <td className="py-1 pr-3 text-xs">{fmtBytes(log.file_size_bytes)}</td>
                    <td className="py-1 pr-3 text-xs">{fmtDate(log.created_at)}</td>
                    <td className="py-1 pr-3 font-mono text-xs">{log.sha256_hash.slice(0, 8)}</td>
                    <td className="py-1">
                      <button
                        onClick={() => setViewLogId(log.id)}
                        className="rounded border border-gray-300 px-2 py-0.5 text-xs hover:bg-gray-50"
                      >
                        View raw
                      </button>
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

      {viewLogId && (
        <RawLogModal logId={viewLogId} onClose={() => setViewLogId(null)} />
      )}
    </PageShell>
  );
}
