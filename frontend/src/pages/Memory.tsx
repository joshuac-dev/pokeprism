import { useCallback, useEffect, useRef, useState } from 'react';
import PageShell from '../components/layout/PageShell';
import CardProfile from '../components/memory/CardProfile';
import MindMapGraph from '../components/memory/MindMapGraph';
import DecisionHistory from '../components/memory/DecisionHistory';
import { getTopCard, getCardProfile, getMemoryGraph } from '../api/memory';
import { searchCards } from '../api/cards';
import type { CardProfile as CardProfileType, MemoryGraph } from '../types/memory';
import type { CardSummary } from '../api/cards';

export default function Memory() {
  const [cardId, setCardId] = useState<string | null>(null);
  const [profile, setProfile] = useState<CardProfileType | null>(null);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [loadingCard, setLoadingCard] = useState(false);
  const [initialEmpty, setInitialEmpty] = useState(false);

  // Search state
  const [searchQ, setSearchQ] = useState('');
  const [searchResults, setSearchResults] = useState<CardSummary[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  // Load profile + graph for a card id
  const loadCard = useCallback(async (id: string) => {
    setLoadingCard(true);
    try {
      const [p, g] = await Promise.all([
        getCardProfile(id),
        getMemoryGraph(id, 2),
      ]);
      setProfile(p);
      setGraph(g);
      setCardId(id);
    } catch {
      // card not found in memory — show empty profile gracefully
    } finally {
      setLoadingCard(false);
    }
  }, []);

  // Initial load: fetch top card by games_included
  useEffect(() => {
    getTopCard()
      .then(card => {
        if (card) {
          loadCard(card);
        } else {
          setInitialEmpty(true);
        }
      })
      .catch(() => setInitialEmpty(true));
  }, [loadCard]);

  // Search debounce
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!searchQ.trim()) { setSearchResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      const res = await searchCards(searchQ, 8).catch(() => []);
      setSearchResults(res);
      setShowDropdown(res.length > 0);
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQ]);

  // Close dropdown on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  function handleSelectCard(card: CardSummary) {
    setShowDropdown(false);
    setSearchQ(card.name);
    loadCard(card.tcgdex_id);
  }

  return (
    <PageShell title="Memory Explorer">
      <div className="max-w-full">
        {/* Search bar */}
        <div ref={searchRef} className="relative mb-6 max-w-md">
          <input
            type="text"
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            placeholder="Search card by name..."
            className="w-full px-4 py-2 rounded-xl bg-app-surface border border-slate-300 dark:border-slate-700 text-app-text placeholder:text-app-text-subtle dark:placeholder:text-app-text-muted focus:outline-none focus:border-app-focus"
          />
          {showDropdown && (
            <div className="absolute left-0 right-0 top-full mt-1 z-20 bg-app-surface border border-app-border rounded-xl shadow-xl overflow-hidden">
              {searchResults.map(card => (
                <button
                  key={card.tcgdex_id}
                  onClick={() => handleSelectCard(card)}
                  className="w-full flex items-center gap-3 px-4 py-2 hover:bg-slate-100 dark:hover:bg-slate-700 text-left"
                >
                  {card.image_url && (
                    <img src={card.image_url} alt="" className="w-8 h-10 object-contain rounded" />
                  )}
                  <div>
                    <div className="text-app-text text-sm">{card.name}</div>
                    <div className="text-app-text-muted text-xs">{card.set_abbrev} {card.set_number}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Empty state */}
        {initialEmpty && !loadingCard && !profile && (
          <div className="flex flex-col items-center justify-center py-20 text-app-text-muted">
            <div className="text-6xl mb-4">🧠</div>
            <div className="text-lg font-semibold mb-2">No memory data yet</div>
            <div className="text-sm">Run simulations with AI players to populate card memory.</div>
          </div>
        )}

        {loadingCard && (
          <div className="text-app-text-subtle text-sm py-10 text-center">Loading card data...</div>
        )}

        {/* Main content */}
        {profile && graph && !loadingCard && (
          <>
            {/* Row 1: card profile + top synergies */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              <CardProfile profile={profile} />

              {/* Top synergies panel */}
              <div className="bg-app-bg-secondary border border-app-border rounded-2xl p-5">
                <h3 className="text-app-text font-semibold mb-4">Top Synergies</h3>
                {profile.partners.length === 0 ? (
                  <p className="text-app-text-muted text-sm">No synergy data recorded yet.</p>
                ) : (
                  <div className="divide-y divide-slate-200 dark:divide-slate-800">
                    {profile.partners.map((p, i) => (
                      <button
                        key={p.card_id}
                        onClick={() => loadCard(p.card_id)}
                        className="w-full flex items-center justify-between py-3 hover:bg-slate-50 dark:hover:bg-slate-800/60 px-2 rounded text-left"
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-app-text-subtle dark:text-slate-600 text-xs w-4">{i + 1}</span>
                          <span className="text-app-text text-sm">{p.name}</span>
                        </div>
                        <div className="text-right">
                          <div className="text-slate-600 dark:text-slate-300 text-sm">{p.weight.toFixed(2)}</div>
                          <div className="text-app-text-subtle dark:text-slate-600 text-xs">{p.games_observed} games</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Row 2: decision history (full width) */}
            {cardId && <div className="mb-6"><DecisionHistory cardId={cardId} /></div>}

            {/* Row 3: mind map graph (full width, tall) */}
            <MindMapGraph graph={graph} onNodeClick={id => loadCard(id)} />
          </>
        )}
      </div>
    </PageShell>
  );
}
