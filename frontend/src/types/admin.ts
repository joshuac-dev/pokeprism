export interface FixedParameters {
  deck_locked: boolean;
  game_mode: string;
  matches_per_opponent: number;
  num_rounds: number;
  target_win_rate: number;
  target_consecutive_rounds: number;
  target_mode: string;
}

export interface LastRerun {
  id: string;
  source_simulation_id: string;
  generated_simulation_id: string | null;
  cycle_number: number;
  source_user_deck_name: string | null;
  source_opponent_deck_names: string[] | null;
  status: string;
  triggered_by: string;
  error_message: string | null;
  created_at: string | null;
}

export interface NightlyHHRerunStatus {
  enabled: boolean;
  schedule: string;
  eligible_source_count: number;
  current_cycle: number;
  current_cycle_completed_count: number;
  current_cycle_total_count: number;
  last_rerun: LastRerun | null;
  fixed_parameters: FixedParameters;
}

export interface Opponent {
  deck_id: string;
  deck_name: string | null;
}

export interface NextSource {
  simulation_id: string;
  created_at: string | null;
  user_deck_id: string | null;
  user_deck_name: string | null;
  opponents: Opponent[];
}

export interface PreviewResult {
  status: 'ok' | 'skipped';
  cycle_number?: number;
  next_source?: NextSource;
  generated_parameters?: FixedParameters;
  reason?: string;
}

export interface TriggerResult {
  status: 'created' | 'skipped' | 'failed';
  source_simulation_id?: string;
  generated_simulation_id?: string;
  cycle_number?: number;
  reason?: string;
}
