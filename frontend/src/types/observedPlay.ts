/**
 * Types for Observed Play Memory API (Phase 1 + Phase 2: parser v1 + Phase 3: card resolution).
 */

export interface ParserDiagnostics {
  unknown_count: number;
  unknown_ratio: number;
  low_confidence_count: number;
  event_type_counts: Record<string, number>;
  top_unknown_raw_lines: string[];
}

export interface LogImportResult {
  log_id: string | null;
  original_filename: string;
  sha256_hash: string;
  status: "imported" | "duplicate" | "failed" | "skipped";
  parse_status: string;
  stored_path: string | null;
  error?: string | null;
  event_count: number;
  confidence_score: number | null;
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
  parser_version: string | null;
  event_count: number;
  confidence_score: number | null;
  winner_raw: string | null;
  win_condition: string | null;
  parser_diagnostics?: ParserDiagnostics | null;
  // Phase 3: card resolution
  card_mention_count?: number;
  resolved_card_count?: number;
  ambiguous_card_count?: number;
  unresolved_card_count?: number;
  card_resolution_status?: string | null;
  // Phase 4: memory ingestion
  memory_item_count?: number;
  last_memory_ingested_at?: string | null;
}

export interface EventSummary {
  id: number;
  event_index: number;
  turn_number: number | null;
  phase: string;
  player_raw: string | null;
  player_alias: string | null;
  actor_type: string | null;
  event_type: string;
  raw_line: string;
  raw_block: string | null;
  card_name_raw: string | null;
  target_card_name_raw: string | null;
  zone: string | null;
  target_zone: string | null;
  amount: number | null;
  damage: number | null;
  base_damage: number | null;
  event_payload_json: Record<string, unknown>;
  confidence_score: number;
  confidence_reasons_json: string[];
}

