import api from './client';
import type { MatchEventRow, DecisionRow, SimulationDetail } from '../types/simulation';
import type { MatchRow, RoundRow, PrizeRaceData, MutationRow } from '../types/dashboard';

export type { SimulationDetail };

export interface SimulationCreateRequest {
  deck_text?: string;
  opponent_deck_texts: string[];
  num_rounds: number;
  matches_per_opponent: number;
  target_win_rate: number;
  target_consecutive_rounds?: number;
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
  opts: { limit?: number; offset?: number; match_id?: string; turn_number?: number; player_id?: string; action_type?: string } = {}
): Promise<DecisionsResponse> {
  const params: Record<string, string | number> = {
    limit: opts.limit ?? 50,
    offset: opts.offset ?? 0,
  };
  if (opts.match_id)    params.match_id    = opts.match_id;
  if (opts.turn_number != null) params.turn_number = opts.turn_number;
  if (opts.player_id)   params.player_id   = opts.player_id;
  if (opts.action_type) params.action_type = opts.action_type;
  const resp = await api.get(`/api/simulations/${id}/decisions`, { params });
  return resp.data as DecisionsResponse;
}

export interface DecisionGraphNode {
  action_type: string;
  count: number;
  top_card_name: string | null;
  top_3_cards: { name: string; count: number; pct: number }[];
}

export interface DecisionGraphEdge {
  source: string;
  target: string;
  count: number;
}

export interface DecisionGraphResponse {
  nodes: DecisionGraphNode[];
  edges: DecisionGraphEdge[];
}

export async function getDecisionGraph(id: string): Promise<DecisionGraphResponse> {
  const resp = await api.get(`/api/simulations/${id}/decision-graph`);
  return resp.data as DecisionGraphResponse;
}

export async function cancelSimulation(id: string): Promise<{ cancelled: boolean; id: string }> {
  const resp = await api.post(`/api/simulations/${id}/cancel`);
  return resp.data;
}

export async function getSimulationRounds(id: string): Promise<RoundRow[]> {
  const resp = await api.get(`/api/simulations/${id}/rounds`);
  return resp.data as RoundRow[];
}

export async function getSimulationMatches(id: string): Promise<MatchRow[]> {
  const resp = await api.get(`/api/simulations/${id}/matches`);
  return resp.data as MatchRow[];
}

export async function getSimulationPrizeRace(id: string): Promise<PrizeRaceData> {
  const resp = await api.get(`/api/simulations/${id}/prize-race`);
  return resp.data as PrizeRaceData;
}

export async function getSimulationMutations(id: string): Promise<MutationRow[]> {
  const resp = await api.get(`/api/simulations/${id}/mutations`);
  return resp.data as MutationRow[];
}
