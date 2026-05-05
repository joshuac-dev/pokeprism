"""Tests for /api/coverage endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_mock_card(
    tcgdex_id="sv06-130",
    name="Dragapult ex",
    set_abbrev="TWM",
    set_number="130",
    category="pokemon",
    subcategory=None,
    attacks=None,
    abilities=None,
    image_url="https://assets.tcgdex.net/en/sv/sv06/130",
):
    card = MagicMock()
    card.tcgdex_id = tcgdex_id
    card.name = name
    card.set_abbrev = set_abbrev
    card.set_number = set_number
    card.category = category
    card.subcategory = subcategory
    card.attacks = attacks or []
    card.abilities = abilities or []
    card.image_url = image_url
    return card


@pytest.fixture
def client():
    from app.main import create_app
    return TestClient(create_app())


def _override_db_and_registry(client, mock_cards, missing_effects=None):
    """Return (override_db, mock_registry) and patch EffectRegistry for the duration."""
    from app.api.coverage import get_db

    async def override_db():
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = mock_cards
        session.execute = AsyncMock(return_value=result)
        yield session

    mock_registry = MagicMock()
    mock_registry.check_card_coverage.return_value = missing_effects or []

    return override_db, mock_registry, get_db


class TestCoverageEndpoint:
    def test_response_includes_required_summary_fields(self, client):
        card = _make_mock_card()
        override_db, mock_registry, get_db = _override_db_and_registry(client, [card])

        with patch("app.engine.effects.registry.EffectRegistry.instance", return_value=mock_registry):
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            resp = client.get("/api/coverage")
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        for field in ("total", "implemented", "flat_only", "missing", "coverage_pct", "cards"):
            assert field in data, f"Missing summary field: {field}"

    def test_each_card_includes_image_url(self, client):
        card = _make_mock_card(image_url="https://assets.tcgdex.net/en/sv/sv06/130")
        override_db, mock_registry, get_db = _override_db_and_registry(client, [card])

        with patch("app.engine.effects.registry.EffectRegistry.instance", return_value=mock_registry):
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            resp = client.get("/api/coverage")
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        cards = resp.json()["cards"]
        assert len(cards) == 1
        assert "image_url" in cards[0]
        assert cards[0]["image_url"] == "https://assets.tcgdex.net/en/sv/sv06/130"

    def test_card_without_image_url_returns_null(self, client):
        card = _make_mock_card(image_url=None)
        override_db, mock_registry, get_db = _override_db_and_registry(client, [card])

        with patch("app.engine.effects.registry.EffectRegistry.instance", return_value=mock_registry):
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            resp = client.get("/api/coverage")
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        cards = resp.json()["cards"]
        assert len(cards) == 1
        assert "image_url" in cards[0]
        assert cards[0]["image_url"] is None

    def test_missing_handler_card_has_missing_status(self, client):
        card = _make_mock_card(
            tcgdex_id="sv05-015",
            name="Weezing",
            attacks=[{"name": "Wafting Heal", "effect": "Heal 30 damage from each of your Pokemon."}],
        )
        override_db, mock_registry, get_db = _override_db_and_registry(
            client, [card], missing_effects=["Wafting Heal"]
        )

        with patch("app.engine.effects.registry.EffectRegistry.instance", return_value=mock_registry):
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            resp = client.get("/api/coverage")
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["missing"] == 1
        assert data["cards"][0]["status"] == "missing"
        assert "Wafting Heal" in data["cards"][0]["missing_effects"]

    def test_test_fixture_card_excluded(self, client):
        """Card with tcgdex_id='test-002' must be skipped."""
        real_card = _make_mock_card()
        fixture_card = _make_mock_card(tcgdex_id="test-002", name="Fixture Card")
        override_db, mock_registry, get_db = _override_db_and_registry(
            client, [real_card, fixture_card]
        )

        with patch("app.engine.effects.registry.EffectRegistry.instance", return_value=mock_registry):
            client.app.fastapi_app.dependency_overrides[get_db] = override_db
            resp = client.get("/api/coverage")
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        ids = [c["tcgdex_id"] for c in data["cards"]]
        assert "test-002" not in ids
