"""Tests for app.observed_play.importer orchestration (unit-level, no DB needed for storage)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

import app.observed_play.storage as storage_mod


@pytest.fixture(autouse=True)
def redirect_root(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "OBSERVED_PLAY_ROOT", tmp_path)
    yield tmp_path


SAMPLE_LOG = b"# PTCGL Battle Log\nPlayer1 vs Player2\nTurn 1\n"


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


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
