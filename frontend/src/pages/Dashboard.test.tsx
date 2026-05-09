import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Dashboard from './Dashboard';

vi.mock('../api/simulations', () => ({
  getSimulation: vi.fn(),
  getSimulationRounds: vi.fn(),
  getSimulationMatches: vi.fn(),
  getSimulationPrizeRace: vi.fn(),
  getSimulationMutations: vi.fn(),
  getSimulationFinalDeck: vi.fn(),
  getSimulationCoachDebug: vi.fn(),
}));

vi.mock('../api/decks', () => ({
  getDeckArchetypeLabelPreview: vi.fn(),
}));

vi.mock('../components/dashboard/SummaryCards', () => ({
  default: () => <div>Summary cards</div>,
}));
vi.mock('../components/dashboard/WinRateDonut', () => ({
  default: () => <div>Win rate donut</div>,
}));
vi.mock('../components/dashboard/WinRateProgress', () => ({
  default: () => <div>Win rate progress</div>,
}));
vi.mock('../components/dashboard/OpponentWinRateBar', () => ({
  default: () => <div>Opponent win rate</div>,
}));
vi.mock('../components/dashboard/MatchupMatrix', () => ({
  default: () => <div>Matchup matrix</div>,
}));
vi.mock('../components/dashboard/WinRateDistribution', () => ({
  default: () => <div>Win rate distribution</div>,
}));
vi.mock('../components/dashboard/PrizeRaceGraph', () => ({
  default: () => <div>Prize race</div>,
}));
vi.mock('../components/dashboard/DecisionMap', () => ({
  default: () => <div>Decision map</div>,
}));
vi.mock('../components/dashboard/CardSwapHeatMap', () => ({
  default: () => <div>Card swap heat map</div>,
}));
vi.mock('../components/dashboard/MutationDiffLog', () => ({
  default: () => <div>Mutation diff log</div>,
}));
vi.mock('../components/simulation/DeckEvolutionPanel', () => ({
  default: () => <div>Deck evolution</div>,
}));
vi.mock('../components/simulation/ObservedPlayRetrievalDebugTile', () => ({
  default: () => <div>Observed-play retrieval debug</div>,
}));

import {
  getSimulation,
  getSimulationRounds,
  getSimulationMatches,
  getSimulationPrizeRace,
  getSimulationMutations,
  getSimulationFinalDeck,
  getSimulationCoachDebug,
} from '../api/simulations';
import { getDeckArchetypeLabelPreview } from '../api/decks';

const baseSimulation = {
  id: 'sim-1',
  user_deck_id: 'deck-1',
  user_deck_name: 'Dragapult test',
  status: 'completed',
  num_rounds: 1,
  rounds_completed: 1,
  matches_per_opponent: 1,
  total_matches: 1,
  final_win_rate: 0.5,
  target_win_rate: 0.65,
};

function setup() {
  return render(
    <MemoryRouter initialEntries={['/dashboard/sim-1']}>
      <Routes>
        <Route path="/dashboard/:id" element={<Dashboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (getSimulation as ReturnType<typeof vi.fn>).mockResolvedValue(baseSimulation);
  (getSimulationRounds as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (getSimulationMatches as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (getSimulationPrizeRace as ReturnType<typeof vi.fn>).mockResolvedValue({ matches: [], average: [] });
  (getSimulationMutations as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (getSimulationFinalDeck as ReturnType<typeof vi.fn>).mockResolvedValue(null);
  (getSimulationCoachDebug as ReturnType<typeof vi.fn>).mockResolvedValue(null);
  (getDeckArchetypeLabelPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
    deck_id: 'deck-1',
    deck_name: 'Dragapult test',
    labels: [
      {
        label: 'Dragapult ex',
        canonical_key: 'dragapult-ex',
        label_type: 'archetype',
        source: 'deck_cards',
        confidence: 0.94,
        review_status: 'suggested',
        player_alias: null,
        evidence_card_ids: ['sv08-130'],
        evidence_card_names: ['Dragapult ex', 'Drakloak'],
        evidence_counts: { 'Dragapult ex': 2, Drakloak: 3 },
        evidence_event_ids: [],
        evidence_memory_item_ids: [],
        notes: null,
        schema_version: 'archetype_label_v1',
      },
    ],
    primary_label: {
      label: 'Dragapult ex',
      canonical_key: 'dragapult-ex',
      label_type: 'archetype',
      source: 'deck_cards',
      confidence: 0.94,
      review_status: 'suggested',
      player_alias: null,
      evidence_card_ids: ['sv08-130'],
      evidence_card_names: ['Dragapult ex', 'Drakloak'],
      evidence_counts: { 'Dragapult ex': 2, Drakloak: 3 },
      evidence_event_ids: [],
      evidence_memory_item_ids: [],
      notes: null,
      schema_version: 'archetype_label_v1',
    },
    ambiguous: false,
    no_label_reason: null,
    source: 'deck_cards',
  });
});

describe('Dashboard archetype label preview', () => {
  it('renders deck labels when user_deck_id exists', async () => {
    setup();

    expect(await screen.findByTestId('dashboard-deck-label-preview')).toBeInTheDocument();
    expect(screen.getByText('Deck Context Labels')).toBeInTheDocument();
    expect(await screen.findByText('Dragapult ex')).toBeInTheDocument();
    expect(screen.getByText(/not currently used for Coach retrieval ranking/i)).toBeInTheDocument();
    expect(getDeckArchetypeLabelPreview).toHaveBeenCalledWith('deck-1');
  });

  it('does not call the deck label preview endpoint without a deck id', async () => {
    (getSimulation as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseSimulation,
      user_deck_id: null,
    });

    setup();

    await waitFor(() => expect(screen.getByText('Summary cards')).toBeInTheDocument());
    expect(screen.queryByTestId('dashboard-deck-label-preview')).not.toBeInTheDocument();
    expect(getDeckArchetypeLabelPreview).not.toHaveBeenCalled();
  });

  it('keeps the dashboard usable when deck label preview fails', async () => {
    (getDeckArchetypeLabelPreview as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));

    setup();

    expect(await screen.findByText('Summary cards')).toBeInTheDocument();
    expect(await screen.findByText('Deck label preview unavailable.')).toBeInTheDocument();
  });
});
