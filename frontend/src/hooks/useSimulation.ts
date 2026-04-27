import { useCallback, useEffect } from 'react';
import { getSimulation } from '../api/simulations';
import { useSimulationStore, SimEvent } from '../stores/simulationStore';
import { useSocket } from './useSocket';

export function useSimulation(simulationId: string | null) {
  const { status, deckName, events, setSimulation, addEvent } = useSimulationStore();

  useEffect(() => {
    if (!simulationId) return;
    const poll = async () => {
      try {
        const data = await getSimulation(simulationId);
        setSimulation(data.id, data.status, data.user_deck_name);
      } catch {
        // ignore transient errors
      }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [simulationId, setSimulation]);

  const handleEvent = useCallback(
    (raw: unknown) => {
      addEvent(raw as SimEvent);
    },
    [addEvent]
  );

  useSocket(simulationId, handleEvent);

  return { status, deckName, events };
}
