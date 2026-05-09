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

  it('shows label ranking debug metadata when available', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            label_strategy: 'archetype_label_boost_v1',
            label_ranking_enabled: true,
            label_boost_cap: 0.10,
            label_boost_applied_count: 1,
            deck_labels: [{
              label: 'Dragapult ex',
              canonical_key: 'dragapult-ex',
              label_type: 'archetype',
              source: 'deck_cards',
              confidence: 0.92,
              review_status: 'suggested',
              player_alias: null,
              evidence_card_ids: ['sv06-001'],
              evidence_card_names: ['Dragapult ex'],
              evidence_counts: { 'dragapult ex': 3 },
              evidence_event_ids: [],
              evidence_memory_item_ids: [],
              notes: null,
              schema_version: 'archetype_label_v1',
            }],
            evidence_selected: [{
              memory_item_id: 'mem-1',
              relevance_score: 1.03,
              base_relevance_score: 0.95,
              label_boost: 0.08,
              final_relevance_score: 1.03,
              tier: 1,
              matched_card_ids: ['sv06-001'],
              matched_card_names: ['Dragapult ex'],
              matched_field: 'actor_card_def_id',
              matched_reason: 'deck_card Dragapult ex matched actor_card_def_id sv06-001',
              matched_label_keys: ['dragapult-ex'],
              matched_label_names: ['Dragapult ex'],
              matched_label_types: ['archetype'],
              source_log_labels: [],
              label_match_reason: 'Matched current archetype label Dragapult ex to source log/player label Dragapult ex.',
              match_source: 'deck_card',
              source_log_id: 'log-abc',
              from_winning_game: true,
            }],
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/Label strategy/i)).toBeInTheDocument();
    expect(screen.getByText('archetype_label_boost_v1')).toBeInTheDocument();
    expect(screen.getByText(/\+0\.08/)).toBeInTheDocument();
    expect(screen.getByText(/base 0\.950/i)).toBeInTheDocument();
    expect(screen.getByText(/Matched current archetype label Dragapult ex/i)).toBeInTheDocument();
  });

  it('shows no-label state for older simulation payloads without label_ranking_enabled', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            // label_ranking_enabled absent → falsy → older simulation fallback
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/No label ranking signal applied/i)).toBeInTheDocument();
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

  // Phase 7.2b matchup context tests
  it('shows matchup context section when matchup_context_enabled is true', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            matchup_context_enabled: true,
            matchup_strategy: 'matchup_context_preview_v1',
            matchup_ranking_enabled: false,
            matchup_candidate_pool_expanded: false,
            matchup_filter_applied: false,
            directed_matchup_key: 'dragapult-ex|vs|gardevoir-ex',
            matchup_confidence: 0.88,
            current_primary_archetype_key: 'dragapult-ex',
            opponent_primary_archetype_key: 'gardevoir-ex',
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/matchup_context_preview_v1/i)).toBeInTheDocument();
    expect(screen.getByText(/Matchup strategy/i)).toBeInTheDocument();
  });

  it('shows directed matchup key when present', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            matchup_context_enabled: true,
            matchup_strategy: 'matchup_context_preview_v1',
            directed_matchup_key: 'dragapult-ex|vs|gardevoir-ex',
            matchup_confidence: 0.88,
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText('dragapult-ex|vs|gardevoir-ex')).toBeInTheDocument();
  });

  it('shows no_matchup_signal_reason when no directed key', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            matchup_context_enabled: true,
            matchup_strategy: 'matchup_context_preview_v1',
            directed_matchup_key: null,
            no_matchup_signal_reason: 'no_opponent_archetype_label',
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/no opponent archetype label/i)).toBeInTheDocument();
  });

  it('shows preview-only advisory copy', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            matchup_context_enabled: true,
            matchup_strategy: 'matchup_context_preview_v1',
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/preview\/debug metadata only in Phase 7\.2b/i)).toBeInTheDocument();
  });

  it('older payload without matchup fields still renders without errors', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            // No matchup fields — backward compat
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    // Matchup section should not render
    expect(screen.queryByText(/Matchup strategy/i)).not.toBeInTheDocument();
  });

  it('shows matchup ranking and pool expansion as disabled', () => {
    render(
      <ObservedPlayRetrievalDebugTile
        simulationId="sim-1"
        rounds={[makeRound({
          retrieval_metadata: makeMetadata({
            matchup_context_enabled: true,
            matchup_strategy: 'matchup_context_preview_v1',
            matchup_ranking_enabled: false,
            matchup_candidate_pool_expanded: false,
            matchup_filter_applied: false,
          }),
        })]}
        flagEnabled={true}
        anyBlockInjected={true}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /Round 1/i }));
    expect(screen.getByText(/Matchup ranking/i)).toBeInTheDocument();
    expect(screen.getByText(/Candidate pool expansion/i)).toBeInTheDocument();
    expect(screen.getByText(/Filter applied/i)).toBeInTheDocument();
  });
});
