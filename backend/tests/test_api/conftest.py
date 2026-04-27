"""Test fixtures for API tests."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_celery():
    """Mock Celery so tasks don't actually run."""
    with patch("app.api.simulations.run_simulation") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "test-task-id"
        mock_task.delay.return_value = mock_result
        yield mock_task


@pytest.fixture
def client(mock_celery):
    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_db_session():
    """Async mock DB session that can be used for dependency overrides."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    return session
