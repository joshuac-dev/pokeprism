import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ArchetypeLabelPreviewPanel from './ArchetypeLabelPreviewPanel';
import type {
  ArchetypeLabel,
  DeckArchetypeLabelPreview,
  ObservedLogArchetypeLabelPreview,
} from '../../types/observedPlay';

const dragapultLabel: ArchetypeLabel = {
  label: 'Dragapult ex',
  canonical_key: 'dragapult-ex',
  label_type: 'archetype',
  source: 'deck_cards',
  confidence: 0.94,
  review_status: 'suggested',
  player_alias: null,
  evidence_card_ids: ['sv08-130'],
  evidence_card_names: ['Dragapult ex', 'Drakloak', 'Dreepy'],
  evidence_counts: { 'Dragapult ex': 2, Drakloak: 3, Dreepy: 4 },
  evidence_event_ids: [],
  evidence_memory_item_ids: [],
  notes: 'Core line detected.',
  schema_version: 'archetype_label_v1',
};

function observedLabel(label: Partial<ArchetypeLabel> = {}): ArchetypeLabel {
  return {
    ...dragapultLabel,
    source: 'observed_log',
    player_alias: 'Player 1',
    evidence_event_ids: ['101'],
    evidence_memory_item_ids: ['mem-1'],
    ...label,
  };
}

describe('ArchetypeLabelPreviewPanel', () => {
  it('renders a successful deck preview with a primary label', () => {
    const preview: DeckArchetypeLabelPreview = {
      deck_id: 'deck-1',
      deck_name: 'Dragapult test',
      labels: [dragapultLabel],
      primary_label: dragapultLabel,
      ambiguous: false,
      no_label_reason: null,
      source: 'deck_cards',
    };

    render(<ArchetypeLabelPreviewPanel variant="deck" preview={preview} />);

    expect(screen.getByText('Dragapult ex')).toBeInTheDocument();
    expect(screen.getByText('Primary preview')).toBeInTheDocument();
    expect(screen.getByText('Confidence 94%')).toBeInTheDocument();
    expect(screen.getByText(/not currently used for Coach retrieval ranking/i)).toBeInTheDocument();
    expect(screen.getByText(/Dragapult ex x2, Drakloak x3, Dreepy x4/)).toBeInTheDocument();
  });

  it('renders observed-log labels grouped by player', () => {
    const preview: ObservedLogArchetypeLabelPreview = {
      observed_play_log_id: 'log-1',
      labels_by_player: {
        'Player 1': [observedLabel()],
        'Player 2': [
          observedLabel({
            label: 'Crustle',
            canonical_key: 'crustle',
            evidence_card_names: ['Crustle', 'Dwebble'],
            evidence_counts: { Crustle: 3, Dwebble: 2 },
            player_alias: 'Player 2',
          }),
        ],
      },
      global_labels: [],
      ambiguous: false,
      no_label_reason: null,
      source: 'observed_log',
    };

    render(<ArchetypeLabelPreviewPanel variant="observed-log" preview={preview} />);

    expect(screen.getByText('Player 1')).toBeInTheDocument();
    expect(screen.getByText('Player 2')).toBeInTheDocument();
    expect(screen.getByText('Dragapult ex')).toBeInTheDocument();
    expect(screen.getByText('Crustle')).toBeInTheDocument();
    expect(screen.getAllByText('Source observed_log').length).toBeGreaterThan(0);
  });

  it('renders no-label state', () => {
    const preview: DeckArchetypeLabelPreview = {
      deck_id: 'deck-unknown',
      deck_name: 'Unknown',
      labels: [],
      primary_label: null,
      ambiguous: false,
      no_label_reason: 'no seeded archetype evidence found',
      source: 'deck_cards',
    };

    render(<ArchetypeLabelPreviewPanel variant="deck" preview={preview} />);

    expect(screen.getByText(/No label preview available: no seeded archetype evidence found/)).toBeInTheDocument();
  });

  it('renders ambiguous state', () => {
    const preview: DeckArchetypeLabelPreview = {
      deck_id: 'deck-ambiguous',
      deck_name: 'Ambiguous',
      labels: [dragapultLabel],
      primary_label: null,
      ambiguous: true,
      no_label_reason: null,
      source: 'deck_cards',
    };

    render(<ArchetypeLabelPreviewPanel variant="deck" preview={preview} />);

    expect(screen.getByText(/Ambiguous preview/)).toBeInTheDocument();
  });

  it('renders API error and loading states', () => {
    const { rerender } = render(
      <ArchetypeLabelPreviewPanel variant="deck" preview={null} loading />,
    );
    expect(screen.getByText('Loading label preview...')).toBeInTheDocument();

    rerender(
      <ArchetypeLabelPreviewPanel
        variant="deck"
        preview={null}
        error="Deck label preview unavailable."
      />,
    );
    expect(screen.getByText('Deck label preview unavailable.')).toBeInTheDocument();
  });
});
