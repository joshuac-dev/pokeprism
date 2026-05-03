import { parsePTCGDeck } from '../../utils/deckParser';

type DeckMode = 'full' | 'partial' | 'none';

interface DeckUploaderProps {
  deckText: string;
  onDeckTextChange: (value: string) => void;
  deckMode: DeckMode;
  onDeckModeChange: (mode: DeckMode) => void;
  deckLocked: boolean;
  onDeckLockedChange: (locked: boolean) => void;
}

export default function DeckUploader({
  deckText,
  onDeckTextChange,
  deckMode,
  onDeckModeChange,
  deckLocked,
  onDeckLockedChange,
}: DeckUploaderProps) {
  const parsed = deckMode !== 'none' ? parsePTCGDeck(deckText) : null;
  const cardCount = parsed?.totalCards ?? 0;
  const hasErrors = (parsed?.errors.length ?? 0) > 0;

  return (
    <div
      className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 flex flex-col gap-4"
      data-testid="deck-uploader"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Your Deck</h2>
        {deckMode !== 'none' && cardCount > 0 && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-mono font-semibold ${
              hasErrors
                ? 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-400 border border-red-300 dark:border-red-700'
                : 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700'
            }`}
          >
            {cardCount} cards
          </span>
        )}
      </div>

      {deckMode !== 'none' && (
        <textarea
          value={deckText}
          onChange={(e) => onDeckTextChange(e.target.value)}
          placeholder={"Pokémon: 4\n4 Dreepy sv06-128\n\nTrainer: 8\n4 Arven sv02-166\n4 Iono sv02-185\n\nEnergy: 4\n4 Basic Darkness Energy sve-7"}
          rows={10}
          className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-600 rounded-md px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          spellCheck={false}
          data-testid="deck-textarea"
        />
      )}

      {parsed && parsed.errors.length > 0 && (
        <ul className="space-y-1">
          {parsed.errors.map((err, i) => (
            <li key={i} className="text-xs text-red-400">
              {err}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-xs text-slate-400 uppercase tracking-wider">Deck Mode</span>
        <div className="flex flex-col gap-1.5">
          {(['none', 'partial', 'full'] as const).map((mode) => (
            <label key={mode} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="deck-mode"
                value={mode}
                checked={deckMode === mode}
                onChange={() => onDeckModeChange(mode)}
                className="accent-blue-500"
                data-testid={`deck-mode-${mode}`}
              />
              <span className="text-sm text-slate-700 dark:text-slate-300">
                {mode === 'none' ? 'No Deck' : mode === 'partial' ? 'Partial Deck' : 'Full Deck'}
              </span>
            </label>
          ))}
        </div>
      </div>

      <label className={`flex items-center gap-2 ${deckMode === 'none' ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}>
        <input
          type="checkbox"
          checked={deckLocked}
          onChange={(e) => onDeckLockedChange(e.target.checked)}
          disabled={deckMode === 'none'}
          className="accent-blue-500"
          data-testid="lock-deck-checkbox"
        />
        <span className="text-sm text-slate-700 dark:text-slate-300">Lock Deck</span>
      </label>
    </div>
  );
}
