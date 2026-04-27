import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useCardSearch } from '../../hooks/useCardSearch';
import { CardSummary } from '../../api/cards';

type GameMode = 'hh' | 'ai_h' | 'ai_ai';
type TargetMode = 'aggregate' | 'per_opponent';

interface ParamFormProps {
  gameMode: GameMode;
  onGameModeChange: (mode: GameMode) => void;
  matchesPerOpponent: number;
  onMatchesPerOpponentChange: (n: number) => void;
  numRounds: number;
  onNumRoundsChange: (n: number) => void;
  targetWinRatePct: number;
  onTargetWinRatePctChange: (n: number) => void;
  targetMode: TargetMode;
  onTargetModeChange: (mode: TargetMode) => void;
  excludedCards: CardSummary[];
  onAddExcludedCard: (card: CardSummary) => void;
  onRemoveExcludedCard: (tcgdexId: string) => void;
}

export default function ParamForm({
  gameMode,
  onGameModeChange,
  matchesPerOpponent,
  onMatchesPerOpponentChange,
  numRounds,
  onNumRoundsChange,
  targetWinRatePct,
  onTargetWinRatePctChange,
  targetMode,
  onTargetModeChange,
  excludedCards,
  onAddExcludedCard,
  onRemoveExcludedCard,
}: ParamFormProps) {
  const { query, setQuery, results, loading, clearResults } = useCardSearch(300);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (results.length > 0) setDropdownOpen(true);
    else setDropdownOpen(false);
  }, [results]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  function handleSelectCard(card: CardSummary) {
    if (!excludedCards.find((c) => c.tcgdex_id === card.tcgdex_id)) {
      onAddExcludedCard(card);
    }
    clearResults();
    setDropdownOpen(false);
  }

  const inputClass =
    'bg-slate-900 border border-slate-700 text-slate-100 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 w-full';

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 flex flex-col gap-4">
      <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Parameters</h2>

      {/* Game Mode */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">Game Mode</label>
        <select
          value={gameMode}
          onChange={(e) => onGameModeChange(e.target.value as GameMode)}
          className={inputClass}
        >
          <option value="hh">H/H (Human vs Human)</option>
          <option value="ai_h">AI vs Heuristic</option>
          <option value="ai_ai">AI vs AI</option>
        </select>
      </div>

      {/* Matches per Opponent */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">Matches per Opponent</label>
        <input
          type="number"
          min={1}
          max={1000}
          value={matchesPerOpponent}
          onChange={(e) => onMatchesPerOpponentChange(Number(e.target.value))}
          className={inputClass}
        />
      </div>

      {/* Rounds */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">Rounds</label>
        <input
          type="number"
          min={1}
          max={100}
          value={numRounds}
          onChange={(e) => onNumRoundsChange(Number(e.target.value))}
          className={inputClass}
        />
      </div>

      {/* Target Win Rate */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">Target Win Rate</label>
        <div className="relative">
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={targetWinRatePct}
            onChange={(e) => onTargetWinRatePctChange(Number(e.target.value))}
            className={`${inputClass} pr-7`}
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm pointer-events-none">
            %
          </span>
        </div>
      </div>

      {/* Target Mode */}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-slate-400">Target Mode</span>
        {(['aggregate', 'per_opponent'] as const).map((mode) => (
          <label key={mode} className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="target-mode"
              value={mode}
              checked={targetMode === mode}
              onChange={() => onTargetModeChange(mode)}
              className="accent-blue-500"
            />
            <span className="text-sm text-slate-300">
              {mode === 'aggregate' ? 'Aggregate' : 'Per Opponent'}
            </span>
          </label>
        ))}
      </div>

      {/* Excluded Cards */}
      <div className="flex flex-col gap-2">
        <span className="text-xs text-slate-400">Excluded Cards</span>

        <div className="relative" ref={dropdownRef}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length > 0 && setDropdownOpen(true)}
            placeholder="Search cards to exclude…"
            className={inputClass}
          />
          {loading && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs">
              …
            </span>
          )}
          {dropdownOpen && results.length > 0 && (
            <ul className="absolute z-10 w-full mt-1 bg-slate-800 border border-slate-700 rounded-md shadow-lg max-h-48 overflow-y-auto">
              {results.map((card) => (
                <li key={card.tcgdex_id}>
                  <button
                    type="button"
                    onClick={() => handleSelectCard(card)}
                    className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 transition-colors"
                  >
                    <span className="font-medium">{card.name}</span>
                    <span className="ml-2 text-slate-500 text-xs">
                      {card.set_abbrev}-{card.set_number}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {excludedCards.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {excludedCards.map((card) => (
              <span
                key={card.tcgdex_id}
                className="flex items-center gap-1 bg-slate-700 border border-slate-600 text-slate-200 text-xs px-2 py-0.5 rounded-full"
              >
                {card.name}
                <button
                  type="button"
                  onClick={() => onRemoveExcludedCard(card.tcgdex_id)}
                  className="text-slate-400 hover:text-slate-100 transition-colors ml-0.5"
                  aria-label={`Remove ${card.name}`}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
