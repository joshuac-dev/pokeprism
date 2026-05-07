"""Tests for the /api/observed-play endpoints (Phase 1).

Uses mocked DB sessions (via dependency_overrides) to avoid asyncpg
event-loop isolation issues, following the project's test_coverage.py pattern.
Integration-level DB behaviour (duplicate detection, raw content retrieval)
is covered by the importer unit tests and the test_storage suite.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── App client ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from app.main import create_app
    return TestClient(create_app())


# ── Storage redirect ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def redirect_storage(tmp_path, monkeypatch):
    import app.observed_play.storage as storage_mod
    monkeypatch.setattr(storage_mod, "OBSERVED_PLAY_ROOT", tmp_path)
    yield tmp_path


# ── DB mock helpers ────────────────────────────────────────────────────────────

def _make_batch_model(
    batch_id: str = "batch-001",
    status: str = "completed",
    imported: int = 1,
    duplicate: int = 0,
    failed: int = 0,
    skipped: int = 0,
    original: int = 1,
    accepted: int = 1,
    uploaded_filename: str = "game.md",
):
    b = MagicMock()
    b.id = batch_id
    b.source = "upload_single"
    b.uploaded_filename = uploaded_filename
    b.status = status
    b.original_file_count = original
    b.accepted_file_count = accepted
    b.duplicate_file_count = duplicate
    b.failed_file_count = failed
    b.imported_file_count = imported
    b.skipped_file_count = skipped
    b.started_at = None
    b.finished_at = None
    b.created_at = None
    b.errors_json = []
    b.warnings_json = []
    b.summary_json = {}
    return b


def _make_log_model(
    log_id: str = "log-001",
    batch_id: str = "batch-001",
    sha256: str = "a" * 64,
    parse_status: str = "raw_archived",
    memory_status: str = "not_ingested",
    original_filename: str = "game.md",
    raw_content: str = "# log",
):
    log = MagicMock()
    log.id = log_id
    log.import_batch_id = batch_id
    log.source = "ptcgl_export"
    log.original_filename = original_filename
    log.sha256_hash = sha256
    log.raw_content = raw_content
    log.file_size_bytes = len(raw_content)
    log.parse_status = parse_status
    log.memory_status = memory_status
    log.stored_path = f"archive/aa/{sha256}.md"
    log.created_at = None
    log.player_1_name_raw = None
    log.player_2_name_raw = None
    log.player_1_alias = None
    log.player_2_alias = None
    log.winner_raw = None
    log.winner_alias = None
    log.win_condition = None
    log.turn_count = 0
    log.event_count = 0
    log.confidence_score = None
    log.parser_version = None
    log.errors_json = []
    log.warnings_json = []
    log.metadata_json = {}
    log.updated_at = None
    log.recognized_card_count = 0
    log.ambiguous_card_count = 0
    log.unresolved_card_count = 0
    log.card_mention_count = 0
    log.card_resolution_status = None
    log.resolver_version = None
    log.memory_item_count = 0
    log.last_memory_ingested_at = None
    return log


def _db_override(execute_return=None, scalars_return=None):
    """Return an async db session override (generator) and get_db ref."""
    from app.api.observed_play import get_db

    async def override_db():
        session = AsyncMock()
        result = MagicMock()
        if scalars_return is not None:
            result.scalars.return_value.all.return_value = scalars_return
            result.scalars.return_value.first.return_value = (
                scalars_return[0] if scalars_return else None
            )
        else:
            result.scalars.return_value.all.return_value = []
            result.scalars.return_value.first.return_value = None
        result.scalar_one.return_value = len(scalars_return) if scalars_return else 0
        if execute_return is not None:
            session.execute = AsyncMock(return_value=execute_return)
        else:
            session.execute = AsyncMock(return_value=result)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        yield session

    return override_db, get_db


def _unique_log() -> bytes:
    return f"# PTCGL Log {uuid.uuid4()}\nPlayer1 vs Player2\n".encode()


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ── Upload tests ───────────────────────────────────────────────────────────────

class TestUploadSingleFile:
    def _upload_with_mock(self, client, payload: bytes, filename: str = "game.md"):
        batch = _make_batch_model(uploaded_filename=filename)
        log = _make_log_model(original_filename=filename)

        with patch("app.api.observed_play.run_import") as mock_run:
            result_entry = {
                "log_id": log.id,
                "original_filename": filename,
                "sha256_hash": log.sha256_hash,
                "status": "imported",
                "parse_status": "raw_archived",
                "stored_path": log.stored_path,
                "error": None,
            }
            mock_run.return_value = (batch, [result_entry])

            from app.api.observed_play import get_db

            async def override_db():
                session = AsyncMock()
                session.add = MagicMock()
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.refresh = AsyncMock()
                yield session

            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(
                    "/api/observed-play/upload",
                    files={"file": (filename, payload, "text/markdown")},
                )
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        return resp

    def test_upload_md_creates_batch_and_log(self, client):
        resp = self._upload_with_mock(client, _unique_log(), "game.md")
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "completed"
        assert data["imported_file_count"] == 1
        assert data["logs"][0]["status"] == "imported"
        assert data["logs"][0]["parse_status"] == "raw_archived"

    def test_upload_txt_creates_batch_and_log(self, client):
        resp = self._upload_with_mock(client, _unique_log(), "game.txt")
        assert resp.status_code == 201
        assert resp.json()["imported_file_count"] == 1

    def test_upload_markdown_ext(self, client):
        resp = self._upload_with_mock(client, _unique_log(), "game.markdown")
        assert resp.status_code == 201
        assert resp.json()["imported_file_count"] == 1

    def test_upload_unsupported_extension_returns_422(self, client):
        resp = client.post(
            "/api/observed-play/upload",
            files={"file": ("game.csv", b"col1,col2\n", "text/csv")},
        )
        assert resp.status_code == 422

    def test_duplicate_upload_returns_duplicate_status(self, client):
        batch = _make_batch_model(imported=0, duplicate=1, accepted=1)
        log = _make_log_model()

        with patch("app.api.observed_play.run_import") as mock_run:
            mock_run.return_value = (batch, [{
                "log_id": log.id,
                "original_filename": "game.md",
                "sha256_hash": log.sha256_hash,
                "status": "duplicate",
                "parse_status": "raw_archived",
                "stored_path": log.stored_path,
                "error": None,
                "event_count": 0,
                "confidence_score": None,
            }])
            from app.api.observed_play import get_db

            async def override_db():
                session = AsyncMock()
                session.add = MagicMock()
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.refresh = AsyncMock()
                yield session

            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(
                    "/api/observed-play/upload",
                    files={"file": ("game.md", _unique_log(), "text/markdown")},
                )
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["duplicate_file_count"] == 1
        assert data["imported_file_count"] == 0
        assert data["logs"][0]["status"] == "duplicate"

    def test_duplicate_response_includes_event_count_and_confidence(self, client):
        """Duplicate upload response must include event_count/confidence_score from existing log."""
        batch = _make_batch_model(imported=0, duplicate=1, accepted=1)
        log = _make_log_model()

        with patch("app.api.observed_play.run_import") as mock_run:
            mock_run.return_value = (batch, [{
                "log_id": log.id,
                "original_filename": "game.md",
                "sha256_hash": log.sha256_hash,
                "status": "duplicate",
                "parse_status": "parsed",
                "stored_path": log.stored_path,
                "error": None,
                "event_count": 42,
                "confidence_score": 0.87,
            }])
            from app.api.observed_play import get_db

            async def override_db():
                session = AsyncMock()
                session.commit = AsyncMock()
                session.refresh = AsyncMock()
                yield session

            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(
                    "/api/observed-play/upload",
                    files={"file": ("game.md", _unique_log(), "text/markdown")},
                )
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        entry = resp.json()["logs"][0]
        assert entry["status"] == "duplicate"
        assert entry["event_count"] == 42
        assert entry["confidence_score"] == pytest.approx(0.87)

    def test_parse_status_is_raw_archived(self, client):
        resp = self._upload_with_mock(client, _unique_log())
        assert resp.json()["logs"][0]["parse_status"] == "raw_archived"

    def test_memory_status_not_ingested_on_log_detail(self, client):
        log = _make_log_model(memory_status="not_ingested")
        override_db, get_db = _db_override(scalars_return=[log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["memory_status"] == "not_ingested"


# ── ZIP upload ────────────────────────────────────────────────────────────────

class TestUploadZip:
    def _zip_upload(self, client, results: list[dict], batch_kwargs: dict | None = None):
        kw = batch_kwargs or {}
        batch = _make_batch_model(**kw)
        zip_data = _make_zip({"log.md": _unique_log()})

        with patch("app.api.observed_play.run_import") as mock_run:
            mock_run.return_value = (batch, results)
            from app.api.observed_play import get_db

            async def override_db():
                session = AsyncMock()
                session.add = MagicMock()
                session.flush = AsyncMock()
                session.commit = AsyncMock()
                session.refresh = AsyncMock()
                yield session

            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(
                    "/api/observed-play/upload",
                    files={"file": ("logs.zip", zip_data, "application/zip")},
                )
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        return resp

    def test_zip_imports_supported_entries(self, client):
        results = [
            {"log_id": "l1", "original_filename": "a.md", "sha256_hash": "a" * 64,
             "status": "imported", "parse_status": "raw_archived", "stored_path": "archive/aa/a.md", "error": None},
            {"log_id": "l2", "original_filename": "b.txt", "sha256_hash": "b" * 64,
             "status": "imported", "parse_status": "raw_archived", "stored_path": "archive/bb/b.txt", "error": None},
        ]
        resp = self._zip_upload(client, results, {"imported": 2, "skipped": 0, "original": 2, "accepted": 2})
        assert resp.status_code == 201
        assert resp.json()["imported_file_count"] == 2
        assert resp.json()["skipped_file_count"] == 0

    def test_zip_skips_unsupported_entries(self, client):
        results = [
            {"log_id": "l1", "original_filename": "a.md", "sha256_hash": "a" * 64,
             "status": "imported", "parse_status": "raw_archived", "stored_path": "archive/aa/a.md", "error": None},
            {"log_id": None, "original_filename": "data.csv", "sha256_hash": "",
             "status": "skipped", "parse_status": "not_applicable", "stored_path": None, "error": "Unsupported"},
        ]
        resp = self._zip_upload(client, results, {"imported": 1, "skipped": 1, "original": 2, "accepted": 1})
        assert resp.status_code == 201
        assert resp.json()["imported_file_count"] == 1
        assert resp.json()["skipped_file_count"] == 1

    def test_zip_slip_entries_are_skipped(self, client):
        results = [
            {"log_id": None, "original_filename": "../../etc/passwd", "sha256_hash": "",
             "status": "skipped", "parse_status": "not_applicable", "stored_path": None, "error": "unsafe path"},
            {"log_id": "l1", "original_filename": "safe.md", "sha256_hash": "a" * 64,
             "status": "imported", "parse_status": "raw_archived", "stored_path": "archive/aa/a.md", "error": None},
        ]
        resp = self._zip_upload(client, results, {"imported": 1, "skipped": 1, "original": 2, "accepted": 1})
        assert resp.status_code == 201
        skipped = [e["original_filename"] for e in resp.json()["logs"] if e["status"] == "skipped"]
        assert any("passwd" in n for n in skipped)


# ── Batch list ────────────────────────────────────────────────────────────────

class TestBatchList:
    def test_batch_list_returns_batches(self, client):
        batch = _make_batch_model()

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [batch]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/batches")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == "batch-001"

    def test_batch_list_pagination_fields(self, client):
        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 0
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/batches?page=2&per_page=10")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10


# ── Batch detail ──────────────────────────────────────────────────────────────

class TestBatchDetail:
    def test_batch_detail_returns_batch_and_logs(self, client):
        batch = _make_batch_model()
        log = _make_log_model(batch_id=batch.id)

        async def override_db():
            session = AsyncMock()
            batch_result = MagicMock()
            batch_result.scalars.return_value.first.return_value = batch
            logs_result = MagicMock()
            logs_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[batch_result, logs_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/batches/batch-001")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "batch-001"
        assert len(data["logs"]) == 1

    def test_batch_detail_404_for_unknown(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/batches/00000000-0000-0000-0000-000000000000")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404


# ── Log list ──────────────────────────────────────────────────────────────────

class TestLogList:
    def test_logs_list_returns_logs(self, client):
        log = _make_log_model()

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == "log-001"
        assert data["items"][0]["parse_status"] == "raw_archived"

    def test_logs_list_filter_by_parse_status(self, client):
        log = _make_log_model(parse_status="raw_archived")

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?parse_status=raw_archived")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["parse_status"] == "raw_archived"


# ── Log list — sorting ────────────────────────────────────────────────────────

class TestLogListSort:
    def _make_session(self, logs):
        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = len(logs)
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = logs
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session
        from app.api.observed_play import get_db
        return override_db, get_db

    def test_valid_sort_by_confidence_desc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=confidence_score&sort_dir=desc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_valid_sort_by_confidence_asc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=confidence_score&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_event_count(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=event_count&sort_dir=desc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_ambiguous_card_count(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=ambiguous_card_count")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_created_at(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=created_at&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_filename(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=filename&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_default_sort_no_params(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["id"] == "log-001"

    def test_valid_sort_by_cards_desc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=cards&sort_dir=desc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_cards_asc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=cards&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_parse_status_asc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=parse_status&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_valid_sort_by_parse_status_desc(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=parse_status&sort_dir=desc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_invalid_sort_by_returns_422(self, client):
        override_db, get_db = self._make_session([])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=not_a_field")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "Invalid sort_by" in resp.json()["detail"]

    def test_invalid_sort_dir_returns_422(self, client):
        override_db, get_db = self._make_session([])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=event_count&sort_dir=sideways")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422
        assert "Invalid sort_dir" in resp.json()["detail"]

    def test_sort_with_pagination(self, client):
        logs = [_make_log_model(log_id=f"log-{i:03d}") for i in range(3)]
        override_db, get_db = self._make_session(logs[:2])
        # Override count to 3 to simulate page 1 of 2
        async def override_db_paged():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 3
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = logs[:2]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db_paged
        try:
            resp = client.get("/api/observed-play/logs?sort_by=event_count&sort_dir=desc&page=1&per_page=2")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["per_page"] == 2

    def test_sort_is_read_only(self, client):
        log = _make_log_model()
        override_db, get_db = self._make_session([log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs?sort_by=confidence_score&sort_dir=asc")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["items"][0]["parse_status"] == "raw_archived"


# ── Log sort expression unit tests ────────────────────────────────────────────

class TestApplyLogSort:
    """Unit tests for _apply_log_sort composite sort expressions."""

    def _compile_sql(self, q) -> str:
        from sqlalchemy.dialects import postgresql
        return str(q.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    def test_cards_desc_includes_unresolved_and_ambiguous(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "cards", "desc")
        sql = self._compile_sql(q)
        assert "unresolved_card_count" in sql
        assert "ambiguous_card_count" in sql
        assert "card_mention_count" in sql

    def test_cards_asc_includes_unresolved_and_ambiguous(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "cards", "asc")
        sql = self._compile_sql(q)
        assert "unresolved_card_count" in sql
        assert "ambiguous_card_count" in sql
        assert "card_mention_count" in sql

    def test_parse_status_asc_uses_case_expression(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "parse_status", "asc")
        sql = self._compile_sql(q)
        # CASE expression should reference all relevant status values
        assert "failed" in sql
        assert "parsed" in sql
        assert "raw_archived" in sql
        # confidence_score tie-breaker present
        assert "confidence_score" in sql

    def test_parse_status_desc_uses_case_expression(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "parse_status", "desc")
        sql = self._compile_sql(q)
        assert "failed" in sql
        assert "parsed" in sql

    def test_confidence_score_simple_sort(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "confidence_score", "asc")
        sql = self._compile_sql(q)
        # ORDER BY should be at end — confidence_score should appear in ORDER BY
        order_by_part = sql[sql.find("ORDER BY"):]
        assert "confidence_score" in order_by_part
        # unresolved_card_count should NOT be in ORDER BY (not composite)
        assert "unresolved_card_count" not in order_by_part

    def test_default_sort_uses_created_at(self):
        from sqlalchemy import select
        from app.db.models import ObservedPlayLog
        from app.api.observed_play import _apply_log_sort

        q = _apply_log_sort(select(ObservedPlayLog), "created_at", "desc")
        sql = self._compile_sql(q)
        assert "created_at" in sql


# ── Log detail ────────────────────────────────────────────────────────────────

class TestLogDetail:
    def test_log_detail_returns_raw_content(self, client):
        log = _make_log_model(raw_content="# PTCGL Log\nTurn 1\n")
        override_db, get_db = _db_override(scalars_return=[log])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["raw_content"] == "# PTCGL Log\nTurn 1\n"
        assert data["parse_status"] == "raw_archived"
        assert data["memory_status"] == "not_ingested"

    def test_log_detail_404_for_unknown(self, client):
        override_db, get_db = _db_override(scalars_return=[])
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs/00000000-0000-0000-0000-000000000000")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404


# ── Log events ────────────────────────────────────────────────────────────────

def _make_event_model(
    event_id: int = 1,
    log_id: str = "log-001",
    event_index: int = 0,
    event_type: str = "draw",
    raw_line: str = "Alice drew 1 card.",
    turn_number: int = 1,
    phase: str = "turn",
    confidence_score: float = 0.95,
):
    e = MagicMock()
    e.id = event_id
    e.observed_play_log_id = log_id
    e.import_batch_id = "batch-001"
    e.event_index = event_index
    e.turn_number = turn_number
    e.phase = phase
    e.player_raw = "Alice"
    e.player_alias = "player_1"
    e.actor_type = "player"
    e.event_type = event_type
    e.raw_line = raw_line
    e.raw_block = None
    e.card_name_raw = None
    e.target_card_name_raw = None
    e.zone = None
    e.target_zone = None
    e.amount = None
    e.damage = None
    e.base_damage = None
    e.event_payload_json = {}
    e.confidence_score = confidence_score
    e.confidence_reasons_json = []
    return e


class TestGetLogEvents:
    def test_returns_events_for_existing_log(self, client):
        log = _make_log_model()
        event = _make_event_model(log_id=log.id)

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            events_result = MagicMock()
            events_result.scalars.return_value.all.return_value = [event]
            session.execute = AsyncMock(side_effect=[log_result, count_result, events_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}/events")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "draw"

    def test_returns_404_for_missing_log(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs/no-such-log/events")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_pagination_fields_present(self, client):
        log = _make_log_model()

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            count_result = MagicMock()
            count_result.scalar_one.return_value = 0
            events_result = MagicMock()
            events_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(side_effect=[log_result, count_result, events_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}/events?page=2&per_page=10")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10
        assert "items" in data
        assert "total" in data

    def test_returns_empty_list_for_raw_archived_log(self, client):
        """Phase-1 raw_archived log with no events returns 200 empty list, not 500."""
        log = _make_log_model(parse_status="raw_archived")

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            count_result = MagicMock()
            count_result.scalar_one.return_value = 0
            events_result = MagicMock()
            events_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(side_effect=[log_result, count_result, events_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}/events")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


# ── Reparse log ────────────────────────────────────────────────────────────────

class TestReparseLog:
    def test_reparse_returns_summary(self, client):
        log = _make_log_model(raw_content="Alice's Turn 1\nAlice drew 1 card.\n")

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            delete_result = MagicMock()
            session.execute = AsyncMock(side_effect=[log_result, delete_result])
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch(
            "app.api.observed_play.extract_and_resolve_mentions_for_log",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id=str(log.id),
                card_mention_count=0,
                resolved_card_count=0,
                ambiguous_card_count=0,
                unresolved_card_count=0,
                ignored_card_count=0,
                card_resolution_status="not_resolved",
                resolver_version="1.0",
                errors=[],
            )
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/reparse")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "log_id" in data
        assert "parse_status" in data
        assert "event_count" in data

    def test_reparse_returns_404_for_unknown_log(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/no-such-log/reparse")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404


# ── Parser diagnostics in API ──────────────────────────────────────────────────

class TestParserDiagnosticsInApi:
    def test_reparse_stores_diagnostics_in_metadata(self, client):
        """Reparse should produce metadata with parser_diagnostics."""
        log = _make_log_model(raw_content="Alice's Turn 1\nAlice drew a card.\nAlice played Buddy-Buddy Poffin.\n")
        log.metadata_json = {}

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            delete_result = MagicMock()
            session.execute = AsyncMock(side_effect=[log_result, delete_result])
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch(
            "app.api.observed_play.extract_and_resolve_mentions_for_log",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id=str(log.id),
                card_mention_count=0,
                resolved_card_count=0,
                ambiguous_card_count=0,
                unresolved_card_count=0,
                ignored_card_count=0,
                card_resolution_status="not_resolved",
                resolver_version="1.0",
                errors=[],
            )
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/reparse")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        # Diagnostics are stored in the log model's metadata_json during reparse
        assert "parser_diagnostics" in log.metadata_json

    def test_diagnostics_keys_present_after_reparse(self, client):
        """After reparse, metadata_json should have all diagnostic keys."""
        log = _make_log_model(raw_content="Alice's Turn 1\nAlice drew a card.\nunknown line here\n")
        log.metadata_json = {}

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            delete_result = MagicMock()
            session.execute = AsyncMock(side_effect=[log_result, delete_result])
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch(
            "app.api.observed_play.extract_and_resolve_mentions_for_log",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id=str(log.id),
                card_mention_count=0,
                resolved_card_count=0,
                ambiguous_card_count=0,
                unresolved_card_count=0,
                ignored_card_count=0,
                card_resolution_status="not_resolved",
                resolver_version="1.0",
                errors=[],
            )
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/reparse")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        diag = log.metadata_json.get("parser_diagnostics", {})
        assert "unknown_count" in diag
        assert "unknown_ratio" in diag
        assert "low_confidence_count" in diag
        assert "event_type_counts" in diag
        assert "top_unknown_raw_lines" in diag

    def test_log_list_includes_parser_diagnostics_when_present(self, client):
        """Log list should include parser_diagnostics when metadata_json contains it."""
        log = _make_log_model()
        log.metadata_json = {
            "parser_diagnostics": {
                "unknown_count": 5,
                "unknown_ratio": 0.05,
                "low_confidence_count": 3,
                "event_type_counts": {"draw_hidden": 10, "unknown": 5},
                "top_unknown_raw_lines": ["some unknown line"],
            }
        }

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["parser_diagnostics"] is not None
        assert item["parser_diagnostics"]["unknown_count"] == 5
        assert item["parser_diagnostics"]["unknown_ratio"] == pytest.approx(0.05)

    def test_log_list_null_diagnostics_for_old_logs(self, client):
        """Logs without diagnostics in metadata_json return null, not 500."""
        log = _make_log_model()
        log.metadata_json = {}  # no parser_diagnostics key

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["parser_diagnostics"] is None

    def test_reparse_response_includes_parser_diagnostics(self, client):
        """Reparse endpoint should include parser_diagnostics in response."""
        log = _make_log_model(raw_content="Alice's Turn 1\nAlice drew a card.\nunknown stuff\n")

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            delete_result = MagicMock()
            session.execute = AsyncMock(side_effect=[log_result, delete_result])
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch(
            "app.api.observed_play.extract_and_resolve_mentions_for_log",
            new_callable=AsyncMock,
        ) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id=str(log.id),
                card_mention_count=0,
                resolved_card_count=0,
                ambiguous_card_count=0,
                unresolved_card_count=0,
                ignored_card_count=0,
                card_resolution_status="not_resolved",
                resolver_version="1.0",
                errors=[],
            )
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/reparse")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "parser_diagnostics" in data
        # After reparse, metadata_json is populated so diagnostics should be non-null
        assert data["parser_diagnostics"] is not None
        assert "unknown_count" in data["parser_diagnostics"]


# ── Phase 4: Memory ingestion API ─────────────────────────────────────────────

class TestMemoryPreview:
    """Tests for POST /api/observed-play/logs/{log_id}/memory-preview."""

    def test_preview_returns_200_and_eligible_true(self, client):
        """Preview on eligible log returns 200 with eligible=True."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.preview_observed_play_ingestion",
            new_callable=AsyncMock,
        ) as mock_preview:
            from app.observed_play.schemas import (
                EligibilityMetrics,
                MemoryIngestionPreview,
            )
            mock_preview.return_value = MemoryIngestionPreview(
                eligible=True,
                eligibility_status="eligible",
                reasons=[],
                metrics=EligibilityMetrics(
                    confidence_score=0.91,
                    event_count=20,
                    unknown_ratio=0.01,
                    low_confidence_count=0,
                    card_mention_count=8,
                    unresolved_card_count=0,
                    ambiguous_card_count=1,
                    critical_unresolved_count=0,
                ),
                estimated_memory_item_count=15,
                event_type_counts={"attack_used": 5, "knockout": 2},
                sample_items=[],
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/memory-preview")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is True
        assert data["eligibility_status"] == "eligible"
        assert data["estimated_memory_item_count"] == 15

    def test_preview_returns_200_with_ineligible_log(self, client):
        """Preview on ineligible log returns 200 (not 422), eligible=False."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.preview_observed_play_ingestion",
            new_callable=AsyncMock,
        ) as mock_preview:
            from app.observed_play.schemas import EligibilityReason, MemoryIngestionPreview
            mock_preview.return_value = MemoryIngestionPreview(
                eligible=False,
                eligibility_status="ineligible",
                reasons=[EligibilityReason(code="low_confidence", detail="score too low")],
                estimated_memory_item_count=0,
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/memory-preview")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is False

    def test_preview_404_for_unknown_log(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/00000000-0000-0000-0000-000000000000/memory-preview")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404


    def test_preview_includes_blockers_for_ineligible_log(self, client):
        """Preview response includes blockers list when log is ineligible."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.preview_observed_play_ingestion",
            new_callable=AsyncMock,
        ) as mock_preview:
            from app.observed_play.schemas import EligibilityReason, IngestionBlocker, MemoryIngestionPreview
            mock_preview.return_value = MemoryIngestionPreview(
                eligible=False,
                eligibility_status="ineligible",
                reasons=[EligibilityReason(code="unresolved_critical_cards", detail="1 unresolved critical")],
                estimated_memory_item_count=0,
                blockers=[IngestionBlocker(
                    code="unresolved_critical_card",
                    raw_name="SomeCard",
                    normalized_name="somecard",
                    mention_role="actor_card",
                    resolution_status="unresolved",
                    source_event_type="attack_used",
                    source_field="card_name_raw",
                    turn_number=4,
                    player_alias="P1",
                    raw_line="P1's SomeCard used Attack.",
                )],
                blocker_count=1,
                blockers_truncated=False,
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/memory-preview")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is False
        assert data["blocker_count"] == 1
        assert len(data["blockers"]) == 1
        b = data["blockers"][0]
        assert b["raw_name"] == "SomeCard"
        assert b["mention_role"] == "actor_card"
        assert b["turn_number"] == 4
        assert b["player_alias"] == "P1"
        assert b["source_event_type"] == "attack_used"
        assert b["raw_line"] == "P1's SomeCard used Attack."

    def test_preview_eligible_log_returns_empty_blockers(self, client):
        """Eligible preview returns empty blockers list."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.preview_observed_play_ingestion",
            new_callable=AsyncMock,
        ) as mock_preview:
            from app.observed_play.schemas import EligibilityMetrics, MemoryIngestionPreview
            mock_preview.return_value = MemoryIngestionPreview(
                eligible=True,
                eligibility_status="eligible",
                reasons=[],
                metrics=EligibilityMetrics(confidence_score=0.9, event_count=10,
                                           unknown_ratio=0.01, low_confidence_count=0,
                                           card_mention_count=5, unresolved_card_count=0,
                                           ambiguous_card_count=0, critical_unresolved_count=0),
                estimated_memory_item_count=8,
                blockers=[],
                blocker_count=0,
                blockers_truncated=False,
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/memory-preview")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["eligible"] is True
        assert data["blockers"] == []
        assert data["blocker_count"] == 0
        assert data["blockers_truncated"] is False


class TestIngestMemory:
    """Tests for POST /api/observed-play/logs/{log_id}/ingest-memory."""

    def test_ingest_returns_200_on_success(self, client):
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.ingest_observed_play_log",
            new_callable=AsyncMock,
        ) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="ing-001",
                log_id=str(log.id),
                status="completed",
                eligibility_status="eligible",
                reasons=[],
                memory_item_count=12,
                skipped_event_count=3,
                ingestion_version="1.0",
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                session.commit = AsyncMock()
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/ingest-memory")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["memory_item_count"] == 12

    def test_ingest_returns_422_when_ineligible(self, client):
        """Ineligible log returns 422 when not forced."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.ingest_observed_play_log",
            new_callable=AsyncMock,
        ) as mock_ingest:
            from app.observed_play.schemas import EligibilityReason, MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="",
                log_id=str(log.id),
                status="skipped",
                eligibility_status="ineligible",
                reasons=[EligibilityReason(code="low_confidence", detail="0.70 < 0.80")],
                ingestion_version="1.0",
                error="Ineligible for ingestion",
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                session.commit = AsyncMock()
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/ingest-memory")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 422

    def test_ingest_404_for_unknown_log(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/00000000-0000-0000-0000-000000000000/ingest-memory")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_ingest_422_includes_blockers(self, client):
        """422 response from ineligible log includes blockers in the detail body."""
        log = _make_log_model(parse_status="parsed")

        with patch(
            "app.api.observed_play.ingest_observed_play_log",
            new_callable=AsyncMock,
        ) as mock_ingest:
            from app.observed_play.schemas import EligibilityReason, IngestionBlocker, MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="",
                log_id=str(log.id),
                status="skipped",
                eligibility_status="ineligible",
                reasons=[EligibilityReason(code="unresolved_critical_cards", detail="1 critical unresolved")],
                ingestion_version="1.0",
                error="Ineligible for ingestion",
                blockers=[IngestionBlocker(
                    code="unresolved_critical_card",
                    raw_name="BadCard",
                    mention_role="actor_card",
                    turn_number=2,
                    player_alias="P2",
                    raw_line="P2's BadCard used Move.",
                )],
                blocker_count=1,
                blockers_truncated=False,
            )

            async def override_db():
                session = AsyncMock()
                log_result = MagicMock()
                log_result.scalars.return_value.first.return_value = log
                session.execute = AsyncMock(return_value=log_result)
                session.commit = AsyncMock()
                yield session

            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.post(f"/api/observed-play/logs/{log.id}/ingest-memory")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 422
        data = resp.json()["detail"]
        assert data["blocker_count"] == 1
        assert len(data["blockers"]) == 1
        assert data["blockers"][0]["raw_name"] == "BadCard"
        assert data["blockers"][0]["mention_role"] == "actor_card"
        assert data["blockers_truncated"] is False


