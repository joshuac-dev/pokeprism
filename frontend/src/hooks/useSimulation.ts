import { useCallback, useEffect, useRef } from 'react';
import { getSimulation, getSimulationEvents } from '../api/simulations';
import { useSimulationStore } from '../stores/simulationStore';
import { normaliseEvent } from '../types/simulation';
import type { LiveEvent, MatchEventRow } from '../types/simulation';
import { useSocket } from './useSocket';

export function useSimulation(simulationId: string | null) {
  const {
    status,
    deckName,
    events,
    totalEvents,
    hasMore,
    firstEventId,
    mutations,
    roundsCompleted,
    numRounds,
    finalWinRate,
    totalMatches,
    matchesPerOpponent,
    targetWinRate,
    gameMode,
    setSimulation,
    prependEvents,
    appendEvent,
    reset,
  } = useSimulationStore();

  const bufferedRef = useRef(false);

  // Reset store when simulation changes
  useEffect(() => {
    if (!simulationId) return;
    reset();
    bufferedRef.current = false;
  }, [simulationId, reset]);

  // Fetch simulation metadata + buffer events once on mount
  useEffect(() => {
    if (!simulationId || bufferedRef.current) return;
    bufferedRef.current = true;

    const init = async () => {
      // Fetch sim detail and events independently so a /events failure
      // doesn't block the status tile from populating.
      let detail;
      try {
        detail = await getSimulation(simulationId);
        setSimulation({
          simulationId: detail.id,
          status: detail.status,
          deckName: detail.user_deck_name,
          numRounds: detail.num_rounds,
          roundsCompleted: detail.rounds_completed,
          finalWinRate: detail.final_win_rate,
          totalMatches: detail.total_matches,
          matchesPerOpponent: detail.matches_per_opponent,
          targetWinRate: detail.target_win_rate,
          gameMode: detail.game_mode,
        });
      } catch {
        // ignore — status tile will remain at defaults
      }

      try {
        const evResp = await getSimulationEvents(simulationId, { limit: 500 });
        prependEvents(
          evResp.events.map(normaliseEvent),
          evResp.total,
          evResp.has_more
        );
      } catch {
        // ignore — console stays empty, not a fatal error
      }
    };

    init();
  }, [simulationId, setSimulation, prependEvents]);

  // Poll status while not terminal
  useEffect(() => {
    if (!simulationId) return;
    const terminal = new Set(['complete', 'failed', 'cancelled']);
    if (status && terminal.has(status)) return;

    const poll = async () => {
      try {
        const data = await getSimulation(simulationId);
        setSimulation({
          status: data.status,
          deckName: data.user_deck_name,
          roundsCompleted: data.rounds_completed,
          finalWinRate: data.final_win_rate,
          totalMatches: data.total_matches,
        });
      } catch {
        // ignore transient errors
      }
    };

    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [simulationId, status, setSimulation]);

  // Load earlier events (cursor-based)
  const loadEarlierEvents = useCallback(async () => {
    if (!simulationId || firstEventId == null || !hasMore) return;
    try {
      const resp = await getSimulationEvents(simulationId, {
        limit: 500,
        beforeId: firstEventId,
      });
      prependEvents(resp.events.map(normaliseEvent), resp.total, resp.has_more);
    } catch {
      // ignore
    }
  }, [simulationId, firstEventId, hasMore, prependEvents]);

  // WebSocket — live events from Redis pub/sub
  const handleLiveEvent = useCallback(
    (raw: unknown) => {
      const ev = raw as LiveEvent;
      if (ev.type === 'deck_mutation') {
        useSimulationStore.getState().addMutation({
          round: (ev.round_number as number) ?? 0,
          card_in: (ev.card_in as string | null) ?? null,
          card_out: (ev.card_out as string | null) ?? null,
          win_rate_before: (ev.win_rate_before as number | null) ?? null,
          win_rate_after: (ev.win_rate_after as number | null) ?? null,
        });
      }
      appendEvent(normaliseEvent(ev as MatchEventRow | LiveEvent));
    },
    [appendEvent]
  );

  useSocket(simulationId, handleLiveEvent);

  return {
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
  };
}
