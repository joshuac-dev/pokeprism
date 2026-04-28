import api from './client';
import type { CardProfile, MemoryGraph, MemoryDecisionsResponse } from '../types/memory';

export async function getTopCard(): Promise<string | null> {
  const resp = await api.get('/api/memory/top-card');
  if (resp.status === 204) return null;
  return (resp.data as { card_id: string }).card_id;
}

export async function getCardProfile(cardId: string): Promise<CardProfile> {
  const resp = await api.get(`/api/memory/card/${encodeURIComponent(cardId)}/profile`);
  return resp.data as CardProfile;
}

export async function getMemoryGraph(cardId: string, depth = 2): Promise<MemoryGraph> {
  const resp = await api.get('/api/memory/graph', { params: { card_id: cardId, depth } });
  return resp.data as MemoryGraph;
}

export async function getCardDecisions(
  cardId: string,
  opts: { offset?: number; limit?: number } = {}
): Promise<MemoryDecisionsResponse> {
  const params = { offset: opts.offset ?? 0, limit: opts.limit ?? 50 };
  const resp = await api.get(`/api/memory/card/${encodeURIComponent(cardId)}/decisions`, { params });
  return resp.data as MemoryDecisionsResponse;
}
