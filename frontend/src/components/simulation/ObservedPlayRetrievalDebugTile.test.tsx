import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import ObservedPlayRetrievalDebugTile from './ObservedPlayRetrievalDebugTile';
import type { CoachDebugAnalysisRound } from '../../types/simulation';
import type { ObservedPlayRetrievalMetadata } from '../../types/observedPlay';

const makeMetadata = (overrides: Partial<ObservedPlayRetrievalMetadata> = {}): ObservedPlayRetrievalMetadata => ({
  strategy: 'deck_overlap_v1',
  deck_card_ids: ['sv06-001'],
  deck_card_names: ['Dragapult ex'],
  candidate_card_ids: ['sv10-012'],
  candidate_card_names: ['Crustle'],
  allow_fallback: false,
  max_items_per_log: 2,
  no_relevant_evidence: false,
  evidence_selected: [
    {
      memory_item_id: 'mem-1',
      relevance_score: 0.97,
      tier: 1,
      matched_card_ids: ['sv06-001'],
      matched_card_names: ['Dragapult ex'],
      matched_field: 'actor_card_def_id',
      matched_reason: 'deck_card Dragapult ex matched actor_card_def_id sv06-001',
      match_source: 'deck_card',
      source_log_id: 'log-abc',
      from_winning_game: true,
    },
  ],
  excluded_summary: {
    low_confidence: 0,
    wrong_archetype: 0,
    source_cap_excluded: 0,
    unresolved_reference: 0,
  },
  ...overrides,
});

const makeRound = (overrides: Partial<CoachDebugAnalysisRound> = {}): CoachDebugAnalysisRound => ({
  round_number: 1,
  block_injected: true,
  no_relevant_evidence: false,
  evidence_ids_available: ['mem-1'],
  acknowledgment: null,
  llm_analysis: null,
  retrieval_metadata: makeMetadata(),
  mutations_produced: 0,
  ...overrides,
});

describe('ObservedPlayRetrievalDebugTile', () => {
  it('shows disabled message when flag is off', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[]}
        flagEnabled={false}
        anyBlockInjected={false}
      />
    );
    expect(screen.getByText(/OBSERVED_PLAY_MEMORY_ENABLED=false/i)).toBeInTheDocument();
  });

  it('shows empty message when no rounds recorded', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[]}
        flagEnabled={true}
        anyBlockInjected={false}
      />
    );
    expect(screen.getByText(/No observed-play analysis rounds recorded/i)).toBeInTheDocument();
  });

  it('renders summary row with round count', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound()]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    // Text is split across spans; check each count element individually
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(screen.getByText(/rounds recorded/i)).toBeInTheDocument();
  });

  it('shows round number and injected badge', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound()]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    expect(screen.getByText('Round 1')).toBeInTheDocument();
    expect(screen.getByText('injected')).toBeInTheDocument();
  });

  it('shows no-relevant-evidence badge when flag is set', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({ block_injected: false, no_relevant_evidence: true })]}
        flagEnabled={true}
        anyBlockInjected={false}
      />
    );
    expect(screen.getByText('no relevant evidence')).toBeInTheDocument();
  });

  it('expands round to show retrieval metadata when clicked', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound()]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText('Deck context')).toBeInTheDocument();
    expect(screen.getAllByText('Dragapult ex').length).toBeGreaterThan(0);
  });

  it('shows deck card count in round header', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound()]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    expect(screen.getByText(/1 deck IDs/i)).toBeInTheDocument();
  });
});
