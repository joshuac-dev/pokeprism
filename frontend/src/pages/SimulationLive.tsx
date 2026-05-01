import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import PageShell from '../components/layout/PageShell';
import { useSimulation } from '../hooks/useSimulation';
import { cancelSimulation } from '../api/simulations';
import LiveConsole from '../components/simulation/LiveConsole';
import SimulationStatus from '../components/simulation/SimulationStatus';
import DeckChangesTile from '../components/simulation/DeckChangesTile';
import DecisionDetail from '../components/simulation/DecisionDetail';
import EventDetail from '../components/simulation/EventDetail';
import type { NormalisedEvent } from '../types/simulation';

export default function SimulationLive() {
  const { id } = useParams<{ id: string }>();
  const {
    status,
    deckName,
    events,
    totalEvents,
    hasMore,
    mutations,
    roundsCompleted,
    numRounds,
    finalWinRate,
    totalMatches,
    matchesPerOpponent,
    targetWinRate,
    gameMode,
    loadEarlierEvents,
  } = useSimulation(id ?? null);

  const [cancelling, setCancelling] = useState(false);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<NormalisedEvent | null>(null);
  const navigate = useNavigate();

  const handleCancel = async () => {
    if (!id) return;
    setCancelling(true);
    try {
      await cancelSimulation(id);
    } catch {
      // status will update via polling
    } finally {
      setCancelling(false);
    }
  };

  const detailProps = {
    status: (status ?? 'pending') as 'pending' | 'running' | 'complete' | 'failed' | 'cancelled',
    num_rounds: numRounds,
    rounds_completed: roundsCompleted,
    matches_per_opponent: matchesPerOpponent,
    total_matches: totalMatches,
    target_win_rate: targetWinRate,
    final_win_rate: finalWinRate,
    game_mode: gameMode,
    user_deck_name: deckName,
    error_message: null,
  };

  const isAiMode = gameMode === 'ai_h' || gameMode === 'ai_ai';

  return (
    <PageShell title={deckName ?? 'Simulation Live'}>
      <div className="flex flex-col lg:flex-row gap-4 h-full">
        {/* Left column: console (grows) */}
        <div className="flex-1 min-h-0 min-w-0 flex flex-col" style={{ minHeight: '60vh' }}>
          <LiveConsole
            events={events}
            totalEvents={totalEvents}
            hasMore={hasMore}
            onLoadEarlier={loadEarlierEvents}
            onEventClick={setSelectedEvent}
          />
        </div>

        {/* Right column: status + deck changes */}
        <div className="w-full lg:w-72 shrink-0 flex flex-col gap-3">
          <SimulationStatus
            detail={detailProps}
            onCancel={handleCancel}
            cancelling={cancelling}
          />

          <DeckChangesTile mutations={mutations} numRounds={numRounds} />

          {/* View Report button — only when complete */}
          {status === 'complete' && id && (
            <button
              onClick={() => navigate(`/dashboard/${id}`)}
              className="w-full py-2 text-sm font-medium bg-app-primary hover:bg-app-primaryHover text-ctp-base rounded-lg transition-colors"
            >
              View Report
            </button>
          )}

          {/* AI decisions button — only useful for ai_h / ai_ai */}
          {isAiMode && id && (
            <button
              onClick={() => setDecisionOpen(true)}
              className="w-full py-2 text-sm text-blue-400 border border-slate-700 rounded-lg
                         hover:bg-slate-800 transition-colors"
            >
              View AI Decisions
            </button>
          )}

          {/* Simulation ID (small, for debugging) */}
          <p className="text-xs text-slate-600 font-mono break-all px-1">{id}</p>
        </div>
      </div>

      {/* Decision panel */}
      {id && (
        <DecisionDetail
          simulationId={id}
          open={decisionOpen}
          onClose={() => setDecisionOpen(false)}
        />
      )}

      {/* Event detail overlay (clickable console rows) */}
      {id && selectedEvent && (
        <EventDetail
          simulationId={id}
          event={selectedEvent}
          isAiMode={isAiMode}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </PageShell>
  );
}
