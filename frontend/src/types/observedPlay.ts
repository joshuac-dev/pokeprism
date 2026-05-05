/**
 * Types for Observed Play Memory API (Phase 1: raw archive only).
 */

export interface LogImportResult {
  log_id: string | null;
  original_filename: string;
  sha256_hash: string;
  status: "imported" | "duplicate" | "failed" | "skipped";
  parse_status: string;
  stored_path: string | null;
  error?: string | null;
}

export interface ObservedPlayUploadResult {
  batch_id: string;
  status: string;
  original_file_count: number;
  accepted_file_count: number;
  duplicate_file_count: number;
  failed_file_count: number;
  imported_file_count: number;
  skipped_file_count: number;
  logs: LogImportResult[];
  errors: string[];
  warnings: string[];
}

export interface ObservedPlayBatch {
  id: string;
  source: string;
  uploaded_filename: string | null;
  status: string;
  original_file_count: number;
  accepted_file_count: number;
  duplicate_file_count: number;
  failed_file_count: number;
  imported_file_count: number;
  skipped_file_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
}

export interface ObservedPlayBatchDetail extends ObservedPlayBatch {
  summary_json: Record<string, unknown>;
  errors_json: string[];
  warnings_json: string[];
  logs: ObservedPlayLog[];
}

export interface ObservedPlayLog {
  id: string;
  import_batch_id: string | null;
  source: string;
  original_filename: string;
  sha256_hash: string;
  file_size_bytes: number;
  parse_status: string;
  memory_status: string;
  stored_path: string | null;
  created_at: string | null;
}

export interface ObservedPlayLogDetail extends ObservedPlayLog {
  raw_content: string | null;
  player_1_name_raw: string | null;
  player_2_name_raw: string | null;
  player_1_alias: string | null;
  player_2_alias: string | null;
  winner_raw: string | null;
  win_condition: string | null;
  turn_count: number;
  event_count: number;
  confidence_score: number | null;
  errors_json: string[];
  warnings_json: string[];
  metadata_json: Record<string, unknown>;
}

export interface PaginatedObservedPlayBatches {
  items: ObservedPlayBatch[];
  total: number;
  page: number;
  per_page: number;
}

export interface PaginatedObservedPlayLogs {
  items: ObservedPlayLog[];
  total: number;
  page: number;
  per_page: number;
}
