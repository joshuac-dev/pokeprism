import { useState, useEffect } from 'react';
import type { CardProfile as CardProfileType } from '../../types/memory';

interface Props {
  profile: CardProfileType;
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-app-surface rounded-lg p-3">
      <div className="text-xs text-app-text-muted mb-1">{label}</div>
      <div className="text-app-text font-semibold">{value}</div>
    </div>
  );
}

export default function CardProfile({ profile }: Props) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const winRatePct = profile.stats.win_rate != null
    ? `${(profile.stats.win_rate * 100).toFixed(1)}%`
    : 'N/A';
  const setLabel = [profile.set_abbrev, profile.set_number].filter(Boolean).join(' ');

  useEffect(() => {
    if (!lightboxOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setLightboxOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightboxOpen]);

  return (
    <div className="bg-app-bg-secondary border border-app-border rounded-2xl p-5">
      {/* Card header */}
      <div className="flex items-start gap-4 mb-4">
        {profile.image_url && (
          <img
            src={profile.image_url}
            alt={profile.name}
            onClick={() => setLightboxOpen(true)}
            className="w-20 h-28 object-contain rounded-lg bg-app-surface cursor-pointer transition-transform hover:scale-105 hover:shadow-lg"
          />
        )}
        <div>
          <h2 className="text-app-text text-xl font-bold">{profile.name}</h2>
          {setLabel && (
            <div className="text-app-text-subtle text-sm">{setLabel}</div>
          )}
          {profile.category && (
            <span className="inline-block mt-1 px-2 py-0.5 rounded text-xs bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
              {profile.category}
            </span>
          )}
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <StatItem label="Games Played" value={profile.stats.games_included.toLocaleString()} />
        <StatItem label="Win Rate" value={winRatePct} />
        <StatItem label="Total KOs" value={profile.stats.total_kos.toLocaleString()} />
        <StatItem label="Total Damage" value={profile.stats.total_damage.toLocaleString()} />
        <StatItem label="Prizes Taken" value={profile.stats.total_prizes.toLocaleString()} />
      </div>

      {/* Lightbox */}
      {lightboxOpen && profile.image_url && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={() => setLightboxOpen(false)}
        >
          <img
            src={profile.image_url}
            alt={profile.name}
            className="max-h-[90vh] max-w-[90vw] rounded-xl shadow-2xl"
            onClick={e => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
