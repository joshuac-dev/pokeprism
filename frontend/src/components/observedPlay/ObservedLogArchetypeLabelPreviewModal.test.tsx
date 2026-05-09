import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ObservedLogArchetypeLabelPreviewModal from './ObservedLogArchetypeLabelPreviewModal';
import { getObservedLogArchetypeLabelPreview } from '../../api/observedPlay';

vi.mock('../../api/observedPlay', () => ({
  getObservedLogArchetypeLabelPreview: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (getObservedLogArchetypeLabelPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
    observed_play_log_id: 'log-1',
    labels_by_player: {
      player_1: [
        {
          label: 'Dragapult ex',
          canonical_key: 'dragapult-ex',
          label_type: 'archetype',
          source: 'observed_log',
          confidence: 0.78,
          review_status: 'suggested',
          player_alias: 'player_1',
          evidence_card_ids: ['me02.5-160'],
          evidence_card_names: ['Dragapult ex'],
          evidence_counts: { 'dragapult ex': 2 },
          evidence_event_ids: ['101'],
          evidence_memory_item_ids: ['mem-1'],
          notes: null,
          schema_version: 'archetype_label_v1',
        },
      ],
    },
    global_labels: [],
    ambiguous: false,
    no_label_reason: null,
    source: 'observed_log',
  });
});

describe('ObservedLogArchetypeLabelPreviewModal', () => {
  it('fetches the selected log and closes from Escape and backdrop', async () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <ObservedLogArchetypeLabelPreviewModal logId="log-1" filename="game.md" onClose={onClose} />,
    );

    expect(await screen.findByText('Observed-Play Label Preview')).toBeInTheDocument();
    expect(screen.getByText('game.md')).toBeInTheDocument();
    expect(screen.getByText('Dragapult ex')).toBeInTheDocument();
    expect(getObservedLogArchetypeLabelPreview).toHaveBeenCalledWith('log-1');

    rerender(
      <ObservedLogArchetypeLabelPreviewModal logId="log-2" filename="game-2.md" onClose={onClose} />,
    );
    await waitFor(() => {
      expect(getObservedLogArchetypeLabelPreview).toHaveBeenCalledWith('log-2');
    });

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.mouseDown(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
