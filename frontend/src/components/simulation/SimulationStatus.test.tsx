import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SimulationStatus from './SimulationStatus';

const BASE_DETAIL = {
  num_rounds: 1,
  rounds_completed: 0,
  matches_per_opponent: 10,
  total_matches: 0,
  target_win_rate: 0.6,
  final_win_rate: null,
  game_mode: 'hh',
  user_deck_name: 'Test Deck',
  error_message: null,
};

describe('SimulationStatus status labels', () => {
  it.each([
    ['pending',   'Pending'],
    ['queued',    'Queued'],
    ['running',   'Running'],
    ['complete',  'Complete'],
    ['failed',    'Failed'],
    ['cancelled', 'Cancelled'],
  ] as const)('renders %s as "%s"', (status, label) => {
    render(<SimulationStatus detail={{ ...BASE_DETAIL, status }} />);
    expect(screen.getByTestId('simulation-status-badge').textContent).toBe(label);
  });
});
