"""Observed Play Memory API — Phase 1: upload, batch listing, log listing."""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObservedPlayImportBatch, ObservedPlayLog
from app.db.session import AsyncSessionLocal
from app.observed_play.importer import run_import
from app.observed_play.schemas import (
    BatchDetail,
    BatchImportResponse,
    BatchSummary,
    LogDetail,
    LogImportResult,
    LogSummary,
    PaginatedBatches,
    PaginatedLogs,
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
