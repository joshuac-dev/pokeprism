"""Tests for app.observed_play.storage helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import app.observed_play.storage as storage_mod


@pytest.fixture(autouse=True)
def redirect_root(tmp_path, monkeypatch):
    """Redirect OBSERVED_PLAY_ROOT to a fresh tmp_path for every test."""
    monkeypatch.setattr(storage_mod, "OBSERVED_PLAY_ROOT", tmp_path)
    yield tmp_path


# ── SHA-256 ────────────────────────────────────────────────────────────────────

def test_compute_sha256_stable():
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert storage_mod.compute_sha256(data) == expected
    assert storage_mod.compute_sha256(data) == expected  # stable on repeat call


def test_compute_sha256_different_inputs():
    assert storage_mod.compute_sha256(b"a") != storage_mod.compute_sha256(b"b")


# ── Safe filename ──────────────────────────────────────────────────────────────

def test_safe_filename_strips_path():
    assert storage_mod.safe_filename("/etc/passwd") == "passwd"
    assert storage_mod.safe_filename("../../etc/passwd") == "passwd"
    assert storage_mod.safe_filename("../dir/file.md") == "file.md"


def test_safe_filename_replaces_special_chars():
    result = storage_mod.safe_filename("my log file (2024).md")
    assert " " not in result
    assert "(" not in result
    assert ")" not in result
    assert result.endswith(".md")


def test_safe_filename_empty_fallback():
    assert storage_mod.safe_filename("") == "log"
    # all-special chars become underscores, not "log"
    assert storage_mod.safe_filename("!!!") == "___"


# ── Archive path ───────────────────────────────────────────────────────────────

def test_relative_archive_path_convention():
    sha = "abcdef1234567890" * 4  # 64 chars
    path = storage_mod.relative_archive_path(sha, "game.md")
    assert path == f"archive/ab/{sha}.md"


def test_relative_archive_path_normalises_ext():
    sha = "abcdef1234567890" * 4
    path = storage_mod.relative_archive_path(sha, "game.MARKDOWN")
    assert path.endswith(".markdown")


def test_relative_archive_path_unknown_ext_uses_md():
    sha = "abcdef1234567890" * 4
    path = storage_mod.relative_archive_path(sha, "game.log")
    assert path.endswith(".md")


# ── ensure_observed_play_dirs ─────────────────────────────────────────────────

def test_ensure_dirs_creates_subdirs(tmp_path):
    storage_mod.ensure_observed_play_dirs()
    for sub in ("inbox", "archive", "failed", "tmp"):
        assert (tmp_path / sub).is_dir()


# ── write_archive_file ────────────────────────────────────────────────────────

def test_write_archive_file_creates_file(tmp_path):
    data = b"# PTCGL Log\nTurn 1\n"
    sha = storage_mod.compute_sha256(data)
    rel_path = storage_mod.write_archive_file(data, sha, "game.md")

    dest = tmp_path / rel_path
    assert dest.exists()
    assert dest.read_bytes() == data
    assert rel_path.startswith(f"archive/{sha[:2]}/")


def test_write_archive_file_idempotent(tmp_path):
    data = b"same content"
    sha = storage_mod.compute_sha256(data)
    rel1 = storage_mod.write_archive_file(data, sha, "game.md")
    rel2 = storage_mod.write_archive_file(data, sha, "game.md")
    assert rel1 == rel2


# ── write_failed_file ──────────────────────────────────────────────────────────

def test_write_failed_file_writes_to_failed(tmp_path):
    data = b"bad content"
    rel_path = storage_mod.write_failed_file(data, "bad.md", "test_reason")

    dest = tmp_path / rel_path
    assert dest.exists()
    assert dest.read_bytes() == data
    assert rel_path.startswith("failed/")
    assert "test_reason" in rel_path


def test_write_failed_file_no_reason(tmp_path):
    data = b"bad content"
    rel_path = storage_mod.write_failed_file(data, "bad.md")
    dest = tmp_path / rel_path
    assert dest.exists()
