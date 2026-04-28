import api from './client';
import type { PaginatedSimulations, SimulationListParams, CompareStats } from '../types/history';
import type { MatchRow } from '../types/dashboard';

export async function listSimulations(params: SimulationListParams = {}): Promise<PaginatedSimulations> {
  const resp = await api.get('/api/simulations/', { params });
  return resp.data as PaginatedSimulations;
}

export async function starSimulation(id: string): Promise<{ starred: boolean }> {
  const resp = await api.patch(`/api/simulations/${id}/star`);
  return resp.data;
}

export async function deleteSimulation(id: string): Promise<void> {
  await api.delete(`/api/simulations/${id}`);
}

export async function getCompareStats(id: string): Promise<CompareStats> {
  const [simResp, matchesResp] = await Promise.all([
    api.get(`/api/simulations/${id}`),
    api.get(`/api/simulations/${id}/matches`),
  ]);
  const sim = simResp.data;
  const matches: MatchRow[] = matchesResp.data;

  const total = matches.length;
  const avgTurns = total > 0
    ? matches.reduce((sum, m) => sum + m.total_turns, 0) / total
    : null;
  const deckOuts = matches.filter(m => m.win_condition === 'deck_out').length;
  const deckOutPct = total > 0 ? deckOuts / total : null;

  return {
    id,
    deck_name: sim.user_deck_name,
    game_mode: sim.game_mode,
    rounds_completed: sim.rounds_completed,
    total_matches: sim.total_matches,
    final_win_rate: sim.final_win_rate,
    target_win_rate: sim.target_win_rate != null ? sim.target_win_rate / 100 : null,
    target_met: sim.final_win_rate != null && sim.target_win_rate != null
      ? sim.final_win_rate >= sim.target_win_rate / 100
      : false,
    avg_turns: avgTurns != null ? Math.round(avgTurns * 10) / 10 : null,
    deck_out_pct: deckOutPct,
  };
}
