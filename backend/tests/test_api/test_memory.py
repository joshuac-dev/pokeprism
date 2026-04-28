"""Tests for /api/memory endpoints (Phase 11).

All DB and Neo4j graph calls are mocked — no real services required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_with_db(override_db):
    from app.main import create_app
    from app.api.memory import get_db
    app = create_app()
    app.fastapi_app.dependency_overrides[get_db] = override_db
    return app


def _scalar_none(session):
    m = MagicMock()
    m.scalar_one_or_none.return_value = None
    m.scalar.return_value = None
    session.execute = AsyncMock(return_value=m)
    return session


# ---------------------------------------------------------------------------
# GET /api/memory/top-card
# ---------------------------------------------------------------------------

class TestGetTopCard:

    def test_returns_card_id_when_data_exists(self):
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = "sv06-130"
            session.execute = AsyncMock(return_value=m)
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/top-card")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["card_id"] == "sv06-130"

    def test_returns_204_when_no_data(self):
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/top-card")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /api/memory/card/{card_id}/profile
# ---------------------------------------------------------------------------

class TestGetCardProfile:

    def _make_card(self):
        m = MagicMock()
        m.tcgdex_id = "sv06-130"
        m.name = "Dragapult ex"
        m.set_abbrev = "sv06"
        m.set_number = "130"
        m.category = "Pokemon"
        m.image_url = None
        return m

    def _make_perf(self):
        m = MagicMock()
        m.games_included = 100
        m.games_won = 62
        m.total_kos = 150
        m.total_damage = 30000
        m.total_prizes = 300
        return m

    def test_returns_404_when_card_missing(self):
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/card/nonexistent/profile")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_returns_profile_with_stats(self):
        from fastapi.testclient import TestClient

        card = self._make_card()
        perf = self._make_perf()
        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar_one_or_none.return_value = card
                else:
                    m.scalar_one_or_none.return_value = perf
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        # Mock Neo4j graph_session to avoid real connection.
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.__aiter__ = MagicMock(return_value=iter([]))
        mock_session.run = AsyncMock(return_value=mock_result)

        app = _make_app_with_db(override_db)
        with patch("app.api.memory.graph_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with TestClient(app) as c:
                resp = c.get("/api/memory/card/sv06-130/profile")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["card_id"] == "sv06-130"
        assert data["name"] == "Dragapult ex"
        assert "stats" in data
        assert data["stats"]["games_included"] == 100
        assert data["stats"]["win_rate"] == pytest.approx(0.62)

    def test_zero_games_returns_zero_win_rate(self):
        from fastapi.testclient import TestClient

        card = self._make_card()
        perf = MagicMock()
        perf.games_included = 0
        perf.games_won = 0
        perf.total_kos = 0
        perf.total_damage = 0
        perf.total_prizes = 0
        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar_one_or_none.return_value = card
                else:
                    m.scalar_one_or_none.return_value = perf
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.__aiter__ = MagicMock(return_value=iter([]))
        mock_session.run = AsyncMock(return_value=mock_result)

        app = _make_app_with_db(override_db)
        with patch("app.api.memory.graph_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with TestClient(app) as c:
                resp = c.get("/api/memory/card/sv06-130/profile")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["stats"]["win_rate"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/memory/graph
# ---------------------------------------------------------------------------

class TestGetMemoryGraph:

    def test_missing_card_id_returns_422(self):
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/graph")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 422

    def test_returns_nodes_and_edges(self):
        from fastapi.testclient import TestClient

        async def override_db():
            yield AsyncMock()

        call_n = {"n": 0}

        def _make_neo4j_result(records):
            result = MagicMock()

            async def _aiter():
                for r in records:
                    yield r

            result.__aiter__ = lambda self: _aiter()
            return result

        focal_record = MagicMock()
        focal_record.__getitem__ = lambda self, k: {"name": "Dragapult ex", "category": "Pokemon"}[k]

        async def _run(cypher, **kwargs):
            call_n["n"] += 1
            if call_n["n"] == 1:
                # Neighbours query
                rec = MagicMock()
                rec.data = lambda: {"id": "sv06-129", "name": "Drakloak", "category": "Pokemon",
                                    "weight": 10.0, "games_observed": 50}
                result = MagicMock()

                async def _aiter():
                    yield rec

                result.__aiter__ = lambda self: _aiter()
                return result
            elif call_n["n"] == 2:
                # Focal card query
                result = AsyncMock()
                result.single = AsyncMock(return_value={"name": "Dragapult ex", "category": "Pokemon"})
                return result
            else:
                # Edges query
                rec = MagicMock()
                rec.data = lambda: {"source": "sv06-130", "target": "sv06-129",
                                    "weight": 10.0, "games_observed": 50}
                result = MagicMock()

                async def _aiter():
                    yield rec

                result.__aiter__ = lambda self: _aiter()
                return result

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=_run)

        app = _make_app_with_db(override_db)
        with patch("app.api.memory.graph_session") as mock_gs:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            with TestClient(app) as c:
                resp = c.get("/api/memory/graph?card_id=sv06-130")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert any(n["id"] == "sv06-130" for n in data["nodes"])


# ---------------------------------------------------------------------------
# GET /api/memory/card/{card_id}/decisions
# ---------------------------------------------------------------------------

class TestGetCardDecisions:

    def _make_decision(self, card_id="sv06-130"):
        m = MagicMock()
        m.id = uuid.uuid4()
        m.match_id = uuid.uuid4()
        m.turn_number = 5
        m.player_id = "p1"
        m.action_type = "ATTACK"
        m.card_def_id = card_id
        m.reasoning = "Best attack available."
        m.legal_action_count = 3
        m.created_at = None
        return m

    def test_returns_paginated_decisions(self):
        from fastapi.testclient import TestClient

        decision = self._make_decision()
        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar.return_value = 1
                else:
                    m.scalars.return_value.all.return_value = [decision]
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/card/sv06-130/decisions")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "decisions" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["action_type"] == "ATTACK"

    def test_empty_decisions_returns_zero_total(self):
        from fastapi.testclient import TestClient

        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar.return_value = 0
                else:
                    m.scalars.return_value.all.return_value = []
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = _make_app_with_db(override_db)
        with TestClient(app) as c:
            resp = c.get("/api/memory/card/sv06-130/decisions")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["decisions"] == []
