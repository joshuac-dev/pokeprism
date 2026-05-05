import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LiveConsole from './LiveConsole';
import type { NormalisedEvent } from '../../types/simulation';

function makeEvent(overrides: Partial<NormalisedEvent> = {}): NormalisedEvent {
  return {
    type: 'match_event',
    eventType: 'energy_attached',
    turn: 21,
    player: 'p1',
    match_id: undefined,
    data: { card: 'Spiky Energy', target: 'Crustle', energy_type: 'Colorless' },
    ...overrides,
  };
}

const BASE_PROPS = {
  events: [] as NormalisedEvent[],
  totalEvents: 0,
  hasMore: false,
  onLoadEarlier: undefined,
  onEventClick: vi.fn(),
};

describe('LiveConsole — ai_decision visibility', () => {
  it('does NOT render a visible row for ai_decision events', () => {
    const aiDecision = makeEvent({
      eventType: 'ai_decision',
      data: {
        action_type: 'ATTACH_ENERGY',
        reasoning: 'Attach Spiky Energy to Crustle because it needs energy',
        card_played: null,
        target: 'Crustle',
        attack_index: null,
      },
    });

    render(<LiveConsole {...BASE_PROPS} events={[aiDecision]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    // No rows should be rendered — ai_decision is hidden
    expect(screen.queryAllByTestId('live-console-event').length).toBe(0);
    // The 🤖 emoji should never appear
    expect(eventList.textContent).not.toContain('🤖');
    expect(eventList.textContent).not.toContain('ATTACH_ENERGY');
    expect(eventList.textContent).not.toContain('Attach Spiky Energy');
  });

  it('still renders energy_attached as a visible row', () => {
    const energyEvent = makeEvent({ eventType: 'energy_attached' });

    render(<LiveConsole {...BASE_PROPS} events={[energyEvent]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('T21');
    expect(eventList.textContent).toContain('Spiky Energy');
    expect(eventList.textContent).toContain('Crustle');
  });

  it('renders visible energy_attached row even when preceded by hidden ai_decision', () => {
    const aiDecision = makeEvent({
      eventType: 'ai_decision',
      data: {
        action_type: 'ATTACH_ENERGY',
        reasoning: 'Attach for coverage',
        card_played: null,
        target: 'Crustle',
        attack_index: null,
      },
    });
    const energyEvent = makeEvent({ eventType: 'energy_attached' });

    render(<LiveConsole {...BASE_PROPS} events={[aiDecision, energyEvent]} totalEvents={2} />);

    const eventList = screen.getByTestId('live-console-events');
    // Only the energy_attached row should be visible
    expect(eventList.textContent).toContain('T21');
    expect(eventList.textContent).toContain('Spiky Energy');
    expect(eventList.textContent).not.toContain('🤖');
    expect(eventList.textContent).not.toContain('Attach for coverage');
  });

  it('renders evolved rows as visible console rows', () => {
    const evolvedEvent = makeEvent({
      eventType: 'evolved',
      data: { from: 'Staryu', to: 'Mega Starmie ex' },
    });

    render(<LiveConsole {...BASE_PROPS} events={[evolvedEvent]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('T21');
  });
});
