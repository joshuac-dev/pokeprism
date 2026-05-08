import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DeckEvolutionPanel from './DeckEvolutionPanel';
import type { FinalDeckResponse, DeckCardEntry } from '../../types/simulation';

const makeCard = (id: string, name: string, qty: number, cat = 'Pokemon'): DeckCardEntry => ({
  tcgdex_id: id,
  name,
  quantity: qty,
  set_abbrev: 'MEG',
  set_number: '001',
  category: cat,
  ptcgl_line: `${qty} ${name} MEG 001`,
});

const NO_MUTATIONS: FinalDeckResponse = {
  original_deck_id: 'orig-id',
  original_deck_name: 'My Deck',
  original_cards: [makeCard('sv06-001', 'Dragapult ex', 4)],
  original_deck_text: '4 Dragapult ex sv06-001',
  original_ptcgl_text: 'Pokémon: 4\n4 Dragapult ex MEG 001',
  final_working_deck_id: null,
  final_deck_name: 'My Deck',
  final_cards: [makeCard('sv06-001', 'Dragapult ex', 4)],
  final_deck_text: '4 Dragapult ex sv06-001',
  final_ptcgl_text: 'Pokémon: 4\n4 Dragapult ex MEG 001',
  changed_cards: [],
  has_mutations: false,
  metadata_warnings: [],
};

const WITH_MUTATIONS: FinalDeckResponse = {
  original_deck_id: 'orig-id',
  original_deck_name: 'My Deck',
  original_cards: [
    makeCard('sv06-001', 'Dragapult ex', 4),
    makeCard('sv06-002', 'Iron Hands ex', 3, 'Pokemon'),
  ],
  original_deck_text: '4 Dragapult ex sv06-001\n3 Iron Hands ex sv06-002',
  original_ptcgl_text: 'Pokémon: 7\n4 Dragapult ex MEG 001\n3 Iron Hands ex MEG 001',
  final_working_deck_id: 'working-id',
  final_deck_name: 'My Deck — sim abc r2',
  final_cards: [
    makeCard('sv06-001', 'Dragapult ex', 4),
    makeCard('sv06-003', "Boss's Orders", 4, 'Trainer'),
  ],
  final_deck_text: '4 Dragapult ex sv06-001\n4 Boss\'s Orders sv06-003',
  final_ptcgl_text: "Pokémon: 4\n4 Dragapult ex MEG 001\n\nTrainer: 4\n4 Boss's Orders MEG 001",
  changed_cards: [
    { tcgdex_id: 'sv06-002', name: 'Iron Hands ex', original_count: 3, final_count: 0 },
    { tcgdex_id: 'sv06-003', name: "Boss's Orders", original_count: 0, final_count: 4 },
  ],
  has_mutations: true,
  metadata_warnings: [],
};

const WITH_WARNINGS: FinalDeckResponse = {
  ...WITH_MUTATIONS,
  metadata_warnings: ['Unknown Card sv99-999 — set/number metadata missing, used TCGdex ID'],
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

  it('shows "Copy PTCGL decklist" button for final deck', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('copy-final-ptcgl-btn')).toBeInTheDocument();
    expect(screen.getByTestId('copy-final-ptcgl-btn')).toHaveTextContent('Copy PTCGL decklist');
  });

  it('shows "Copy PTCGL decklist" button for original deck', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('copy-original-ptcgl-btn')).toBeInTheDocument();
    expect(screen.getByTestId('copy-original-ptcgl-btn')).toHaveTextContent('Copy PTCGL decklist');
  });

  it('shows toggle button for final PTCGL decklist', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('toggle-final-ptcgl-decklist')).toBeInTheDocument();
  });

  it('expands final PTCGL decklist on toggle click and shows human-readable text', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    fireEvent.click(screen.getByTestId('toggle-final-ptcgl-decklist'));
    const pre = screen.getByTestId('decklist-pre-final-ptcgl-decklist');
    expect(pre).toBeInTheDocument();
    expect(pre.textContent).toContain('Dragapult ex');
    expect(pre.textContent).toContain('MEG');
  });

  it('shows toggle button for original PTCGL decklist', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.getByTestId('toggle-original-ptcgl-decklist')).toBeInTheDocument();
  });

  it('expands original PTCGL decklist on toggle click', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    fireEvent.click(screen.getByTestId('toggle-original-ptcgl-decklist'));
    expect(screen.getByTestId('decklist-pre-original-ptcgl-decklist')).toBeInTheDocument();
  });

  it('shows metadata warning when present', () => {
    render(<DeckEvolutionPanel data={WITH_WARNINGS} />);
    expect(screen.getByTestId('deck-evolution-metadata-warnings')).toBeInTheDocument();
    expect(screen.getByText(/Some cards could not be fully formatted/i)).toBeInTheDocument();
  });

  it('does not show metadata warning when warnings list is empty', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.queryByTestId('deck-evolution-metadata-warnings')).not.toBeInTheDocument();
  });

  it('does not show no-mutations message when has_mutations is true', () => {
    render(<DeckEvolutionPanel data={WITH_MUTATIONS} />);
    expect(screen.queryByTestId('deck-evolution-no-mutations')).not.toBeInTheDocument();
  });
});
