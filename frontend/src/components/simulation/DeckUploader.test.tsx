import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import DeckUploader from './DeckUploader';

const defaultProps = {
  deckText: '',
  onDeckTextChange: vi.fn(),
  deckMode: 'full' as const,
  onDeckModeChange: vi.fn(),
  deckLocked: false,
  onDeckLockedChange: vi.fn(),
  deckName: '',
  onDeckNameChange: vi.fn(),
};

describe('DeckUploader', () => {
  it('shows full, partial, and no-deck modes as selectable workflows', async () => {
    const onDeckModeChange = vi.fn();
    const user = userEvent.setup();

    render(<DeckUploader {...defaultProps} onDeckModeChange={onDeckModeChange} />);

    expect(screen.getByRole('radio', { name: 'Full Deck' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Partial Deck' })).toBeEnabled();
    expect(screen.getByRole('radio', { name: 'No Deck' })).toBeEnabled();

    await user.click(screen.getByRole('radio', { name: 'Partial Deck' }));
    expect(onDeckModeChange).toHaveBeenCalledWith('partial');

    await user.click(screen.getByRole('radio', { name: 'No Deck' }));
    expect(onDeckModeChange).toHaveBeenCalledWith('none');
  });

  it('hides deck text input and disables lock only in no-deck mode', () => {
    render(<DeckUploader {...defaultProps} deckMode="none" />);

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Lock Deck' })).toBeDisabled();
  });

  it('shows deck name input when deck mode is not none', () => {
    render(<DeckUploader {...defaultProps} deckMode="full" />);
    expect(screen.getByTestId('deck-name-input')).toBeInTheDocument();
  });

  it('hides deck name input in no-deck mode', () => {
    render(<DeckUploader {...defaultProps} deckMode="none" />);
    expect(screen.queryByTestId('deck-name-input')).not.toBeInTheDocument();
  });

  it('calls onDeckNameChange when deck name input changes', async () => {
    const onDeckNameChange = vi.fn();
    const user = userEvent.setup();

    render(<DeckUploader {...defaultProps} onDeckNameChange={onDeckNameChange} />);

    await user.type(screen.getByTestId('deck-name-input'), 'My Deck');
    expect(onDeckNameChange).toHaveBeenCalled();
  });
});
