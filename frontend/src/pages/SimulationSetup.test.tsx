import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SimulationSetup from './SimulationSetup';

// Mock ParamForm to avoid card search API calls
vi.mock('../components/simulation/ParamForm', () => ({
  default: () => <div data-testid="param-form" />,
}));

// Mock parsePTCGDeck to return a valid 60-card deck so form validation passes
vi.mock('../utils/deckParser', () => ({
  parsePTCGDeck: vi.fn().mockReturnValue({
    totalCards: 60,
    pokemon: [],
    trainers: [],
    energy: [],
    errors: [],
  }),
}));

const mockCreateSimulation = vi.fn();
vi.mock('../api/simulations', () => ({
  createSimulation: (...args: unknown[]) => mockCreateSimulation(...args),
}));

// Mock useNavigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderSetup() {
  return render(
    <MemoryRouter>
      <SimulationSetup />
    </MemoryRouter>
  );
}

describe('SimulationSetup — deck name overrides', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateSimulation.mockResolvedValue({ simulation_id: 'test-sim-1', status: 'pending' });
  });

  it('renders the deck name input when deck mode is full', () => {
    renderSetup();
    expect(screen.getByTestId('deck-name-input')).toBeInTheDocument();
  });

  it('does not render deck name input in no-deck mode', async () => {
    const user = userEvent.setup();
    renderSetup();

    await user.click(screen.getByRole('radio', { name: 'No Deck' }));
    expect(screen.queryByTestId('deck-name-input')).not.toBeInTheDocument();
  });

  it('includes user_deck_name in submission when filled', async () => {
    const user = userEvent.setup();
    renderSetup();

    // Fill user deck name
    await user.type(screen.getByTestId('deck-name-input'), 'My Test Deck');

    // Add one opponent
    await user.click(screen.getByTestId('add-opponent-button'));

    // Submit
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(mockCreateSimulation).toHaveBeenCalledWith(
        expect.objectContaining({ user_deck_name: 'My Test Deck' })
      );
    });
  });

  it('sends null user_deck_name when deck name is blank', async () => {
    const user = userEvent.setup();
    renderSetup();

    // Add one opponent
    await user.click(screen.getByTestId('add-opponent-button'));

    // Submit without filling deck name
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(mockCreateSimulation).toHaveBeenCalledWith(
        expect.objectContaining({ user_deck_name: null })
      );
    });
  });

  it('includes opponent_deck_names in submission', async () => {
    const user = userEvent.setup();
    renderSetup();

    // Add opponent (auto-expands at index 0)
    await user.click(screen.getByTestId('add-opponent-button'));

    // Fill name (already expanded from add)
    await user.type(screen.getByTestId('opponent-name-input-0'), 'Opponent Custom Name');

    // Submit
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(mockCreateSimulation).toHaveBeenCalledWith(
        expect.objectContaining({
          opponent_deck_names: ['Opponent Custom Name'],
        })
      );
    });
  });

  it('sends null for blank opponent deck names', async () => {
    const user = userEvent.setup();
    renderSetup();

    // Add opponent (no name filled)
    await user.click(screen.getByTestId('add-opponent-button'));

    // Submit
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(mockCreateSimulation).toHaveBeenCalledWith(
        expect.objectContaining({
          opponent_deck_names: [null],
        })
      );
    });
  });

  it('aligns opponent_deck_names with opponent_deck_texts', async () => {
    const user = userEvent.setup();
    renderSetup();

    // Add two opponents
    await user.click(screen.getByTestId('add-opponent-button'));
    await user.click(screen.getByTestId('add-opponent-button'));

    // Name the first opponent
    await user.click(screen.getByText('Opponent 1'));
    await user.type(screen.getByTestId('opponent-name-input-0'), 'Named Opponent');

    // Collapse first, expand second (no name for second)
    await user.click(screen.getByText('Named Opponent'));
    await user.click(screen.getByText('Opponent 2'));

    // Submit
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(mockCreateSimulation).toHaveBeenCalledWith(
        expect.objectContaining({
          opponent_deck_texts: ['', ''],
          opponent_deck_names: ['Named Opponent', null],
        })
      );
    });
  });

  it('shows validation error when user deck name exceeds 120 chars', async () => {
    const user = userEvent.setup();
    renderSetup();

    await user.type(screen.getByTestId('deck-name-input'), 'x'.repeat(121));
    await user.click(screen.getByTestId('add-opponent-button'));
    await user.click(screen.getByTestId('start-simulation-button'));

    await waitFor(() => {
      expect(screen.getByTestId('simulation-error')).toHaveTextContent(
        'Deck name must be 120 characters or fewer'
      );
    });
    expect(mockCreateSimulation).not.toHaveBeenCalled();
  });

  it('renders start simulation button', () => {
    renderSetup();
    expect(screen.getByTestId('start-simulation-button')).toBeInTheDocument();
  });
});
