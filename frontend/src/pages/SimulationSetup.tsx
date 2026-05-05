import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import PageShell from '../components/layout/PageShell';
import DeckUploader from '../components/simulation/DeckUploader';
import ParamForm from '../components/simulation/ParamForm';
import OpponentDeckList, { type OpponentDeckInput } from '../components/simulation/OpponentDeckList';
import { createSimulation } from '../api/simulations';
import { parsePTCGDeck } from '../utils/deckParser';
import { CardSummary } from '../api/cards';

type DeckMode = 'full' | 'partial' | 'none';
type GameMode = 'hh' | 'ai_h' | 'ai_ai';
type TargetMode = 'aggregate' | 'per_opponent';

export default function SimulationSetup() {
  const navigate = useNavigate();

  // Deck state
  const [deckText, setDeckText] = useState('');
  const [deckMode, setDeckMode] = useState<DeckMode>('full');
  const [deckLocked, setDeckLocked] = useState(false);
  const [userDeckName, setUserDeckName] = useState('');

  // Param state
  const [gameMode, setGameMode] = useState<GameMode>('hh');
  const [matchesPerOpponent, setMatchesPerOpponent] = useState(100);
  const [numRounds, setNumRounds] = useState(3);
  const [targetWinRatePct, setTargetWinRatePct] = useState(60);
  const [targetConsecutiveRounds, setTargetConsecutiveRounds] = useState(1);
  const [targetMode, setTargetMode] = useState<TargetMode>('aggregate');
  const [excludedCards, setExcludedCards] = useState<CardSummary[]>([]);

  // Opponent decks
  const [opponents, setOpponents] = useState<OpponentDeckInput[]>([]);

  // Submit state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  function validateForm(): string | null {
    const parsed = parsePTCGDeck(deckText);
    if (deckMode === 'full' && parsed.totalCards !== 60) {
      return `Full deck mode requires exactly 60 cards. You have ${parsed.totalCards}.`;
    }
    if (deckMode === 'partial' && (parsed.totalCards <= 0 || parsed.totalCards >= 60)) {
      return `Partial deck mode requires 1-59 cards. You have ${parsed.totalCards}.`;
    }
    if (deckMode === 'none' && deckText.trim()) {
      return 'No Deck mode starts from the card pool; clear your deck text or choose Partial Deck.';
    }
    if (deckMode === 'none' && deckLocked) {
      return 'Cannot lock deck when deck mode is "No Deck".';
    }
    if (matchesPerOpponent < 1 || matchesPerOpponent > 1000) {
      return 'Matches per opponent must be between 1 and 1000.';
    }
    if (numRounds < 1 || numRounds > 100) {
      return 'Rounds must be between 1 and 100.';
    }
    if (targetWinRatePct < 0 || targetWinRatePct > 100) {
      return 'Target win rate must be between 0% and 100%.';
    }
    if (userDeckName.trim().length > 120) {
      return 'Deck name must be 120 characters or fewer.';
    }
    for (const opp of opponents) {
      if (opp.deckName.trim().length > 120) {
        return 'Opponent deck name must be 120 characters or fewer.';
      }
    }
    if (opponents.length === 0) {
      return 'Add at least one opponent deck.';
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setWarning(null);

    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    try {
      const trimmedUserDeckName = userDeckName.trim() || null;
      const resp = await createSimulation({
        deck_text: deckMode !== 'none' ? deckText : undefined,
        opponent_deck_texts: opponents.map((o) => o.deckText),
        num_rounds: numRounds,
        matches_per_opponent: matchesPerOpponent,
        target_win_rate: targetWinRatePct / 100,
        target_consecutive_rounds: targetConsecutiveRounds,
        target_mode: targetMode,
        game_mode: gameMode,
        deck_mode: deckMode,
        deck_locked: deckLocked,
        excluded_card_ids: excludedCards.map((c) => c.tcgdex_id),
        user_deck_name: trimmedUserDeckName,
        opponent_deck_names: opponents.map((o) => o.deckName.trim() || null),
      });

      if (resp.warning) {
        setWarning(resp.warning);
      }

      navigate(`/simulation/${resp.simulation_id}`);
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response) {
        const detail = err.response.data?.detail;
        if (typeof detail === 'string') {
          setError(detail);
        } else if (Array.isArray(detail)) {
          setError(detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; '));
        } else if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
          setError(detail.message);
        } else {
          setError(`Server error: ${err.response.status}`);
        }
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Unexpected error: ${msg}`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PageShell title="Simulation Setup">
      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-6 max-w-5xl mx-auto"
        data-testid="simulation-form"
      >
        {warning && (
          <div
            className="bg-yellow-50 dark:bg-yellow-900/40 border border-yellow-300 dark:border-yellow-700 text-yellow-800 dark:text-yellow-300 rounded-md px-4 py-3 text-sm"
            data-testid="simulation-warning"
          >
            ⚠ {warning}
          </div>
        )}
        {error && (
          <div
            className="bg-red-50 dark:bg-red-900/40 border border-red-300 dark:border-red-700 text-red-800 dark:text-red-300 rounded-md px-4 py-3 text-sm"
            data-testid="simulation-error"
          >
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DeckUploader
            deckText={deckText}
            onDeckTextChange={setDeckText}
            deckMode={deckMode}
            onDeckModeChange={(mode) => {
              setDeckMode(mode);
              if (mode === 'none') setDeckLocked(false);
            }}
            deckLocked={deckLocked}
            onDeckLockedChange={setDeckLocked}
            deckName={userDeckName}
            onDeckNameChange={setUserDeckName}
          />
          <ParamForm
            gameMode={gameMode}
            onGameModeChange={setGameMode}
            matchesPerOpponent={matchesPerOpponent}
            onMatchesPerOpponentChange={setMatchesPerOpponent}
            numRounds={numRounds}
            onNumRoundsChange={setNumRounds}
            targetWinRatePct={targetWinRatePct}
            onTargetWinRatePctChange={setTargetWinRatePct}
            targetConsecutiveRounds={targetConsecutiveRounds}
            onTargetConsecutiveRoundsChange={setTargetConsecutiveRounds}
            targetMode={targetMode}
            onTargetModeChange={setTargetMode}
            excludedCards={excludedCards}
            onAddExcludedCard={(card) => setExcludedCards((prev) => [...prev, card])}
            onRemoveExcludedCard={(id) =>
              setExcludedCards((prev) => prev.filter((c) => c.tcgdex_id !== id))
            }
          />
        </div>

        <OpponentDeckList
          opponents={opponents}
          onAdd={() => setOpponents((prev) => [...prev, { deckText: '', deckName: '' }])}
          onRemove={(i) => setOpponents((prev) => prev.filter((_, idx) => idx !== i))}
          onUpdateText={(i, text) =>
            setOpponents((prev) => prev.map((o, idx) => (idx === i ? { ...o, deckText: text } : o)))
          }
          onUpdateName={(i, name) =>
            setOpponents((prev) => prev.map((o, idx) => (idx === i ? { ...o, deckName: name } : o)))
          }
        />

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-md text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-950"
          data-testid="start-simulation-button"
        >
          {submitting ? 'Starting Simulation…' : 'Start Simulation'}
        </button>
      </form>
    </PageShell>
  );
}
