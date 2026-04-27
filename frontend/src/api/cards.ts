import api from './client';

export interface CardSummary {
  tcgdex_id: string;
  name: string;
  set_abbrev: string;
  set_number: string;
  category: string;
  subcategory: string | null;
  hp: number | null;
  types: string[];
  image_url: string | null;
}

export interface CardDetail extends CardSummary {
  evolve_from: string | null;
  stage: string | null;
  attacks: unknown[];
  abilities: unknown[];
  weaknesses: unknown[];
  resistances: unknown[];
  retreat_cost: number;
  regulation_mark: string | null;
  rarity: string | null;
}

export async function searchCards(q: string, limit = 10): Promise<CardSummary[]> {
  const resp = await api.get('/api/cards/search', { params: { q, limit } });
  return resp.data as CardSummary[];
}

export async function listCards(params?: {
  page?: number;
  page_size?: number;
  category?: string;
}): Promise<{ total: number; page: number; page_size: number; cards: CardSummary[] }> {
  const resp = await api.get('/api/cards', { params });
  return resp.data as { total: number; page: number; page_size: number; cards: CardSummary[] };
}

export async function getCard(tcgdexId: string): Promise<CardDetail> {
  const resp = await api.get(`/api/cards/${tcgdexId}`);
  return resp.data as CardDetail;
}
