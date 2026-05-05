import type { MouseEvent } from 'react';

const MAX_VISIBLE = 3;

interface Props {
  opponents: string[];
  onShowAll: (e: MouseEvent<HTMLButtonElement>) => void;
}

export default function OpponentListCell({ opponents, onShowAll }: Props) {
  if (opponents.length === 0) {
    return <span className="text-slate-400">—</span>;
  }

  const visible = opponents.slice(0, MAX_VISIBLE);
  const hiddenCount = opponents.length - visible.length;

  return (
    <span className="text-slate-600 dark:text-slate-300 text-xs">
      {visible.join(', ')}
      {hiddenCount > 0 && (
        <>
          {', '}
          <button
            type="button"
            onClick={e => { e.stopPropagation(); onShowAll(e); }}
            className="text-blue-500 hover:text-blue-400 hover:underline"
            aria-label={`Show all ${opponents.length} opponent decks`}
            data-testid="opponent-more-btn"
          >
            More… (+{hiddenCount})
          </button>
        </>
      )}
    </span>
  );
}
