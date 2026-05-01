import { useState } from 'react';
import { PlusCircle, Trash2 } from 'lucide-react';
import { parsePTCGDeck } from '../../utils/deckParser';

interface OpponentDeckListProps {
  opponentTexts: string[];
  onAdd: () => void;
  onRemove: (index: number) => void;
  onUpdate: (index: number, text: string) => void;
}

function inferDeckName(text: string, fallbackIndex: number): string {
  // Try to find the first ex or V Pokémon name from the parsed deck
  const parsed = parsePTCGDeck(text);
  for (const card of parsed.pokemon) {
    if (/ ex\b/i.test(card.name) || /\bV\b/.test(card.name) || /\bVMAX\b/.test(card.name)) {
      return card.name;
    }
  }
  if (parsed.pokemon.length > 0) return parsed.pokemon[0].name;
  return `Opponent ${fallbackIndex + 1}`;
}

export default function OpponentDeckList({
  opponentTexts,
  onAdd,
  onRemove,
  onUpdate,
}: OpponentDeckListProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  return (
    <div className="bg-app-surface border border-app-border rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-app-text-subtle uppercase tracking-wider">
          Opponent Decks
        </h2>
        <button
          type="button"
          onClick={() => {
            onAdd();
            setExpandedIndex(opponentTexts.length);
          }}
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          <PlusCircle size={14} />
          Add Opponent
        </button>
      </div>

      {opponentTexts.length === 0 && (
        <p className="text-xs text-app-text-muted italic">No opponent decks added yet.</p>
      )}

      <div className="flex flex-col gap-3">
        {opponentTexts.map((text, i) => {
          const parsed = parsePTCGDeck(text);
          const name = text.trim() ? inferDeckName(text, i) : `Opponent ${i + 1}`;
          const cardCount = parsed.totalCards;
          const hasErrors = parsed.errors.length > 0;
          const isExpanded = expandedIndex === i;

          return (
            <div key={i} className="border border-app-border rounded-md overflow-hidden">
              <div
                className="flex items-center justify-between px-3 py-2 bg-slate-50 dark:bg-slate-900 cursor-pointer"
                onClick={() => setExpandedIndex(isExpanded ? null : i)}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs text-app-text-muted font-mono">{i + 1}.</span>
                  <span className="text-sm text-app-text">{name}</span>
                  {cardCount > 0 && (
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded-full font-mono ${
                        hasErrors
                          ? 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-ctp-red border border-red-300 dark:border-red-700'
                          : 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-ctp-green border border-green-300 dark:border-green-700'
                      }`}
                    >
                      {cardCount}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(i);
                    if (expandedIndex === i) setExpandedIndex(null);
                  }}
                  className="text-app-text-muted hover:text-ctp-red transition-colors p-1"
                  aria-label="Remove opponent deck"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              {isExpanded && (
                <div className="p-3 bg-slate-100/50 dark:bg-slate-800/50">
                  <textarea
                    value={text}
                    onChange={(e) => onUpdate(i, e.target.value)}
                    placeholder={"Pokémon: 4\n4 Charizard ex sv03-125\n\nTrainer: 8\n4 Arven sv02-166\n4 Iono sv02-185\n\nEnergy: 4\n4 Basic Fire Energy sve-2"}
                    rows={8}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-app-text placeholder-slate-400 dark:placeholder-slate-600 rounded-md px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:border-app-focus focus:ring-1 focus:ring-app-focus"
                    spellCheck={false}
                  />
                  {parsed.errors.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {parsed.errors.map((err, j) => (
                        <li key={j} className="text-xs text-ctp-red">
                          {err}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
