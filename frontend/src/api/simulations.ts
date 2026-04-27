import api from './client';
import type { MatchEventRow, DecisionRow, SimulationDetail } from '../types/simulation';

export type { SimulationDetail };

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

export interface EventsResponse {
  events: MatchEventRow[];
  total: number;
  has_more: boolean;
}

export interface DecisionsResponse {
  decisions: DecisionRow[];
  total: number;
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

export async function getSimulationEvents(
  id: string,
  opts: { limit?: number; beforeId?: number } = {}
): Promise<EventsResponse> {
  const params: Record<string, string | number> = { limit: opts.limit ?? 500 };
  if (opts.beforeId != null) params.before_id = opts.beforeId;
  const resp = await api.get(`/api/simulations/${id}/events`, { params });
  return resp.data as EventsResponse;
}

export async function getSimulationDecisions(
  id: string,
  opts: { limit?: number; offset?: number } = {}
): Promise<DecisionsResponse> {
  const params = { limit: opts.limit ?? 50, offset: opts.offset ?? 0 };
  const resp = await api.get(`/api/simulations/${id}/decisions`, { params });
  return resp.data as DecisionsResponse;
}

export async function cancelSimulation(id: string): Promise<{ cancelled: boolean; id: string }> {
  const resp = await api.post(`/api/simulations/${id}/cancel`);
  return resp.data;
}
