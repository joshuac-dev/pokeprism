"""Observed Play Memory API — Phase 1–3: upload, batch listing, log listing, card resolution."""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
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
    UnresolvedCardItem,
    UnresolvedCardsResponse,
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

@router.get("/logs")
async def list_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    parse_status: Optional[str] = Query(None),
    memory_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedLogs:
    """List raw observed play logs."""
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
    q = q.order_by(ObservedPlayLog.created_at.desc())

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

    items = [
        UnresolvedCardItem(
            raw_name=row.raw_name,
            normalized_name=row.normalized_name,
            status=row.resolution_status,
            mention_count=row.mention_count,
            log_count=row.log_count,
            candidate_count=row.candidate_count or 0,
            candidates=row.candidates_json or [],
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
    if body.action not in ("resolve", "ignore"):
        raise HTTPException(status_code=422, detail="action must be 'resolve' or 'ignore'")
    if body.action == "resolve" and not body.target_card_def_id:
        raise HTTPException(
            status_code=422,
            detail="target_card_def_id is required for action='resolve'",
        )
    norm = normalize_card_name(body.raw_name)
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
