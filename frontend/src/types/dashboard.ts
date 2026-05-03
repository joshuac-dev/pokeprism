export interface MatchRow {
  id: string;
  round_number: number;
  winner: 'p1' | 'p2';
  win_condition: string;
  total_turns: number;
  p1_prizes_taken: number;
  p2_prizes_taken: number;
  p1_deck_name: string | null;
  p2_deck_name: string | null;
  opponent_deck_id: string | null;
}

export interface RoundRow {
  id: string;
  round_number: number;
  win_rate: number | null;
  total_matches: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface PrizeTurnPoint {
  turn: number;
  p1_cumulative: number;
  p2_cumulative: number;
}

export interface PrizeRaceMatch {
  match_id: string;
  round_number: number;
  p1_deck_name: string | null;
  p2_deck_name: string | null;
  turns: PrizeTurnPoint[];
}

export interface PrizeRaceAvgPoint {
  turn: number;
  p1_avg: number;
  p2_avg: number;
}

export interface PrizeRaceData {
  matches: PrizeRaceMatch[];
  average: PrizeRaceAvgPoint[];
}

export interface MutationRow {
  id: string;
  round_number: number;
  card_removed: string;
  card_added: string;
  reasoning: string | null;
  evidence: MutationEvidence[];
  created_at: string | null;
}

export interface MutationEvidence {
  kind: 'card_performance' | 'synergy' | 'round_result' | 'candidate_metric';
  ref: string;
  value: string;
}

/** Per-opponent aggregated stats derived client-side from matches */
export interface OpponentStat {
  name: string;
  wins: number;
  total: number;
  win_rate: number;
}