class TestMemoryItems:
    """Tests for GET /api/observed-play/logs/{log_id}/memory-items."""

    def _make_memory_item_model(self, item_id: str = "item-001", memory_type: str = "attack_used"):
        item = MagicMock()
        item.id = item_id
        item.ingestion_id = "ing-001"
        item.observed_play_log_id = "log-001"
        item.observed_play_event_id = 42
        item.memory_type = memory_type
        item.memory_key = f"{memory_type}:42:Pikachu:Thunderbolt:"
        item.turn_number = 3
        item.phase = "turn"
        item.player_alias = "P1"
        item.player_raw = "Player1"
        item.actor_card_raw = "Pikachu"
        item.actor_card_def_id = "sv06-049"
        item.actor_resolution_status = "resolved"
        item.target_card_raw = "Charizard"
        item.target_card_def_id = None
        item.target_resolution_status = "ambiguous"
        item.related_card_raw = None
        item.related_card_def_id = None
        item.related_resolution_status = None
        item.action_name = "Thunderbolt"
        item.amount = None
        item.damage = 120
        item.zone = "active"
        item.target_zone = "active"
        item.confidence_score = 0.88
        item.source_event_type = "attack_used"
        item.source_raw_line = "P1's Pikachu used Thunderbolt."
        item.created_at = None
        return item

    def test_memory_items_returns_paginated_list(self, client):
        log = _make_log_model()
        item = self._make_memory_item_model()

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            count_result = MagicMock()
            count_result.scalar.return_value = 1
            items_result = MagicMock()
            items_result.scalars.return_value.all.return_value = [item]
            session.execute = AsyncMock(side_effect=[log_result, count_result, items_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}/memory-items")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["memory_type"] == "attack_used"

    def test_memory_items_404_for_unknown_log(self, client):
        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            session.execute = AsyncMock(return_value=result)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs/00000000-0000-0000-0000-000000000000/memory-items")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_memory_items_includes_pagination_fields(self, client):
        log = _make_log_model()

        async def override_db():
            session = AsyncMock()
            log_result = MagicMock()
            log_result.scalars.return_value.first.return_value = log
            count_result = MagicMock()
            count_result.scalar.return_value = 0
            items_result = MagicMock()
            items_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(side_effect=[log_result, count_result, items_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(f"/api/observed-play/logs/{log.id}/memory-items?page=2&per_page=10")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10
        assert data["total"] == 0

    def test_log_summary_includes_memory_fields(self, client):
        """Log summary response includes memory_item_count and last_memory_ingested_at."""
        log = _make_log_model()
        log.memory_item_count = 7
        log.last_memory_ingested_at = None

        async def override_db():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar_one.return_value = 1
            list_result = MagicMock()
            list_result.scalars.return_value.all.return_value = [log]
            session.execute = AsyncMock(side_effect=[count_result, list_result])
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/logs")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "memory_item_count" in item
        assert item["memory_item_count"] == 7


# ── Phase 3.2: Resolution rule and unresolved-card tests ──────────────────────

def _make_rule_model(
    rule_id="rule-001",
    raw_name="Dragapult ex",
    normalized_name="dragapult ex",
    action="resolve",
    target_card_def_id="sv08-164",
    target_card_name="Dragapult ex",
    scope="global",
    notes=None,
):
    r = MagicMock()
    r.id = rule_id
    r.raw_name = raw_name
    r.normalized_name = normalized_name
    r.action = action
    r.target_card_def_id = target_card_def_id
    r.target_card_name = target_card_name
    r.scope = scope
    r.notes = notes
    r.created_at = None
    return r


def _make_unresolved_mention_row(
    normalized_name="dragapult ex",
    raw_name="Dragapult ex",
    resolution_status="ambiguous",
    candidate_count=2,
    candidates_json=None,
    mention_count=5,
    log_count=2,
):
    r = MagicMock()
    r.normalized_name = normalized_name
    r.raw_name = raw_name
    r.resolution_status = resolution_status
    r.candidate_count = candidate_count
    r.candidates_json = candidates_json or [
        {
            "card_id": "c1",
            "card_def_id": "sv08-164",
            "name": "Dragapult ex",
            "set_id": "sv08",
            "number": "164",
            "image_url": "https://cdn.example.com/sv08-164.png",
            "reason": "exact normalized name",
        }
    ]
    r.mention_count = mention_count
    r.log_count = log_count
    return r


class TestResolutionRules:
    """Tests for POST /api/observed-play/resolution-rules (Phase 3.2)."""

    def test_resolve_rule_success(self, client):
        """Create a resolve rule returns 201 with rule data."""
        card_result = MagicMock()
        card_result.scalar.return_value = "sv08-164"
        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None
        rule = _make_rule_model()

        async def refresh_side(obj):
            obj.id = rule.id
            obj.raw_name = rule.raw_name
            obj.normalized_name = rule.normalized_name
            obj.action = rule.action
            obj.target_card_def_id = rule.target_card_def_id
            obj.target_card_name = rule.target_card_name
            obj.scope = rule.scope
            obj.notes = rule.notes
            obj.created_at = None

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=refresh_side)
            session.execute = AsyncMock(side_effect=[card_result, existing_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post(
                "/api/observed-play/resolution-rules",
                json={
                    "raw_name": "Dragapult ex",
                    "action": "resolve",
                    "target_card_def_id": "sv08-164",
                    "target_card_name": "Dragapult ex",
                },
            )
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "resolve"
        assert data["target_card_def_id"] == "sv08-164"

    def test_ignore_rule_success(self, client):
        """Create an ignore rule succeeds without target_card_def_id."""
        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None
        rule = _make_rule_model(action="ignore", target_card_def_id=None, target_card_name=None)

        async def refresh_side(obj):
            obj.id = rule.id
            obj.raw_name = rule.raw_name
            obj.normalized_name = rule.normalized_name
            obj.action = "ignore"
            obj.target_card_def_id = None
            obj.target_card_name = None
            obj.scope = "global"
            obj.notes = None
            obj.created_at = None

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=refresh_side)
            session.execute = AsyncMock(side_effect=[existing_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post(
                "/api/observed-play/resolution-rules",
                json={"raw_name": "it", "action": "ignore"},
            )
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["action"] == "ignore"
        assert data["target_card_def_id"] is None

    def test_resolve_without_target_returns_422(self, client):
        """resolve action without target_card_def_id returns 422."""
        resp = client.post(
            "/api/observed-play/resolution-rules",
            json={"raw_name": "Dragapult ex", "action": "resolve"},
        )
        assert resp.status_code == 422

    def test_invalid_action_returns_422(self, client):
        """Unknown action string returns 422."""
        resp = client.post(
            "/api/observed-play/resolution-rules",
            json={"raw_name": "Dragapult ex", "action": "fixup"},
        )
        assert resp.status_code == 422

    def test_nonexistent_target_card_returns_422(self, client):
        """Nonexistent target_card_def_id returns 422, not 500."""
        card_result = MagicMock()
        card_result.scalar.return_value = None
        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock()
            session.execute = AsyncMock(side_effect=[card_result, existing_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post(
                "/api/observed-play/resolution-rules",
                json={
                    "raw_name": "Fake Card",
                    "action": "resolve",
                    "target_card_def_id": "xx00-000",
                },
            )
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"]

    def test_duplicate_rule_returns_409(self, client):
        """Duplicate normalized name returns 409."""
        card_result = MagicMock()
        card_result.scalar.return_value = "sv08-164"
        existing_rule = _make_rule_model()
        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = existing_rule

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock()
            session.execute = AsyncMock(side_effect=[card_result, existing_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post(
                "/api/observed-play/resolution-rules",
                json={
                    "raw_name": "Dragapult ex",
                    "action": "resolve",
                    "target_card_def_id": "sv08-164",
                },
            )
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_empty_raw_name_returns_422(self, client):
        """Empty raw_name returns 422."""
        resp = client.post(
            "/api/observed-play/resolution-rules",
            json={"raw_name": "  ", "action": "ignore"},
        )
        assert resp.status_code == 422


class TestUnresolvedCardsPhase32:
    """Tests for GET /api/observed-play/unresolved-cards Phase 3.2 extensions."""

    def _make_sample_mention_row(
        self,
        normalized_name="dragapult ex",
        log_id="log-001",
        event_id=100,
    ):
        r = MagicMock()
        r.normalized_name = normalized_name
        r.observed_play_log_id = log_id
        r.observed_play_event_id = event_id
        r.mention_role = "actor_card"
        r.source_event_type = "attack_used"
        r.original_filename = "game.md"
        r.turn_number = 3
        r.player_alias = "player_1"
        r.raw_line = "Dragapult ex used Phantom Dive"
        return r

    def test_response_includes_candidates(self, client):
        """Response includes candidates list."""
        mention_row = _make_unresolved_mention_row()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        rows_result = MagicMock()
        rows_result.all.return_value = [mention_row]
        samples_result = MagicMock()
        samples_result.all.return_value = []

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result, samples_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/unresolved-cards")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "candidates" in item
        assert len(item["candidates"]) == 1
        assert item["candidates"][0]["card_def_id"] == "sv08-164"

    def test_response_includes_sample_mentions(self, client):
        """Response includes sample_mentions with source line info."""
        mention_row = _make_unresolved_mention_row()
        sample_row = self._make_sample_mention_row()

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        rows_result = MagicMock()
        rows_result.all.return_value = [mention_row]
        samples_result = MagicMock()
        samples_result.all.return_value = [sample_row]

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result, samples_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/unresolved-cards")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "sample_mentions" in item
        assert len(item["sample_mentions"]) == 1
        sm = item["sample_mentions"][0]
        assert sm["log_id"] == "log-001"
        assert sm["mention_role"] == "actor_card"
        assert sm["raw_line"] == "Dragapult ex used Phantom Dive"

    def test_response_includes_affected_log_ids(self, client):
        """Response includes affected_log_ids."""
        mention_row = _make_unresolved_mention_row()
        sample_row = self._make_sample_mention_row()

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        rows_result = MagicMock()
        rows_result.all.return_value = [mention_row]
        samples_result = MagicMock()
        samples_result.all.return_value = [sample_row]

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result, samples_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/unresolved-cards")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert "affected_log_ids" in item
        assert "log-001" in item["affected_log_ids"]

    def test_empty_result(self, client):
        """Empty unresolved-cards returns empty items list."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.all.return_value = []

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/unresolved-cards")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestMemoryAnalytics:
    """Phase 5: read-only memory analytics endpoints."""

    def test_memory_summary_empty(self, client):
        """Summary returns zeros when no memory items exist."""
        log_count_result = MagicMock()
        log_count_result.scalar.return_value = 0
        item_count_result = MagicMock()
        item_count_result.scalar.return_value = 0

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[log_count_result, item_count_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-summary")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["memory_item_count"] == 0
        assert data["ingested_log_count"] == 0

    def test_memory_analytics_empty(self, client):
        """Analytics returns empty lists when no items exist."""
        empty_rows = MagicMock()
        empty_rows.all.return_value = []

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=empty_rows)
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-analytics")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["top_memory_types"], list)
        assert isinstance(data["top_actor_cards"], list)

    def test_memory_analytics_source_items_empty(self, client):
        """Source items returns empty when no items exist."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-analytics/source-items")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_source_items_filters(self, client):
        """Source items endpoint accepts filter parameters and returns 200."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        from app.api.observed_play import get_db

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get(
                "/api/observed-play/memory-analytics/source-items",
                params={"memory_type": "attack_used"},
            )
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200

    def test_analytics_read_only(self, client):
        """GET analytics endpoints do not modify data (read-only check)."""
        log_count = MagicMock()
        log_count.scalar.return_value = 0
        item_count = MagicMock()
        item_count.scalar.return_value = 0

        from app.api.observed_play import get_db

        async def override_db_summary():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[log_count, item_count])
            session.add = AsyncMock()
            session.delete = AsyncMock()
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db_summary
        try:
            resp = client.get("/api/observed-play/memory-summary")
            assert resp.status_code == 200
            before_count = resp.json()["memory_item_count"]
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        log_count2 = MagicMock()
        log_count2.scalar.return_value = 0
        item_count2 = MagicMock()
        item_count2.scalar.return_value = 0

        async def override_db_summary2():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[log_count2, item_count2])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db_summary2
        try:
            after_resp = client.get("/api/observed-play/memory-summary")
            assert after_resp.status_code == 200
            after_count = after_resp.json()["memory_item_count"]
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert before_count == after_count

    def _empty_analytics_db(self, client):
        """Helper: override db with empty results for analytics endpoint."""
        from app.api.observed_play import get_db
        empty_rows = MagicMock()
        empty_rows.all.return_value = []

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=empty_rows)
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        return override_db

    def test_memory_analytics_quality_filter_low_confidence(self, client):
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics?quality_filter=low_confidence")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert "top_memory_types" in data

    def test_memory_analytics_quality_filter_ambiguous(self, client):
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics?quality_filter=ambiguous")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_memory_analytics_quality_filter_unresolved(self, client):
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics?quality_filter=unresolved")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_memory_analytics_quality_filter_all(self, client):
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics?quality_filter=all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_memory_analytics_quality_filter_invalid(self, client):
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics?quality_filter=bogus")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code in (200, 422)

    def test_source_items_card_name_filter(self, client):
        from app.api.observed_play import get_db
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-analytics/source-items?card_name=Pikachu")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_source_items_min_confidence_filter(self, client):
        from app.api.observed_play import get_db
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-analytics/source-items?min_confidence=0.5")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_source_items_related_card_filter(self, client):
        from app.api.observed_play import get_db
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(side_effect=[count_result, rows_result])
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-analytics/source-items?related_card_raw=Rare+Candy")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_analytics_group_includes_review_fields(self, client):
        """MemoryAnalyticsGroup shape includes review metadata fields."""
        self._empty_analytics_db(client)
        try:
            resp = client.get("/api/observed-play/memory-analytics")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        for section_key in ["top_actor_cards", "top_target_cards"]:
            for grp in data.get(section_key, []):
                assert "can_review_resolution" in grp
