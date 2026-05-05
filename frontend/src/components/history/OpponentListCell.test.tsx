import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import OpponentListCell from './OpponentListCell';

describe('OpponentListCell', () => {
  it('renders — for zero opponents', () => {
    render(<OpponentListCell opponents={[]} onShowAll={vi.fn()} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('renders all names inline for one opponent with no More…', () => {
    render(<OpponentListCell opponents={['Cinderace ex Deck']} onShowAll={vi.fn()} />);
    expect(screen.getByText(/Cinderace ex Deck/)).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('renders all three names inline for exactly three opponents with no More…', () => {
    const ops = ['Deck A', 'Deck B', 'Deck C'];
    render(<OpponentListCell opponents={ops} onShowAll={vi.fn()} />);
    expect(screen.getByText(/Deck A, Deck B, Deck C/)).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('shows only first three names and More… button for four opponents', () => {
    const ops = ['Deck A', 'Deck B', 'Deck C', 'Deck D'];
    render(<OpponentListCell opponents={ops} onShowAll={vi.fn()} />);
    expect(screen.getByText(/Deck A, Deck B, Deck C/)).toBeInTheDocument();
    expect(screen.queryByText('Deck D')).not.toBeInTheDocument();
    expect(screen.getByTestId('opponent-more-btn')).toBeInTheDocument();
  });

  it('shows hidden count in More… button label', () => {
    const ops = ['A', 'B', 'C', 'D', 'E', 'F'];
    render(<OpponentListCell opponents={ops} onShowAll={vi.fn()} />);
    expect(screen.getByTestId('opponent-more-btn')).toHaveTextContent('More… (+3)');
  });

  it('calls onShowAll when More… is clicked', async () => {
    const onShowAll = vi.fn();
    const user = userEvent.setup();
    const ops = ['A', 'B', 'C', 'D'];
    render(<OpponentListCell opponents={ops} onShowAll={onShowAll} />);
    await user.click(screen.getByTestId('opponent-more-btn'));
    expect(onShowAll).toHaveBeenCalledOnce();
  });

  it('More… button has accessible aria-label with total count', () => {
    const ops = ['A', 'B', 'C', 'D', 'E'];
    render(<OpponentListCell opponents={ops} onShowAll={vi.fn()} />);
    expect(screen.getByTestId('opponent-more-btn')).toHaveAttribute(
      'aria-label',
      'Show all 5 opponent decks',
    );
  });
});
