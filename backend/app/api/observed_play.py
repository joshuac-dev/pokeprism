"""Observed Play Memory API — Phase 1: upload, batch listing, log listing."""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObservedPlayEvent, ObservedPlayImportBatch, ObservedPlayLog
from app.db.session import AsyncSessionLocal
from app.observed_play.constants import PARSER_VERSION
from app.observed_play.importer import run_import
from app.observed_play.parser import parse_log
from app.observed_play.schemas import (
    BatchDetail,
    BatchImportResponse,
    BatchSummary,
    EventSummary,
    LogDetail,
    LogImportResult,
    LogSummary,
    PaginatedBatches,
    PaginatedEvents,
    PaginatedLogs,
    ReparseSummary,
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

    return ReparseSummary(
        log_id=str(log.id),
        parse_status=log.parse_status,
        event_count=log.event_count or 0,
        turn_count=log.turn_count or 0,
        confidence_score=log.confidence_score,
        parser_version=log.parser_version,
        warnings=log.warnings_json or [],
        errors=log.errors_json or [],
    )
