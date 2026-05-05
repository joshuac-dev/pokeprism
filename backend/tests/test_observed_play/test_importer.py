"""Tests for app.observed_play.importer orchestration (unit-level, no DB needed for storage)."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.observed_play.storage as storage_mod


@pytest.fixture(autouse=True)
def redirect_root(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "OBSERVED_PLAY_ROOT", tmp_path)
    yield tmp_path


SAMPLE_LOG = b"# PTCGL Battle Log\nPlayer1 vs Player2\nTurn 1\n"

# Realistic PTCGL log with bullets (•), curly apostrophes ('), and spaces in content.
REALISTIC_PTCGL_LOG = (
    "Setup\n"
    "QafePuya chose tails for the opening coin flip.\n"
    "gehejo won the coin toss.\n"
    "gehejo decided to go first.\n"
    "QafePuya drew 7 cards for the opening hand.\n"
    "- 7 drawn cards.\n"
    "gehejo drew 7 cards for the opening hand.\n"
    "- 7 drawn cards.\n"
    "   \u2022 Lillie\u2019s Determination, Basic Darkness Energy, Crispin\n"
).encode("utf-8")


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_db(existing_log=None):
    """Return a mock AsyncSession that returns *existing_log* for duplicate checks."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing_log
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestStorageIntegration:
    """Verify importer's use of storage helpers works end-to-end (no DB)."""

    def test_archive_file_is_readable_after_write(self, tmp_path):
        data = SAMPLE_LOG
        sha = storage_mod.compute_sha256(data)
        rel = storage_mod.write_archive_file(data, sha, "game.md")
        dest = tmp_path / rel
        assert dest.read_bytes() == data

    def test_duplicate_hash_same_path(self, tmp_path):
        data = b"content"
        sha = storage_mod.compute_sha256(data)
        r1 = storage_mod.write_archive_file(data, sha, "a.md")
        r2 = storage_mod.write_archive_file(data, sha, "b.md")
        assert r1 == r2  # same archive path for same hash

    def test_size_limit_constant_is_positive(self):
        assert storage_mod.MAX_SINGLE_FILE_BYTES > 0
        assert storage_mod.MAX_ZIP_BYTES > storage_mod.MAX_SINGLE_FILE_BYTES
        assert storage_mod.MAX_ZIP_ENTRIES > 0

    def test_supported_extensions(self):
        exts = storage_mod.SUPPORTED_EXTENSIONS
        assert ".md" in exts
        assert ".markdown" in exts
        assert ".txt" in exts
        assert ".zip" not in exts  # zip is handled at the upload level

    def test_safe_filename_no_path_traversal(self):
        assert "/" not in storage_mod.safe_filename("../../etc/passwd")
        assert ".." not in storage_mod.safe_filename("../escape.md")

    def test_failed_write_creates_file(self, tmp_path):
        data = b"broken content"
        rel = storage_mod.write_failed_file(data, "bad.md", "encoding_error")
        dest = tmp_path / rel
        assert dest.exists()


# ── run_import async tests ────────────────────────────────────────────────────

class TestRunImport:
    """Test the run_import orchestrator with a mocked DB session."""

    async def test_realistic_ptcgl_log_imports_successfully(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), REALISTIC_PTCGL_LOG, "2026-05-01 14.17.md")
        assert batch.status == "completed"
        assert results[0]["status"] == "imported"
        assert results[0]["parse_status"] in {"parsed", "parsed_with_warnings", "parse_failed"}

    async def test_spaced_filename_imports_successfully(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), SAMPLE_LOG, "2026-05-01 14.17.md")
        assert results[0]["status"] == "imported"

    async def test_utf8_bom_file_imports_successfully(self, tmp_path):
        from app.observed_play.importer import run_import
        bom_content = b"\xef\xbb\xbf# PTCGL Log\nTurn 1: Player did something\n"
        batch, results = await run_import(_make_db(), bom_content, "log.md")
        assert results[0]["status"] == "imported"
        assert results[0]["parse_status"] in {"parsed", "parsed_with_warnings", "parse_failed"}

    async def test_invalid_binary_fails_with_clear_error(self, tmp_path):
        from app.observed_play.importer import run_import
        invalid = bytes(range(256))  # random binary, not valid UTF-8
        batch, results = await run_import(_make_db(), invalid, "bad.md")
        assert results[0]["status"] == "failed"
        assert results[0]["error"] is not None
        assert "UTF-8" in results[0]["error"] or "utf" in results[0]["error"].lower()

    async def test_successful_import_has_parsed_status(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), SAMPLE_LOG, "game.md")
        assert results[0]["parse_status"] in {"parsed", "parsed_with_warnings"}

    async def test_successful_import_no_parse_status_failed(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), SAMPLE_LOG, "game.md")
        assert results[0]["parse_status"] != "failed"

    async def test_failed_import_parse_status_not_failed(self, tmp_path):
        """Infrastructure failures should NOT use parse_status='failed'."""
        from app.observed_play.importer import run_import
        invalid = bytes(range(256))
        batch, results = await run_import(_make_db(), invalid, "bad.md")
        assert results[0]["parse_status"] != "failed"

    async def test_archive_directory_created_if_missing(self, tmp_path):
        from app.observed_play.importer import run_import
        # Ensure no subdirs exist before import
        assert not (tmp_path / "archive").exists()
        await run_import(_make_db(), SAMPLE_LOG, "game.md")
        assert (tmp_path / "archive").is_dir()

    async def test_archive_file_exists_at_stored_path(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), SAMPLE_LOG, "game.md")
        stored = results[0]["stored_path"]
        assert stored is not None
        assert (tmp_path / stored).exists()

    async def test_failed_result_includes_error_field(self, tmp_path):
        from app.observed_play.importer import run_import
        invalid = bytes(range(256))
        batch, results = await run_import(_make_db(), invalid, "bad.md")
        assert "error" in results[0]
        assert results[0]["error"]

    async def test_batch_errors_json_populated_on_failure(self, tmp_path):
        from app.observed_play.importer import run_import
        invalid = bytes(range(256))
        batch, results = await run_import(_make_db(), invalid, "bad.md")
        assert batch.errors_json  # list should be non-empty

    async def test_batch_summary_json_includes_files(self, tmp_path):
        from app.observed_play.importer import run_import
        batch, results = await run_import(_make_db(), SAMPLE_LOG, "game.md")
        assert "files" in batch.summary_json
        assert len(batch.summary_json["files"]) == len(results)

    async def test_duplicate_does_not_create_second_log(self, tmp_path):
        from app.observed_play.importer import run_import
        existing = MagicMock()
        existing.id = "existing-log-id"
        existing.parse_status = "raw_archived"
        existing.stored_path = "archive/ab/existing.md"
        batch, results = await run_import(_make_db(existing_log=existing), SAMPLE_LOG, "game.md")
        assert results[0]["status"] == "duplicate"
        assert results[0]["log_id"] == "existing-log-id"
        assert batch.duplicate_file_count == 1
        # add() should only have been called for the batch, not a new log
        db = _make_db(existing_log=existing)
        batch2, _ = await run_import(db, SAMPLE_LOG, "game.md")
        # db.add should be called at most twice (batch + one flush update), not for a new log
        added_types = [type(call.args[0]).__name__ for call in db.add.call_args_list]
        assert "ObservedPlayLog" not in added_types