export interface PaginatedEvents {
  items: EventSummary[];
  total: number;
  page: number;
  per_page: number;
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

// ── Phase 3: Card resolution types ──────────────────────────────────────────

export interface CardCandidateItem {
  card_def_id: string;
  name: string;
  set_abbrev: string;
  set_number: string;
  image_url: string | null;
  confidence: number;
  reason: string;
}

export interface CardMentionItem {
  id: string;
  observed_play_log_id: string;
  observed_play_event_id: number | null;
  mention_index: number;
  mention_role: string;
  raw_name: string;
  normalized_name: string;
  resolved_card_def_id: string | null;
  resolved_card_name: string | null;
  resolution_status: "resolved" | "ambiguous" | "unresolved" | "ignored";
  resolution_confidence: number | null;
  resolution_method: string | null;
  candidate_count: number;
  candidates_json: CardCandidateItem[];
  source_event_type: string | null;
  source_field: string | null;
  source_payload_path: string | null;
  resolver_version: string;
}

export interface CardMentionListResponse {
  items: CardMentionItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface CardResolutionSummaryResponse {
  log_id: string;
  card_mention_count: number;
  resolved_card_count: number;
  ambiguous_card_count: number;
  unresolved_card_count: number;
  ignored_card_count: number;
  card_resolution_status: string;
  resolver_version: string;
  errors: string[];
}

export interface SampleMentionItem {
  log_id: string;
  filename: string | null;
  event_id: number;
  turn_number: number | null;
  player_alias: string | null;
  mention_role: string;
  source_event_type: string | null;
  raw_line: string | null;
}

export interface UnresolvedCardItem {
  raw_name: string;
  normalized_name: string;
  status: "unresolved" | "ambiguous";
  mention_count: number;
  log_count: number;
  candidate_count: number;
  candidates: CardCandidateItem[];
  sample_mentions?: SampleMentionItem[];
  affected_log_ids?: string[];
}

export interface UnresolvedCardsResponse {
  items: UnresolvedCardItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface ResolutionRuleCreate {
  raw_name: string;
  action: "resolve" | "ignore";
  target_card_def_id?: string | null;
  target_card_name?: string | null;
  notes?: string | null;
}

export interface ResolutionRuleResponse {
  id: string;
  raw_name: string;
  normalized_name: string;
  action: "resolve" | "ignore";
  target_card_def_id: string | null;
  target_card_name: string | null;
  scope: string;
  notes: string | null;
  created_at: string | null;
}

// ── Phase 4: Memory ingestion types ─────────────────────────────────────────

export interface IngestionConfig {
  min_confidence?: number;
  max_unknown_ratio?: number;
  max_unresolved?: number;
  allow_unresolved?: boolean;
  force?: boolean;
}

export interface EligibilityReason {
  code: string;
  detail: string;
}

export interface EligibilityMetrics {
  confidence_score: number;
  event_count: number;
  unknown_ratio: number;
  low_confidence_count: number;
  card_mention_count: number;
  unresolved_card_count: number;
  ambiguous_card_count: number;
  critical_unresolved_count: number;
}

export interface MemoryItemPreview {
  event_id: number;
  event_type: string;
  memory_type: string;
  turn_number: number | null;
  actor_card_raw: string | null;
  target_card_raw: string | null;
  action_name: string | null;
  damage: number | null;
  confidence_score: number;
}

export interface IngestionBlocker {
  code: string;
  raw_name?: string | null;
  normalized_name?: string | null;
  mention_role?: string | null;
  resolution_status?: string | null;
  source_event_type?: string | null;
  source_field?: string | null;
  turn_number?: number | null;
  player_alias?: string | null;
  raw_line?: string | null;
  observed_play_event_id?: number | null;
  observed_card_mention_id?: string | null;
}

export interface MemoryIngestionPreview {
  eligible: boolean;
  eligibility_status: string;
  reasons: EligibilityReason[];
  metrics?: EligibilityMetrics | null;
  estimated_memory_item_count: number;
  event_type_counts?: Record<string, number>;
  sample_items?: MemoryItemPreview[];
  blockers?: IngestionBlocker[];
  blocker_count?: number;
  blockers_truncated?: boolean;
}

export interface MemoryItemSummary {
  id: string;
  ingestion_id: string;
  observed_play_log_id: string;
  observed_play_event_id: number | null;
  memory_type: string;
  memory_key: string;
  turn_number: number | null;
  phase: string | null;
  player_alias: string | null;
  player_raw: string | null;
  actor_card_raw: string | null;
  actor_card_def_id: string | null;
  actor_resolution_status: string | null;
  target_card_raw: string | null;
  target_card_def_id: string | null;
  target_resolution_status: string | null;
  related_card_raw: string | null;
  related_card_def_id: string | null;
  related_resolution_status: string | null;
  action_name: string | null;
  amount: number | null;
  damage: number | null;
  zone: string | null;
  target_zone: string | null;
  confidence_score: number;
  source_event_type: string;
  source_raw_line: string | null;
  created_at: string | null;
}

export interface MemoryIngestionSummary {
  ingestion_id: string;
  log_id: string;
  status: "completed" | "skipped" | "failed";
  eligibility_status: string;
  reasons: EligibilityReason[];
  memory_item_count?: number;
  skipped_event_count?: number;
  ingestion_version: string;
  error?: string | null;
  blockers?: IngestionBlocker[];
  blocker_count?: number;
  blockers_truncated?: boolean;
}

export interface PaginatedMemoryItems {
  items: MemoryItemSummary[];
  total: number;
  page: number;
  per_page: number;
}

// ── Phase 5: Memory analytics ─────────────────────────────────────────────────

export interface MemorySummary {
  ingested_log_count: number;
  memory_item_count: number;
  memory_type_counts: Record<string, number>;
  average_confidence: number | null;
  low_confidence_count: number;
  ambiguous_reference_count: number;
  unresolved_reference_count: number;
  latest_ingested_at: string | null;
}

export interface MemoryAnalyticsGroup {
  label: string;
  memory_type: string;
  count: number;
  average_confidence: number | null;
  resolved_count: number;
  ambiguous_count: number;
  unresolved_count: number;
  sample_memory_item_ids: string[];
  sample_source_lines: string[];
  // Phase 5.1: review metadata
  review_raw_name?: string | null;
  review_status?: string | null;
  can_review_resolution?: boolean;
}

export interface MemoryAnalyticsResponse {
  top_memory_types: MemoryAnalyticsGroup[];
  top_actor_cards: MemoryAnalyticsGroup[];
  top_target_cards: MemoryAnalyticsGroup[];
  top_actions: MemoryAnalyticsGroup[];
  top_attacks: MemoryAnalyticsGroup[];
  top_abilities: MemoryAnalyticsGroup[];
  top_attachments: MemoryAnalyticsGroup[];
  top_evolutions: MemoryAnalyticsGroup[];
  top_knockouts: MemoryAnalyticsGroup[];
  quality_flags: MemoryAnalyticsGroup[];
}

export interface MemoryAnalyticsSourceItemsParams {
  memory_type?: string;
  actor_card_raw?: string;
  actor_card_def_id?: string;
  target_card_raw?: string;
  target_card_def_id?: string;
  related_card_raw?: string;
  action_name?: string;
  quality_flag?: string;
  min_confidence?: number;
  card_name?: string;
  page?: number;
  per_page?: number;
}

// ── Bulk actions ───────────────────────────────────────────────────────────────

export interface BulkReparseRequest {
  include_ingested?: boolean;
}

export interface BulkIngestEligibleRequest {
  include_already_ingested?: boolean;
}

export interface BulkReparseLogResult {
  log_id: string;
  filename: string | null;
  status: 'reparsed' | 'skipped' | 'failed';
  reason?: string;
  error?: string;
  parse_status?: string;
  confidence_score?: number;
  event_count?: number;
  had_existing_memory?: boolean;
  memory_warning?: string | null;
}

export interface BulkReparseSummary {
  considered_count: number;
  reparsed_count: number;
  skipped_count: number;
  failed_count: number;
  ingested_reparsed_count?: number;
  reparsed: BulkReparseLogResult[];
  skipped: BulkReparseLogResult[];
  failed: BulkReparseLogResult[];
  average_confidence: number | null;
  total_event_count: number;
}

export interface BulkIngestPreviewLog {
  log_id: string;
  filename: string | null;
  status: 'eligible' | 'eligible_for_reingest' | 'ineligible' | 'already_ingested' | 'not_ready';
  confidence_score?: number;
  event_count?: number;
  estimated_memory_item_count?: number;
  blocker_reasons: string[];
}

export interface BulkIngestEligiblePreview {
  considered_count: number;
  eligible_count: number;
  eligible_for_reingest_count?: number;
  ineligible_count: number;
  already_ingested_count: number;
  not_ready_count: number;
  estimated_memory_item_count: number;
  include_already_ingested?: boolean;
  eligible_logs: BulkIngestPreviewLog[];
  skipped_logs: BulkIngestPreviewLog[];
  top_blocker_reasons: { reason: string; count: number }[];
}

export interface BulkIngestLogResult {
  log_id: string;
  filename: string | null;
  status: 'ingested' | 'reingested' | 'skipped' | 'failed';
  reason?: string;
  memory_item_count: number;
  error?: string;
}

export interface BulkIngestEligibleSummary {
  considered_count: number;
  eligible_count: number;
  ingested_count: number;
  reingested_count?: number;
  skipped_count: number;
  failed_count: number;
  memory_items_created: number;
  include_already_ingested?: boolean;
  ingested_logs: BulkIngestLogResult[];
  skipped_logs: BulkIngestLogResult[];
  failed_logs: BulkIngestLogResult[];
}
