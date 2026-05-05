import api from './client';
import type {
  ObservedPlayBatchDetail,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
  PaginatedEvents,
  PaginatedObservedPlayBatches,
  PaginatedObservedPlayLogs,
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
}

export interface ListEventsParams {
  page?: number;
  per_page?: number;
  event_type?: string;
  turn_number?: number;
  min_confidence?: number;
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
): Promise<{ log_id: string; parse_status: string; event_count: number; turn_count: number; confidence_score: number | null; parser_version: string | null; warnings: unknown[]; errors: unknown[] }> {
  const resp = await api.post(`/api/observed-play/logs/${logId}/reparse`);
  return resp.data;
}
