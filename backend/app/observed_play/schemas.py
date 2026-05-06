"""Pydantic schemas for the Observed Play Memory API (Phase 1–3)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParserDiagnostics(BaseModel):
    unknown_count: int = 0
    unknown_ratio: float = 0.0
    low_confidence_count: int = 0
    event_type_counts: dict[str, int] = Field(default_factory=dict)
    top_unknown_raw_lines: list[str] = Field(default_factory=list)


# ── Per-file import result ─────────────────────────────────────────────────────

class LogImportResult(BaseModel):
    log_id: str | None
    original_filename: str
    sha256_hash: str
    status: str  # imported | duplicate | failed | skipped
    parse_status: str
    stored_path: str | None
    error: str | None = None
    event_count: int = 0
    confidence_score: float | None = None


# ── Upload response ────────────────────────────────────────────────────────────

class BatchImportResponse(BaseModel):
    batch_id: str
    status: str
    original_file_count: int
    accepted_file_count: int
    duplicate_file_count: int
    failed_file_count: int
    imported_file_count: int
    skipped_file_count: int
    logs: list[LogImportResult]
    errors: list[str]
    warnings: list[str]


# ── Log summaries (list views) ─────────────────────────────────────────────────

class LogSummary(BaseModel):
    id: str
    import_batch_id: str | None
    source: str
    original_filename: str
    sha256_hash: str
    file_size_bytes: int
    parse_status: str
    memory_status: str
    stored_path: str | None
    created_at: str | None
    parser_version: str | None = None
    event_count: int = 0
    confidence_score: float | None = None
    winner_raw: str | None = None
    win_condition: str | None = None
    parser_diagnostics: ParserDiagnostics | None = None
    # Phase 3 card resolution counters
    card_mention_count: int = 0
    resolved_card_count: int = 0
    ambiguous_card_count: int = 0
    unresolved_card_count: int = 0
    card_resolution_status: str | None = None
    # Phase 4 memory ingestion
    memory_item_count: int = 0
    last_memory_ingested_at: str | None = None


class LogDetail(LogSummary):
    raw_content: str | None
    player_1_name_raw: str | None
    player_2_name_raw: str | None
    player_1_alias: str | None
    player_2_alias: str | None
    winner_raw: str | None
    win_condition: str | None
    turn_count: int
    event_count: int
    confidence_score: float | None
    errors_json: list[Any]
    warnings_json: list[Any]
    metadata_json: dict[str, Any]


# ── Batch summaries (list views) ───────────────────────────────────────────────

class BatchSummary(BaseModel):
    id: str
    source: str
    uploaded_filename: str | None
    status: str
    original_file_count: int
    accepted_file_count: int
    duplicate_file_count: int
    failed_file_count: int
    imported_file_count: int
    skipped_file_count: int
    started_at: str | None
    finished_at: str | None
    created_at: str | None


class BatchDetail(BatchSummary):
    summary_json: dict[str, Any]
    errors_json: list[Any]
    warnings_json: list[Any]
    logs: list[LogSummary] = []


# ── Pagination wrappers ────────────────────────────────────────────────────────

class PaginatedBatches(BaseModel):
    items: list[BatchSummary]
    total: int
    page: int
    per_page: int


class PaginatedLogs(BaseModel):
    items: list[LogSummary]
    total: int
    page: int
    per_page: int


class EventSummary(BaseModel):
    id: int
    event_index: int
    turn_number: int | None
    phase: str
    player_raw: str | None
    player_alias: str | None
    actor_type: str | None
    event_type: str
    raw_line: str
    raw_block: str | None
    card_name_raw: str | None
    target_card_name_raw: str | None
    zone: str | None
    target_zone: str | None
    amount: int | None
    damage: int | None
    base_damage: int | None
    event_payload_json: dict
    confidence_score: float
    confidence_reasons_json: list


class PaginatedEvents(BaseModel):
    items: list[EventSummary]
    total: int
    page: int
    per_page: int


class ReparseSummary(BaseModel):
    log_id: str
    parse_status: str
    event_count: int
    turn_count: int
    confidence_score: float | None
    parser_version: str | None
    warnings: list[Any]
    errors: list[Any]
    parser_diagnostics: ParserDiagnostics | None = None
    # Phase 3: resolution summary after reparse
    card_mention_count: int = 0
    resolved_card_count: int = 0
    ambiguous_card_count: int = 0
    unresolved_card_count: int = 0
    card_resolution_status: str | None = None


# ── Phase 3: Card mention schemas ─────────────────────────────────────────────

class CardCandidateItem(BaseModel):
    card_def_id: str
    name: str
    set_abbrev: str
    set_number: str
    image_url: str | None = None
    confidence: float
    reason: str


class CardMentionItem(BaseModel):
    id: str
    observed_play_log_id: str
    observed_play_event_id: int
    mention_index: int
    mention_role: str
    raw_name: str
    normalized_name: str
    resolved_card_def_id: str | None
    resolved_card_name: str | None
    resolution_status: str
    resolution_confidence: float | None
    resolution_method: str | None
    candidate_count: int
    candidates_json: list[Any]
    source_event_type: str
    source_field: str
    source_payload_path: str | None
    resolver_version: str


class PaginatedCardMentions(BaseModel):
    items: list[CardMentionItem]
    total: int
    page: int
    per_page: int


class CardResolutionSummaryResponse(BaseModel):
    log_id: str
    card_mention_count: int
    resolved_card_count: int
    ambiguous_card_count: int
    unresolved_card_count: int
    ignored_card_count: int
    card_resolution_status: str
    resolver_version: str
    errors: list[str]


class UnresolvedCardItem(BaseModel):
    raw_name: str
    normalized_name: str
    status: str
    mention_count: int
    log_count: int
    candidate_count: int
    candidates: list[Any]


class UnresolvedCardsResponse(BaseModel):
    items: list[UnresolvedCardItem]
    total: int
    page: int
    per_page: int


class ResolutionRuleCreate(BaseModel):
    raw_name: str
    action: str  # resolve | ignore
    target_card_def_id: str | None = None
    target_card_name: str | None = None
    notes: str | None = None


class ResolutionRuleResponse(BaseModel):
    id: str
    raw_name: str
    normalized_name: str
    action: str
    target_card_def_id: str | None
    target_card_name: str | None
    scope: str
    notes: str | None
    created_at: str | None


# ── Phase 4: Memory ingestion schemas ─────────────────────────────────────────

class IngestionConfig(BaseModel):
    allow_unresolved: bool = False
    force: bool = False
    max_unresolved: int = 0
    min_confidence: float = 0.8
    max_unknown_ratio: float = 0.05


class EligibilityMetrics(BaseModel):
    confidence_score: float | None = None
    event_count: int = 0
    unknown_ratio: float = 0.0
    low_confidence_count: int = 0
    card_mention_count: int = 0
    unresolved_card_count: int = 0
    ambiguous_card_count: int = 0
    critical_unresolved_count: int = 0


class EligibilityReason(BaseModel):
    code: str
    detail: str


class EligibilityResult(BaseModel):
    eligible: bool
    status: str  # eligible / ineligible / forced
    reasons: list[EligibilityReason] = []
    metrics: EligibilityMetrics = EligibilityMetrics()


class MemoryItemPreview(BaseModel):
    memory_type: str
    memory_key: str
    turn_number: int | None
    player_alias: str | None
    actor_card_raw: str | None
    actor_card_def_id: str | None
    actor_resolution_status: str | None
    action_name: str | None
    target_card_raw: str | None
    damage: int | None
    confidence_score: float
    source_event_type: str
    source_raw_line: str


class MemoryIngestionPreview(BaseModel):
    eligible: bool
    eligibility_status: str
    reasons: list[EligibilityReason] = []
    metrics: EligibilityMetrics = EligibilityMetrics()
    estimated_memory_item_count: int = 0
    event_type_counts: dict[str, int] = Field(default_factory=dict)
    sample_items: list[MemoryItemPreview] = []


class MemoryIngestionSummary(BaseModel):
    ingestion_id: str
    log_id: str
    status: str
    eligibility_status: str
    reasons: list[EligibilityReason] = []
    source_event_count: int = 0
    memory_item_count: int = 0
    skipped_event_count: int = 0
    blocked_reason_count: int = 0
    ingestion_version: str
    error: str | None = None


class MemoryItemSummary(BaseModel):
    id: str
    ingestion_id: str
    observed_play_log_id: str
    observed_play_event_id: int
    memory_type: str
    memory_key: str
    turn_number: int | None
    phase: str | None
    player_alias: str | None
    player_raw: str | None
    actor_card_raw: str | None
    actor_card_def_id: str | None
    actor_resolution_status: str | None
    target_card_raw: str | None
    target_card_def_id: str | None
    target_resolution_status: str | None
    related_card_raw: str | None
    related_card_def_id: str | None
    related_resolution_status: str | None
    action_name: str | None
    amount: int | None
    damage: int | None
    zone: str | None
    target_zone: str | None
    confidence_score: float
    source_event_type: str
    source_raw_line: str
    created_at: str | None


class PaginatedMemoryItems(BaseModel):
    items: list[MemoryItemSummary]
    total: int
    page: int
    per_page: int
