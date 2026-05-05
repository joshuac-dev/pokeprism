import { useEffect } from 'react';

interface Props {
  simulationId: string;
  userDeckName: string | null;
  opponents: string[];
  onClose: () => void;
}

export default function OpponentDeckListModal({ simulationId, userDeckName, opponents, onClose }: Props) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Opponent deck list"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      data-testid="opponent-deck-modal"
    >
      <div
        className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Opponent Decks</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-900 dark:hover:text-white text-xl leading-none"
            aria-label="Close opponent deck list"
            data-testid="opponent-deck-modal-close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          <p className="text-slate-500 dark:text-slate-400 text-xs mb-3" data-testid="opponent-deck-modal-context">
            {userDeckName ?? `Simulation ${simulationId.slice(0, 8)}`}
          </p>
          <ol
            className="max-h-[70vh] overflow-y-auto space-y-1"
            data-testid="opponent-deck-list"
          >
            {opponents.map((name, i) => (
              <li key={i} className="text-slate-900 dark:text-white text-sm">
                <span className="text-slate-500 dark:text-slate-400 mr-2">{i + 1}.</span>
                {name}
              </li>
            ))}
          </ol>
        </div>

        <div className="px-6 pb-5 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-900 dark:text-white text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
