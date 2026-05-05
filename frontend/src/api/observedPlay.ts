import api from './client';
import type {
  ObservedPlayBatchDetail,
  ObservedPlayLogDetail,
  ObservedPlayUploadResult,
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
