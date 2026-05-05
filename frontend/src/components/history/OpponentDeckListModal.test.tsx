import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import OpponentDeckListModal from './OpponentDeckListModal';

const ALL_OPPONENTS = ['Cinderace ex Deck', 'Dragapult ex Deck', 'Meowth ex Deck', 'Regirock Deck'];

describe('OpponentDeckListModal', () => {
  it('renders all opponent names in the list', () => {
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName="My Deck"
        opponents={ALL_OPPONENTS}
        onClose={vi.fn()}
      />,
    );
    const list = screen.getByTestId('opponent-deck-list');
    ALL_OPPONENTS.forEach(name => expect(list).toHaveTextContent(name));
  });

  it('shows user deck name as context', () => {
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName="My Test Deck"
        opponents={ALL_OPPONENTS}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId('opponent-deck-modal-context')).toHaveTextContent('My Test Deck');
  });

  it('falls back to truncated simulation ID when userDeckName is null', () => {
    render(
      <OpponentDeckListModal
        simulationId="abc12345-long-id"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId('opponent-deck-modal-context')).toHaveTextContent('Simulation abc12345');
  });

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={onClose}
      />,
    );
    await user.click(screen.getByTestId('opponent-deck-modal-close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onClose when backdrop is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={onClose}
      />,
    );
    await user.click(screen.getByTestId('opponent-deck-modal'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onClose on Escape key', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={onClose}
      />,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('has role=dialog and aria-modal', () => {
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={vi.fn()}
      />,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('close button has aria-label="Close opponent deck list"', () => {
    render(
      <OpponentDeckListModal
        simulationId="abc-123"
        userDeckName={null}
        opponents={ALL_OPPONENTS}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Close opponent deck list')).toBeInTheDocument();
  });
});
