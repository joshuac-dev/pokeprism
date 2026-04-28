/** Shared TypeScript types for Phase 9 simulation data. */

// ----- Events ----------------------------------------------------------------

/** A single match event as returned by GET /api/simulations/:id/events */
export interface MatchEventRow {
  id: number;
  /** Always "match_event" from the REST API */
  type: 'match_event';
  /** Discriminator: energy_attached, attack, ko, prize_taken, etc. */
  event_type: string;
  round_number: number;
  match_id: string;
  p1_deck_name: string | null;
  p2_deck_name: string | null;
  turn: number | null;
  player: string | null;
  data: Record<string, unknown>;
}

/** A live WebSocket event (uses "event" not "event_type") */
export interface LiveEvent {
  type: string;
  simulation_id?: string;
  round_number?: number;
  match_number?: number;
  /** Live events use "event" as the discriminator */
  event?: string;
  /** REST buffered events use "event_type" */
  event_type?: string;
  [key: string]: unknown;
}

/** Normalised event — both REST and WS unify here */
export interface NormalisedEvent {
  id?: number;
  type: string;
  /** Unified discriminator: falls back from event_type → event */
  eventType: string;
  round_number?: number;
  match_id?: string;
  p1_deck_name?: string | null;
  p2_deck_name?: string | null;
  turn?: number | null;
  player?: string | null;
  data: Record<string, unknown>;
}

export function normaliseEvent(raw: MatchEventRow | LiveEvent): NormalisedEvent {
  const restRaw = raw as MatchEventRow;
  const liveRaw = raw as Record<string, unknown>;
  return {
    id: restRaw.id,
    type: raw.type,
    eventType: (restRaw.event_type ?? (raw as LiveEvent).event ?? raw.type),
    round_number: raw.round_number,
    match_id: restRaw.match_id,
    p1_deck_name: restRaw.p1_deck_name,
    p2_deck_name: restRaw.p2_deck_name,
    // For live match_events, turn/player are published as top-level fields
    turn: restRaw.turn ?? (liveRaw.turn as number | null | undefined) ?? null,
    player: restRaw.player ?? (liveRaw.player as string | null | undefined) ?? null,
    // For REST events, data is the JSONB payload. For lifecycle live events
    // (match_start/match_end) that have no nested data field, fall back to the
    // whole raw object so ev.data.match_number / ev.data.p1_deck etc. are accessible.
    data: restRaw.data ?? (liveRaw as Record<string, unknown>),
  };
}

// ----- Decisions -------------------------------------------------------------

export interface DecisionRow {
  id: string;
  match_id: string | null;
  turn_number: number;
  player_id: string;
  action_type: string;
  card_played: string | null;
  target: string | null;
  reasoning: string | null;
  legal_action_count: number;
  game_state_summary: string | null;
  created_at: string | null;
}

// ----- Simulation detail -----------------------------------------------------

export interface SimulationDetail {
  id: string;
  status: 'pending' | 'running' | 'complete' | 'failed' | 'cancelled';
  user_deck_name: string | null;
  game_mode: string;
  deck_mode: string;
  num_rounds: number;
  rounds_completed: number;
  matches_per_opponent: number;
  total_matches: number;
  target_win_rate: number;
  final_win_rate: number | null;
  starred: boolean;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

// ----- Deck mutations --------------------------------------------------------

export interface DeckMutation {
  round: number;
  card_in: string | null;
  card_out: string | null;
  win_rate_before: number | null;
  win_rate_after: number | null;
}
