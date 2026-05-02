/** Types for the Memory Explorer page (Phase 11). */

export interface CardStat {
  games_included: number;
  games_won: number;
  win_rate: number;
  total_kos: number;
  total_damage: number;
  total_prizes: number;
}

export interface CardPartner {
  card_id: string;
  name: string;
  weight: number;
  games_observed: number;
}

export interface CardProfile {
  card_id: string;
  name: string;
  set_abbrev: string | null;
  set_number: string | null;
  category: string | null;
  image_url: string | null;
  stats: CardStat;
  partners: CardPartner[];
}

export interface MemoryNode {
  id: string;
  name: string | null;
  category: string | null;
  weight: number | null;
  games_observed: number | null;
}

export interface MemoryEdge {
  source: string;
  target: string;
  weight: number;
  games_observed: number | null;
}

export interface MemoryGraph {
  nodes: MemoryNode[];
  edges: MemoryEdge[];
}

export interface MemoryDecisionRow {
  id: string;
  match_id: string | null;
  turn_number: number;
  player_id: string;
  action_type: string;
  card_def_id: string | null;
  reasoning: string | null;
  legal_action_count: number | null;
  created_at: string | null;
}

export interface MemoryDecisionsResponse {
  decisions: MemoryDecisionRow[];
  total: number;
  offset: number;
  limit: number;
}
