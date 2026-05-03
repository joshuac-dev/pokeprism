import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import DeckUploader from './DeckUploader';

describe('DeckUploader', () => {
  it('shows full, partial, and no-deck modes as selectable workflows', async () => {
    const onDeckModeChange = vi.fn();
    const user = userEvent.setup();

    render(
      <DeckUploader
        deckText=""
        onDeckTextChange={vi.fn()}
        deckMode="full"
        onDeckModeChange={onDeckModeChange}
        deckLocked={false}
        onDeckLockedChange={vi.fn()}
      />
    );

    expect(screen.getByRole('radio', { name: 'Full Deck' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Partial Deck' })).toBeEnabled();
    expect(screen.getByRole('radio', { name: 'No Deck' })).toBeEnabled();

    await user.click(screen.getByRole('radio', { name: 'Partial Deck' }));
    expect(onDeckModeChange).toHaveBeenCalledWith('partial');

    await user.click(screen.getByRole('radio', { name: 'No Deck' }));
    expect(onDeckModeChange).toHaveBeenCalledWith('none');
  });

  it('hides deck text input and disables lock only in no-deck mode', () => {
    render(
      <DeckUploader
        deckText=""
        onDeckTextChange={vi.fn()}
        deckMode="none"
        onDeckModeChange={vi.fn()}
        deckLocked={false}
        onDeckLockedChange={vi.fn()}
      />
    );

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Lock Deck' })).toBeDisabled();
  });
});
