"""Fixtures for Celery task unit tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def simulation_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_redis():
    with patch("app.tasks.simulation.redis") as mock_r:
        mock_client = MagicMock()
        mock_r.Redis.from_url.return_value = mock_client
        yield mock_client
