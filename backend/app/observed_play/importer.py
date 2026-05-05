"""Phase 1 import orchestration for Observed Play Memory.

Handles single .md/.txt files and .zip archives.
No event parsing or memory ingestion occurs in this phase — raw content
is archived and a DB record is created.

The session is flushed internally but NOT committed; the caller (API route)
is responsible for committing or rolling back.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObservedPlayImportBatch, ObservedPlayLog
from app.observed_play.storage import (
    MAX_SINGLE_FILE_BYTES,
    MAX_ZIP_BYTES,
    MAX_ZIP_ENTRIES,
    SUPPORTED_EXTENSIONS,
    compute_sha256,
    write_archive_file,
    write_failed_file,
)

logger = logging.getLogger(__name__)


# ── Single-file import ────────────────────────────────────────────────────────

async def _import_single_file(
    db: AsyncSession,
    data: bytes,
    original_filename: str,
    batch: ObservedPlayImportBatch,
) -> dict:
    """Import one raw log file and return a LogImportResult dict.

    Updates batch counters in-place. Flushes log row to get its ID but does NOT
    commit — the caller must commit.
    """
    ext = Path(original_filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        batch.skipped_file_count = (batch.skipped_file_count or 0) + 1
        return {
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "skipped",
            "parse_status": "not_applicable",
            "stored_path": None,
            "error": f"Unsupported file type: {ext!r}",
        }

    if len(data) > MAX_SINGLE_FILE_BYTES:
        batch.failed_file_count = (batch.failed_file_count or 0) + 1
        try:
            write_failed_file(data, original_filename, "too_large")
        except Exception:
            pass
        return {
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": f"File exceeds {MAX_SINGLE_FILE_BYTES // (1024 * 1024)} MB limit",
        }

    try:
        raw_content = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        batch.failed_file_count = (batch.failed_file_count or 0) + 1
        try:
            write_failed_file(data, original_filename, "encoding_error")
        except Exception:
            pass
        return {
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": "File is not valid UTF-8",
        }

    sha256_hash = compute_sha256(data)
    batch.accepted_file_count = (batch.accepted_file_count or 0) + 1

    # Duplicate detection
    result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.sha256_hash == sha256_hash)
    )
    existing = result.scalars().first()
    if existing is not None:
        batch.duplicate_file_count = (batch.duplicate_file_count or 0) + 1
        return {
            "log_id": str(existing.id),
            "original_filename": original_filename,
            "sha256_hash": sha256_hash,
            "status": "duplicate",
            "parse_status": existing.parse_status,
            "stored_path": existing.stored_path,
            "error": None,
        }

    # Archive to filesystem
    try:
        stored_path = write_archive_file(data, sha256_hash, original_filename)
    except Exception as exc:
        logger.exception("Archive write failed for %s", original_filename)
        batch.failed_file_count = (batch.failed_file_count or 0) + 1
        try:
            write_failed_file(data, original_filename, "archive_error")
        except Exception:
            pass
        return {
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": sha256_hash,
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": f"Archive write failed: {exc}",
        }

    # Create log row
    log = ObservedPlayLog(
        import_batch_id=batch.id,
        source="ptcgl_export",
        original_filename=original_filename,
        stored_path=stored_path,
        sha256_hash=sha256_hash,
        raw_content=raw_content,
        file_size_bytes=len(data),
        parse_status="raw_archived",
        memory_status="not_ingested",
    )
    db.add(log)
    await db.flush()

    batch.imported_file_count = (batch.imported_file_count or 0) + 1
    return {
        "log_id": str(log.id),
        "original_filename": original_filename,
        "sha256_hash": sha256_hash,
        "status": "imported",
        "parse_status": "raw_archived",
        "stored_path": stored_path,
        "error": None,
    }


# ── ZIP import ────────────────────────────────────────────────────────────────

async def _import_zip(
    db: AsyncSession,
    data: bytes,
    original_filename: str,
    batch: ObservedPlayImportBatch,
) -> list[dict]:
    """Extract and import all valid log files from a ZIP archive.

    Processes synchronously. Returns list of LogImportResult dicts.
    Does NOT commit — caller must commit.
    """
    if len(data) > MAX_ZIP_BYTES:
        batch.failed_file_count = (batch.failed_file_count or 0) + 1
        batch.status = "failed"
        return [{
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": f"ZIP file exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB limit",
        }]

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        batch.failed_file_count = (batch.failed_file_count or 0) + 1
        batch.status = "failed"
        return [{
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": f"Invalid ZIP file: {exc}",
        }]

    entries = [e for e in zf.infolist() if not e.is_dir()]
    batch.original_file_count = len(entries)

    if len(entries) > MAX_ZIP_ENTRIES:
        batch.status = "failed"
        return [{
            "log_id": None,
            "original_filename": original_filename,
            "sha256_hash": "",
            "status": "failed",
            "parse_status": "failed",
            "stored_path": None,
            "error": f"ZIP contains {len(entries)} entries — limit is {MAX_ZIP_ENTRIES}",
        }]

    results: list[dict] = []
    for entry in entries:
        entry_name = entry.filename

        # Zip slip protection
        if ".." in entry_name or entry_name.startswith("/"):
            batch.skipped_file_count = (batch.skipped_file_count or 0) + 1
            results.append({
                "log_id": None,
                "original_filename": entry_name,
                "sha256_hash": "",
                "status": "skipped",
                "parse_status": "not_applicable",
                "stored_path": None,
                "error": "Skipped: unsafe path",
            })
            continue

        try:
            entry_data = zf.read(entry_name)
        except Exception as exc:
            batch.failed_file_count = (batch.failed_file_count or 0) + 1
            results.append({
                "log_id": None,
                "original_filename": entry_name,
                "sha256_hash": "",
                "status": "failed",
                "parse_status": "failed",
                "stored_path": None,
                "error": f"Read error: {exc}",
            })
            continue

        entry_basename = Path(entry_name).name
        result = await _import_single_file(db, entry_data, entry_basename, batch)
        results.append(result)

    return results


# ── Top-level orchestration ───────────────────────────────────────────────────

async def run_import(
    db: AsyncSession,
    data: bytes,
    original_filename: str,
) -> tuple[ObservedPlayImportBatch, list[dict]]:
    """Create a batch, import the file(s), and return (batch, results).

    For single .md/.txt files: import inline.
    For .zip files: extract and import each valid entry synchronously.

    The session is NOT committed by this function — the caller must commit.
    """
    now = datetime.now(timezone.utc)
    is_zip = Path(original_filename).suffix.lower() == ".zip"
    src = "upload_zip" if is_zip else "upload_single"

    batch = ObservedPlayImportBatch(
        source=src,
        uploaded_filename=original_filename,
        status="running",
        original_file_count=0 if is_zip else 1,
        accepted_file_count=0,
        duplicate_file_count=0,
        failed_file_count=0,
        imported_file_count=0,
        skipped_file_count=0,
        started_at=now,
    )
    db.add(batch)
    await db.flush()  # get batch.id

    if is_zip:
        results = await _import_zip(db, data, original_filename, batch)
    else:
        results = [await _import_single_file(db, data, original_filename, batch)]

    batch.finished_at = datetime.now(timezone.utc)

    # Determine final status (only update if not already set to failed by zip handler)
    if batch.status != "failed":
        if batch.failed_file_count > 0 and batch.imported_file_count == 0:
            batch.status = "failed"
        elif batch.failed_file_count > 0 or batch.skipped_file_count > 0:
            batch.status = "completed_with_warnings"
        else:
            batch.status = "completed"

    batch.summary_json = {"files": results}
    db.add(batch)
    await db.flush()

    return batch, results
