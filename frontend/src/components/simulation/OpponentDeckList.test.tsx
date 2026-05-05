import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import OpponentDeckList, { type OpponentDeckInput } from './OpponentDeckList';

vi.mock('../../utils/deckParser', () => ({
  parsePTCGDeck: vi.fn().mockReturnValue({
    totalCards: 0,
    pokemon: [],
    trainers: [],
    energy: [],
    errors: [],
  }),
}));

const defaultProps = {
  opponents: [] as OpponentDeckInput[],
  onAdd: vi.fn(),
  onRemove: vi.fn(),
  onUpdateText: vi.fn(),
  onUpdateName: vi.fn(),
};

describe('OpponentDeckList', () => {
  it('renders empty state when no opponents', () => {
    render(<OpponentDeckList {...defaultProps} />);
    expect(screen.getByText('No opponent decks added yet.')).toBeInTheDocument();
  });

  it('renders add opponent button', () => {
    render(<OpponentDeckList {...defaultProps} />);
    expect(screen.getByTestId('add-opponent-button')).toBeInTheDocument();
  });

  it('calls onAdd when add button clicked', async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(<OpponentDeckList {...defaultProps} onAdd={onAdd} />);
    await user.click(screen.getByTestId('add-opponent-button'));
    expect(onAdd).toHaveBeenCalled();
  });

  it('shows fallback header name when deckName is blank', () => {
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: '' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} />);
    expect(screen.getByText('Opponent 1')).toBeInTheDocument();
  });

  it('shows manual deck name in header when deckName is set', () => {
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: 'My Custom Name' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} />);
    expect(screen.getByText('My Custom Name')).toBeInTheDocument();
  });

  it('calls onRemove when remove button clicked', async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: '' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} onRemove={onRemove} />);
    await user.click(screen.getByRole('button', { name: 'Remove opponent deck' }));
    expect(onRemove).toHaveBeenCalledWith(0);
  });

  it('shows name input in expanded section', async () => {
    const user = userEvent.setup();
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: '' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} />);

    // Click header to expand
    await user.click(screen.getByText('Opponent 1'));
    expect(screen.getByTestId('opponent-name-input-0')).toBeInTheDocument();
  });

  it('calls onUpdateName when name input changes', async () => {
    const onUpdateName = vi.fn();
    const user = userEvent.setup();
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: '' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} onUpdateName={onUpdateName} />);

    // Expand
    await user.click(screen.getByText('Opponent 1'));
    await user.type(screen.getByTestId('opponent-name-input-0'), 'New Name');
    expect(onUpdateName).toHaveBeenCalled();
  });

  it('calls onUpdateText when deck textarea changes', async () => {
    const onUpdateText = vi.fn();
    const user = userEvent.setup();
    const opponents: OpponentDeckInput[] = [{ deckText: '', deckName: '' }];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} onUpdateText={onUpdateText} />);

    await user.click(screen.getByText('Opponent 1'));
    await user.type(screen.getByTestId('opponent-deck-textarea-0'), '4 Dreepy sv06-128');
    expect(onUpdateText).toHaveBeenCalled();
  });

  it('renders multiple opponents', () => {
    const opponents: OpponentDeckInput[] = [
      { deckText: '', deckName: 'First' },
      { deckText: '', deckName: 'Second' },
    ];
    render(<OpponentDeckList {...defaultProps} opponents={opponents} />);
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });
});
