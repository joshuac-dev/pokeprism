"""Observed Play Memory API — Phase 1–3: upload, batch listing, log listing, card resolution."""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, asc, case, delete, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Card,
    ObservedCardMention,
    ObservedCardResolutionRule,
    ObservedPlayEvent,
    ObservedPlayImportBatch,
    ObservedPlayLog,
    ObservedPlayMemoryItem,
    ObservedPlayMemoryIngestion,
)
from app.db.session import AsyncSessionLocal
from app.observed_play.card_mentions import normalize_card_name
from app.observed_play.card_resolution import RESOLVER_VERSION, extract_and_resolve_mentions_for_log
from app.observed_play.constants import PARSER_VERSION
from app.observed_play.importer import run_import
from app.observed_play.memory_ingestion import (
    evaluate_log_ingestion_eligibility,
    ingest_observed_play_log,
    preview_observed_play_ingestion,
)
from app.observed_play.parser import parse_log
from app.observed_play.schemas import (
    BatchDetail,
    BatchImportResponse,
    BatchSummary,
    BulkIngestEligiblePreview,
    BulkIngestEligibleSummary,
    BulkIngestLogResult,
    BulkIngestPreviewLog,
    BulkReparseLogResult,
    BulkReparseSummary,
    CardMentionItem,
    CardResolutionSummaryResponse,
    EligibilityResult,
    EventSummary,
    IngestionConfig,
    LogDetail,
    LogImportResult,
    LogSummary,
    MemoryIngestionPreview,
    MemoryIngestionSummary,
    MemoryItemSummary,
    PaginatedBatches,
    PaginatedCardMentions,
    PaginatedEvents,
    PaginatedLogs,
    PaginatedMemoryItems,
    ParserDiagnostics,
    ReparseSummary,
    ResolutionRuleCreate,
    ResolutionRuleResponse,
    SampleMentionItem,
    UnresolvedCardItem,
    UnresolvedCardsResponse,
    LOW_CONFIDENCE_THRESHOLD,
    MemoryAnalyticsGroup,
    MemoryAnalyticsResponse,
    MemorySummary,
)
from app.observed_play.storage import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter()

SUPPORTED_UPLOAD_EXTENSIONS = SUPPORTED_EXTENSIONS | {".zip"}


# ── DB dependency ─────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────────

def _batch_to_summary(b: ObservedPlayImportBatch) -> BatchSummary:
    return BatchSummary(
        id=str(b.id),
        source=b.source or "",
        uploaded_filename=b.uploaded_filename,
        status=b.status or "",
        original_file_count=b.original_file_count or 0,
        accepted_file_count=b.accepted_file_count or 0,
        duplicate_file_count=b.duplicate_file_count or 0,
        failed_file_count=b.failed_file_count or 0,
        imported_file_count=b.imported_file_count or 0,
        skipped_file_count=b.skipped_file_count or 0,
        started_at=b.started_at.isoformat() if b.started_at else None,
        finished_at=b.finished_at.isoformat() if b.finished_at else None,
        created_at=b.created_at.isoformat() if b.created_at else None,
    )


def _log_to_summary(log: ObservedPlayLog) -> LogSummary:
    diag_raw = (log.metadata_json or {}).get("parser_diagnostics")
    diag: Optional[ParserDiagnostics] = None
    if diag_raw and isinstance(diag_raw, dict):
        try:
            diag = ParserDiagnostics(**diag_raw)
        except Exception:
            diag = None
    return LogSummary(
        id=str(log.id),
        import_batch_id=str(log.import_batch_id) if log.import_batch_id else None,
        source=log.source or "",
        original_filename=log.original_filename or "",
        sha256_hash=log.sha256_hash or "",
        file_size_bytes=log.file_size_bytes or 0,
        parse_status=log.parse_status or "",
        memory_status=log.memory_status or "",
        stored_path=log.stored_path,
        created_at=log.created_at.isoformat() if log.created_at else None,
        parser_version=getattr(log, "parser_version", None),
        event_count=log.event_count or 0,
        confidence_score=log.confidence_score,
        winner_raw=log.winner_raw,
        win_condition=log.win_condition,
        parser_diagnostics=diag,
        card_mention_count=getattr(log, "card_mention_count", None) or 0,
        resolved_card_count=getattr(log, "recognized_card_count", None) or 0,
        ambiguous_card_count=getattr(log, "ambiguous_card_count", None) or 0,
        unresolved_card_count=getattr(log, "unresolved_card_count", None) or 0,
        card_resolution_status=getattr(log, "card_resolution_status", None),
        memory_item_count=getattr(log, "memory_item_count", None) or 0,
        last_memory_ingested_at=(
            log.last_memory_ingested_at.isoformat()
            if getattr(log, "last_memory_ingested_at", None)
            else None
        ),
    )


def _log_to_detail(log: ObservedPlayLog) -> LogDetail:
    return LogDetail(
        id=str(log.id),
        import_batch_id=str(log.import_batch_id) if log.import_batch_id else None,
        source=log.source or "",
        original_filename=log.original_filename or "",
        sha256_hash=log.sha256_hash or "",
        file_size_bytes=log.file_size_bytes or 0,
        parse_status=log.parse_status or "",
        memory_status=log.memory_status or "",
        stored_path=log.stored_path,
        created_at=log.created_at.isoformat() if log.created_at else None,
        raw_content=log.raw_content,
        player_1_name_raw=log.player_1_name_raw,
        player_2_name_raw=log.player_2_name_raw,
        player_1_alias=log.player_1_alias,
        player_2_alias=log.player_2_alias,
        winner_raw=log.winner_raw,
        win_condition=log.win_condition,
        turn_count=log.turn_count or 0,
        event_count=log.event_count or 0,
        confidence_score=log.confidence_score,
        errors_json=log.errors_json or [],
        warnings_json=log.warnings_json or [],
        metadata_json=log.metadata_json or {},
    )


# ── Upload endpoint ───────────────────────────────────────────────────────────

@router.post("/upload", status_code=201)
async def upload_observed_play_log(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> BatchImportResponse:
    """Upload a single .md/.markdown/.txt or .zip file containing PTCGL battle logs.

    Single text/markdown files are imported inline.
    ZIP files are processed synchronously (Phase 1); Celery support is Phase 2.
    """
    from pathlib import Path

    filename = file.filename or "upload.md"
    ext = Path(filename).suffix.lower()

    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type {ext!r}. "
                f"Accepted: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}"
            ),
        )

    data = await file.read()

    try:
        batch, results = await run_import(db, data, filename)
        await db.commit()
        await db.refresh(batch)
    except Exception as exc:
        await db.rollback()
        logger.exception("Import failed for %s", filename)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc

    return BatchImportResponse(
        batch_id=str(batch.id),
        status=batch.status or "",
        original_file_count=batch.original_file_count or 0,
        accepted_file_count=batch.accepted_file_count or 0,
        duplicate_file_count=batch.duplicate_file_count or 0,
        failed_file_count=batch.failed_file_count or 0,
        imported_file_count=batch.imported_file_count or 0,
        skipped_file_count=batch.skipped_file_count or 0,
        logs=[LogImportResult(**r) for r in results],
        errors=batch.errors_json or [],
        warnings=batch.warnings_json or [],
    )


# ── Batch list ────────────────────────────────────────────────────────────────

