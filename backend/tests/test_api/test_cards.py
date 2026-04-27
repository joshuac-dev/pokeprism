"""Tests for /api/cards endpoints."""

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
    hp=310,
    types=["Psychic"],
    image_url="https://assets.tcgdex.net/en/sv/sv06/130",
    evolve_from="Drakloak",
    stage="Stage2",
    attacks=[],
    abilities=[],
    weaknesses=[],
    resistances=[],
    retreat_cost=2,
    regulation_mark="H",
    rarity="Double Rare",
):
    card = MagicMock()
    card.tcgdex_id = tcgdex_id
    card.name = name
    card.set_abbrev = set_abbrev
    card.set_number = set_number
    card.category = category
    card.subcategory = subcategory
    card.hp = hp
    card.types = types
    card.image_url = image_url
    card.evolve_from = evolve_from
    card.stage = stage
    card.attacks = attacks
    card.abilities = abilities
    card.weaknesses = weaknesses
    card.resistances = resistances
    card.retreat_cost = retreat_cost
    card.regulation_mark = regulation_mark
    card.rarity = rarity
    return card


@pytest.fixture
def client():
    from app.main import create_app
    return TestClient(create_app())


class TestSearchCards:
    def test_search_returns_matching_cards(self, client):
        mock_card = _make_mock_card()
        with patch("app.api.cards.get_db") as mock_get_db:
            session = AsyncMock()
            result = MagicMock()
            result.all.return_value = [
                MagicMock(
                    tcgdex_id="sv06-130",
                    name="Dragapult ex",
                    set_abbrev="TWM",
                    set_number="130",
                    category="pokemon",
                )
            ]
            session.execute = AsyncMock(return_value=result)

            async def override():
                yield session

            mock_get_db.return_value = override()
            # Use dependency override instead
            from app.api.cards import get_db

            app = client.app
            app.fastapi_app.dependency_overrides[get_db] = lambda: override()
            resp = client.get("/api/cards/search?q=dragapult")
            app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_search_requires_q_param(self, client):
        resp = client.get("/api/cards/search")
        assert resp.status_code == 422

    def test_search_rejects_empty_q(self, client):
        resp = client.get("/api/cards/search?q=")
        assert resp.status_code == 422

    def test_search_with_db_override(self, client):
        from app.api.cards import get_db

        async def override_db():
            session = AsyncMock()
            result = MagicMock()
            result.all.return_value = []
            session.execute = AsyncMock(return_value=result)
            yield session

        app = client.app
        app.fastapi_app.dependency_overrides[get_db] = override_db
        resp = client.get("/api/cards/search?q=pikachu")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json() == []


class TestListCards:
    def test_list_returns_paginated_result(self, client):
        from app.api.cards import get_db

        mock_card = _make_mock_card()

        async def override_db():
            session = AsyncMock()

            mock_rows = MagicMock()
            mock_rows.scalars.return_value.all.return_value = [mock_card]

            mock_count = MagicMock()
            mock_count.scalar_one.return_value = 157

            session.execute = AsyncMock(side_effect=[mock_rows, mock_count])
            yield session

        app = client.app
        app.fastapi_app.dependency_overrides[get_db] = override_db
        resp = client.get("/api/cards")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "cards" in data
        assert "page" in data

    def test_list_validates_page_size(self, client):
        resp = client.get("/api/cards?page_size=999")
        assert resp.status_code == 422

    def test_list_page_zero_rejected(self, client):
        resp = client.get("/api/cards?page=0")
        assert resp.status_code == 422


class TestGetCard:
    def test_get_card_returns_full_detail(self, client):
        from app.api.cards import get_db

        mock_card = _make_mock_card()

        async def override_db():
            session = AsyncMock()
            session.get = AsyncMock(return_value=mock_card)
            yield session

        app = client.app
        app.fastapi_app.dependency_overrides[get_db] = override_db
        resp = client.get("/api/cards/sv06-130")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["tcgdex_id"] == "sv06-130"
        assert data["name"] == "Dragapult ex"
        assert "attacks" in data
        assert "stage" in data

    def test_get_card_not_found_returns_404(self, client):
        from app.api.cards import get_db

        async def override_db():
            session = AsyncMock()
            session.get = AsyncMock(return_value=None)
            yield session

        app = client.app
        app.fastapi_app.dependency_overrides[get_db] = override_db
        resp = client.get("/api/cards/nonexistent-000")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404
