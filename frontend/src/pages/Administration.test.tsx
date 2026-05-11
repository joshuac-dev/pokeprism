import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Administration from './Administration';

// ── Mock API ─────────────────────────────────────────────────────────────────

vi.mock('../api/admin', () => ({
  getNightlyHHRerunStatus: vi.fn(),
  previewNightlyHHRerun: vi.fn(),
  triggerNightlyHHRerun: vi.fn(),
}));

import {
  getNightlyHHRerunStatus,
  previewNightlyHHRerun,
  triggerNightlyHHRerun,
} from '../api/admin';

const mockStatus = {
  enabled: true,
  schedule: '02:00 UTC nightly',
  eligible_source_count: 3,
  current_cycle: 2,
  current_cycle_completed_count: 1,
  current_cycle_total_count: 3,
  last_rerun: null,
  fixed_parameters: {
    deck_locked: false,
    game_mode: 'hh',
    matches_per_opponent: 25,
    num_rounds: 3,
    target_win_rate: 60,
    target_consecutive_rounds: 3,
    target_mode: 'per_opponent',
  },
};

function renderPage() {
  return render(
    <MemoryRouter>
      <Administration />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  (getNightlyHHRerunStatus as ReturnType<typeof vi.fn>).mockResolvedValue(mockStatus);
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Administration page', () => {
  it('renders nightly H/H rerun section heading', async () => {
    renderPage();
    expect(await screen.findByText('Nightly H/H Rerun')).toBeInTheDocument();
  });

  it('displays fixed parameters from status', async () => {
    renderPage();
    // Matches per Opponent
    expect(await screen.findByText('25')).toBeInTheDocument();
    // Target Win Rate
    expect(await screen.findByText('60%')).toBeInTheDocument();
    // Lock Deck
    expect(await screen.findByText('Disabled')).toBeInTheDocument();
    // Target Mode
    expect(await screen.findByText('per_opponent')).toBeInTheDocument();
    // Rounds (3 appears twice — just check multiple)
    const threes = await screen.findAllByText('3');
    expect(threes.length).toBeGreaterThanOrEqual(2);
  });

  it('displays schedule and cycle info', async () => {
    renderPage();
    expect(await screen.findByText('02:00 UTC nightly')).toBeInTheDocument();
    expect(await screen.findByText('2')).toBeInTheDocument(); // current cycle
  });

  it('preview button calls previewNightlyHHRerun and shows source', async () => {
    const previewResult = {
      status: 'ok',
      cycle_number: 2,
      next_source: {
        simulation_id: 'abc123-full-uuid',
        created_at: '2026-01-01T00:00:00Z',
        user_deck_id: 'deck-uuid',
        user_deck_name: 'TestDeck',
        opponents: [{ deck_id: 'opp-uuid', deck_name: 'RivalDeck' }],
      },
      generated_parameters: mockStatus.fixed_parameters,
    };
    (previewNightlyHHRerun as ReturnType<typeof vi.fn>).mockResolvedValue(previewResult);

    renderPage();
    await screen.findByText('Nightly H/H Rerun');

    await userEvent.click(screen.getByText('Preview Next Run'));

    expect(await screen.findByText('TestDeck')).toBeInTheDocument();
    expect(await screen.findByText('RivalDeck')).toBeInTheDocument();
  });

  it('preview button shows skipped reason', async () => {
    (previewNightlyHHRerun as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'skipped',
      reason: 'simulation queue busy',
    });

    renderPage();
    await screen.findByText('Nightly H/H Rerun');

    await userEvent.click(screen.getByText('Preview Next Run'));

    expect(await screen.findByText(/simulation queue busy/)).toBeInTheDocument();
  });

  it('trigger button calls triggerNightlyHHRerun and shows created result', async () => {
    (triggerNightlyHHRerun as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'created',
      source_simulation_id: 'src-uuid',
      generated_simulation_id: 'gen-uuid-here',
      cycle_number: 2,
    });

    renderPage();
    await screen.findByText('Nightly H/H Rerun');

    await userEvent.click(screen.getByText('Trigger Nightly H/H Rerun Now'));

    expect(await screen.findByText(/Created/)).toBeInTheDocument();
    expect(await screen.findByText(/gen-uuid/)).toBeInTheDocument();
  });

  it('trigger button shows skipped result', async () => {
    (triggerNightlyHHRerun as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'skipped',
      reason: 'no eligible source simulations',
    });

    renderPage();
    await screen.findByText('Nightly H/H Rerun');

    await userEvent.click(screen.getByText('Trigger Nightly H/H Rerun Now'));

    expect(await screen.findByText(/no eligible source simulations/)).toBeInTheDocument();
  });
});

describe('Sidebar Administration link', () => {
  it('renders Administration nav item', async () => {
    const { render: r } = await import('@testing-library/react');
    const { default: Sidebar } = await import('../components/layout/Sidebar');
    const { screen: s } = await import('@testing-library/react');

    r(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    );

    expect(s.getByText('Administration')).toBeInTheDocument();
  });
});
