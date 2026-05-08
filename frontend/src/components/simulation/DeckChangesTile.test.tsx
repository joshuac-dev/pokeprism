import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DeckChangesTile from './DeckChangesTile';
import type { DeckMutation } from '../../types/simulation';

const makeMutation = (overrides: Partial<DeckMutation> = {}): DeckMutation => ({
  round_number: 1,
  card_removed: 'Bidoof',
  card_added: 'Pikachu',
  reasoning: 'Pikachu has better synergy.',
  win_rate_before: null,
  win_rate_after: null,
  ...overrides,
});

describe('DeckChangesTile', () => {
  it('shows "No deck swaps recommended" when mutations is empty', () => {
    render(<DeckChangesTile mutations={[]} numRounds={5} />);
    expect(screen.getByText(/No deck swaps recommended/i)).toBeInTheDocument();
  });

  it('shows helpful message when numRounds > 0 and no swaps', () => {
    render(<DeckChangesTile mutations={[]} numRounds={3} />);
    expect(screen.getByText(/no valid improvements/i)).toBeInTheDocument();
  });

  it('renders swap count badge', () => {
    const muts = [makeMutation(), makeMutation({ round_number: 2 })];
    render(<DeckChangesTile mutations={muts} numRounds={5} />);
    expect(screen.getByText('2 swaps')).toBeInTheDocument();
  });

  it('renders card_removed and card_added', () => {
    render(<DeckChangesTile mutations={[makeMutation()]} numRounds={1} />);
    expect(screen.getByText(/Bidoof/)).toBeInTheDocument();
    expect(screen.getByText(/Pikachu/)).toBeInTheDocument();
  });

  it('renders round badge with correct round number', () => {
    render(<DeckChangesTile mutations={[makeMutation({ round_number: 3 })]} numRounds={5} />);
    expect(screen.getByText('R3')).toBeInTheDocument();
  });

  it('shows Show reasoning button when reasoning is present', () => {
    render(<DeckChangesTile mutations={[makeMutation()]} numRounds={1} />);
    expect(screen.getByText(/Show reasoning/i)).toBeInTheDocument();
  });

  it('expands reasoning on click', () => {
    render(<DeckChangesTile mutations={[makeMutation()]} numRounds={1} />);
    const btn = screen.getByText(/Show reasoning/i);
    fireEvent.click(btn);
    expect(screen.getByText('Pikachu has better synergy.')).toBeInTheDocument();
    expect(screen.getByText(/Hide reasoning/i)).toBeInTheDocument();
  });

  it('hides reasoning on second click', () => {
    render(<DeckChangesTile mutations={[makeMutation()]} numRounds={1} />);
    const btn = screen.getByText(/Show reasoning/i);
    fireEvent.click(btn);
    fireEvent.click(screen.getByText(/Hide reasoning/i));
    expect(screen.queryByText('Pikachu has better synergy.')).not.toBeInTheDocument();
  });

  it('does not show reasoning button when reasoning is null', () => {
    render(<DeckChangesTile mutations={[makeMutation({ reasoning: null })]} numRounds={1} />);
    expect(screen.queryByText(/Show reasoning/i)).not.toBeInTheDocument();
  });

  it('shows 1 swap singular badge', () => {
    render(<DeckChangesTile mutations={[makeMutation()]} numRounds={1} />);
    expect(screen.getByText('1 swap')).toBeInTheDocument();
  });
});
