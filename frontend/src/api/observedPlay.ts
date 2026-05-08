import api from './client';
import type {
  BulkIngestEligiblePreview,
  BulkIngestEligibleRequest,
  BulkIngestEligibleSummary,
  BulkReparseRequest,
  BulkReparseSummary,
  CardMentionListResponse,
  CardResolutionSummaryResponse,
  CorpusReadinessReport,
  IngestionConfig,
  MemoryAnalyticsResponse,
  MemoryAnalyticsSourceItemsParams,
  MemoryIngestionPreview,
  MemoryIngestionSummary,
  MemorySummary,
  ObservedPlayBatchDetail,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
  PaginatedEvents,
  PaginatedMemoryItems,
  PaginatedObservedPlayBatches,
  PaginatedObservedPlayLogs,
  ParserDiagnostics,
  ResolutionRuleCreate,
  ResolutionRuleResponse,
  UnresolvedCardsResponse,
  CoachEvidenceResponse,
  GetCoachEvidenceParams,
} from '../types/observedPlay';

export interface ListBatchesParams {
  page?: number;
  per_page?: number;
  status?: string;
}

export interface ListLogsParams {
  page?: number;
  per_page?: number;
  parse_status?: string;
  memory_status?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export interface ListEventsParams {
  page?: number;
  per_page?: number;
  event_type?: string;
  turn_number?: number;
  min_confidence?: number;
}

export interface ListCardMentionsParams {
  page?: number;
  per_page?: number;
  resolution_status?: string;
  mention_role?: string;
  search?: string;
}

export interface ListUnresolvedCardsParams {
  status?: 'unresolved' | 'ambiguous';
  search?: string;
  page?: number;
  per_page?: number;
}

export async function uploadObservedPlayLog(
  file: File,
): Promise<ObservedPlayUploadResult> {
  const form = new FormData();
  form.append('file', file);
  const resp = await api.post('/api/observed-play/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return resp.data as ObservedPlayUploadResult;
}

export async function listObservedPlayBatches(
  params: ListBatchesParams = {},
): Promise<PaginatedObservedPlayBatches> {
  const resp = await api.get('/api/observed-play/batches', { params });
  return resp.data as PaginatedObservedPlayBatches;
}

export async function getObservedPlayBatch(
  batchId: string,
): Promise<ObservedPlayBatchDetail> {
  const resp = await api.get(`/api/observed-play/batches/${batchId}`);
  return resp.data as ObservedPlayBatchDetail;
}

export async function listObservedPlayLogs(
  params: ListLogsParams = {},
): Promise<PaginatedObservedPlayLogs> {
  const resp = await api.get('/api/observed-play/logs', { params });
  return resp.data as PaginatedObservedPlayLogs;
}

export async function getObservedPlayLog(
  logId: string,
): Promise<ObservedPlayLogDetail> {
  const resp = await api.get(`/api/observed-play/logs/${logId}`);
  return resp.data as ObservedPlayLogDetail;
}

export async function getObservedPlayLogEvents(
  logId: string,
  params: ListEventsParams = {},
): Promise<PaginatedEvents> {
  const resp = await api.get(`/api/observed-play/logs/${logId}/events`, { params });
  return resp.data as PaginatedEvents;
}

export async function reparseObservedPlayLog(
  logId: string,
): Promise<{ log_id: string; parse_status: string; event_count: number; turn_count: number; confidence_score: number | null; parser_version: string | null; warnings: unknown[]; errors: unknown[]; parser_diagnostics: ParserDiagnostics | null; card_mention_count: number; resolved_card_count: number; ambiguous_card_count: number; unresolved_card_count: number; card_resolution_status: string | null }> {
  const resp = await api.post(`/api/observed-play/logs/${logId}/reparse`);
  return resp.data;
}

export async function getCardMentions(
  logId: string,
  params: ListCardMentionsParams = {},
): Promise<CardMentionListResponse> {
  const resp = await api.get(`/api/observed-play/logs/${logId}/card-mentions`, { params });
  return resp.data as CardMentionListResponse;
}

export async function resolveCards(
  logId: string,
): Promise<CardResolutionSummaryResponse> {
  const resp = await api.post(`/api/observed-play/logs/${logId}/resolve-cards`);
  return resp.data as CardResolutionSummaryResponse;
}

export async function getUnresolvedCards(
  params: ListUnresolvedCardsParams = {},
): Promise<UnresolvedCardsResponse> {
  const resp = await api.get('/api/observed-play/unresolved-cards', { params });
  return resp.data as UnresolvedCardsResponse;
}

export async function createResolutionRule(
  body: ResolutionRuleCreate,
): Promise<ResolutionRuleResponse> {
  const resp = await api.post('/api/observed-play/resolution-rules', body);
  return resp.data as ResolutionRuleResponse;
}

// ── Phase 4: Memory ingestion API ────────────────────────────────────────────

export async function previewMemoryIngestion(
  logId: string,
  config: IngestionConfig = {},
): Promise<MemoryIngestionPreview> {
  const resp = await api.post(`/api/observed-play/logs/${logId}/memory-preview`, config);
  return resp.data as MemoryIngestionPreview;
}

export async function ingestMemory(
  logId: string,
  config: IngestionConfig = {},
): Promise<MemoryIngestionSummary> {
  const resp = await api.post(`/api/observed-play/logs/${logId}/ingest-memory`, config);
  return resp.data as MemoryIngestionSummary;
}

export interface ListMemoryItemsParams {
  page?: number;
  per_page?: number;
  memory_type?: string;
  card_name?: string;
}

export async function getMemoryItems(
  logId: string,
  params: ListMemoryItemsParams = {},
): Promise<PaginatedMemoryItems> {
  const resp = await api.get(`/api/observed-play/logs/${logId}/memory-items`, { params });
  return resp.data as PaginatedMemoryItems;
}

// ── Phase 5: Memory analytics API ─────────────────────────────────────────────

export async function getMemorySummary(): Promise<MemorySummary> {
  const resp = await api.get('/api/observed-play/memory-summary');
  return resp.data as MemorySummary;
}

export interface GetMemoryAnalyticsParams {
  limit?: number;
  memory_type?: string;
  min_confidence?: number;
  quality_filter?: string;
}

export async function getMemoryAnalytics(
  params: GetMemoryAnalyticsParams = {},
): Promise<MemoryAnalyticsResponse> {
  const resp = await api.get('/api/observed-play/memory-analytics', { params });
  return resp.data as MemoryAnalyticsResponse;
}

export async function getMemoryAnalyticsSourceItems(
  params: MemoryAnalyticsSourceItemsParams = {},
): Promise<PaginatedMemoryItems> {
  const resp = await api.get('/api/observed-play/memory-analytics/source-items', { params });
  return resp.data as PaginatedMemoryItems;
}

// ── Bulk actions ───────────────────────────────────────────────────────────────

export async function bulkReparseAll(opts: BulkReparseRequest = {}): Promise<BulkReparseSummary> {
  const resp = await api.post('/api/observed-play/logs/reparse-all', opts);
  return resp.data as BulkReparseSummary;
}

export async function bulkPreviewEligible(opts: BulkIngestEligibleRequest = {}): Promise<BulkIngestEligiblePreview> {
  const resp = await api.post('/api/observed-play/memory-ingestion/preview-eligible', opts);
  return resp.data as BulkIngestEligiblePreview;
}

export async function bulkIngestEligible(opts: BulkIngestEligibleRequest = {}): Promise<BulkIngestEligibleSummary> {
  const resp = await api.post('/api/observed-play/memory-ingestion/ingest-eligible', opts);
  return resp.data as BulkIngestEligibleSummary;
}

export async function getCorpusReadiness(): Promise<CorpusReadinessReport> {
  const resp = await api.get('/api/observed-play/corpus-readiness');
  return resp.data as CorpusReadinessReport;
}

export async function getCoachEvidence(params: GetCoachEvidenceParams = {}): Promise<CoachEvidenceResponse> {
  const resp = await api.get('/api/observed-play/coach-evidence', { params });
  return resp.data as CoachEvidenceResponse;
}
