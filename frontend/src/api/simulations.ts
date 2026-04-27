import api from './client';

export interface SimulationCreateRequest {
  deck_text?: string;
  opponent_deck_texts: string[];
  num_rounds: number;
  matches_per_opponent: number;
  target_win_rate: number;
  game_mode: 'hh' | 'ai_h' | 'ai_ai';
  deck_mode: 'full' | 'partial' | 'none';
  deck_locked: boolean;
  excluded_card_ids?: string[];
}

export interface SimulationCreateResponse {
  simulation_id: string;
  status: string;
  warning?: string;
}

export interface SimulationDetail {
  id: string;
  status: string;
  user_deck_name: string | null;
  game_mode: string;
  deck_mode: string;
  num_rounds: number;
  matches_per_opponent: number;
  target_win_rate: number;
  current_round: number;
  created_at: string;
}

export async function createSimulation(req: SimulationCreateRequest): Promise<SimulationCreateResponse> {
  const resp = await api.post('/api/simulations', req);
  return resp.data as SimulationCreateResponse;
}

export async function getSimulation(id: string): Promise<SimulationDetail> {
  const resp = await api.get(`/api/simulations/${id}`);
  return resp.data as SimulationDetail;
}

export async function listSimulations(): Promise<SimulationDetail[]> {
  const resp = await api.get('/api/simulations');
  return resp.data as SimulationDetail[];
}
