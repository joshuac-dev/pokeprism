import api from './client';
import type { NightlyHHRerunStatus, PreviewResult, TriggerResult } from '../types/admin';

export async function getNightlyHHRerunStatus(): Promise<NightlyHHRerunStatus> {
  const resp = await api.get('/api/admin/nightly-hh-rerun/status');
  return resp.data as NightlyHHRerunStatus;
}

export async function previewNightlyHHRerun(): Promise<PreviewResult> {
  const resp = await api.get('/api/admin/nightly-hh-rerun/preview');
  return resp.data as PreviewResult;
}

export async function triggerNightlyHHRerun(): Promise<TriggerResult> {
  const resp = await api.post('/api/admin/nightly-hh-rerun/trigger');
  return resp.data as TriggerResult;
}
