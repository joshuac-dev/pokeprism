import { create } from 'zustand';

export interface SimEvent {
  type: string;
  timestamp: string;
  [key: string]: unknown;
}

interface SimulationState {
  simulationId: string | null;
  status: string | null;
  deckName: string | null;
  events: SimEvent[];
  setSimulation: (id: string, status: string, deckName?: string | null) => void;
  addEvent: (event: SimEvent) => void;
  reset: () => void;
}

export const useSimulationStore = create<SimulationState>((set) => ({
  simulationId: null,
  status: null,
  deckName: null,
  events: [],
  setSimulation: (id, status, deckName = null) => set({ simulationId: id, status, deckName }),
  addEvent: (event) => set((state) => ({ events: [...state.events.slice(-500), event] })),
  reset: () => set({ simulationId: null, status: null, deckName: null, events: [] }),
}));
