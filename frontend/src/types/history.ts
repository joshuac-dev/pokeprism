/** Types for the History page (Phase 11). */

export interface SimulationRow {
  id: string;
  status: 'pending' | 'running' | 'complete' | 'failed' | 'cancelled';
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
}

export interface PaginatedSimulations {
  items: SimulationRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface SimulationListParams {
  page?: number;
  per_page?: number;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  starred?: boolean;
  min_win_rate?: number;
  max_win_rate?: number;
}

/** Data fetched per simulation for the compare modal. */
export interface CompareStats {
  id: string;
  deck_name: string | null;
  game_mode: string;
  rounds_completed: number;
  total_matches: number;
  final_win_rate: number | null;
  target_win_rate: number | null;
  target_met: boolean;
  avg_turns: number | null;
  deck_out_pct: number | null;
}
