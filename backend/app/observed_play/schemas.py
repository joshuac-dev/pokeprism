"""Pydantic schemas for the Observed Play Memory API (Phase 1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
