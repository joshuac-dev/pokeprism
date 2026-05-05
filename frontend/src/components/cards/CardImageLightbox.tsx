import { useEffect } from 'react';
import { X } from 'lucide-react';

export interface CardImageLightboxCard {
  name: string;
  tcgdex_id: string;
  set_abbrev?: string | null;
  set_number?: string | null;
  category?: string | null;
  subcategory?: string | null;
  image_url?: string | null;
  status?: string;
  missing_effects?: string[];
}

interface Props {
  card: CardImageLightboxCard;
  onClose: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  implemented: '✅ Implemented',
  flat_only:   '⚡ Flat Damage Only',
  missing:     '❌ Missing',
};

const STATUS_COLOR: Record<string, string> = {
  implemented: 'text-green-600 dark:text-green-400',
  flat_only:   'text-yellow-600 dark:text-yellow-400',
  missing:     'text-red-600 dark:text-red-400',
};

export default function CardImageLightbox({ card, onClose }: Props) {
  const setLabel = [card.set_abbrev, card.set_number].filter(Boolean).join(' ');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${card.name} card preview`}
      data-testid="card-lightbox"
    >
      <div
        className="relative bg-white dark:bg-slate-900 rounded-2xl shadow-2xl p-6 flex flex-col items-center gap-4 max-w-sm w-full mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          aria-label="Close card preview"
          className="absolute top-3 right-3 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          data-testid="card-lightbox-close"
        >
          <X size={20} />
        </button>

        {/* Card image or fallback */}
        {card.image_url ? (
          <img
            src={card.image_url}
            alt={card.name}
            className="max-h-[60vh] max-w-[80vw] rounded-xl shadow-xl object-contain"
            data-testid="card-lightbox-image"
          />
        ) : (
          <div
            className="flex items-center justify-center w-40 h-56 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-400 text-sm text-center px-3"
            data-testid="card-lightbox-no-image"
          >
            No card image available.
          </div>
        )}

        {/* Metadata */}
        <div className="text-center w-full">
          <div
            className="text-slate-900 dark:text-white font-bold text-lg"
            data-testid="card-lightbox-name"
          >
            {card.name}
          </div>
          {setLabel && (
            <div
              className="text-slate-400 text-sm font-mono mt-0.5"
              data-testid="card-lightbox-set"
            >
              {setLabel}
            </div>
          )}
          <div
            className="text-slate-400 text-xs font-mono mt-0.5"
            data-testid="card-lightbox-tcgdex-id"
          >
            {card.tcgdex_id}
          </div>
          {(card.category || card.subcategory) && (
            <div className="text-slate-500 dark:text-slate-400 text-xs mt-1 capitalize">
              {card.category}{card.subcategory ? ` / ${card.subcategory}` : ''}
            </div>
          )}
          {card.status && STATUS_LABEL[card.status] && (
            <div
              className={`text-xs mt-1 ${STATUS_COLOR[card.status] ?? ''}`}
              data-testid="card-lightbox-status"
            >
              {STATUS_LABEL[card.status]}
            </div>
          )}
          {card.missing_effects && card.missing_effects.length > 0 && (
            <div className="text-xs text-red-400 mt-1" data-testid="card-lightbox-missing">
              Missing: {card.missing_effects.join(', ')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
