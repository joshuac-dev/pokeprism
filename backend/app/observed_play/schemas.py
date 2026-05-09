"""Pydantic schemas for the Observed Play Memory API (Phase 1–3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


LabelType = Literal["archetype", "package", "strategy", "matchup", "format"]
LabelSource = Literal["manual", "deck_cards", "observed_log", "llm_suggestion", "imported"]
LabelReviewStatus = Literal["suggested", "accepted", "rejected", "edited", "stale", "needs_review"]


class ArchetypeLabel(BaseModel):
    """Advisory deck/log context label produced by Phase 7.1 inference."""
    label: str
    canonical_key: str
    label_type: LabelType
    source: LabelSource
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: LabelReviewStatus = "suggested"
    player_alias: str | None = None
    evidence_card_ids: list[str] = Field(default_factory=list)
    evidence_card_names: list[str] = Field(default_factory=list)
    evidence_counts: dict[str, int] = Field(default_factory=dict)
    evidence_event_ids: list[str] = Field(default_factory=list)
    evidence_memory_item_ids: list[str] = Field(default_factory=list)
    notes: str | None = None
    schema_version: str = "archetype_label_v1"


class DeckArchetypeLabelPreview(BaseModel):
    """Read-only archetype/package/strategy label preview for one deck."""
    deck_id: str
    deck_name: str | None = None
    labels: list[ArchetypeLabel] = Field(default_factory=list)
    primary_label: ArchetypeLabel | None = None
    ambiguous: bool = False
    no_label_reason: str | None = None
    source: Literal["deck_cards"] = "deck_cards"


class ObservedLogArchetypeLabelPreview(BaseModel):
    """Read-only archetype/package/strategy label preview for one observed log."""
    observed_play_log_id: str
    labels_by_player: dict[str, list[ArchetypeLabel]] = Field(default_factory=dict)
    global_labels: list[ArchetypeLabel] = Field(default_factory=list)
    ambiguous: bool = False
    no_label_reason: str | None = None
    source: Literal["observed_log"] = "observed_log"


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


class SampleMentionItem(BaseModel):
    log_id: str
    filename: str | None = None
    event_id: int
    turn_number: int | None = None
    player_alias: str | None = None
    mention_role: str
    source_event_type: str | None = None
    raw_line: str | None = None


class UnresolvedCardItem(BaseModel):
    raw_name: str
    normalized_name: str
    status: str
    mention_count: int
    log_count: int
    candidate_count: int
    candidates: list[Any]
    sample_mentions: list[SampleMentionItem] = Field(default_factory=list)
    affected_log_ids: list[str] = Field(default_factory=list)


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


class IngestionBlocker(BaseModel):
    """Structured details for one unresolved critical card mention blocking ingestion."""
    code: str = "unresolved_critical_card"
    raw_name: str | None = None
    normalized_name: str | None = None
    mention_role: str | None = None
    resolution_status: str | None = None
    source_event_type: str | None = None
    source_field: str | None = None
    turn_number: int | None = None
    player_alias: str | None = None
    raw_line: str | None = None
    observed_play_event_id: int | None = None
    observed_card_mention_id: str | None = None


class EligibilityResult(BaseModel):
    eligible: bool
    status: str  # eligible / ineligible / forced
    reasons: list[EligibilityReason] = []
    metrics: EligibilityMetrics = EligibilityMetrics()
    blockers: list[IngestionBlocker] = []
    blocker_count: int = 0
    blockers_truncated: bool = False


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
    blockers: list[IngestionBlocker] = []
    blocker_count: int = 0
    blockers_truncated: bool = False


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
    blockers: list[IngestionBlocker] = []
    blocker_count: int = 0
    blockers_truncated: bool = False


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

# ── Phase 5: Memory analytics ──────────────────────────────────────────────────

LOW_CONFIDENCE_THRESHOLD = 0.75  # items below this are "low confidence"


class MemorySummary(BaseModel):
    ingested_log_count: int = 0
    memory_item_count: int = 0
    memory_type_counts: dict[str, int] = Field(default_factory=dict)
    average_confidence: float | None = None
    low_confidence_count: int = 0
    ambiguous_reference_count: int = 0
    unresolved_reference_count: int = 0
    latest_ingested_at: str | None = None


class MemoryAnalyticsGroup(BaseModel):
    label: str
    memory_type: str
    count: int
    average_confidence: float | None = None
    resolved_count: int = 0
    ambiguous_count: int = 0
    unresolved_count: int = 0
    sample_memory_item_ids: list[str] = Field(default_factory=list)
    sample_source_lines: list[str] = Field(default_factory=list)
    # Phase 5.1: review metadata
    review_raw_name: str | None = None
    review_status: str | None = None
    can_review_resolution: bool = False


class MemoryAnalyticsResponse(BaseModel):
    top_memory_types: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_actor_cards: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_target_cards: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_actions: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_attacks: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_abilities: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_attachments: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_evolutions: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    top_knockouts: list[MemoryAnalyticsGroup] = Field(default_factory=list)
    quality_flags: list[MemoryAnalyticsGroup] = Field(default_factory=list)


# ── Bulk actions ───────────────────────────────────────────────────────────────

class BulkReparseRequest(BaseModel):
    include_ingested: bool = False


class BulkIngestEligibleRequest(BaseModel):
    include_already_ingested: bool = False


class BulkReparseLogResult(BaseModel):
    log_id: str
    filename: str | None = None
    status: str  # reparsed / skipped / failed
    reason: str | None = None
    error: str | None = None
    parse_status: str | None = None
    confidence_score: float | None = None
    event_count: int | None = None
    had_existing_memory: bool = False
    memory_warning: str | None = None


class BulkReparseSummary(BaseModel):
    considered_count: int = 0
    reparsed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    ingested_reparsed_count: int = 0
    reparsed: list[BulkReparseLogResult] = Field(default_factory=list)
    skipped: list[BulkReparseLogResult] = Field(default_factory=list)
    failed: list[BulkReparseLogResult] = Field(default_factory=list)
    average_confidence: float | None = None
    total_event_count: int = 0


class BulkIngestPreviewLog(BaseModel):
    log_id: str
    filename: str | None = None
    status: str  # eligible / eligible_for_reingest / ineligible / already_ingested / not_ready
    confidence_score: float | None = None
    event_count: int | None = None
    estimated_memory_item_count: int | None = None
    blocker_reasons: list[str] = Field(default_factory=list)


class BulkIngestEligiblePreview(BaseModel):
    considered_count: int = 0
    eligible_count: int = 0
    eligible_for_reingest_count: int = 0
    ineligible_count: int = 0
    already_ingested_count: int = 0
    not_ready_count: int = 0
    estimated_memory_item_count: int = 0
    include_already_ingested: bool = False
    eligible_logs: list[BulkIngestPreviewLog] = Field(default_factory=list)
    skipped_logs: list[BulkIngestPreviewLog] = Field(default_factory=list)
    top_blocker_reasons: list[dict] = Field(default_factory=list)


class BulkIngestLogResult(BaseModel):
    log_id: str
    filename: str | None = None
    status: str  # ingested / reingested / skipped / failed
    reason: str | None = None
    memory_item_count: int = 0
    error: str | None = None


class BulkIngestEligibleSummary(BaseModel):
    considered_count: int = 0
    eligible_count: int = 0
    ingested_count: int = 0
    reingested_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    memory_items_created: int = 0
    include_already_ingested: bool = False
    ingested_logs: list[BulkIngestLogResult] = Field(default_factory=list)
    skipped_logs: list[BulkIngestLogResult] = Field(default_factory=list)
    failed_logs: list[BulkIngestLogResult] = Field(default_factory=list)


# ── Phase 5.2: Corpus Readiness Scorecard ─────────────────────────────────────

# Event-level threshold used by the low-confidence audit and ingestion eligibility logic.
READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD = 0.80
# Minimum ingestion coverage ratio to avoid a "needs_review" warning.
READINESS_INGESTION_COVERAGE_THRESHOLD = 0.90
# Minimum average event confidence to avoid a "needs_review" warning.
READINESS_AVG_EVENT_CONFIDENCE_THRESHOLD = 0.85
# Minimum average memory confidence to avoid a "needs_review" warning.
# Same as LOW_CONFIDENCE_THRESHOLD used by memory item quality flags.
READINESS_AVG_MEMORY_CONFIDENCE_THRESHOLD = 0.75
# Maximum number of top ambiguous/unresolved raw names returned in the report.
READINESS_TOP_N_LIMIT = 10


class CorpusStats(BaseModel):
    """Corpus coverage: how many logs were uploaded, parsed, and ingested."""
    log_count: int = 0
    parsed_log_count: int = 0
    ingested_log_count: int = 0
    not_ingested_log_count: int = 0
    failed_log_count: int = 0
    event_count: int = 0
    memory_item_count: int = 0


class ParserQualityStats(BaseModel):
    """Aggregate parser quality metrics across all events and logs."""
    avg_event_confidence: float | None = None
    min_log_confidence: float | None = None
    avg_log_confidence: float | None = None
    unknown_event_count: int = 0
    low_confidence_event_count: int = 0
    low_confidence_threshold: float = READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD
    logs_below_ingestion_threshold: int = 0


class CardResolutionStats(BaseModel):
    """Card-mention resolution burden across the full corpus."""
    card_mention_count: int = 0
    resolved_count: int = 0
    ambiguous_count: int = 0
    unresolved_count: int = 0
    critical_unresolved_count: int = 0
    top_ambiguous: list[str] = Field(default_factory=list)
    top_unresolved: list[str] = Field(default_factory=list)


class MemoryQualityStats(BaseModel):
    """Aggregate quality metrics across ingested memory items."""
    avg_memory_confidence: float | None = None
    low_confidence_memory_item_count: int = 0
    ambiguous_reference_item_count: int = 0
    unresolved_reference_item_count: int = 0
    memory_type_counts: list[dict] = Field(default_factory=list)
    top_quality_flags: list[dict] = Field(default_factory=list)


class CorpusReadinessReport(BaseModel):
    """
    Read-only Corpus Quality / Readiness Scorecard.

    Verdict rules (deterministic, no LLM):
      not_ready  — any blocker: no parsed/ingested logs, unknown events,
                   events below 0.80, critical unresolved mentions, or failed logs.
      needs_review — any warning: ambiguous/unresolved mentions, low-confidence
                   memory items, ingestion coverage < 90 %, avg confidence thresholds.
      ready      — all blockers and warnings absent.

    Score (0–100):
      Parser quality  35 pts  (no unknowns 10, no low-conf 10, avg confidence 15)
      Ingestion       25 pts  (coverage ratio 20, no failures 5)
      Card resolution 20 pts  (no critical unresolved 10, resolution ratio 10)
      Memory quality  20 pts  (avg memory confidence 10, low-conf burden 10)
    """
    verdict: str  # "ready" | "needs_review" | "not_ready"
    readiness_score: float
    generated_at: str
    review_only: bool = True
    safety_note: str = (
        "This scorecard is read-only. Observed memories are not used by Coach, "
        "AI Player, simulator runtime, deck builder, pgvector, Neo4j, "
        "match_events, or card_performance."
    )
    corpus: CorpusStats = Field(default_factory=CorpusStats)
    parser_quality: ParserQualityStats = Field(default_factory=ParserQualityStats)
    card_resolution: CardResolutionStats = Field(default_factory=CardResolutionStats)
    memory_quality: MemoryQualityStats = Field(default_factory=MemoryQualityStats)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ── Phase 6.0: Coach Advisory Evidence ───────────────────────────────────────

# Default minimum confidence for coach evidence retrieval (matches ingestion gate).
COACH_EVIDENCE_DEFAULT_MIN_CONFIDENCE = 0.80
# Default number of evidence items returned per request.
COACH_EVIDENCE_DEFAULT_LIMIT = 25
# Hard cap on evidence items per request.
COACH_EVIDENCE_MAX_LIMIT = 100


class CoachEvidenceQuery(BaseModel):
    """Parameters used to retrieve coach advisory evidence."""
    card_name: str | None = None
    memory_type: str | None = None
    action_name: str | None = None
    player_alias: str | None = None
    min_confidence: float = COACH_EVIDENCE_DEFAULT_MIN_CONFIDENCE
    limit: int = COACH_EVIDENCE_DEFAULT_LIMIT


class CoachEvidenceSummary(BaseModel):
    """Aggregate summary over the full set of matching evidence items."""
    matching_item_count: int = 0
    avg_confidence: float | None = None
    memory_type_counts: list[dict] = Field(default_factory=list)
    top_actors: list[dict] = Field(default_factory=list)
    top_targets: list[dict] = Field(default_factory=list)
    top_actions: list[dict] = Field(default_factory=list)


class CoachEvidenceItem(BaseModel):
    """One source-linked observed memory item formatted for Coach advisory review."""
    memory_item_id: str
    log_id: str
    filename: str
    turn_number: int | None = None
    player_alias: str | None = None
    memory_type: str
    actor_card_raw: str | None = None
    actor_card_def_id: str | None = None
    target_card_raw: str | None = None
    target_card_def_id: str | None = None
    related_card_raw: str | None = None
    action_name: str | None = None
    damage: int | None = None
    amount: int | None = None
    confidence_score: float
    source_event_type: str
    source_raw_line: str
    source_link: dict = Field(default_factory=dict)


class CoachEvidenceResponse(BaseModel):
    """
    Read-only Coach advisory evidence response.

    Evidence is filtered to high-confidence, resolved memory items only.
    Unresolved card references are excluded by default.
    This response is advisory only and must not drive gameplay decisions.
    """
    review_only: bool = True
    safety_note: str = (
        "Observed-play evidence is advisory only and is not used by Coach/AI "
        "runtime decisions, simulator, deck builder, pgvector, Neo4j, "
        "match_events, or card_performance."
    )
    query: CoachEvidenceQuery = Field(default_factory=CoachEvidenceQuery)
    summary: CoachEvidenceSummary = Field(default_factory=CoachEvidenceSummary)
    evidence: list[CoachEvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 6.1 — Coach context preview (feature-flagged)
# ---------------------------------------------------------------------------

class ObservedPlayCoachContextQuery(BaseModel):
    """Optional filter parameters for the Coach context preview endpoint."""
    card_name: str | None = None
    action_name: str | None = None
    memory_type: str | None = None
    player_alias: str | None = None
    min_confidence: float | None = None  # defaults to OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE
    limit: int | None = None             # defaults to OBSERVED_PLAY_MEMORY_MAX_EVIDENCE


class ObservedPlayEvidencePromptItem(BaseModel):
    """One evidence item formatted for inclusion in a Coach prompt block."""
    memory_item_id: str
    log_id: str
    turn_number: int | None = None
    confidence_score: float
    memory_type: str
    actor_card_raw: str | None = None
    target_card_raw: str | None = None
    action_name: str | None = None
    damage: int | None = None
    source_raw_line: str


class EvidenceSelectionDetail(BaseModel):
    """Debug detail for one evidence item produced by tiered retrieval (Phase 6.2a)."""
    memory_item_id: str
    relevance_score: float
    base_relevance_score: float | None = None
    label_boost: float = 0.0
    final_relevance_score: float | None = None
    tier: int
    match_source: str | None = None  # "deck_card" | "candidate_card" | "name_fallback_deck" | "name_fallback_candidate" | "global_fallback"
    matched_card_ids: list[str] = Field(default_factory=list)
    matched_card_names: list[str] = Field(default_factory=list)
    matched_field: str | None = None
    matched_reason: str | None = None
    matched_label_keys: list[str] = Field(default_factory=list)
    matched_label_names: list[str] = Field(default_factory=list)
    matched_label_types: list[str] = Field(default_factory=list)
    source_log_labels: list[ArchetypeLabel] = Field(default_factory=list)
    label_match_reason: str | None = None
    source_log_id: str
    from_winning_game: bool | None = None
    # Phase 7.2b — matchup context preview (metadata only, does not affect scoring)
    matchup_boost: float = 0.0
    source_log_matchup_key: str | None = None
    source_log_current_player_labels: list[ArchetypeLabel] = Field(default_factory=list)
    source_log_opponent_player_labels: list[ArchetypeLabel] = Field(default_factory=list)
    matchup_match_reason: str | None = None


class EvidenceExclusionSummary(BaseModel):
    """Count of candidates excluded during tiered evidence selection (Phase 6.2a).

    Note: wrong_archetype is always 0 — tiered queries use targeted IN/ILIKE
    filters so non-matching items are never fetched and cannot be counted as
    excluded. It is intentionally not computed.
    """
    low_confidence: int = 0
    wrong_archetype: int = 0   # not computed; see docstring
    source_cap_excluded: int = 0
    unresolved_reference: int = 0


class ObservedPlayRetrievalMetadata(BaseModel):
    """Metadata describing the tiered evidence retrieval decision (Phase 6.2a)."""
    strategy: str = "deck_overlap_v1"
    label_strategy: str | None = None
    label_ranking_enabled: bool = False
    deck_card_ids: list[str] = Field(default_factory=list)
    deck_card_names: list[str] = Field(default_factory=list)
    candidate_card_ids: list[str] = Field(default_factory=list)
    candidate_card_names: list[str] = Field(default_factory=list)
    deck_labels: list[ArchetypeLabel] = Field(default_factory=list)
    candidate_labels: list[ArchetypeLabel] = Field(default_factory=list)
    label_boost_cap: float = 0.0
    label_boost_applied_count: int = 0
    allow_fallback: bool = False
    max_items_per_log: int = 2
    no_relevant_evidence: bool = False
    evidence_selected: list[EvidenceSelectionDetail] = Field(default_factory=list)
    excluded_summary: EvidenceExclusionSummary = Field(default_factory=EvidenceExclusionSummary)
    # Phase 7.2b — matchup context preview (metadata only, no scoring/ordering change)
    matchup_strategy: str | None = None
    matchup_context_enabled: bool = False
    matchup_ranking_enabled: bool = False
    matchup_candidate_pool_expanded: bool = False
    matchup_filter_applied: bool = False
    current_archetype_labels: list[ArchetypeLabel] = Field(default_factory=list)
    opponent_archetype_labels: list[ArchetypeLabel] = Field(default_factory=list)
    current_primary_archetype_key: str | None = None
    opponent_primary_archetype_key: str | None = None
    directed_matchup_key: str | None = None
    matchup_confidence: float | None = None
    no_matchup_signal_reason: str | None = None


class ObservedPlayCoachContextPreview(BaseModel):
    """
    Preview of the observed-play evidence block that would be injected into a
    Coach prompt when OBSERVED_PLAY_MEMORY_ENABLED=true.

    This response is read-only and does not modify any data.
    The prompt_block is advisory only and must not override card rules, game
    state, simulator results, or card database facts.
    """
    enabled: bool
    readiness_verdict: str | None = None
    readiness_score: float | None = None
    would_inject: bool
    reason: str
    prompt_block: str
    evidence_count: int
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    filters_applied: dict = Field(default_factory=dict)
    # Phase 6.2a — tiered retrieval additions
    retrieval_metadata: ObservedPlayRetrievalMetadata | None = None
    no_relevant_evidence: bool = False
