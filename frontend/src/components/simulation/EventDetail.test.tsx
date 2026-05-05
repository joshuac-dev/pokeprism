import { render, screen, within, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import EventDetail from './EventDetail';
import type { NormalisedEvent, DecisionRow } from '../../types/simulation';

// ── API mock ──────────────────────────────────────────────────────────────────
vi.mock('../../api/simulations', () => ({
  getSimulationDecisions: vi.fn(),
}));

import { getSimulationDecisions } from '../../api/simulations';
const mockGetDecisions = vi.mocked(getSimulationDecisions);

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeEvent(overrides: Partial<NormalisedEvent> = {}): NormalisedEvent {
  return {
    type: 'match_event',
    eventType: 'attack_damage',
    turn: 5,
    player: 'p1',
    match_id: undefined,
    data: { final_damage: 120, attacker: 'Dragapult ex' },
    ...overrides,
  };
}

function makeAiDecisionEvent(overrides: Partial<NormalisedEvent> = {}): NormalisedEvent {
  return {
    type: 'match_event',
    eventType: 'ai_decision',
    turn: 5,
    player: 'p1',
    match_id: undefined,
    data: {
      action_type: 'ATTACK',
      reasoning: 'Phantom Dive for the KO',
      card_played: null,
      target: null,
      attack_index: 0,
    },
    ...overrides,
  };
}

function makeDecisionRow(overrides: Partial<DecisionRow> = {}): DecisionRow {
  return {
    id: 'db-row-1',
    match_id: 'match-abc',
    turn_number: 5,
    player_id: 'p1',
    action_type: 'ATTACK',
    card_played: null,
    target: null,
    reasoning: 'DB reasoning text',
    legal_action_count: 12,
    game_state_summary: null,
    created_at: null,
    ...overrides,
  };
}

const BASE_PROPS = {
  simulationId: 'sim-123',
  isAiMode: true,
  onClose: vi.fn(),
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('EventDetail — live AI reasoning', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // Default: DB returns empty
    mockGetDecisions.mockResolvedValue({ decisions: [], total: 0 });
  });

  it('shows reasoning immediately when clicked event IS an ai_decision (no API call)', () => {
    const aiDecisionEvent = makeAiDecisionEvent();
    const liveEvents = [aiDecisionEvent];

    render(
      <EventDetail
        {...BASE_PROPS}
        event={aiDecisionEvent}
        liveEvents={liveEvents}
      />
    );

    expect(screen.getByTestId('event-detail-ai-reasoning')).toBeInTheDocument();
    const reasoningSection = screen.getByTestId('event-detail-ai-reasoning');
    expect(within(reasoningSection).getByText('Phantom Dive for the KO')).toBeInTheDocument();
    expect(screen.getByTestId('event-detail-live-reasoning')).toBeInTheDocument();
    // No DB call since no match_id
    expect(mockGetDecisions).not.toHaveBeenCalled();
  });

  it('shows reasoning from prior ai_decision event when clicking a correlated action event', () => {
    const aiDecisionEvent = makeAiDecisionEvent();
    const attackEvent = makeEvent({ turn: 5, player: 'p1', eventType: 'attack_damage' });
    const liveEvents = [aiDecisionEvent, attackEvent];

    render(
      <EventDetail
        {...BASE_PROPS}
        event={attackEvent}
        liveEvents={liveEvents}
      />
    );

    expect(screen.getByTestId('event-detail-ai-reasoning')).toBeInTheDocument();
    const reasoningSection2 = screen.getByTestId('event-detail-ai-reasoning');
    expect(within(reasoningSection2).getByText('Phantom Dive for the KO')).toBeInTheDocument();
    expect(screen.getByTestId('event-detail-live-reasoning')).toBeInTheDocument();
  });

  it('calls getSimulationDecisions as fallback when no live reasoning and event has match_id', async () => {
    const eventWithMatch = makeEvent({ match_id: 'match-abc' });
    const liveEvents = [eventWithMatch]; // no prior ai_decision

    mockGetDecisions.mockResolvedValue({ decisions: [makeDecisionRow()], total: 1 });

    render(
      <EventDetail
        {...BASE_PROPS}
        event={eventWithMatch}
        liveEvents={liveEvents}
      />
    );

    await waitFor(() => {
      expect(mockGetDecisions).toHaveBeenCalledWith('sim-123', expect.objectContaining({
        match_id: 'match-abc',
        turn_number: 5,
      }));
    });

    expect(await screen.findByText('DB reasoning text')).toBeInTheDocument();
  });

  it('keeps live reasoning visible when DB API returns empty', async () => {
    const aiDecisionEvent = makeAiDecisionEvent({
      match_id: 'match-abc', // has match_id — DB fetch will run
    });
    const attackEvent = makeEvent({ turn: 5, player: 'p1', eventType: 'attack_damage', match_id: 'match-abc' });
    const liveEvents = [aiDecisionEvent, attackEvent];

    // DB returns empty
    mockGetDecisions.mockResolvedValue({ decisions: [], total: 0 });

    render(
      <EventDetail
        {...BASE_PROPS}
        event={attackEvent}
        liveEvents={liveEvents}
      />
    );

    // Live reasoning is immediately present
    const liveSection = screen.getByTestId('event-detail-ai-reasoning');
    expect(within(liveSection).getByText('Phantom Dive for the KO')).toBeInTheDocument();

    // After DB fetch completes (returns empty), live reasoning should remain
    await waitFor(() => expect(mockGetDecisions).toHaveBeenCalled());
    expect(within(screen.getByTestId('event-detail-ai-reasoning')).getByText('Phantom Dive for the KO')).toBeInTheDocument();
  });

  it('does not render AI reasoning section when isAiMode is false', () => {
    const attackEvent = makeEvent();
    const liveEvents = [makeAiDecisionEvent(), attackEvent];

    render(
      <EventDetail
        {...BASE_PROPS}
        isAiMode={false}
        event={attackEvent}
        liveEvents={liveEvents}
      />
    );

    expect(screen.queryByTestId('event-detail-ai-reasoning')).not.toBeInTheDocument();
  });

  it('shows "has not been persisted yet" message when no live or DB decision available', async () => {
    const attackEvent = makeEvent(); // no match_id, no live ai_decision before it
    const liveEvents = [attackEvent];

    render(
      <EventDetail
        {...BASE_PROPS}
        event={attackEvent}
        liveEvents={liveEvents}
      />
    );

    expect(screen.getByText(/has not been persisted yet/i)).toBeInTheDocument();
  });

  it('does not correlate ai_decision from a different turn', () => {
    const aiDecisionWrongTurn = makeAiDecisionEvent({ turn: 3 });
    const attackEvent = makeEvent({ turn: 5 });
    const liveEvents = [aiDecisionWrongTurn, attackEvent];

    render(
      <EventDetail
        {...BASE_PROPS}
        event={attackEvent}
        liveEvents={liveEvents}
      />
    );

    // No live decision found since turn differs
    expect(screen.queryByTestId('event-detail-live-reasoning')).not.toBeInTheDocument();
    expect(screen.getByText(/has not been persisted yet/i)).toBeInTheDocument();
  });
});
