"""Storage helpers for Observed Play Memory log archive.

Paths are rooted at OBSERVED_PLAY_ROOT (default: /data/ptcgl_logs).
Set OBSERVED_PLAY_LOG_ROOT env var to override (used in tests with tmp_path).
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

OBSERVED_PLAY_ROOT: Path = Path(os.getenv("OBSERVED_PLAY_LOG_ROOT", "/data/ptcgl_logs"))

# Supported file extensions for raw log import.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".txt"})

# Import size limits.
MAX_SINGLE_FILE_BYTES: int = 2 * 1024 * 1024   # 2 MB
MAX_ZIP_BYTES: int          = 25 * 1024 * 1024  # 25 MB
MAX_ZIP_ENTRIES: int        = 500


def ensure_observed_play_dirs() -> None:
    """Create inbox/archive/failed/tmp subdirectories if they don't exist."""
    for sub in ("inbox", "archive", "failed", "tmp"):
        (OBSERVED_PLAY_ROOT / sub).mkdir(parents=True, exist_ok=True)


def compute_sha256(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    """Strip path components and replace unsafe characters.

    Returns a filename-safe string suitable for use in filesystem paths.
    """
    name = Path(name).name  # take only the base component
    name = re.sub(r"[^A-Za-z0-9_\-.]", "_", name)
    return name or "log"


def _archive_ext(original_filename: str) -> str:
    """Return the archive file extension to use for this log."""
    ext = Path(original_filename).suffix.lower()
    return ext if ext in SUPPORTED_EXTENSIONS else ".md"


def relative_archive_path(sha256_hash: str, original_filename: str) -> str:
    """Return the stored_path string relative to OBSERVED_PLAY_ROOT.

    Convention: archive/{sha[:2]}/{sha}{ext}
    """
    ext = _archive_ext(original_filename)
    subdir = sha256_hash[:2]
    return f"archive/{subdir}/{sha256_hash}{ext}"


def write_archive_file(data: bytes, sha256_hash: str, original_filename: str) -> str:
    """Write *data* to the archive.

    Creates directories as needed. Idempotent — overwrites an existing file
    with the same hash (safe: same hash → same content).

    Returns the relative stored_path string.
    """
    ensure_observed_play_dirs()
    rel = relative_archive_path(sha256_hash, original_filename)
    dest = OBSERVED_PLAY_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel


def write_failed_file(
    data: bytes,
    original_filename: str,
    reason_slug: str | None = None,
) -> str:
    """Write a failed log to the failed directory.

    Returns the relative path of the written file.
    """
    ensure_observed_play_dirs()
    safe_name = safe_filename(original_filename)
    slug = f"_{reason_slug}" if reason_slug else ""
    ts = int(time.time())
    fname = f"{ts}{slug}_{safe_name}"
    dest = OBSERVED_PLAY_ROOT / "failed" / fname
    dest.write_bytes(data)
    return f"failed/{fname}"
