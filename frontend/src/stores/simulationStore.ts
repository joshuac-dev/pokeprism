import { create } from 'zustand';
import type { NormalisedEvent, DeckMutation } from '../types/simulation';

interface SimulationState {
  simulationId: string | null;
  status: string | null;
  deckName: string | null;
  numRounds: number;
  roundsCompleted: number;
  finalWinRate: number | null;
  totalMatches: number;
  matchesPerOpponent: number;
  targetWinRate: number;
  gameMode: string;

  /** All events (buffered REST + live WS), oldest-first */
  events: NormalisedEvent[];
  /** Total event count from REST response (for "X of Y events" display) */
  totalEvents: number;
  /** Smallest event id currently loaded (for Load-earlier cursor) */
  firstEventId: number | null;
  /** Whether older events exist before firstEventId */
  hasMore: boolean;

  /** Deck mutation history */
  mutations: DeckMutation[];

  setSimulation: (fields: Partial<Omit<SimulationState, keyof SimulationActions>>) => void;
  prependEvents: (events: NormalisedEvent[], total: number, hasMore: boolean) => void;
  appendEvent: (event: NormalisedEvent) => void;
  addMutation: (m: DeckMutation) => void;
  reset: () => void;
}

interface SimulationActions {
  setSimulation: SimulationState['setSimulation'];
  prependEvents: SimulationState['prependEvents'];
  appendEvent: SimulationState['appendEvent'];
  addMutation: SimulationState['addMutation'];
  reset: SimulationState['reset'];
}

const INITIAL: Omit<SimulationState, keyof SimulationActions> = {
  simulationId: null,
  status: null,
  deckName: null,
  numRounds: 0,
  roundsCompleted: 0,
  finalWinRate: null,
  totalMatches: 0,
  matchesPerOpponent: 0,
  targetWinRate: 0,
  gameMode: '',
  events: [],
  totalEvents: 0,
  firstEventId: null,
  hasMore: false,
  mutations: [],
};

export const useSimulationStore = create<SimulationState>((set) => ({
  ...INITIAL,

  setSimulation: (fields) => set((s) => ({ ...s, ...fields })),

  prependEvents: (newEvents, total, hasMore) =>
    set((s) => {
      const combined = [...newEvents, ...s.events];
      const firstId = combined.length > 0 ? (combined[0].id ?? null) : null;
      return {
        events: combined,
        totalEvents: total,
        firstEventId: firstId,
        hasMore,
      };
    }),

  appendEvent: (event) =>
    set((s) => ({
      events: [...s.events, event],
    })),

  addMutation: (m) =>
    set((s) => ({ mutations: [...s.mutations, m] })),

  reset: () => set({ ...INITIAL }),
}));

// Legacy re-export so Phase 8 code still compiles
export type SimEvent = NormalisedEvent;
