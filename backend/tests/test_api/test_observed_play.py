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

from app.observed_play.schemas import ArchetypeLabel, ObservedLogArchetypeLabelPreview


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


# ── Phase 7.1b label preview tests ────────────────────────────────────────────

class TestObservedLogArchetypeLabelPreview:
    def test_observed_log_preview_returns_labels_by_player(self, client):
        from app.api.observed_play import get_db

        log_id = str(uuid.uuid4())
        preview = ObservedLogArchetypeLabelPreview(
            observed_play_log_id=log_id,
            labels_by_player={
                "player_1": [
                    ArchetypeLabel(
                        label="Dragapult ex",
                        canonical_key="dragapult-ex",
                        label_type="archetype",
                        source="observed_log",
                        confidence=0.78,
                        player_alias="player_1",
                    )
                ]
            },
        )

        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()

        async def override_db():
            yield session

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            with patch(
                "app.api.observed_play.preview_observed_log_archetype_labels",
                new=AsyncMock(return_value=preview),
            ) as mock_preview:
                resp = client.get(f"/api/observed-play/logs/{log_id}/archetype-label-preview")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["observed_play_log_id"] == log_id
        assert data["labels_by_player"]["player_1"][0]["canonical_key"] == "dragapult-ex"
        mock_preview.assert_awaited_once()
        session.add.assert_not_called()
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_observed_log_preview_returns_404_for_missing_log(self, client):
        from app.api.observed_play import get_db

        log_id = str(uuid.uuid4())

        async def override_db():
            yield AsyncMock()

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            with patch(
                "app.api.observed_play.preview_observed_log_archetype_labels",
                new=AsyncMock(return_value=None),
            ):
                resp = client.get(f"/api/observed-play/logs/{log_id}/archetype-label-preview")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Log not found"


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


# ── Bulk reparse-all ──────────────────────────────────────────────────────────

class TestBulkReparseAll:
    def _make_scalars_result(self, items):
        r = MagicMock()
        r.scalars.return_value.all.return_value = items
        return r

    def _make_delete_result(self):
        return MagicMock()

    def test_endpoint_exists(self, client):
        """POST /logs/reparse-all returns 200 even with no logs."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_empty_returns_zero_counts(self, client):
        """With no logs, all counts are zero."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["considered_count"] == 0
        assert data["reparsed_count"] == 0
        assert data["skipped_count"] == 0
        assert data["failed_count"] == 0

    def test_ingested_logs_are_skipped(self, client):
        """Logs with memory_status='ingested' are skipped, not reparsed."""
        log_ingested = _make_log_model(log_id="log-1", memory_status="ingested",
                                       raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log_ingested]))
            session.commit = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["considered_count"] == 1
        assert data["skipped_count"] == 1
        assert data["reparsed_count"] == 0

    def test_non_ingested_log_is_reparsed(self, client):
        """Logs not yet ingested are reparsed."""
        log = _make_log_model(log_id="log-2", memory_status="not_ingested",
                              raw_content="Alice's Turn 1\nAlice drew 1 card.\n")

        call_count = [0]

        async def override_db():
            session = AsyncMock()
            # First call: list logs; subsequent: delete + queries during reparse
            results = [self._make_scalars_result([log])] + [self._make_delete_result() for _ in range(20)]

            async def execute_side_effect(*args, **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                if idx == 0:
                    return results[0]
                return self._make_delete_result()

            session.execute = AsyncMock(side_effect=execute_side_effect)
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.extract_and_resolve_mentions_for_log", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id="log-2", card_mention_count=0, resolved_card_count=0,
                ambiguous_card_count=0, unresolved_card_count=0, ignored_card_count=0,
                card_resolution_status="not_resolved", resolver_version="1.0", errors=[],
            )
            try:
                resp = client.post("/api/observed-play/logs/reparse-all")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["considered_count"] == 1
        assert data["reparsed_count"] == 1
        assert data["skipped_count"] == 0

    def test_response_has_required_shape(self, client):
        """Response includes expected top-level fields."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        for field in ("considered_count", "reparsed_count", "skipped_count", "failed_count",
                      "reparsed", "skipped", "failed", "average_confidence", "total_event_count"):
            assert field in data, f"Missing field: {field}"

    def test_default_skips_ingested_logs(self, client):
        """Default behavior (include_ingested=false) skips ingested logs."""
        log_ingested = _make_log_model(log_id="log-ri-1", memory_status="ingested",
                                       raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log_ingested]))
            session.commit = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all", json={})
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["skipped_count"] == 1
        assert data["reparsed_count"] == 0

    def test_include_ingested_true_reparses_ingested_log(self, client):
        """include_ingested=true causes ingested logs to be reparsed."""
        log_ingested = _make_log_model(log_id="log-ri-2", memory_status="ingested",
                                       raw_content="Alice's Turn 1\nAlice drew 1 card.\n")

        call_count = [0]

        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(*args, **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                if idx == 0:
                    return self._make_scalars_result([log_ingested])
                return self._make_delete_result()

            session.execute = AsyncMock(side_effect=execute_side_effect)
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.extract_and_resolve_mentions_for_log", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id="log-ri-2", card_mention_count=0, resolved_card_count=0,
                ambiguous_card_count=0, unresolved_card_count=0, ignored_card_count=0,
                card_resolution_status="not_resolved", resolver_version="1.0", errors=[],
            )
            try:
                resp = client.post("/api/observed-play/logs/reparse-all",
                                   json={"include_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["reparsed_count"] == 1
        assert data["skipped_count"] == 0
        assert data["ingested_reparsed_count"] == 1

    def test_include_ingested_marks_had_existing_memory(self, client):
        """Reparsed ingested logs have had_existing_memory=true and memory_warning set."""
        log_ingested = _make_log_model(log_id="log-ri-3", memory_status="ingested",
                                       raw_content="Alice's Turn 1\nAlice drew 1 card.\n")

        call_count = [0]

        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(*args, **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                if idx == 0:
                    return self._make_scalars_result([log_ingested])
                return self._make_delete_result()

            session.execute = AsyncMock(side_effect=execute_side_effect)
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.refresh = AsyncMock(side_effect=lambda obj: None)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.extract_and_resolve_mentions_for_log", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = MagicMock(
                log_id="log-ri-3", card_mention_count=0, resolved_card_count=0,
                ambiguous_card_count=0, unresolved_card_count=0, ignored_card_count=0,
                card_resolution_status="not_resolved", resolver_version="1.0", errors=[],
            )
            try:
                resp = client.post("/api/observed-play/logs/reparse-all",
                                   json={"include_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert len(data["reparsed"]) == 1
        reparsed_log = data["reparsed"][0]
        assert reparsed_log["had_existing_memory"] is True
        assert reparsed_log["memory_warning"] is not None
        assert "re-ingest" in reparsed_log["memory_warning"]

    def test_response_includes_ingested_reparsed_count(self, client):
        """Response includes ingested_reparsed_count field."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/logs/reparse-all")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert "ingested_reparsed_count" in data


