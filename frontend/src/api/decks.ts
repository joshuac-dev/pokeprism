import api from './client';
import type { DeckArchetypeLabelPreview } from '../types/observedPlay';

export async function getDeckArchetypeLabelPreview(
  deckId: string,
): Promise<DeckArchetypeLabelPreview> {
  const resp = await api.get(`/api/decks/${deckId}/archetype-label-preview`);
  return resp.data as DeckArchetypeLabelPreview;
}
