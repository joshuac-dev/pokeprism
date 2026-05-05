import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import History from './History';

// ── Mock API ─────────────────────────────────────────────────────────────────

vi.mock('../api/history', () => ({
  listSimulations: vi.fn(),
  starSimulation: vi.fn().mockResolvedValue({ starred: true }),
  deleteSimulation: vi.fn().mockResolvedValue(undefined),
  getCompareStats: vi.fn(),
}));

import { listSimulations } from '../api/history';

function makeSim(overrides: Partial<{
  id: string;
  status: string;
  game_mode: string;
  deck_mode: string;
  num_rounds: number;
  rounds_completed: number;
  total_matches: number;
  final_win_rate: number | null;
  user_deck_name: string | null;
  starred: boolean;
  created_at: string | null;
  opponents: string[];
}> = {}) {
  return {
    id: 'sim-001',
    status: 'complete',
    game_mode: 'standard',
    deck_mode: 'single',
    num_rounds: 10,
    rounds_completed: 10,
    total_matches: 10,
    final_win_rate: 0.7,
    user_deck_name: 'My Deck',
    starred: false,
    created_at: '2026-01-01T00:00:00Z',
    opponents: [],
    ...overrides,
  };
}

const paginatedResponse = (items: ReturnType<typeof makeSim>[]) => ({
  items,
  total: items.length,
  page: 1,
  per_page: 25,
});

function setup() {
  return render(
    <MemoryRouter>
      <History />
    </MemoryRouter>,
  );
}

async function waitForTable() {
  await waitFor(() => expect(screen.getByTestId('history-table')).toBeInTheDocument());
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('History page', () => {
  // ── Basic render ────────────────────────────────────────────────────────────

  it('renders the history table', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(paginatedResponse([makeSim()]));
    setup();
    await waitForTable();
    expect(screen.getByTestId('history-table')).toBeInTheDocument();
  });

  // ── Opponent display ────────────────────────────────────────────────────────

  it('renders — for zero opponents', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents: [] })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('renders one opponent inline without More…', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents: ['Deck A'] })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByText(/Deck A/)).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('renders exactly three opponents inline without More…', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents: ['Deck A', 'Deck B', 'Deck C'] })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByText(/Deck A, Deck B, Deck C/)).toBeInTheDocument();
    expect(screen.queryByTestId('opponent-more-btn')).not.toBeInTheDocument();
  });

  it('shows only first three opponents and More… for four-plus opponents', async () => {
    const opponents = ['Deck A', 'Deck B', 'Deck C', 'Deck D', 'Deck E'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByText(/Deck A, Deck B, Deck C/)).toBeInTheDocument();
    // Hidden opponents not rendered inline
    expect(screen.queryByText(/Deck D/)).not.toBeInTheDocument();
    expect(screen.getByTestId('opponent-more-btn')).toBeInTheDocument();
  });

  it('More… button has accessible aria-label with total opponent count', async () => {
    const opponents = ['A', 'B', 'C', 'D', 'E'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByTestId('opponent-more-btn')).toHaveAttribute(
      'aria-label',
      'Show all 5 opponent decks',
    );
  });

  // ── Modal open/close ────────────────────────────────────────────────────────

  it('clicking More… opens the opponent deck modal with all opponents', async () => {
    const user = userEvent.setup();
    const opponents = ['Deck A', 'Deck B', 'Deck C', 'Deck D'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ id: 'sim-x', user_deck_name: 'My Deck', opponents })]),
    );
    setup();
    await waitForTable();
    await user.click(screen.getByTestId('opponent-more-btn'));
    const modal = screen.getByTestId('opponent-deck-modal');
    expect(modal).toBeInTheDocument();
    const list = screen.getByTestId('opponent-deck-list');
    opponents.forEach(name => expect(list).toHaveTextContent(name));
  });

  it('modal shows user deck name as context', async () => {
    const user = userEvent.setup();
    const opponents = ['A', 'B', 'C', 'D'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ user_deck_name: 'Pikachu ex Deck', opponents })]),
    );
    setup();
    await waitForTable();
    await user.click(screen.getByTestId('opponent-more-btn'));
    expect(screen.getByTestId('opponent-deck-modal-context')).toHaveTextContent('Pikachu ex Deck');
  });

  it('Escape closes the opponent deck modal', async () => {
    const user = userEvent.setup();
    const opponents = ['A', 'B', 'C', 'D'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents })]),
    );
    setup();
    await waitForTable();
    await user.click(screen.getByTestId('opponent-more-btn'));
    expect(screen.getByTestId('opponent-deck-modal')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByTestId('opponent-deck-modal')).not.toBeInTheDocument(),
    );
  });

  it('backdrop click closes the opponent deck modal', async () => {
    const user = userEvent.setup();
    const opponents = ['A', 'B', 'C', 'D'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents })]),
    );
    setup();
    await waitForTable();
    await user.click(screen.getByTestId('opponent-more-btn'));
    expect(screen.getByTestId('opponent-deck-modal')).toBeInTheDocument();
    await user.click(screen.getByTestId('opponent-deck-modal'));
    await waitFor(() =>
      expect(screen.queryByTestId('opponent-deck-modal')).not.toBeInTheDocument(),
    );
  });

  it('close button closes the opponent deck modal', async () => {
    const user = userEvent.setup();
    const opponents = ['A', 'B', 'C', 'D'];
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ opponents })]),
    );
    setup();
    await waitForTable();
    await user.click(screen.getByTestId('opponent-more-btn'));
    await user.click(screen.getByTestId('opponent-deck-modal-close'));
    await waitFor(() =>
      expect(screen.queryByTestId('opponent-deck-modal')).not.toBeInTheDocument(),
    );
  });

  // ── Controls still work ─────────────────────────────────────────────────────

  it('View and Delete buttons still render', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(
      paginatedResponse([makeSim({ status: 'complete' })]),
    );
    setup();
    await waitForTable();
    expect(screen.getByRole('button', { name: /View/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete/i })).toBeInTheDocument();
  });

  it('pagination controls render', async () => {
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(paginatedResponse([makeSim()]));
    setup();
    await waitForTable();
    expect(screen.getByRole('button', { name: /Prev/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Next/i })).toBeInTheDocument();
  });

  it('search input renders and does not open modal', async () => {
    const user = userEvent.setup();
    (listSimulations as ReturnType<typeof vi.fn>).mockResolvedValue(paginatedResponse([makeSim()]));
    setup();
    await waitForTable();
    const searchInput = screen.getByPlaceholderText(/Search/i);
    await user.type(searchInput, 'Pikachu');
    expect(screen.queryByTestId('opponent-deck-modal')).not.toBeInTheDocument();
  });
});
