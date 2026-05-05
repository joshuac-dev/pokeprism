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

  it('renders pass events as visible console rows with "Pass" text', () => {
    const passEvent = makeEvent({
      eventType: 'pass',
      turn: 12,
      player: 'p2',
      data: {},
    });

    render(<LiveConsole {...BASE_PROPS} events={[passEvent]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('T12');
    expect(eventList.textContent).toContain('Pass');
  });

  it('renders end_turn events as visible console rows with "End turn" text', () => {
    const endTurnEvent = makeEvent({
      eventType: 'end_turn',
      turn: 13,
      player: 'p1',
      data: {},
    });

    render(<LiveConsole {...BASE_PROPS} events={[endTurnEvent]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('T13');
    expect(eventList.textContent).toContain('End turn');
  });

  it('renders turn_start events as a visible separator row', () => {
    const turnStart = makeEvent({ eventType: 'turn_start', turn: 5, player: 'p1', data: { turn: 5 } });

    render(<LiveConsole {...BASE_PROPS} events={[turnStart]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    const rows = screen.queryAllByTestId('live-console-event');
    expect(rows.length).toBe(1);
    expect(eventList.textContent).toContain('T5');
  });
});

describe('LiveConsole — setup phase events', () => {
  it('renders setup_start as a match banner', () => {
    const ev = makeEvent({
      eventType: 'setup_start',
      turn: undefined,
      player: undefined,
      data: { p1_deck: 'Meowth ex Deck', p2_deck: 'Roselia Deck' },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Setup');
    expect(eventList.textContent).toContain('Meowth ex Deck');
    expect(eventList.textContent).toContain('Roselia Deck');
  });

  it('renders opening_hand_drawn with card names', () => {
    const ev = makeEvent({
      eventType: 'opening_hand_drawn',
      turn: undefined,
      player: 'p1',
      data: {
        count: 3,
        cards: ['Meowth ex', 'Ignition Energy', "Boss's Orders"],
      },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Hand');
    expect(eventList.textContent).toContain('Meowth ex');
    expect(eventList.textContent).toContain('Ignition Energy');
  });

  it('renders coin_flip with first player indication', () => {
    const ev = makeEvent({
      eventType: 'coin_flip',
      turn: undefined,
      player: undefined,
      data: { first_player: 'p1' },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('coin flip');
    expect(eventList.textContent).toContain('p1');
  });

  it('renders place_active as setup active selection', () => {
    const ev = makeEvent({
      eventType: 'place_active',
      turn: undefined,
      player: 'p2',
      data: { card: "Cynthia's Roselia" },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Active');
    expect(eventList.textContent).toContain("Cynthia's Roselia");
  });

  it('renders place_bench as setup bench placement', () => {
    const ev = makeEvent({
      eventType: 'place_bench',
      turn: undefined,
      player: 'p1',
      data: { card: 'Fezandipiti ex' },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Bench');
    expect(eventList.textContent).toContain('Fezandipiti ex');
  });

  it('renders prizes_set with count', () => {
    const ev = makeEvent({
      eventType: 'prizes_set',
      turn: undefined,
      player: 'p1',
      data: { count: 6, cards: ['A', 'B', 'C', 'D', 'E', 'F'] },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Prizes');
    expect(eventList.textContent).toContain('6');
  });

  it('renders setup_complete as a completion banner', () => {
    const ev = makeEvent({
      eventType: 'setup_complete',
      turn: undefined,
      player: undefined,
      data: {
        p1_active: 'Meowth ex',
        p2_active: "Cynthia's Roselia",
        p1_bench: [],
        p2_bench: [],
        p1_prizes: 6,
        p2_prizes: 6,
      },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Setup complete');
    expect(eventList.textContent).toContain('Meowth ex');
  });

  it('renders mulligan event with new hand', () => {
    const ev = makeEvent({
      eventType: 'mulligan',
      turn: undefined,
      player: 'p2',
      data: { new_hand_size: 2, new_hand: ['Duskull', 'Water Energy'] },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Mulligan');
    expect(eventList.textContent).toContain('Duskull');
  });
});

describe('LiveConsole — draw event formatting', () => {
  it('renders draw with card names when cards field is present', () => {
    const ev = makeEvent({
      eventType: 'draw',
      turn: 7,
      player: 'p1',
      data: { count: 1, cards: ['Meowth ex'], hand_size: 5 },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('T7');
    expect(eventList.textContent).toContain('Meowth ex');
    expect(eventList.textContent).toContain('Draw');
  });

  it('renders draw as Draw×N when no cards field', () => {
    const ev = makeEvent({
      eventType: 'draw',
      turn: 3,
      player: 'p2',
      data: { count: 4, hand_size: 7 },
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Draw');
    expect(eventList.textContent).toContain('4');
  });

  it('renders shuffle_deck with readable text', () => {
    const ev = makeEvent({
      eventType: 'shuffle_deck',
      turn: 9,
      player: 'p1',
      data: {},
    });

    render(<LiveConsole {...BASE_PROPS} events={[ev]} totalEvents={1} />);

    const eventList = screen.getByTestId('live-console-events');
    expect(eventList.textContent).toContain('Shuffle deck');
  });
});
