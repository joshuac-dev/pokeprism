import { useState } from 'react';
import type { FinalDeckResponse, DeckCardEntry, ChangedCard } from '../../types/simulation';

interface Props {
  data: FinalDeckResponse | null;
  loading?: boolean;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available — silently ignore
    }
  };
  return (
    <button
      onClick={handleCopy}
      className="text-xs px-2 py-0.5 rounded border border-slate-600 text-slate-400 hover:text-slate-200 hover:border-slate-400 transition-colors"
      data-testid="copy-decklist-btn"
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  );
}

function DeckCardList({ cards, label }: { cards: DeckCardEntry[]; label: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!cards.length) return null;
  return (
    <div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="text-xs text-slate-400 hover:text-slate-200 underline underline-offset-2 transition-colors"
        data-testid={`toggle-${label.toLowerCase().replace(/\s+/g, '-')}`}
      >
        {expanded ? 'Hide' : 'Show'} {label} ({cards.length} types)
      </button>
      {expanded && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-300 font-mono" data-testid={`card-list-${label.toLowerCase().replace(/\s+/g, '-')}`}>
          {cards.map((c) => (
            <li key={c.tcgdex_id} className="flex gap-2">
              <span className="w-6 text-right shrink-0 text-slate-400">{c.quantity}</span>
              <span>{c.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ChangedCardsTable({ changed }: { changed: ChangedCard[] }) {
  if (!changed.length) return null;
  return (
    <div data-testid="changed-cards-table">
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">Changed Cards</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 text-left">
            <th className="pb-1 font-normal">Card</th>
            <th className="pb-1 font-normal text-right">Before</th>
            <th className="pb-1 font-normal text-center">→</th>
            <th className="pb-1 font-normal text-right">After</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {changed.map((c) => {
            const delta = c.final_count - c.original_count;
            const cls = delta > 0 ? 'text-green-400' : delta < 0 ? 'text-red-400' : 'text-slate-400';
            return (
              <tr key={c.tcgdex_id} className="py-0.5">
                <td className="py-1 text-slate-200">{c.name}</td>
                <td className="py-1 text-right text-slate-400">{c.original_count}</td>
                <td className="py-1 text-center text-slate-600">→</td>
                <td className={`py-1 text-right font-semibold ${cls}`}>{c.final_count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function DeckEvolutionPanel({ data, loading }: Props) {
  if (loading) {
    return (
      <div className="text-slate-500 text-sm py-4 text-center" data-testid="deck-evolution-loading">
        Loading deck evolution…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-slate-500 text-sm py-4 text-center" data-testid="deck-evolution-unavailable">
        Deck evolution data not available.
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid="deck-evolution-panel">
      {/* Safety note */}
      <div
        className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-blue-950/40 border border-blue-800/50 text-blue-300"
        data-testid="deck-evolution-safety-note"
      >
        <span>🔒</span>
        <span>Original deck was not overwritten. This is a read-only candidate result.</span>
      </div>

      {!data.has_mutations ? (
        <p className="text-slate-400 text-sm" data-testid="deck-evolution-no-mutations">
          No mutations were applied — the final deck is identical to the original.
        </p>
      ) : (
        <>
          {/* Changed cards summary */}
          <ChangedCardsTable changed={data.changed_cards} />

          {/* Final deck with copy */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                Final Candidate Deck
              </p>
              {data.final_deck_text && (
                <CopyButton text={data.final_deck_text} />
              )}
            </div>
            <DeckCardList cards={data.final_cards} label="Final Decklist" />
          </div>

          {/* Original deck (collapsible) */}
          {data.original_cards.length > 0 && (
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">
                Original Deck
              </p>
              <DeckCardList cards={data.original_cards} label="Original Decklist" />
            </div>
          )}
        </>
      )}
    </div>
  );
}
