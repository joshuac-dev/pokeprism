import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DeckEvolutionPanel from './DeckEvolutionPanel';
import type { FinalDeckResponse } from '../../types/simulation';

const makeCard = (id: string, name: string, qty: number) => ({ tcgdex_id: id, name, quantity: qty });

const NO_MUTATIONS: FinalDeckResponse = {
  original_deck_id: 'orig-id',
  original_deck_name: 'My Deck',
  original_cards: [makeCard('sv06-001', 'Dragapult ex', 4)],
  original_deck_text: '4 Dragapult ex sv06-001',
  final_working_deck_id: null,
  final_deck_name: 'My Deck',
  final_cards: [makeCard('sv06-001', 'Dragapult ex', 4)],
  final_deck_text: '4 Dragapult ex sv06-001',
  changed_cards: [],
  has_mutations: false,
};

const WITH_MUTATIONS: FinalDeckResponse = {
  original_deck_id: 'orig-id',
  original_deck_name: 'My Deck',
  original_cards: [
    makeCard('sv06-001', 'Dragapult ex', 4),
    makeCard('sv06-002', 'Iron Hands ex', 3),
  ],
  original_deck_text: '4 Dragapult ex sv06-001\n3 Iron Hands ex sv06-002',
  final_working_deck_id: 'working-id',
  final_deck_name: 'My Deck — sim abc r2',
  final_cards: [
    makeCard('sv06-001', 'Dragapult ex', 4),
    makeCard('sv06-003', 'Boss\'s Orders', 4),
  ],
  final_deck_text: '4 Dragapult ex sv06-001\n4 Boss\'s Orders sv06-003',
  changed_cards: [
    { tcgdex_id: 'sv06-002', name: 'Iron Hands ex', original_count: 3, final_count: 0 },
    { tcgdex_id: 'sv06-003', name: "Boss's Orders", original_count: 0, final_count: 4 },
  ],
  has_mutations: true,
};

describe('DeckEvolutionPanel', () => {
  it('shows loading state', () => {
    render(<DeckEvolutionPanel data={null} loading />);
    expect(screen.getByTestId('deck-evolution-loading')).toBeInTheDocument();
  });

  it('shows unavailable state when no data and not loading', () => {
    render(<DeckEvolutionPanel data={null} />);
    expect(screen.getByTestId('deck-evolution-unavailable')).toBeInTheDocument();
  });

  it('shows safety note for all non-null data', () => {
    render(<DeckEvolutionPanel data={NO_MUTATIONS} />);
    expect(screen.getByTestId('deck-evolution-safety-note')).toBeInTheDocument();
    expect(screen.getByText(/Original deck was not overwritten/i)).toBeInTheDocument();
  });

  it('shows no-mutations message when has_mutations is false', () => {
    render(<DeckEvolutionPanel data={NO_MUTATIONS} />);
    expect(screen.getByTestId('deck-evolution-no-mutations')).toBeInTheDocument();
    expect(screen.getByText(/identical to the original/i)).toBeInTheDocument();
  });

  it('shows changed-cards table when has_mutations is true', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('changed-cards-table')).toBeInTheDocument();
  });

  it('shows removed card in changed-cards table', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByText('Iron Hands ex')).toBeInTheDocument();
  });

  it('shows added card in changed-cards table', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByText("Boss's Orders")).toBeInTheDocument();
  });

  it('shows copy button for final deck text', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('copy-decklist-btn')).toBeInTheDocument();
  });

  it('shows toggle button for final decklist', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('toggle-final-decklist')).toBeInTheDocument();
  });

  it('expands final decklist on toggle click', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    fireEvent.click(screen.getByTestId('toggle-final-decklist'));
    expect(screen.getByTestId('card-list-final-decklist')).toBeInTheDocument();
    expect(screen.getByText('Dragapult ex')).toBeInTheDocument();
  });

  it('shows toggle button for original decklist', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('toggle-original-decklist')).toBeInTheDocument();
  });

  it('expands original decklist on toggle click', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    fireEvent.click(screen.getByTestId('toggle-original-decklist'));
    expect(screen.getByTestId('card-list-original-decklist')).toBeInTheDocument();
  });

  it('does not show no-mutations message when has_mutations is true', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.queryByTestId('deck-evolution-no-mutations')).not.toBeInTheDocument();
  });
});
