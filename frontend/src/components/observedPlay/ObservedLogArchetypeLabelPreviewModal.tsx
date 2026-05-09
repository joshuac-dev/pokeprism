import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { getObservedLogArchetypeLabelPreview } from '../../api/observedPlay';
import type { ObservedLogArchetypeLabelPreview } from '../../types/observedPlay';
import ArchetypeLabelPreviewPanel from './ArchetypeLabelPreviewPanel';

interface Props {
  logId: string;
  filename?: string | null;
  onClose: () => void;
}

export default function ObservedLogArchetypeLabelPreviewModal({
  logId,
  filename,
  onClose,
}: Props) {
  const [preview, setPreview] = useState<ObservedLogArchetypeLabelPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPreview(null);

    getObservedLogArchetypeLabelPreview(logId)
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.response?.status === 404
            ? 'Label preview unavailable: observed-play log was not found.'
            : 'Label preview unavailable.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [logId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Observed-play label preview"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-white">
              Observed-Play Label Preview
            </h3>
            {filename && (
              <p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{filename}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:text-slate-400 dark:hover:text-slate-200"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <ArchetypeLabelPreviewPanel
          variant="observed-log"
          preview={preview}
          loading={loading}
          error={error}
        />
      </div>
    </div>
  );
}