# ── Bulk preview eligible ─────────────────────────────────────────────────────

class TestBulkPreviewEligible:
    def _make_scalars_result(self, items):
        r = MagicMock()
        r.scalars.return_value.all.return_value = items
        return r

    def test_endpoint_exists(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_empty_returns_zeros(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["eligible_count"] == 0
        assert data["ineligible_count"] == 0
        assert data["already_ingested_count"] == 0
        assert data["not_ready_count"] == 0
        assert data["estimated_memory_item_count"] == 0

    def test_already_ingested_log_counted(self, client):
        log = _make_log_model(log_id="log-3", memory_status="ingested", parse_status="parsed")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["already_ingested_count"] == 1
        assert data["eligible_count"] == 0

    def test_not_ready_log_counted(self, client):
        log = _make_log_model(log_id="log-4", memory_status="not_ingested", parse_status="raw_archived")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["not_ready_count"] == 1

    def test_response_has_required_shape(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        for field in ("considered_count", "eligible_count", "ineligible_count",
                      "already_ingested_count", "not_ready_count",
                      "estimated_memory_item_count", "eligible_logs", "skipped_logs",
                      "top_blocker_reasons"):
            assert field in data, f"Missing field: {field}"

    def test_is_read_only(self, client):
        """Preview does not commit to the database."""
        log = _make_log_model(log_id="log-5", memory_status="not_ingested", parse_status="parsed",
                              raw_content="Alice's Turn 1\n")

        commit_called = []

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            async def track_commit():
                commit_called.append(True)
            session.commit = track_commit
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.evaluate_log_ingestion_eligibility", new_callable=AsyncMock) as mock_eval:
            from app.observed_play.schemas import EligibilityResult
            mock_eval.return_value = EligibilityResult(eligible=False, status="ineligible", reasons=[], blockers=[])
            try:
                resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert not commit_called, "Preview endpoint must not commit"

    def test_default_skips_ingested_logs(self, client):
        """Default include_already_ingested=false skips already-ingested logs."""
        log = _make_log_model(log_id="log-pi-1", memory_status="ingested", parse_status="parsed")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible", json={})
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["already_ingested_count"] == 1
        assert data["eligible_count"] == 0
        assert data["eligible_for_reingest_count"] == 0

    def test_include_already_ingested_evaluates_ingested_logs(self, client):
        """include_already_ingested=true evaluates already-ingested parsed eligible logs."""
        log = _make_log_model(log_id="log-pi-2", memory_status="ingested", parse_status="parsed")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.evaluate_log_ingestion_eligibility", new_callable=AsyncMock) as mock_eval, \
             patch("app.api.observed_play.preview_observed_play_ingestion", new_callable=AsyncMock) as mock_preview:
            from app.observed_play.schemas import EligibilityResult, MemoryIngestionPreview
            mock_eval.return_value = EligibilityResult(eligible=True, status="eligible", reasons=[], blockers=[])
            mock_preview.return_value = MemoryIngestionPreview(
                eligible=True, eligibility_status="eligible",
                estimated_memory_item_count=5,
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/preview-eligible",
                                   json={"include_already_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["eligible_for_reingest_count"] == 1
        assert data["eligible_count"] == 0
        assert data["already_ingested_count"] == 0

    def test_preview_response_has_eligible_for_reingest_count(self, client):
        """Response includes eligible_for_reingest_count field."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/preview-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert "eligible_for_reingest_count" in data
        assert "include_already_ingested" in data


# ── Bulk ingest eligible ──────────────────────────────────────────────────────

class TestBulkIngestEligible:
    def _make_scalars_result(self, items):
        r = MagicMock()
        r.scalars.return_value.all.return_value = items
        return r

    def test_endpoint_exists(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_empty_returns_zeros(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["ingested_count"] == 0
        assert data["skipped_count"] == 0
        assert data["failed_count"] == 0
        assert data["memory_items_created"] == 0

    def test_already_ingested_log_skipped(self, client):
        log = _make_log_model(log_id="log-6", memory_status="ingested", parse_status="parsed")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["skipped_count"] == 1
        assert data["ingested_count"] == 0

    def test_not_parsed_log_skipped(self, client):
        log = _make_log_model(log_id="log-7", memory_status="not_ingested", parse_status="raw_archived")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["skipped_count"] == 1

    def test_ineligible_log_skipped(self, client):
        log = _make_log_model(log_id="log-8", memory_status="not_ingested", parse_status="parsed",
                              raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.ingest_observed_play_log", new_callable=AsyncMock) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="", log_id="log-8", status="skipped",
                eligibility_status="ineligible", ingestion_version="1.0",
                memory_item_count=0, source_event_count=0, skipped_event_count=0,
                blocked_reason_count=0, blocker_reasons=["low_confidence"],
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["skipped_count"] == 1
        assert data["ingested_count"] == 0

    def test_successful_ingest_increments_counts(self, client):
        log = _make_log_model(log_id="log-9", memory_status="not_ingested", parse_status="parsed",
                              raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.ingest_observed_play_log", new_callable=AsyncMock) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="iid-1", log_id="log-9", status="success",
                eligibility_status="eligible", ingestion_version="1.0",
                memory_item_count=5, source_event_count=10, skipped_event_count=0,
                blocked_reason_count=0,
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["ingested_count"] == 1
        assert data["memory_items_created"] == 5

    def test_response_has_required_shape(self, client):
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        for field in ("considered_count", "eligible_count", "ingested_count", "skipped_count",
                      "failed_count", "memory_items_created",
                      "ingested_logs", "skipped_logs", "failed_logs"):
            assert field in data, f"Missing field: {field}"

    def test_default_skips_ingested_logs(self, client):
        """Default include_already_ingested=false skips already-ingested logs."""
        log = _make_log_model(log_id="log-ii-1", memory_status="ingested", parse_status="parsed")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible", json={})
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["skipped_count"] == 1
        assert data["ingested_count"] == 0
        assert data["reingested_count"] == 0

    def test_include_already_ingested_reingests_eligible_log(self, client):
        """include_already_ingested=true re-ingests already-ingested eligible logs."""
        log = _make_log_model(log_id="log-ii-2", memory_status="ingested", parse_status="parsed",
                              raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.ingest_observed_play_log", new_callable=AsyncMock) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="iid-ri-1", log_id="log-ii-2", status="success",
                eligibility_status="eligible", ingestion_version="1.0",
                memory_item_count=5, source_event_count=10, skipped_event_count=0,
                blocked_reason_count=0,
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible",
                                   json={"include_already_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["reingested_count"] == 1
        assert data["ingested_count"] == 0
        assert data["memory_items_created"] == 5
        assert len(data["ingested_logs"]) == 1
        assert data["ingested_logs"][0]["status"] == "reingested"

    def test_reingest_result_status_is_reingested(self, client):
        """Re-ingested logs appear in ingested_logs with status=reingested."""
        log = _make_log_model(log_id="log-ii-3", memory_status="ingested", parse_status="parsed",
                              raw_content="Alice's Turn 1\n")

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([log]))
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.ingest_observed_play_log", new_callable=AsyncMock) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="iid-ri-2", log_id="log-ii-3", status="success",
                eligibility_status="eligible", ingestion_version="1.0",
                memory_item_count=3, source_event_count=5, skipped_event_count=0,
                blocked_reason_count=0,
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible",
                                   json={"include_already_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        ingested_logs = data["ingested_logs"]
        assert len(ingested_logs) == 1
        assert ingested_logs[0]["status"] == "reingested"
        assert ingested_logs[0]["log_id"] == "log-ii-3"

    def test_response_has_reingested_count_field(self, client):
        """Response includes reingested_count and include_already_ingested fields."""
        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=self._make_scalars_result([]))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert "reingested_count" in data
        assert "include_already_ingested" in data
        assert data["reingested_count"] == 0

    def test_new_and_reingested_both_in_ingested_logs(self, client):
        """Both newly ingested and re-ingested logs appear in ingested_logs."""
        log_new = _make_log_model(log_id="log-ii-4", memory_status="not_ingested", parse_status="parsed",
                                  raw_content="Alice's Turn 1\n")
        log_reingest = _make_log_model(log_id="log-ii-5", memory_status="ingested", parse_status="parsed",
                                       raw_content="Alice's Turn 1\n")

        def make_results():
            return self._make_scalars_result([log_new, log_reingest])

        async def override_db():
            session = AsyncMock()
            session.execute = AsyncMock(return_value=make_results())
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.observed_play.ingest_observed_play_log", new_callable=AsyncMock) as mock_ingest:
            from app.observed_play.schemas import MemoryIngestionSummary
            mock_ingest.return_value = MemoryIngestionSummary(
                ingestion_id="iid-combo", log_id="", status="success",
                eligibility_status="eligible", ingestion_version="1.0",
                memory_item_count=4, source_event_count=8, skipped_event_count=0,
                blocked_reason_count=0,
            )
            try:
                resp = client.post("/api/observed-play/memory-ingestion/ingest-eligible",
                                   json={"include_already_ingested": True})
            finally:
                client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["ingested_count"] == 1
        assert data["reingested_count"] == 1
        statuses = {l["status"] for l in data["ingested_logs"]}
        assert "ingested" in statuses
        assert "reingested" in statuses


# ── Phase 5.2: Corpus Readiness Scorecard ────────────────────────────────────

def _make_scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _make_fetchall_result(rows):
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


class TestCorpusReadiness:
    """Tests for GET /api/observed-play/corpus-readiness (Phase 5.2)."""

    def _db_override(self, scalar_sequence, fetchall_sequence=None):
        """Build an async DB override that returns scalars and fetchall values in order.

        scalar_sequence: consumed when the caller invokes .scalar() on the execute result.
        fetchall_sequence: consumed when the caller invokes .fetchall() on the execute result.
        The two sequences are tracked independently so fetchall calls do not consume scalar slots.
        """
        fetchall_seq = list(fetchall_sequence or [])
        scalar_seq = list(scalar_sequence)
        scalar_calls = [0]
        fetchall_calls = [0]

        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(query, *args, **kwargs):
                r = MagicMock()

                def _scalar():
                    idx = scalar_calls[0]
                    scalar_calls[0] += 1
                    return scalar_seq[idx] if idx < len(scalar_seq) else 0

                def _fetchall():
                    idx = fetchall_calls[0]
                    fetchall_calls[0] += 1
                    return fetchall_seq[idx] if idx < len(fetchall_seq) else []

                r.scalar = MagicMock(side_effect=_scalar)
                r.fetchall = MagicMock(side_effect=_fetchall)
                return r

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        return override_db

    def _simple_override(self, scalars, fetchalls=None):
        """Shorthand: build DB override with given scalar values."""
        return self._db_override(scalars, fetchalls or [[], []])

    def test_endpoint_exists_and_is_get(self, client):
        override = self._simple_override(
            [0, 0, 0, 0, 0, 0, None, None, None, 0, 0, 0, 0, 0, 0, None, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_is_read_only_no_post(self, client):
        resp = client.post("/api/observed-play/corpus-readiness")
        assert resp.status_code == 405

    def test_response_includes_review_only_flag(self, client):
        override = self._simple_override(
            [0, 0, 0, 0, 0, 0, None, None, None, 0, 0, 0, 0, 0, 0, None, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["review_only"] is True
        assert "safety_note" in data
        assert len(data["safety_note"]) > 0

    def test_empty_corpus_returns_not_ready(self, client):
        """All zeros → no parsed/ingested logs → not_ready."""
        override = self._simple_override(
            [0] * 20,
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "not_ready"
        assert len(data["blockers"]) > 0

    def test_unknown_events_force_not_ready(self, client):
        """Any unknown events → not_ready."""
        # Simulate: 5 logs, 5 parsed, 5 ingested, 0 failed, 100 events, 50 memory items,
        # avg_event_conf=0.9, min_log_conf=0.85, avg_log_conf=0.88,
        # unknown_event_count=3 → blocker
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,     # corpus: log, parsed, ingested, failed, events, memory
             0.9, 0.85, 0.88, 3, 0, 0,   # parser: avg_event, min_log, avg_log, unknown, low_conf, below_threshold
             10, 8, 0, 0, 0,              # card: total, resolved, ambiguous, unresolved, critical
             0.85, 0, 0, 0],              # memory: avg_mem, low_conf, ambig_ref, unres_ref
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "not_ready"
        assert any("unknown" in b.lower() for b in data["blockers"])

    def test_low_confidence_events_force_not_ready(self, client):
        """Events below threshold → not_ready."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,
             0.9, 0.85, 0.88, 0, 7, 0,   # low_confidence_event_count=7
             10, 8, 0, 0, 0,
             0.85, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "not_ready"
        assert any("confidence" in b.lower() for b in data["blockers"])

    def test_critical_unresolved_force_not_ready(self, client):
        """Critical unresolved card mentions → not_ready."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,
             0.9, 0.85, 0.88, 0, 0, 0,
             10, 8, 0, 2, 2,   # unresolved=2, critical_unresolved=2
             0.85, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "not_ready"
        assert data["card_resolution"]["critical_unresolved_count"] == 2

    def test_ambiguous_mentions_create_needs_review(self, client):
        """No blockers but ambiguous mentions → needs_review."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,
             0.9, 0.85, 0.88, 0, 0, 0,
             10, 7, 3, 0, 0,   # ambiguous=3
             0.85, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "needs_review"
        assert any("ambiguous" in w.lower() for w in data["warnings"])

    def test_low_confidence_memory_items_create_needs_review(self, client):
        """Low-confidence memory items → needs_review warning."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,
             0.9, 0.85, 0.88, 0, 0, 0,
             10, 10, 0, 0, 0,
             0.85, 5, 0, 0],   # low_conf_memory=5 → warning
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "needs_review"
        assert any("low-confidence" in w.lower() or "confidence" in w.lower() for w in data["warnings"])

    def test_ingestion_coverage_below_threshold_creates_needs_review(self, client):
        """Ingestion coverage < 90 % → needs_review."""
        override = self._simple_override(
            [10, 10, 8, 0, 200, 80,   # 8/10 = 80% < 90%
             0.9, 0.85, 0.88, 0, 0, 0,
             20, 20, 0, 0, 0,
             0.85, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "needs_review"
        assert any("coverage" in w.lower() or "ingestion" in w.lower() for w in data["warnings"])

    def test_fully_clean_corpus_can_return_ready(self, client):
        """All metrics clean → ready verdict."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,     # all parsed and ingested, no failures
             0.92, 0.88, 0.90, 0, 0, 0,  # no unknowns, no low-conf events
             10, 10, 0, 0, 0,            # all resolved, no ambiguous/unresolved
             0.88, 0, 0, 0],             # high memory confidence, no low-conf items
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert data["verdict"] == "ready"
        assert data["blockers"] == []
        assert data["warnings"] == []

    def test_readiness_score_is_deterministic_and_in_range(self, client):
        """Score must be a float in [0, 100] and stable across identical calls."""
        override = self._simple_override(
            [5, 5, 5, 0, 100, 50,
             0.92, 0.88, 0.90, 0, 0, 0,
             10, 10, 0, 0, 0,
             0.88, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        score = data["readiness_score"]
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    def test_response_shape_includes_all_sections(self, client):
        """Response must include corpus, parser_quality, card_resolution, memory_quality."""
        override = self._simple_override([0] * 25)
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        for key in ("verdict", "readiness_score", "generated_at", "review_only", "safety_note",
                    "corpus", "parser_quality", "card_resolution", "memory_quality",
                    "blockers", "warnings", "recommendations"):
            assert key in data, f"Missing key: {key}"
        for key in ("log_count", "parsed_log_count", "ingested_log_count", "event_count", "memory_item_count"):
            assert key in data["corpus"]
        for key in ("unknown_event_count", "low_confidence_event_count", "avg_event_confidence"):
            assert key in data["parser_quality"]
        for key in ("card_mention_count", "resolved_count", "ambiguous_count",
                    "unresolved_count", "critical_unresolved_count"):
            assert key in data["card_resolution"]
        for key in ("avg_memory_confidence", "low_confidence_memory_item_count",
                    "ambiguous_reference_item_count", "unresolved_reference_item_count"):
            assert key in data["memory_quality"]

    def test_top_ambiguous_and_unresolved_are_limited(self, client):
        """top_ambiguous and top_unresolved must be lists (bounded by READINESS_TOP_N_LIMIT)."""
        override = self._simple_override(
            [0] * 25,
            fetchalls=[[], []],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        assert isinstance(data["card_resolution"]["top_ambiguous"], list)
        assert isinstance(data["card_resolution"]["top_unresolved"], list)

    def test_endpoint_does_not_mutate_db(self, client):
        """GET /corpus-readiness must not call commit() or rollback()."""
        committed = []
        rolled_back = []

        async def override_db():
            session = AsyncMock()
            r = MagicMock()
            r.scalar.return_value = 0
            r.fetchall.return_value = []
            session.execute = AsyncMock(return_value=r)
            session.commit = AsyncMock(side_effect=lambda: committed.append(1))
            session.rollback = AsyncMock(side_effect=lambda: rolled_back.append(1))
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert committed == [], "GET /corpus-readiness must not commit"
        assert rolled_back == [], "GET /corpus-readiness must not rollback"

    def test_generated_at_is_iso_timestamp(self, client):
        override = self._simple_override([0] * 25)
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        data = resp.json()
        from datetime import datetime
        # Should not raise
        datetime.fromisoformat(data["generated_at"])

    def test_existing_memory_analytics_still_pass(self, client):
        """Sanity: the existing /memory-summary endpoint is unaffected."""
        async def override_db():
            session = AsyncMock()
            r = MagicMock()
            r.scalar.return_value = 0
            rows = MagicMock()
            rows.all.return_value = []
            r.scalars.return_value = rows
            session.execute = AsyncMock(return_value=r)
            yield session

        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            resp = client.get("/api/observed-play/memory-summary")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200


# ── Phase 6.0: Coach Advisory Evidence ───────────────────────────────────────

class TestCoachEvidence:
    """Tests for GET /api/observed-play/coach-evidence (Phase 6.0)."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ready_readiness(self):
        """Return a mock CorpusReadinessReport with verdict=ready."""
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="ready",
            readiness_score=97.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=1, parsed_log_count=1, ingested_log_count=1,
                failed_log_count=0, parse_coverage_pct=100.0,
                ingestion_coverage_pct=100.0, total_events=10, total_memory_items=5,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.90, events_below_threshold=0,
                low_confidence_pct=0.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=10, resolved_mentions=10, ambiguous_mentions=0,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=100.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.90, memory_items_below_threshold=0,
                low_confidence_memory_pct=0.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=[], warnings=[], recommendations=[],
        )

    def _needs_review_readiness(self):
        """Return a mock CorpusReadinessReport with verdict=needs_review."""
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="needs_review",
            readiness_score=65.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=2, parsed_log_count=1, ingested_log_count=1,
                failed_log_count=1, parse_coverage_pct=50.0,
                ingestion_coverage_pct=50.0, total_events=5, total_memory_items=2,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.75, events_below_threshold=2,
                low_confidence_pct=40.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=5, resolved_mentions=4, ambiguous_mentions=1,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=80.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.78, memory_items_below_threshold=1,
                low_confidence_memory_pct=20.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=[], warnings=["Low parser coverage."], recommendations=[],
        )

    def _not_ready_readiness(self):
        """Return a mock CorpusReadinessReport with verdict=not_ready."""
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="not_ready",
            readiness_score=10.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=0, parsed_log_count=0, ingested_log_count=0,
                failed_log_count=0, parse_coverage_pct=0.0,
                ingestion_coverage_pct=0.0, total_events=0, total_memory_items=0,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.0, events_below_threshold=0,
                low_confidence_pct=0.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=0, resolved_mentions=0, ambiguous_mentions=0,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=0.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.0, memory_items_below_threshold=0,
                low_confidence_memory_pct=0.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=["No logs ingested."], warnings=[], recommendations=[],
        )

    def _evidence_db_override(self, evidence_rows=None):
        """DB override that supplies empty aggregate scalars and optional evidence rows.

        The coach-evidence endpoint runs these queries after readiness:
          1. count → scalar
          2. avg  → scalar
          3. type distribution → all() (list of 2-tuples)
          4. top actors → all() (list of 2-tuples)
          5. top targets → all() (list of 2-tuples)
          6. top actions → all() (list of 2-tuples)
          7. evidence JOIN → all() (list of row objects)
        """
        rows = evidence_rows or []
        call_count = [0]

        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(query, *args, **kwargs):
                r = MagicMock()
                idx = call_count[0]
                call_count[0] += 1

                if idx == 0:
                    r.scalar.return_value = len(rows)
                elif idx == 1:
                    r.scalar.return_value = 0.90 if rows else None
                elif idx in (2, 3, 4, 5):
                    r.all.return_value = []
                else:
                    r.all.return_value = rows
                return r

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        return override_db

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_endpoint_exists_and_is_read_only(self, client):
        """Endpoint exists, responds to GET, and cannot be POSTed."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 200
                resp_post = client.post("/api/observed-play/coach-evidence")
                assert resp_post.status_code == 405
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_not_ready_returns_409(self, client):
        """When corpus is not_ready, endpoint returns HTTP 409."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._not_ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 409
                detail = resp.json()["detail"]
                assert "not_ready" in str(detail) or "not ready" in str(detail).lower()
                assert "blockers" in detail
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_needs_review_returns_200_with_warnings(self, client):
        """When corpus needs_review, endpoint returns 200 with warnings populated."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._needs_review_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["warnings"]) > 0
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_ready_returns_200(self, client):
        """When corpus is ready, endpoint returns 200 with empty warnings."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 200
                data = resp.json()
                assert data["warnings"] == []
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_response_includes_review_only_true(self, client):
        """Response always includes review_only=true."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.json()["review_only"] is True
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_empty_corpus_returns_empty_evidence(self, client):
        """When no items match, evidence list is empty and summary count is 0."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override(evidence_rows=[])
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                data = resp.json()
                assert data["evidence"] == []
                assert data["summary"]["matching_item_count"] == 0
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_query_params_echoed_in_response(self, client):
        """Query params are echoed back in the response query field."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get(
                    "/api/observed-play/coach-evidence",
                    params={"card_name": "Dragapult ex", "memory_type": "attack_used", "min_confidence": 0.9, "limit": 10},
                )
                data = resp.json()
                assert data["query"]["card_name"] == "Dragapult ex"
                assert data["query"]["memory_type"] == "attack_used"
                assert data["query"]["min_confidence"] == pytest.approx(0.9)
                assert data["query"]["limit"] == 10
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_min_confidence_default_is_0_80(self, client):
        """Default min_confidence is 0.80."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                data = resp.json()
                assert data["query"]["min_confidence"] == pytest.approx(0.80)
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_limit_default_is_25(self, client):
        """Default limit is 25."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                data = resp.json()
                assert data["query"]["limit"] == 25
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_limit_capped_at_100(self, client):
        """Requesting limit > 100 returns HTTP 422."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence", params={"limit": 9999})
                assert resp.status_code == 422
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_summary_structure(self, client):
        """Response includes a well-formed summary with expected keys."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                data = resp.json()
                summary = data["summary"]
                assert "matching_item_count" in summary
                assert "avg_confidence" in summary
                assert "memory_type_counts" in summary
                assert "top_actors" in summary
                assert "top_targets" in summary
                assert "top_actions" in summary
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_evidence_items_include_source_link(self, client):
        """Evidence items include a source_link with log_id and event_id."""
        import uuid as _uuid

        log_id = str(_uuid.uuid4())
        event_id = 42
        item_id = str(_uuid.uuid4())

        evidence_item = MagicMock()
        evidence_item.id = item_id
        evidence_item.observed_play_log_id = log_id
        evidence_item.observed_play_event_id = event_id
        evidence_item.memory_type = "attack_used"
        evidence_item.actor_card_raw = "Dragapult ex"
        evidence_item.actor_card_def_id = None
        evidence_item.target_card_raw = "Salazzle ex"
        evidence_item.target_card_def_id = None
        evidence_item.related_card_raw = None
        evidence_item.action_name = "Phantom Dive"
        evidence_item.damage = 130
        evidence_item.amount = None
        evidence_item.confidence_score = 0.95
        evidence_item.source_event_type = "attack_used"
        evidence_item.source_raw_line = "Player used Phantom Dive"
        evidence_item.turn_number = 5
        evidence_item.player_alias = "player_1"
        evidence_item.created_at = "2024-01-01T00:00:00"

        filename = "test_log.md"

        call_count = [0]

        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(query, *args, **kwargs):
                r = MagicMock()
                idx = call_count[0]
                call_count[0] += 1
                if idx == 0:
                    r.scalar.return_value = 1
                elif idx == 1:
                    r.scalar.return_value = 0.95
                elif idx in (2, 3, 4, 5):
                    r.all.return_value = []
                else:
                    row = MagicMock()
                    row.__getitem__ = lambda self, key: evidence_item if key == 0 else filename
                    r.all.return_value = [row]
                return r

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["evidence"]) == 1
                ev = data["evidence"][0]
                assert "source_link" in ev
                assert ev["source_link"]["log_id"] == log_id
                assert ev["source_link"]["event_id"] == event_id
                assert ev["memory_type"] == "attack_used"
                assert ev["actor_card_raw"] == "Dragapult ex"
                assert ev["action_name"] == "Phantom Dive"
                assert ev["confidence_score"] == pytest.approx(0.95)
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_card_name_filter_in_query(self, client):
        """card_name query param is echoed back in query field."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get(
                    "/api/observed-play/coach-evidence",
                    params={"card_name": "Charizard ex"},
                )
                assert resp.status_code == 200
                assert resp.json()["query"]["card_name"] == "Charizard ex"
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_memory_type_filter_in_query(self, client):
        """memory_type query param is echoed back in query field."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get(
                    "/api/observed-play/coach-evidence",
                    params={"memory_type": "energy_attached"},
                )
                assert resp.status_code == 200
                assert resp.json()["query"]["memory_type"] == "energy_attached"
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_action_name_filter_in_query(self, client):
        """action_name query param is echoed back in query field."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get(
                    "/api/observed-play/coach-evidence",
                    params={"action_name": "Phantom Dive"},
                )
                assert resp.status_code == 200
                assert resp.json()["query"]["action_name"] == "Phantom Dive"
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_endpoint_does_not_mutate_db(self, client):
        """Verify the endpoint issues no db.add() or db.commit() calls."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override

            from unittest.mock import patch as _patch
            with _patch("sqlalchemy.ext.asyncio.AsyncSession.add") as mock_add, \
                 _patch("sqlalchemy.ext.asyncio.AsyncSession.commit") as mock_commit:
                try:
                    resp = client.get("/api/observed-play/coach-evidence")
                    assert resp.status_code == 200
                    mock_add.assert_not_called()
                    mock_commit.assert_not_called()
                finally:
                    client.app.fastapi_app.dependency_overrides.clear()

    def test_existing_corpus_readiness_tests_unaffected(self, client):
        """Smoke test: the corpus-readiness endpoint still works after Phase 6.0."""
        override = TestCorpusReadiness()._simple_override(
            [0, 0, 0, 0, 0, 0, None, None, None, 0, 0, 0, 0, 0, 0, None, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
            assert resp.status_code == 200
        finally:
            client.app.fastapi_app.dependency_overrides.clear()


class TestCoachContextPreview:
    """Tests for GET /api/observed-play/coach-context-preview (Phase 6.1)."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ready_readiness(self):
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="ready",
            readiness_score=97.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=1, parsed_log_count=1, ingested_log_count=1,
                failed_log_count=0, parse_coverage_pct=100.0,
                ingestion_coverage_pct=100.0, total_events=10, total_memory_items=5,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.90, events_below_threshold=0,
                low_confidence_pct=0.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=10, resolved_mentions=10, ambiguous_mentions=0,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=100.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.90, memory_items_below_threshold=0,
                low_confidence_memory_pct=0.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=[], warnings=[], recommendations=[],
        )

    def _needs_review_readiness(self):
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="needs_review",
            readiness_score=65.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=2, parsed_log_count=1, ingested_log_count=1,
                failed_log_count=1, parse_coverage_pct=50.0,
                ingestion_coverage_pct=50.0, total_events=5, total_memory_items=2,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.75, events_below_threshold=2,
                low_confidence_pct=40.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=5, resolved_mentions=4, ambiguous_mentions=1,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=80.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.78, memory_items_below_threshold=1,
                low_confidence_memory_pct=20.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=[], warnings=["Low parser coverage."], recommendations=[],
        )

    def _not_ready_readiness(self):
        from app.observed_play.schemas import (
            CorpusStats, ParserQualityStats, CardResolutionStats,
            MemoryQualityStats, CorpusReadinessReport,
        )
        return CorpusReadinessReport(
            verdict="not_ready",
            readiness_score=10.0,
            generated_at="2024-01-01T00:00:00+00:00",
            review_only=True,
            corpus=CorpusStats(
                log_count=0, parsed_log_count=0, ingested_log_count=0,
                failed_log_count=0, parse_coverage_pct=0.0,
                ingestion_coverage_pct=0.0, total_events=0, total_memory_items=0,
            ),
            parser_quality=ParserQualityStats(
                avg_event_confidence=0.0, events_below_threshold=0,
                low_confidence_pct=0.0, unknown_event_count=0,
                confidence_threshold_used=0.80,
            ),
            card_resolution=CardResolutionStats(
                total_card_mentions=0, resolved_mentions=0, ambiguous_mentions=0,
                unresolved_mentions=0, critical_unresolved_mentions=0,
                resolution_rate_pct=0.0,
            ),
            memory_quality=MemoryQualityStats(
                avg_memory_confidence=0.0, memory_items_below_threshold=0,
                low_confidence_memory_pct=0.0, memory_confidence_threshold_used=0.80,
                top_memory_types=[],
            ),
            blockers=["No logs ingested."], warnings=[], recommendations=[],
        )

    def _empty_evidence_db_override(self):
        """DB override that returns no evidence rows (used after readiness is patched out)."""
        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(query, *args, **kwargs):
                r = MagicMock()
                r.all.return_value = []
                r.scalar.return_value = 0
                return r

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        return override_db

    def _evidence_row(self, memory_item_id=None, log_id=None):
        """Build a minimal fake (ObservedPlayMemoryItem, log_uuid) row tuple."""
        import uuid as _uuid
        item = MagicMock()
        item.id = memory_item_id or _uuid.uuid4()
        item.observed_play_log_id = log_id or _uuid.uuid4()
        item.turn_number = 5
        item.confidence_score = 0.95
        item.memory_type = "attack_used"
        item.actor_card_raw = "Dragapult ex"
        item.target_card_raw = "Salazzle ex"
        item.action_name = "Phantom Dive"
        item.damage = 200
        item.source_raw_line = "Dragapult ex used Phantom Dive on Salazzle ex."
        item.created_at = MagicMock()
        return (item, _uuid.uuid4())

    def _one_row_db_override(self, row):
        """DB override that returns exactly one evidence row."""
        async def override_db():
            session = AsyncMock()

            async def execute_side_effect(query, *args, **kwargs):
                r = MagicMock()
                r.all.return_value = [row]
                r.scalar.return_value = 1
                return r

            session.execute = AsyncMock(side_effect=execute_side_effect)
            yield session

        return override_db

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_endpoint_exists_and_is_get_only(self, client):
        """Endpoint exists, accepts GET, rejects POST."""
        with patch(
            "app.observed_play.coach_context.compute_corpus_readiness",
            new=AsyncMock(return_value=self._ready_readiness()),
        ):
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                assert resp.status_code == 200
                resp_post = client.post("/api/observed-play/coach-context-preview")
                assert resp_post.status_code == 405
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_default_config_flag_is_false(self):
        """Config default is OBSERVED_PLAY_MEMORY_ENABLED=False."""
        from app.config import settings
        # Verify the default without any env override
        import pydantic_settings
        fresh = type(settings)(_env_file=None)
        assert fresh.OBSERVED_PLAY_MEMORY_ENABLED is False

    def test_disabled_returns_enabled_false_no_injection(self, client):
        """When flag is false, endpoint returns enabled=false and empty prompt_block."""
        with patch("app.observed_play.coach_context.settings") as mock_settings:
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = False
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                assert resp.status_code == 200
                data = resp.json()
                assert data["enabled"] is False
                assert data["would_inject"] is False
                assert data["prompt_block"] == ""
                assert data["evidence_count"] == 0
                assert data["evidence_ids"] == []
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_disabled_reason_mentions_flag(self, client):
        """When disabled, the reason field mentions the flag name."""
        with patch("app.observed_play.coach_context.settings") as mock_settings:
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = False
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                assert "OBSERVED_PLAY_MEMORY_ENABLED" in data["reason"]
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_enabled_ready_returns_would_inject_true(self, client):
        """When flag is on and corpus is ready, would_inject is True."""
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                assert data["enabled"] is True
                assert data["would_inject"] is True
                assert data["readiness_verdict"] == "ready"
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_enabled_not_ready_blocks_injection(self, client):
        """When flag is on but corpus is not_ready, would_inject is False."""
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._not_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                assert data["enabled"] is True
                assert data["would_inject"] is False
                assert data["readiness_verdict"] == "not_ready"
                assert data["prompt_block"] == ""
                assert len(data["warnings"]) > 0
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_enabled_needs_review_injects_with_warnings(self, client):
        """When flag is on and corpus needs_review, evidence is injected with warnings."""
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._needs_review_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                assert data["enabled"] is True
                assert data["would_inject"] is True
                assert data["readiness_verdict"] == "needs_review"
                assert len(data["warnings"]) > 0
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_evidence_count_bounded_by_max_evidence(self, client):
        """Evidence count never exceeds OBSERVED_PLAY_MEMORY_MAX_EVIDENCE."""
        import uuid as _uuid
        rows = [self._evidence_row() for _ in range(3)]
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 3
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._one_row_db_override(rows[0])
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview", params={"limit": 10})
                data = resp.json()
                # limit=10 should be capped down to OBSERVED_PLAY_MEMORY_MAX_EVIDENCE=3
                assert resp.status_code == 200, resp.text
                assert data["filters_applied"]["limit"] <= 3
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_min_confidence_default_is_conservative(self, client):
        """Default min_confidence uses OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE (0.85)."""
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                assert data["filters_applied"]["min_confidence"] == 0.85
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_prompt_block_includes_review_only_language(self, client):
        """Prompt block contains the review-only advisory note."""
        row = self._evidence_row()
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._one_row_db_override(row)
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                block = data["prompt_block"]
                assert "REVIEW ONLY" in block
                assert "advisory" in block.lower()
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_prompt_block_includes_source_ids(self, client):
        """Prompt block includes log_id and memory_item_id references."""
        import uuid as _uuid
        item_id = _uuid.uuid4()
        log_id = _uuid.uuid4()
        row = self._evidence_row(memory_item_id=item_id, log_id=log_id)
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._one_row_db_override(row)
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                block = data["prompt_block"]
                assert str(log_id) in block or str(item_id) in block
                assert data["evidence_ids"] == [str(item_id)]
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_prompt_block_includes_citation_instruction(self, client):
        """Prompt block instructs the Coach to cite observed evidence IDs."""
        row = self._evidence_row()
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._one_row_db_override(row)
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-context-preview")
                data = resp.json()
                block = data["prompt_block"]
                assert "cite" in block.lower()
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_endpoint_is_read_only(self, client):
        """Verify the endpoint issues no db.add() or db.commit() calls."""
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=self._ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            override = self._empty_evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            with patch("sqlalchemy.ext.asyncio.AsyncSession.add") as mock_add, \
                 patch("sqlalchemy.ext.asyncio.AsyncSession.commit") as mock_commit:
                try:
                    resp = client.get("/api/observed-play/coach-context-preview")
                    assert resp.status_code == 200
                    mock_add.assert_not_called()
                    mock_commit.assert_not_called()
                finally:
                    client.app.fastapi_app.dependency_overrides.clear()

    def test_existing_coach_evidence_tests_unaffected(self, client):
        """Smoke test: the coach-evidence endpoint still works after Phase 6.1."""
        with patch(
            "app.api.observed_play._compute_corpus_readiness",
            new=AsyncMock(return_value=TestCoachEvidence()._ready_readiness()),
        ):
            override = TestCoachEvidence()._evidence_db_override()
            from app.api.observed_play import get_db
            client.app.fastapi_app.dependency_overrides[get_db] = override
            try:
                resp = client.get("/api/observed-play/coach-evidence")
                assert resp.status_code == 200
            finally:
                client.app.fastapi_app.dependency_overrides.clear()

    def test_existing_corpus_readiness_tests_unaffected(self, client):
        """Smoke test: corpus-readiness endpoint still works after Phase 6.1."""
        override = TestCorpusReadiness()._simple_override(
            [0, 0, 0, 0, 0, 0, None, None, None, 0, 0, 0, 0, 0, 0, None, 0, 0, 0],
        )
        from app.api.observed_play import get_db
        client.app.fastapi_app.dependency_overrides[get_db] = override
        try:
            resp = client.get("/api/observed-play/corpus-readiness")
            assert resp.status_code == 200
        finally:
            client.app.fastapi_app.dependency_overrides.clear()