@router.get("/batches")
async def list_batches(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedBatches:
    """List import batches, most recent first."""
    q = select(ObservedPlayImportBatch)
    if status:
        q = q.where(ObservedPlayImportBatch.status == status)
    q = q.order_by(ObservedPlayImportBatch.created_at.desc())

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(q)).scalars().all()

    return PaginatedBatches(
        items=[_batch_to_summary(b) for b in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Batch detail ──────────────────────────────────────────────────────────────

@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
) -> BatchDetail:
    """Return full batch detail including associated log summaries."""
    result = await db.execute(
        select(ObservedPlayImportBatch).where(
            ObservedPlayImportBatch.id == batch_id
        )
    )
    batch = result.scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    logs_result = await db.execute(
        select(ObservedPlayLog)
        .where(ObservedPlayLog.import_batch_id == batch.id)
        .order_by(ObservedPlayLog.created_at.asc())
    )
    logs = logs_result.scalars().all()

    return BatchDetail(
        **_batch_to_summary(batch).model_dump(),
        summary_json=batch.summary_json or {},
        errors_json=batch.errors_json or [],
        warnings_json=batch.warnings_json or [],
        logs=[_log_to_summary(log) for log in logs],
    )


# ── Log list ──────────────────────────────────────────────────────────────────

# Single-column sort fields. parse_status and cards use composite logic below.
LOG_SORT_FIELDS: dict[str, object] = {
    "filename": ObservedPlayLog.original_filename,
    "memory_status": ObservedPlayLog.memory_status,
    "event_count": ObservedPlayLog.event_count,
    "confidence_score": ObservedPlayLog.confidence_score,
    "card_mention_count": ObservedPlayLog.card_mention_count,
    "resolved_card_count": ObservedPlayLog.recognized_card_count,
    "ambiguous_card_count": ObservedPlayLog.ambiguous_card_count,
    "unresolved_card_count": ObservedPlayLog.unresolved_card_count,
    "memory_item_count": ObservedPlayLog.memory_item_count,
    "file_size_bytes": ObservedPlayLog.file_size_bytes,
    "created_at": ObservedPlayLog.created_at,
    "sha256_hash": ObservedPlayLog.sha256_hash,
}

# Composite/special sort keys handled by _apply_log_sort.
_COMPOSITE_SORT_KEYS: frozenset[str] = frozenset({"parse_status", "cards"})
_ALL_SORT_KEYS: frozenset[str] = frozenset(LOG_SORT_FIELDS.keys()) | _COMPOSITE_SORT_KEYS


def _apply_log_sort(q, sort_by: str, sort_dir: str):
    """Apply composite-aware sort to the log list query."""
    is_asc = sort_dir == "asc"
    order_fn = asc if is_asc else desc

    if sort_by == "parse_status":
        # Rank statuses so sort is useful even when many rows share one value.
        # Tie-break with confidence_score asc so lower-confidence logs surface
        # for review within the same status group.
        parse_rank = case(
            (ObservedPlayLog.parse_status == "failed", 0),
            (ObservedPlayLog.parse_status == "raw_archived", 1),
            (ObservedPlayLog.parse_status == "parsed", 2),
            (ObservedPlayLog.parse_status == "parsed_with_warnings", 3),
            else_=4,
        )
        return q.order_by(
            order_fn(parse_rank),
            asc(func.coalesce(ObservedPlayLog.confidence_score, 0)),
            ObservedPlayLog.created_at.desc(),
            ObservedPlayLog.id.desc(),
        )

    if sort_by == "cards":
        # Composite: surface logs most needing card-resolution review.
        if is_asc:
            return q.order_by(
                asc(func.coalesce(ObservedPlayLog.unresolved_card_count, 0)),
                asc(func.coalesce(ObservedPlayLog.ambiguous_card_count, 0)),
                asc(func.coalesce(ObservedPlayLog.card_mention_count, 0)),
                desc(func.coalesce(ObservedPlayLog.confidence_score, 0)),
                ObservedPlayLog.created_at.desc(),
                ObservedPlayLog.id.desc(),
            )
        return q.order_by(
            desc(func.coalesce(ObservedPlayLog.unresolved_card_count, 0)),
            desc(func.coalesce(ObservedPlayLog.ambiguous_card_count, 0)),
            desc(func.coalesce(ObservedPlayLog.card_mention_count, 0)),
            asc(func.coalesce(ObservedPlayLog.confidence_score, 1)),
            ObservedPlayLog.created_at.desc(),
            ObservedPlayLog.id.desc(),
        )

    sort_col = LOG_SORT_FIELDS.get(sort_by, ObservedPlayLog.created_at)
    return q.order_by(order_fn(sort_col), ObservedPlayLog.created_at.desc(), ObservedPlayLog.id.desc())


@router.get("/logs")
async def list_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    parse_status: Optional[str] = Query(None),
    memory_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedLogs:
    """List raw observed play logs."""
    if sort_by and sort_by not in _ALL_SORT_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_by: {sort_by!r}. Allowed: {sorted(_ALL_SORT_KEYS)}",
        )
    if sort_dir and sort_dir not in ("asc", "desc"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_dir: {sort_dir!r}. Must be 'asc' or 'desc'.",
        )

    q = select(ObservedPlayLog)
    if parse_status:
        q = q.where(ObservedPlayLog.parse_status == parse_status)
    if memory_status:
        q = q.where(ObservedPlayLog.memory_status == memory_status)
    if search:
        q = q.where(
            ObservedPlayLog.original_filename.ilike(f"%{search}%")
            | ObservedPlayLog.sha256_hash.ilike(f"{search}%")
        )

    q = _apply_log_sort(q, sort_by or "created_at", sort_dir or "desc")

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(q)).scalars().all()

    return PaginatedLogs(
        items=[_log_to_summary(log) for log in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


# ── Log detail ────────────────────────────────────────────────────────────────

@router.get("/logs/{log_id}")
async def get_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
) -> LogDetail:
    """Return full log detail including raw content."""
    result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    log = result.scalars().first()
    if log is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return _log_to_detail(log)


# ── Log events ────────────────────────────────────────────────────────────────

@router.get("/logs/{log_id}/events")
async def get_log_events(
    log_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    turn_number: Optional[int] = Query(None),
    min_confidence: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedEvents:
    """Return paginated parsed events for a log."""
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")

    q = select(ObservedPlayEvent).where(ObservedPlayEvent.observed_play_log_id == log_id)
    if event_type:
        q = q.where(ObservedPlayEvent.event_type == event_type)
    if turn_number is not None:
        q = q.where(ObservedPlayEvent.turn_number == turn_number)
    if min_confidence is not None:
        q = q.where(ObservedPlayEvent.confidence_score >= min_confidence)
    q = q.order_by(ObservedPlayEvent.event_index.asc())

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.offset((page - 1) * per_page).limit(per_page)
    rows = (await db.execute(q)).scalars().all()

    items = [
        EventSummary(
            id=row.id,
            event_index=row.event_index,
            turn_number=row.turn_number,
            phase=row.phase,
            player_raw=row.player_raw,
            player_alias=row.player_alias,
            actor_type=row.actor_type,
            event_type=row.event_type,
            raw_line=row.raw_line,
            raw_block=row.raw_block,
            card_name_raw=row.card_name_raw,
            target_card_name_raw=row.target_card_name_raw,
            zone=row.zone,
            target_zone=row.target_zone,
            amount=row.amount,
            damage=row.damage,
            base_damage=row.base_damage,
            event_payload_json=row.event_payload_json or {},
            confidence_score=row.confidence_score,
            confidence_reasons_json=row.confidence_reasons_json or [],
        )
        for row in rows
    ]

    return PaginatedEvents(items=items, total=total, page=page, per_page=per_page)


# ── Reparse log ────────────────────────────────────────────────────────────────

@router.post("/logs/{log_id}/reparse")
async def reparse_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReparseSummary:
    """Re-parse an existing log, replacing all events."""
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    log = log_result.scalars().first()
    if log is None:
        raise HTTPException(status_code=404, detail="Log not found")

    raw_content = log.raw_content or ""

    await db.execute(
        delete(ObservedPlayEvent).where(ObservedPlayEvent.observed_play_log_id == log_id)
    )

    parsed_log = parse_log(raw_content)

    for evt in parsed_log.events:
        event_row = ObservedPlayEvent(
            observed_play_log_id=log.id,
            import_batch_id=log.import_batch_id,
            event_index=evt.event_index,
            turn_number=evt.turn_number,
            phase=evt.phase,
            player_raw=evt.player_raw,
            player_alias=evt.player_alias,
            actor_type=evt.actor_type,
            event_type=evt.event_type,
            raw_line=evt.raw_line,
            raw_block=evt.raw_block,
            card_name_raw=evt.card_name_raw,
            target_card_name_raw=evt.target_card_name_raw,
            zone=evt.zone,
            target_zone=evt.target_zone,
            amount=evt.amount,
            damage=evt.damage,
            base_damage=evt.base_damage,
            weakness_damage=evt.weakness_damage,
            resistance_delta=evt.resistance_delta,
            healing_amount=evt.healing_amount,
            energy_type=evt.energy_type,
            prize_count_delta=evt.prize_count_delta,
            deck_count_delta=evt.deck_count_delta,
            hand_count_delta=evt.hand_count_delta,
            discard_count_delta=evt.discard_count_delta,
            event_payload_json=evt.event_payload,
            confidence_score=evt.confidence_score,
            confidence_reasons_json=evt.confidence_reasons,
            parser_version=PARSER_VERSION,
        )
        db.add(event_row)

    log.parser_version = parsed_log.parser_version
    log.parse_status = "parsed" if not parsed_log.warnings else "parsed_with_warnings"
    log.player_1_name_raw = parsed_log.player_1_name_raw
    log.player_2_name_raw = parsed_log.player_2_name_raw
    log.player_1_alias = parsed_log.player_1_alias
    log.player_2_alias = parsed_log.player_2_alias
    log.winner_raw = parsed_log.winner_raw
    log.winner_alias = parsed_log.winner_alias
    log.win_condition = parsed_log.win_condition
    log.turn_count = parsed_log.turn_count
    log.event_count = parsed_log.event_count
    log.confidence_score = parsed_log.confidence_score
    log.warnings_json = parsed_log.warnings
    log.errors_json = parsed_log.errors
    log.metadata_json = parsed_log.metadata

    await db.commit()
    await db.refresh(log)

    # Phase 3: run card mention extraction/resolution after reparse
    resolution_summary = None
    try:
        resolution_summary = await extract_and_resolve_mentions_for_log(db, log.id)
        await db.commit()
        await db.refresh(log)
    except Exception as exc:
        logger.error("Card resolution failed for log %s: %s", log_id, exc)

    diag_raw = (log.metadata_json or {}).get("parser_diagnostics")
    diag: Optional[ParserDiagnostics] = None
    if diag_raw and isinstance(diag_raw, dict):
        try:
            diag = ParserDiagnostics(**diag_raw)
        except Exception:
            diag = None

    return ReparseSummary(
        log_id=str(log.id),
        parse_status=log.parse_status,
        event_count=log.event_count or 0,
        turn_count=log.turn_count or 0,
        confidence_score=log.confidence_score,
        parser_version=log.parser_version,
        warnings=log.warnings_json or [],
        errors=log.errors_json or [],
        parser_diagnostics=diag,
        card_mention_count=getattr(log, "card_mention_count", None) or 0,
        resolved_card_count=getattr(log, "recognized_card_count", None) or 0,
        ambiguous_card_count=getattr(log, "ambiguous_card_count", None) or 0,
        unresolved_card_count=getattr(log, "unresolved_card_count", None) or 0,
        card_resolution_status=getattr(log, "card_resolution_status", None),
    )


# ── Card mentions ─────────────────────────────────────────────────────────────

@router.get("/logs/{log_id}/card-mentions")
async def get_card_mentions(
    log_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    resolution_status: Optional[str] = Query(None),
    mention_role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedCardMentions:
    """List card mentions for a log, with optional filters."""
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")

    q = select(ObservedCardMention).where(
        ObservedCardMention.observed_play_log_id == log_id
    )
    if resolution_status:
        q = q.where(ObservedCardMention.resolution_status == resolution_status)
    if mention_role:
        q = q.where(ObservedCardMention.mention_role == mention_role)
    if search:
        q = q.where(ObservedCardMention.normalized_name.ilike(f"%{search.lower()}%"))
    q = q.order_by(ObservedCardMention.observed_play_event_id, ObservedCardMention.mention_index)

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar() or 0

    rows_result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    rows = rows_result.scalars().all()

    items = [
        CardMentionItem(
            id=str(row.id),
            observed_play_log_id=str(row.observed_play_log_id),
            observed_play_event_id=row.observed_play_event_id,
            mention_index=row.mention_index,
            mention_role=row.mention_role,
            raw_name=row.raw_name,
            normalized_name=row.normalized_name,
            resolved_card_def_id=row.resolved_card_def_id,
            resolved_card_name=row.resolved_card_name,
            resolution_status=row.resolution_status,
            resolution_confidence=row.resolution_confidence,
            resolution_method=row.resolution_method,
            candidate_count=row.candidate_count or 0,
            candidates_json=row.candidates_json or [],
            source_event_type=row.source_event_type,
            source_field=row.source_field,
            source_payload_path=row.source_payload_path,
            resolver_version=row.resolver_version or RESOLVER_VERSION,
        )
        for row in rows
    ]
    return PaginatedCardMentions(items=items, total=total, page=page, per_page=per_page)


# ── Resolve cards for a log ───────────────────────────────────────────────────

@router.post("/logs/{log_id}/resolve-cards")
async def resolve_cards(
    log_id: str,
    db: AsyncSession = Depends(get_db),
) -> CardResolutionSummaryResponse:
    """Re-extract and re-resolve all card mentions for a log."""
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")

    summary = await extract_and_resolve_mentions_for_log(db, log_id)
    await db.commit()

    return CardResolutionSummaryResponse(
        log_id=summary.log_id,
        card_mention_count=summary.card_mention_count,
        resolved_card_count=summary.resolved_card_count,
        ambiguous_card_count=summary.ambiguous_card_count,
        unresolved_card_count=summary.unresolved_card_count,
        ignored_card_count=summary.ignored_card_count,
        card_resolution_status=summary.card_resolution_status,
        resolver_version=summary.resolver_version,
        errors=summary.errors,
    )


# ── Unresolved / ambiguous card review ───────────────────────────────────────

@router.get("/unresolved-cards")
async def get_unresolved_cards(
    status: Optional[str] = Query(None, description="unresolved | ambiguous"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> UnresolvedCardsResponse:
    """Return grouped unresolved/ambiguous card mentions across all logs."""
    from sqlalchemy import Integer, cast, literal_column, text

    q = (
        select(
            ObservedCardMention.normalized_name,
            ObservedCardMention.raw_name,
            ObservedCardMention.resolution_status,
            ObservedCardMention.candidate_count,
            ObservedCardMention.candidates_json,
            func.count(ObservedCardMention.id).label("mention_count"),
            func.count(func.distinct(ObservedCardMention.observed_play_log_id)).label("log_count"),
        )
        .where(
            ObservedCardMention.resolution_status.in_(["unresolved", "ambiguous"])
        )
        .group_by(
            ObservedCardMention.normalized_name,
            ObservedCardMention.raw_name,
            ObservedCardMention.resolution_status,
            ObservedCardMention.candidate_count,
            ObservedCardMention.candidates_json,
        )
        .order_by(func.count(ObservedCardMention.id).desc())
    )
    if status:
        q = q.where(ObservedCardMention.resolution_status == status)
    if search:
        q = q.where(ObservedCardMention.normalized_name.ilike(f"%{search.lower()}%"))

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar() or 0

    rows_result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    rows = rows_result.all()

    if not rows:
        return UnresolvedCardsResponse(items=[], total=total, page=page, per_page=per_page)

    # Fetch sample mentions (up to 5 per normalized_name) and affected log IDs in one query
    _MAX_SAMPLES = 5
    _MAX_AFFECTED = 25
    norm_names = [row.normalized_name for row in rows]

    samples_q = (
        select(
            ObservedCardMention.normalized_name,
            ObservedCardMention.observed_play_log_id,
            ObservedCardMention.observed_play_event_id,
            ObservedCardMention.mention_role,
            ObservedCardMention.source_event_type,
            ObservedPlayLog.original_filename,
            ObservedPlayEvent.turn_number,
            ObservedPlayEvent.player_alias,
            ObservedPlayEvent.raw_line,
        )
        .join(
            ObservedPlayLog,
            ObservedCardMention.observed_play_log_id == ObservedPlayLog.id,
        )
        .join(
            ObservedPlayEvent,
            ObservedCardMention.observed_play_event_id == ObservedPlayEvent.id,
        )
        .where(
            ObservedCardMention.normalized_name.in_(norm_names),
            ObservedCardMention.resolution_status.in_(["unresolved", "ambiguous"]),
        )
        .order_by(ObservedCardMention.normalized_name, ObservedCardMention.observed_play_event_id)
    )
    samples_result = await db.execute(samples_q)
    sample_rows = samples_result.all()

    # Group samples and affected_log_ids by normalized_name
    from collections import defaultdict
    sample_by_norm: dict[str, list] = defaultdict(list)
    log_ids_by_norm: dict[str, list] = defaultdict(list)
    for sr in sample_rows:
        n = sr.normalized_name
        if len(sample_by_norm[n]) < _MAX_SAMPLES:
            sample_by_norm[n].append(SampleMentionItem(
                log_id=str(sr.observed_play_log_id),
                filename=sr.original_filename,
                event_id=int(sr.observed_play_event_id),
                turn_number=sr.turn_number,
                player_alias=sr.player_alias,
                mention_role=sr.mention_role,
                source_event_type=sr.source_event_type,
                raw_line=sr.raw_line,
            ))
        log_id_str = str(sr.observed_play_log_id)
        if log_id_str not in log_ids_by_norm[n] and len(log_ids_by_norm[n]) < _MAX_AFFECTED:
            log_ids_by_norm[n].append(log_id_str)

    items = [
        UnresolvedCardItem(
            raw_name=row.raw_name,
            normalized_name=row.normalized_name,
            status=row.resolution_status,
            mention_count=row.mention_count,
            log_count=row.log_count,
            candidate_count=row.candidate_count or 0,
            candidates=row.candidates_json or [],
            sample_mentions=sample_by_norm.get(row.normalized_name, []),
            affected_log_ids=log_ids_by_norm.get(row.normalized_name, []),
        )
        for row in rows
    ]
    return UnresolvedCardsResponse(items=items, total=total, page=page, per_page=per_page)


# ── Resolution rules ──────────────────────────────────────────────────────────

@router.post("/resolution-rules", status_code=201)
async def create_resolution_rule(
    body: ResolutionRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> ResolutionRuleResponse:
    """Create a manual resolution/ignore rule for a raw card name."""
    if not body.raw_name or not body.raw_name.strip():
        raise HTTPException(status_code=422, detail="raw_name is required and must not be empty")
    if body.action not in ("resolve", "ignore"):
        raise HTTPException(status_code=422, detail="action must be 'resolve' or 'ignore'")
    if body.action == "resolve" and not body.target_card_def_id:
        raise HTTPException(
            status_code=422,
            detail="target_card_def_id is required for action='resolve'",
        )
    norm = normalize_card_name(body.raw_name)

    # Check target card exists for resolve actions
    if body.action == "resolve" and body.target_card_def_id:
        card_result = await db.execute(
            select(Card.tcgdex_id).where(Card.tcgdex_id == body.target_card_def_id)
        )
        if card_result.scalar() is None:
            raise HTTPException(
                status_code=422,
                detail=f"target_card_def_id '{body.target_card_def_id}' not found in card database",
            )

    # Check for existing rule with same normalized name and action
    existing_result = await db.execute(
        select(ObservedCardResolutionRule).where(
            ObservedCardResolutionRule.normalized_name == norm,
            ObservedCardResolutionRule.scope == "global",
        )
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A resolution rule already exists for normalized name '{norm}' (action='{existing.action}'). Delete it first to create a new one.",
        )

    rule = ObservedCardResolutionRule(
        raw_name=body.raw_name,
        normalized_name=norm,
        target_card_def_id=body.target_card_def_id,
        target_card_name=body.target_card_name,
        action=body.action,
        scope="global",
        notes=body.notes,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return ResolutionRuleResponse(
        id=str(rule.id),
        raw_name=rule.raw_name,
        normalized_name=rule.normalized_name,
        action=rule.action,
        target_card_def_id=rule.target_card_def_id,
        target_card_name=rule.target_card_name,
        scope=rule.scope,
        notes=rule.notes,
        created_at=rule.created_at.isoformat() if rule.created_at else None,
    )


# ── Memory ingestion ──────────────────────────────────────────────────────────

@router.post("/logs/{log_id}/memory-preview")
async def preview_memory_ingestion(
    log_id: str,
    config: IngestionConfig = None,
    db: AsyncSession = Depends(get_db),
) -> MemoryIngestionPreview:
    """Preview memory ingestion for a log without writing anything."""
    if config is None:
        config = IngestionConfig()
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return await preview_observed_play_ingestion(db, log_id, config)


@router.post("/logs/{log_id}/ingest-memory")
async def ingest_memory(
    log_id: str,
    config: IngestionConfig = None,
    db: AsyncSession = Depends(get_db),
) -> MemoryIngestionSummary:
    """Ingest parsed events for a log into observed play memory items.

    Returns 422 with eligibility reasons if the log is ineligible and
    force=False or allow_unresolved=False.

    Observed memories are stored for review only.
    They are not used by Coach or AI Player yet.
    """
    if config is None:
        config = IngestionConfig()
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")

    summary = await ingest_observed_play_log(db, log_id, config)
    if summary.status == "skipped":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Log is not eligible for ingestion",
                "eligibility_status": summary.eligibility_status,
                "reasons": [r.model_dump() for r in summary.reasons],
                "blockers": [b.model_dump() for b in summary.blockers],
                "blocker_count": summary.blocker_count,
                "blockers_truncated": summary.blockers_truncated,
            },
        )

    await db.commit()
    return summary


@router.get("/logs/{log_id}/memory-items")
async def get_memory_items(
    log_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    memory_type: Optional[str] = Query(None),
    card_name: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedMemoryItems:
    """List memory items for a log."""
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    if log_result.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Log not found")

    q = select(ObservedPlayMemoryItem).where(
        ObservedPlayMemoryItem.observed_play_log_id == log_id
    )
    if memory_type:
        q = q.where(ObservedPlayMemoryItem.memory_type == memory_type)
    if card_name:
        search = f"%{card_name.lower()}%"
        q = q.where(
            ObservedPlayMemoryItem.actor_card_raw.ilike(search)
            | ObservedPlayMemoryItem.target_card_raw.ilike(search)
            | ObservedPlayMemoryItem.related_card_raw.ilike(search)
        )
    q = q.order_by(ObservedPlayMemoryItem.created_at.asc())

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0

    rows_result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    rows = rows_result.scalars().all()

    items = [
        MemoryItemSummary(
            id=str(row.id),
            ingestion_id=str(row.ingestion_id),
            observed_play_log_id=str(row.observed_play_log_id),
            observed_play_event_id=row.observed_play_event_id,
            memory_type=row.memory_type,
            memory_key=row.memory_key,
            turn_number=row.turn_number,
            phase=row.phase,
            player_alias=row.player_alias,
            player_raw=row.player_raw,
            actor_card_raw=row.actor_card_raw,
            actor_card_def_id=row.actor_card_def_id,
            actor_resolution_status=row.actor_resolution_status,
            target_card_raw=row.target_card_raw,
            target_card_def_id=row.target_card_def_id,
            target_resolution_status=row.target_resolution_status,
            related_card_raw=row.related_card_raw,
            related_card_def_id=row.related_card_def_id,
            related_resolution_status=row.related_resolution_status,
            action_name=row.action_name,
            amount=row.amount,
            damage=row.damage,
            zone=row.zone,
            target_zone=row.target_zone,
            confidence_score=row.confidence_score,
            source_event_type=row.source_event_type,
            source_raw_line=row.source_raw_line,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]
    return PaginatedMemoryItems(items=items, total=total, page=page, per_page=per_page)


@router.get("/memory-items")
async def list_all_memory_items(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    memory_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedMemoryItems:
    """List observed play memory items across all logs (read-only)."""
    q = select(ObservedPlayMemoryItem)
    if memory_type:
        q = q.where(ObservedPlayMemoryItem.memory_type == memory_type)
    q = q.order_by(ObservedPlayMemoryItem.created_at.desc())

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0

    rows_result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    rows = rows_result.scalars().all()

    items = [
        MemoryItemSummary(
            id=str(row.id),
            ingestion_id=str(row.ingestion_id),
            observed_play_log_id=str(row.observed_play_log_id),
            observed_play_event_id=row.observed_play_event_id,
            memory_type=row.memory_type,
            memory_key=row.memory_key,
            turn_number=row.turn_number,
            phase=row.phase,
            player_alias=row.player_alias,
            player_raw=row.player_raw,
            actor_card_raw=row.actor_card_raw,
            actor_card_def_id=row.actor_card_def_id,
            actor_resolution_status=row.actor_resolution_status,
            target_card_raw=row.target_card_raw,
            target_card_def_id=row.target_card_def_id,
            target_resolution_status=row.target_resolution_status,
            related_card_raw=row.related_card_raw,
            related_card_def_id=row.related_card_def_id,
            related_resolution_status=row.related_resolution_status,
            action_name=row.action_name,
            amount=row.amount,
            damage=row.damage,
            zone=row.zone,
            target_zone=row.target_zone,
            confidence_score=row.confidence_score,
            source_event_type=row.source_event_type,
            source_raw_line=row.source_raw_line,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]
    return PaginatedMemoryItems(items=items, total=total, page=page, per_page=per_page)


# ── Phase 5: Memory analytics ──────────────────────────────────────────────────

@router.get("/memory-summary")
async def get_memory_summary(db: AsyncSession = Depends(get_db)) -> MemorySummary:
    """Read-only summary of all ingested observed play memory items."""
    log_count_result = await db.execute(
        select(func.count(ObservedPlayLog.id)).where(ObservedPlayLog.memory_status == "ingested")
    )
    ingested_log_count = log_count_result.scalar() or 0

    item_count_result = await db.execute(select(func.count(ObservedPlayMemoryItem.id)))
    memory_item_count = item_count_result.scalar() or 0

    if memory_item_count == 0:
        return MemorySummary(ingested_log_count=ingested_log_count)

    stats_result = await db.execute(
        select(
            func.avg(ObservedPlayMemoryItem.confidence_score),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.confidence_score < LOW_CONFIDENCE_THRESHOLD
            ),
        )
    )
    avg_conf, low_conf_count = stats_result.one()

    ambiguous_result = await db.execute(
        select(func.count(ObservedPlayMemoryItem.id)).where(
            (ObservedPlayMemoryItem.actor_resolution_status == "ambiguous")
            | (ObservedPlayMemoryItem.target_resolution_status == "ambiguous")
            | (ObservedPlayMemoryItem.related_resolution_status == "ambiguous")
        )
    )
    ambiguous_reference_count = ambiguous_result.scalar() or 0

    unresolved_result = await db.execute(
        select(func.count(ObservedPlayMemoryItem.id)).where(
            (ObservedPlayMemoryItem.actor_resolution_status == "unresolved")
            | (ObservedPlayMemoryItem.target_resolution_status == "unresolved")
            | (ObservedPlayMemoryItem.related_resolution_status == "unresolved")
        )
    )
    unresolved_reference_count = unresolved_result.scalar() or 0

    type_count_result = await db.execute(
        select(ObservedPlayMemoryItem.memory_type, func.count(ObservedPlayMemoryItem.id))
        .group_by(ObservedPlayMemoryItem.memory_type)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
    )
    memory_type_counts = {row[0]: row[1] for row in type_count_result}

    latest_result = await db.execute(
        select(func.max(ObservedPlayLog.last_memory_ingested_at)).where(
            ObservedPlayLog.memory_status == "ingested"
        )
    )
    latest_ts = latest_result.scalar()

    return MemorySummary(
        ingested_log_count=ingested_log_count,
        memory_item_count=memory_item_count,
        memory_type_counts=memory_type_counts,
        average_confidence=float(avg_conf) if avg_conf is not None else None,
        low_confidence_count=low_conf_count or 0,
        ambiguous_reference_count=ambiguous_reference_count,
        unresolved_reference_count=unresolved_reference_count,
        latest_ingested_at=latest_ts.isoformat() if latest_ts else None,
    )


async def _fetch_analytics_groups(
    db: AsyncSession,
    group_by_col,
    memory_type_label: str,
    limit: int,
    extra_filter=None,
    label_prefix: str | None = None,
    is_card_group: bool = False,
) -> list[MemoryAnalyticsGroup]:
    """Helper: aggregate memory items by a grouping column."""
    q = (
        select(
            group_by_col.label("grp"),
            func.count(ObservedPlayMemoryItem.id).label("cnt"),
            func.avg(ObservedPlayMemoryItem.confidence_score).label("avg_conf"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "resolved"
            ).label("res_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "ambiguous"
            ).label("amb_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "unresolved"
            ).label("unr_cnt"),
        )
        .where(group_by_col.isnot(None))
        .group_by(group_by_col)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
        .limit(limit)
    )
    if extra_filter is not None:
        q = q.where(extra_filter)

    rows = (await db.execute(q)).all()
    groups = []
    for row in rows:
        grp_val = row.grp
        if not grp_val:
            continue
        label = f"{label_prefix}:{grp_val}" if label_prefix else grp_val

        sample_q = (
            select(ObservedPlayMemoryItem.id, ObservedPlayMemoryItem.source_raw_line)
            .where(group_by_col == grp_val)
            .limit(3)
        )
        if extra_filter is not None:
            sample_q = sample_q.where(extra_filter)
        samples = (await db.execute(sample_q)).all()

        amb = row.amb_cnt or 0
        unr = row.unr_cnt or 0
        can_review = is_card_group and (amb + unr) > 0
        review_status: str | None = None
        if can_review:
            review_status = "ambiguous" if amb > 0 else "unresolved"

        groups.append(
            MemoryAnalyticsGroup(
                label=label,
                memory_type=memory_type_label,
                count=row.cnt,
                average_confidence=float(row.avg_conf) if row.avg_conf is not None else None,
                resolved_count=row.res_cnt or 0,
                ambiguous_count=amb,
                unresolved_count=unr,
                sample_memory_item_ids=[str(s.id) for s in samples],
                sample_source_lines=[s.source_raw_line for s in samples if s.source_raw_line],
                review_raw_name=grp_val if can_review else None,
                review_status=review_status,
                can_review_resolution=can_review,
            )
        )
    return groups


@router.get("/memory-analytics")
async def get_memory_analytics(
    limit: int = Query(10, ge=1, le=50),
    memory_type: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None),
    quality_filter: Optional[str] = Query(None, description="all|ambiguous|low_confidence|unresolved"),
    db: AsyncSession = Depends(get_db),
) -> MemoryAnalyticsResponse:
    """Read-only analytics aggregates over ingested observed play memory items."""

    def _base_filter():
        filters = []
        if memory_type:
            filters.append(ObservedPlayMemoryItem.memory_type == memory_type)
        if min_confidence is not None:
            filters.append(ObservedPlayMemoryItem.confidence_score >= min_confidence)
        if quality_filter == "ambiguous":
            filters.append(
                (ObservedPlayMemoryItem.actor_resolution_status == "ambiguous")
                | (ObservedPlayMemoryItem.target_resolution_status == "ambiguous")
                | (ObservedPlayMemoryItem.related_resolution_status == "ambiguous")
            )
        elif quality_filter == "low_confidence":
            filters.append(ObservedPlayMemoryItem.confidence_score < LOW_CONFIDENCE_THRESHOLD)
        elif quality_filter == "unresolved":
            filters.append(
                (ObservedPlayMemoryItem.actor_resolution_status == "unresolved")
                | (ObservedPlayMemoryItem.target_resolution_status == "unresolved")
                | (ObservedPlayMemoryItem.related_resolution_status == "unresolved")
            )
        # quality_filter="all" or None → no additional filter
        return and_(*filters) if filters else None

    base = _base_filter()

    mt_q = (
        select(
            ObservedPlayMemoryItem.memory_type.label("grp"),
            func.count(ObservedPlayMemoryItem.id).label("cnt"),
            func.avg(ObservedPlayMemoryItem.confidence_score).label("avg_conf"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "resolved"
            ).label("res_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "ambiguous"
            ).label("amb_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "unresolved"
            ).label("unr_cnt"),
        )
        .group_by(ObservedPlayMemoryItem.memory_type)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
        .limit(limit)
    )
    if base is not None:
        mt_q = mt_q.where(base)
    mt_rows = (await db.execute(mt_q)).all()

    async def _samples(extra_where, limit_n: int = 3):
        sq = select(ObservedPlayMemoryItem.id, ObservedPlayMemoryItem.source_raw_line).where(extra_where).limit(limit_n)
        return (await db.execute(sq)).all()

    top_memory_types = []
    for row in mt_rows:
        s = await _samples(ObservedPlayMemoryItem.memory_type == row.grp)
        top_memory_types.append(MemoryAnalyticsGroup(
            label=row.grp,
            memory_type=row.grp,
            count=row.cnt,
            average_confidence=float(row.avg_conf) if row.avg_conf is not None else None,
            resolved_count=row.res_cnt or 0,
            ambiguous_count=row.amb_cnt or 0,
            unresolved_count=row.unr_cnt or 0,
            sample_memory_item_ids=[str(r.id) for r in s],
            sample_source_lines=[r.source_raw_line for r in s if r.source_raw_line],
        ))

    top_actor_cards = await _fetch_analytics_groups(
        db, ObservedPlayMemoryItem.actor_card_raw, "actor_card", limit,
        extra_filter=base, is_card_group=True,
    )

    top_target_cards = await _fetch_analytics_groups(
        db, ObservedPlayMemoryItem.target_card_raw, "target_card", limit,
        extra_filter=base, is_card_group=True,
    )

    action_q = (
        select(
            ObservedPlayMemoryItem.memory_type.label("mtype"),
            ObservedPlayMemoryItem.action_name.label("aname"),
            func.count(ObservedPlayMemoryItem.id).label("cnt"),
            func.avg(ObservedPlayMemoryItem.confidence_score).label("avg_conf"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "resolved"
            ).label("res_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "ambiguous"
            ).label("amb_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(
                ObservedPlayMemoryItem.actor_resolution_status == "unresolved"
            ).label("unr_cnt"),
        )
        .where(ObservedPlayMemoryItem.action_name.isnot(None))
        .group_by(ObservedPlayMemoryItem.memory_type, ObservedPlayMemoryItem.action_name)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
        .limit(limit)
    )
    if base is not None:
        action_q = action_q.where(base)
    action_rows = (await db.execute(action_q)).all()
    top_actions = []
    for row in action_rows:
        label = f"{row.mtype}:{row.aname}"
        s = await _samples(
            and_(ObservedPlayMemoryItem.memory_type == row.mtype, ObservedPlayMemoryItem.action_name == row.aname)
        )
        top_actions.append(MemoryAnalyticsGroup(
            label=label,
            memory_type=row.mtype,
            count=row.cnt,
            average_confidence=float(row.avg_conf) if row.avg_conf is not None else None,
            resolved_count=row.res_cnt or 0,
            ambiguous_count=row.amb_cnt or 0,
            unresolved_count=row.unr_cnt or 0,
            sample_memory_item_ids=[str(r.id) for r in s],
            sample_source_lines=[r.source_raw_line for r in s if r.source_raw_line],
        ))

    atk_filter = and_(
        ObservedPlayMemoryItem.memory_type == "attack_used",
        ObservedPlayMemoryItem.actor_card_raw.isnot(None),
        ObservedPlayMemoryItem.action_name.isnot(None),
        *([] if base is None else [base]),
    )
    atk_q = (
        select(
            ObservedPlayMemoryItem.actor_card_raw.label("actor"),
            ObservedPlayMemoryItem.action_name.label("aname"),
            func.count(ObservedPlayMemoryItem.id).label("cnt"),
            func.avg(ObservedPlayMemoryItem.confidence_score).label("avg_conf"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "resolved").label("res_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "ambiguous").label("amb_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "unresolved").label("unr_cnt"),
        )
        .where(atk_filter)
        .group_by(ObservedPlayMemoryItem.actor_card_raw, ObservedPlayMemoryItem.action_name)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
        .limit(limit)
    )
    atk_rows = (await db.execute(atk_q)).all()
    top_attacks = []
    for row in atk_rows:
        label = f"{row.actor}:{row.aname}"
        s = await _samples(
            and_(ObservedPlayMemoryItem.memory_type == "attack_used",
                 ObservedPlayMemoryItem.actor_card_raw == row.actor,
                 ObservedPlayMemoryItem.action_name == row.aname)
        )
        top_attacks.append(MemoryAnalyticsGroup(
            label=label, memory_type="attack_used", count=row.cnt,
            average_confidence=float(row.avg_conf) if row.avg_conf is not None else None,
            resolved_count=row.res_cnt or 0, ambiguous_count=row.amb_cnt or 0, unresolved_count=row.unr_cnt or 0,
            sample_memory_item_ids=[str(r.id) for r in s],
            sample_source_lines=[r.source_raw_line for r in s if r.source_raw_line],
        ))

    abl_filter = and_(
        ObservedPlayMemoryItem.memory_type == "ability_used",
        ObservedPlayMemoryItem.actor_card_raw.isnot(None),
        ObservedPlayMemoryItem.action_name.isnot(None),
        *([] if base is None else [base]),
    )
    abl_q = (
        select(
            ObservedPlayMemoryItem.actor_card_raw.label("actor"),
            ObservedPlayMemoryItem.action_name.label("aname"),
            func.count(ObservedPlayMemoryItem.id).label("cnt"),
            func.avg(ObservedPlayMemoryItem.confidence_score).label("avg_conf"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "resolved").label("res_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "ambiguous").label("amb_cnt"),
            func.count(ObservedPlayMemoryItem.id).filter(ObservedPlayMemoryItem.actor_resolution_status == "unresolved").label("unr_cnt"),
        )
        .where(abl_filter)
        .group_by(ObservedPlayMemoryItem.actor_card_raw, ObservedPlayMemoryItem.action_name)
        .order_by(func.count(ObservedPlayMemoryItem.id).desc())
        .limit(limit)
    )
    abl_rows = (await db.execute(abl_q)).all()
    top_abilities = []
    for row in abl_rows:
        label = f"{row.actor}:{row.aname}"
        s = await _samples(
            and_(ObservedPlayMemoryItem.memory_type == "ability_used",
                 ObservedPlayMemoryItem.actor_card_raw == row.actor,
                 ObservedPlayMemoryItem.action_name == row.aname)
        )
        top_abilities.append(MemoryAnalyticsGroup(
            label=label, memory_type="ability_used", count=row.cnt,
            average_confidence=float(row.avg_conf) if row.avg_conf is not None else None,
            resolved_count=row.res_cnt or 0, ambiguous_count=row.amb_cnt or 0, unresolved_count=row.unr_cnt or 0,
            sample_memory_item_ids=[str(r.id) for r in s],
            sample_source_lines=[r.source_raw_line for r in s if r.source_raw_line],
        ))

    top_attachments = await _fetch_analytics_groups(
        db, ObservedPlayMemoryItem.target_card_raw, "card_attached", limit,
        extra_filter=and_(ObservedPlayMemoryItem.memory_type == "card_attached", *([] if base is None else [base])),
        is_card_group=True,
    )

    top_evolutions = await _fetch_analytics_groups(
        db, ObservedPlayMemoryItem.actor_card_raw, "card_evolved", limit,
        extra_filter=and_(ObservedPlayMemoryItem.memory_type == "card_evolved", *([] if base is None else [base])),
        is_card_group=True,
    )

    top_knockouts = await _fetch_analytics_groups(
        db, ObservedPlayMemoryItem.target_card_raw, "knockout", limit,
        extra_filter=and_(ObservedPlayMemoryItem.memory_type == "knockout", *([] if base is None else [base])),
        is_card_group=True,
    )

    quality_flags = []
    qf_defs = [
        ("low_confidence", ObservedPlayMemoryItem.confidence_score < LOW_CONFIDENCE_THRESHOLD),
        ("ambiguous_actor", ObservedPlayMemoryItem.actor_resolution_status == "ambiguous"),
        ("ambiguous_target", ObservedPlayMemoryItem.target_resolution_status == "ambiguous"),
        ("unresolved_actor", ObservedPlayMemoryItem.actor_resolution_status == "unresolved"),
        ("unresolved_target", ObservedPlayMemoryItem.target_resolution_status == "unresolved"),
    ]
    for qf_label, qf_filter in qf_defs:
        cnt_r = await db.execute(select(func.count(ObservedPlayMemoryItem.id)).where(qf_filter))
        cnt = cnt_r.scalar() or 0
        s = await _samples(qf_filter)
        quality_flags.append(MemoryAnalyticsGroup(
            label=qf_label, memory_type="quality", count=cnt,
            average_confidence=None, resolved_count=0, ambiguous_count=0, unresolved_count=0,
            sample_memory_item_ids=[str(r.id) for r in s],
            sample_source_lines=[r.source_raw_line for r in s if r.source_raw_line],
        ))

    return MemoryAnalyticsResponse(
        top_memory_types=top_memory_types,
        top_actor_cards=top_actor_cards,
        top_target_cards=top_target_cards,
        top_actions=top_actions,
        top_attacks=top_attacks,
        top_abilities=top_abilities,
        top_attachments=top_attachments,
        top_evolutions=top_evolutions,
        top_knockouts=top_knockouts,
        quality_flags=quality_flags,
    )


@router.get("/memory-analytics/source-items")
async def get_memory_analytics_source_items(
    memory_type: Optional[str] = Query(None),
    actor_card_raw: Optional[str] = Query(None),
    actor_card_def_id: Optional[str] = Query(None),
    target_card_raw: Optional[str] = Query(None),
    target_card_def_id: Optional[str] = Query(None),
    action_name: Optional[str] = Query(None),
    quality_flag: Optional[str] = Query(None),
    related_card_raw: Optional[str] = Query(None),
    min_confidence: Optional[float] = Query(None),
    card_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PaginatedMemoryItems:
    """Drill-down: list memory items matching analytics filter criteria (read-only)."""
    q = select(ObservedPlayMemoryItem)
    if memory_type:
        q = q.where(ObservedPlayMemoryItem.memory_type == memory_type)
    if actor_card_raw:
        q = q.where(ObservedPlayMemoryItem.actor_card_raw == actor_card_raw)
    if actor_card_def_id:
        q = q.where(ObservedPlayMemoryItem.actor_card_def_id == actor_card_def_id)
    if target_card_raw:
        q = q.where(ObservedPlayMemoryItem.target_card_raw == target_card_raw)
    if target_card_def_id:
        q = q.where(ObservedPlayMemoryItem.target_card_def_id == target_card_def_id)
    if action_name:
        q = q.where(ObservedPlayMemoryItem.action_name == action_name)
    if quality_flag == "low_confidence":
        q = q.where(ObservedPlayMemoryItem.confidence_score < LOW_CONFIDENCE_THRESHOLD)
    elif quality_flag == "ambiguous_actor":
        q = q.where(ObservedPlayMemoryItem.actor_resolution_status == "ambiguous")
    elif quality_flag == "ambiguous_target":
        q = q.where(ObservedPlayMemoryItem.target_resolution_status == "ambiguous")
    elif quality_flag == "unresolved_actor":
        q = q.where(ObservedPlayMemoryItem.actor_resolution_status == "unresolved")
    elif quality_flag == "unresolved_target":
        q = q.where(ObservedPlayMemoryItem.target_resolution_status == "unresolved")
    if related_card_raw:
        q = q.where(ObservedPlayMemoryItem.related_card_raw == related_card_raw)
    if min_confidence is not None:
        q = q.where(ObservedPlayMemoryItem.confidence_score >= min_confidence)
    if card_name:
        ilike_val = f"%{card_name}%"
        q = q.where(
            ObservedPlayMemoryItem.actor_card_raw.ilike(ilike_val)
            | ObservedPlayMemoryItem.target_card_raw.ilike(ilike_val)
            | ObservedPlayMemoryItem.related_card_raw.ilike(ilike_val)
        )
    q = q.order_by(ObservedPlayMemoryItem.created_at.desc())

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0
    rows_result = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    rows = rows_result.scalars().all()

    items = [
        MemoryItemSummary(
            id=str(row.id),
            ingestion_id=str(row.ingestion_id),
            observed_play_log_id=str(row.observed_play_log_id),
            observed_play_event_id=row.observed_play_event_id,
            memory_type=row.memory_type,
            memory_key=row.memory_key,
            turn_number=row.turn_number,
            phase=row.phase,
            player_alias=row.player_alias,
            player_raw=row.player_raw,
            actor_card_raw=row.actor_card_raw,
            actor_card_def_id=row.actor_card_def_id,
            actor_resolution_status=row.actor_resolution_status,
            target_card_raw=row.target_card_raw,
            target_card_def_id=row.target_card_def_id,
            target_resolution_status=row.target_resolution_status,
            related_card_raw=row.related_card_raw,
            related_card_def_id=row.related_card_def_id,
            related_resolution_status=row.related_resolution_status,
            action_name=row.action_name,
            amount=row.amount,
            damage=row.damage,
            zone=row.zone,
            target_zone=row.target_zone,
            confidence_score=row.confidence_score,
            source_event_type=row.source_event_type,
            source_raw_line=row.source_raw_line,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]
    return PaginatedMemoryItems(items=items, total=total, page=page, per_page=per_page)


# ── Bulk actions ───────────────────────────────────────────────────────────────

@router.post("/logs/reparse-all")
async def reparse_all_logs(
    db: AsyncSession = Depends(get_db),
) -> BulkReparseSummary:
    """Reparse all non-ingested observed-play logs with the current parser.

    Already-ingested logs are skipped to avoid desync between parsed events
    and existing memory items.  No memory items are created.
    """
    logs_result = await db.execute(
        select(ObservedPlayLog).order_by(ObservedPlayLog.created_at.asc())
    )
    logs = logs_result.scalars().all()

    reparsed: list[BulkReparseLogResult] = []
    skipped: list[BulkReparseLogResult] = []
    failed: list[BulkReparseLogResult] = []

    for log in logs:
        log_id = str(log.id)
        filename = log.original_filename or log_id

        if log.memory_status == "ingested":
            skipped.append(BulkReparseLogResult(
                log_id=log_id, filename=filename,
                status="skipped", reason="already_ingested",
            ))
            continue

        try:
            raw_content = log.raw_content or ""

            await db.execute(
                delete(ObservedPlayEvent).where(
                    ObservedPlayEvent.observed_play_log_id == log.id
                )
            )

            parsed_log = parse_log(raw_content)

            for evt in parsed_log.events:
                db.add(ObservedPlayEvent(
                    observed_play_log_id=log.id,
                    import_batch_id=log.import_batch_id,
                    event_index=evt.event_index,
                    turn_number=evt.turn_number,
                    phase=evt.phase,
                    player_raw=evt.player_raw,
                    player_alias=evt.player_alias,
                    actor_type=evt.actor_type,
                    event_type=evt.event_type,
                    raw_line=evt.raw_line,
                    raw_block=evt.raw_block,
                    card_name_raw=evt.card_name_raw,
                    target_card_name_raw=evt.target_card_name_raw,
                    zone=evt.zone,
                    target_zone=evt.target_zone,
                    amount=evt.amount,
                    damage=evt.damage,
                    base_damage=evt.base_damage,
                    weakness_damage=evt.weakness_damage,
                    resistance_delta=evt.resistance_delta,
                    healing_amount=evt.healing_amount,
                    energy_type=evt.energy_type,
                    prize_count_delta=evt.prize_count_delta,
                    deck_count_delta=evt.deck_count_delta,
                    hand_count_delta=evt.hand_count_delta,
                    discard_count_delta=evt.discard_count_delta,
                    event_payload_json=evt.event_payload,
                    confidence_score=evt.confidence_score,
                    confidence_reasons_json=evt.confidence_reasons,
                    parser_version=PARSER_VERSION,
                ))

            log.parser_version = parsed_log.parser_version
            log.parse_status = "parsed" if not parsed_log.warnings else "parsed_with_warnings"
            log.player_1_name_raw = parsed_log.player_1_name_raw
            log.player_2_name_raw = parsed_log.player_2_name_raw
            log.player_1_alias = parsed_log.player_1_alias
            log.player_2_alias = parsed_log.player_2_alias
            log.winner_raw = parsed_log.winner_raw
            log.winner_alias = parsed_log.winner_alias
            log.win_condition = parsed_log.win_condition
            log.turn_count = parsed_log.turn_count
            log.event_count = parsed_log.event_count
            log.confidence_score = parsed_log.confidence_score
            log.warnings_json = parsed_log.warnings
            log.errors_json = parsed_log.errors
            log.metadata_json = parsed_log.metadata

            await db.commit()
            await db.refresh(log)

            try:
                await extract_and_resolve_mentions_for_log(db, log.id)
                await db.commit()
                await db.refresh(log)
            except Exception as exc:
                logger.warning("Card resolution failed for log %s during bulk reparse: %s", log_id, exc)

            reparsed.append(BulkReparseLogResult(
                log_id=log_id, filename=filename,
                status="reparsed",
                parse_status=log.parse_status,
                confidence_score=log.confidence_score,
                event_count=log.event_count or 0,
            ))

        except Exception as exc:
            logger.error("Bulk reparse failed for log %s: %s", log_id, exc)
            await db.rollback()
            failed.append(BulkReparseLogResult(
                log_id=log_id, filename=filename,
                status="failed", error=str(exc),
            ))

    total_event_count = sum(r.event_count or 0 for r in reparsed)
    confidences = [r.confidence_score for r in reparsed if r.confidence_score is not None]
    avg_confidence = sum(confidences) / len(confidences) if confidences else None

    return BulkReparseSummary(
        considered_count=len(logs),
        reparsed_count=len(reparsed),
        skipped_count=len(skipped),
        failed_count=len(failed),
        reparsed=reparsed,
        skipped=skipped,
        failed=failed,
        average_confidence=avg_confidence,
        total_event_count=total_event_count,
    )


@router.post("/memory-ingestion/preview-eligible")
async def preview_ingest_eligible(
    db: AsyncSession = Depends(get_db),
) -> BulkIngestEligiblePreview:
    """Preview which logs are eligible for bulk memory ingestion.

    Logs that are already ingested or not yet parsed are reported as skipped.
    This is a read-only endpoint; no memory items are created.
    """
    config = IngestionConfig()

    logs_result = await db.execute(
        select(ObservedPlayLog).order_by(ObservedPlayLog.created_at.asc())
    )
    logs = logs_result.scalars().all()

    eligible_logs: list[BulkIngestPreviewLog] = []
    skipped_logs: list[BulkIngestPreviewLog] = []
    blocker_tally: dict[str, int] = {}

    for log in logs:
        log_id = str(log.id)
        filename = log.original_filename or log_id

        if log.memory_status == "ingested":
            skipped_logs.append(BulkIngestPreviewLog(
                log_id=log_id, filename=filename,
                status="already_ingested",
                confidence_score=log.confidence_score,
                event_count=log.event_count or 0,
            ))
            continue

        parse_status = log.parse_status or ""
        if parse_status not in ("parsed", "parsed_with_warnings"):
            skipped_logs.append(BulkIngestPreviewLog(
                log_id=log_id, filename=filename,
                status="not_ready",
                confidence_score=log.confidence_score,
                event_count=log.event_count or 0,
                blocker_reasons=["not_parsed"],
            ))
            continue

        eligibility = await evaluate_log_ingestion_eligibility(db, log.id, config)

        if eligibility.eligible:
            # Estimate memory item count using preview (but skip writing)
            preview = await preview_observed_play_ingestion(db, log.id, config)
            eligible_logs.append(BulkIngestPreviewLog(
                log_id=log_id, filename=filename,
                status="eligible",
                confidence_score=log.confidence_score,
                event_count=log.event_count or 0,
                estimated_memory_item_count=preview.estimated_memory_item_count,
            ))
        else:
            reasons = [r.code for r in eligibility.reasons]
            for r in reasons:
                blocker_tally[r] = blocker_tally.get(r, 0) + 1
            skipped_logs.append(BulkIngestPreviewLog(
                log_id=log_id, filename=filename,
                status="ineligible",
                confidence_score=log.confidence_score,
                event_count=log.event_count or 0,
                blocker_reasons=reasons,
            ))

    ineligible_count = sum(1 for s in skipped_logs if s.status == "ineligible")
    already_ingested_count = sum(1 for s in skipped_logs if s.status == "already_ingested")
    not_ready_count = sum(1 for s in skipped_logs if s.status == "not_ready")
    estimated_total = sum(e.estimated_memory_item_count or 0 for e in eligible_logs)

    top_blockers = [
        {"reason": k, "count": v}
        for k, v in sorted(blocker_tally.items(), key=lambda x: x[1], reverse=True)
    ]

    return BulkIngestEligiblePreview(
        considered_count=len(logs),
        eligible_count=len(eligible_logs),
        ineligible_count=ineligible_count,
        already_ingested_count=already_ingested_count,
        not_ready_count=not_ready_count,
        estimated_memory_item_count=estimated_total,
        eligible_logs=eligible_logs,
        skipped_logs=skipped_logs,
        top_blocker_reasons=top_blockers,
    )


@router.post("/memory-ingestion/ingest-eligible")
async def ingest_all_eligible(
    db: AsyncSession = Depends(get_db),
) -> BulkIngestEligibleSummary:
    """Ingest all eligible parsed/not-yet-ingested logs into observed-play memory.

    Uses the same eligibility gates as single-log ingestion.
    Already-ingested logs are skipped (idempotent).
    No force ingest; ineligible logs are skipped and reported.
    Each log is committed individually so a failure on one log
    does not roll back previously successful ingestions.
    """
    config = IngestionConfig()

    logs_result = await db.execute(
        select(ObservedPlayLog).order_by(ObservedPlayLog.created_at.asc())
    )
    logs = logs_result.scalars().all()

    ingested: list[BulkIngestLogResult] = []
    skipped: list[BulkIngestLogResult] = []
    failed: list[BulkIngestLogResult] = []

    for log in logs:
        log_id = str(log.id)
        filename = log.original_filename or log_id

        if log.memory_status == "ingested":
            skipped.append(BulkIngestLogResult(
                log_id=log_id, filename=filename,
                status="skipped", reason="already_ingested",
            ))
            continue

        parse_status = log.parse_status or ""
        if parse_status not in ("parsed", "parsed_with_warnings"):
            skipped.append(BulkIngestLogResult(
                log_id=log_id, filename=filename,
                status="skipped", reason="not_parsed",
            ))
            continue

        try:
            summary = await ingest_observed_play_log(db, log.id, config)

            if summary.status == "skipped":
                reason_codes = [r.code for r in summary.reasons]
                skipped.append(BulkIngestLogResult(
                    log_id=log_id, filename=filename,
                    status="skipped", reason=",".join(reason_codes) if reason_codes else "ineligible",
                ))
                await db.rollback()
            else:
                await db.commit()
                ingested.append(BulkIngestLogResult(
                    log_id=log_id, filename=filename,
                    status="ingested",
                    memory_item_count=summary.memory_item_count,
                ))

        except Exception as exc:
            logger.error("Bulk ingest failed for log %s: %s", log_id, exc)
            await db.rollback()
            failed.append(BulkIngestLogResult(
                log_id=log_id, filename=filename,
                status="failed", error=str(exc),
            ))

    eligible_count = len(ingested) + len(failed) + sum(
        1 for s in skipped if s.reason not in ("already_ingested", "not_parsed")
    )
    memory_items_created = sum(r.memory_item_count for r in ingested)

    return BulkIngestEligibleSummary(
        considered_count=len(logs),
        eligible_count=eligible_count,
        ingested_count=len(ingested),
        skipped_count=len(skipped),
        failed_count=len(failed),
        memory_items_created=memory_items_created,
        ingested_logs=ingested,
        skipped_logs=skipped,
        failed_logs=failed,
    )
