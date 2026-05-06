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
