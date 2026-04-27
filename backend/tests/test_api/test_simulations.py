"""Tests for /api/simulations endpoints.

Pure Pydantic-validation tests run without any DB or server.
TestClient-based tests mock the DB session dependency.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.simulations import SimulationCreate, count_deck_cards


# ---------------------------------------------------------------------------
# Deck card-count helper
# ---------------------------------------------------------------------------

class TestCountDeckCards:
    def test_ptcgl_format(self):
        deck = "4 Dragapult ex sv06-130\n3 Drakloak sv06-129\n2 Dreepy sv06-128\n"
        assert count_deck_cards(deck) == 9

    def test_compact_format(self):
        deck = "4 sv06-130\n3 sv06-129"
        assert count_deck_cards(deck) == 7

    def test_empty_string_returns_zero(self):
        assert count_deck_cards("") == 0

    def test_comment_lines_ignored(self):
        deck = "# Pokémon\n4 sv06-130\n# Trainers\n3 sv05-144"
        assert count_deck_cards(deck) == 7

    def test_blank_lines_ignored(self):
        deck = "\n4 sv06-130\n\n3 sv06-129\n"
        assert count_deck_cards(deck) == 7


# ---------------------------------------------------------------------------
# SimulationCreate Pydantic validation
# ---------------------------------------------------------------------------

class TestSimulationCreateValidation:
    def _valid_payload(self, **overrides) -> dict:
        base = {
            "deck_text": "",
            "deck_mode": "none",
            "game_mode": "hh",
            "deck_locked": False,
            "num_rounds": 2,
            "matches_per_opponent": 5,
            "target_win_rate": 0.60,
            "opponent_deck_texts": [],
            "excluded_card_ids": [],
        }
        base.update(overrides)
        return base

    def test_valid_payload_parses(self):
        obj = SimulationCreate(**self._valid_payload())
        assert obj.game_mode == "hh"
        assert obj.deck_mode == "none"

    def test_invalid_game_mode_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(game_mode="invalid"))

    def test_invalid_deck_mode_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(deck_mode="something"))

    def test_deck_locked_with_none_deck_mode_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(deck_locked=True, deck_mode="none"))

    def test_num_rounds_out_of_range_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(num_rounds=0))
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(num_rounds=101))

    def test_matches_per_opponent_out_of_range_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(matches_per_opponent=0))
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(matches_per_opponent=1001))

    def test_target_win_rate_out_of_range_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(target_win_rate=-0.1))
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(target_win_rate=1.1))

    def test_boundary_values_accepted(self):
        obj = SimulationCreate(**self._valid_payload(
            num_rounds=100,
            matches_per_opponent=1000,
            target_win_rate=1.0,
        ))
        assert obj.num_rounds == 100
        assert obj.matches_per_opponent == 1000

    def test_deck_locked_true_with_full_mode_accepted(self):
        obj = SimulationCreate(**self._valid_payload(
            deck_locked=True,
            deck_mode="full",
            deck_text="",
        ))
        assert obj.deck_locked is True


# ---------------------------------------------------------------------------
# API endpoint tests (require TestClient + mocked DB)
# ---------------------------------------------------------------------------

_MINIMAL_DECK_60 = "\n".join(
    [f"4 Dreepy sv06-128"] * 1           # 4
    + [f"4 Drakloak sv06-129"] * 1        # 4
    + [f"4 Dragapult ex sv06-130"] * 1    # 4
    + [f"4 Duskull sv08.5-035"] * 1       # 4
    + [f"2 Dusclops sv08.5-036"] * 1      # 2
    + [f"2 Dusknoir sv08.5-037"] * 1      # 2
    + [f"4 Buddy-Buddy Poffin sv05-144"] * 1  # 4
    + [f"3 Ultra Ball me01-131"] * 1       # 3
    + [f"3 Rare Candy me01-125"] * 1       # 3
    + [f"2 Night Stretcher me02.5-196"] * 1  # 2
    + [f"2 Prime Catcher sv05-157"] * 1    # 2
    + [f"2 Boss's Orders me01-114"] * 1    # 2
    + [f"2 Maximum Belt sv05-154"] * 1     # 2
    + [f"2 Legacy Energy sv06-167"] * 1    # 2
    + [f"2 Morty's Conviction sv05-155"] * 1  # 2
    + [f"2 Eri sv05-146"] * 1              # 2
    + [f"2 Secret Box sv06-163"] * 1       # 2
    + [f"1 Bug Catching Set sv06-143"] * 1  # 1
    + [f"1 Enhanced Hammer sv06-148"] * 1   # 1
    + [f"1 Binding Mochi sv08.5-095"] * 1   # 1
    + [f"1 Janine's Secret Art sv08.5-112"] * 1  # 1
    + [f"1 Fezandipiti ex me02.5-142"] * 1      # 1
    + [f"1 Munkidori sv06-095"] * 1             # 1
    + [f"4 Psychic Energy mee-005"] * 1    # 4
    + [f"2 Mist Energy sv05-161"] * 1      # 2
    + [f"2 Prism Energy me02.5-216"] * 1   # 2
)

# Verify at import time that our test deck is 60 cards
_deck_count = count_deck_cards(_MINIMAL_DECK_60)
assert _deck_count == 60, f"Test deck has {_deck_count} cards, expected 60"


def _make_mock_session(sim_id: uuid.UUID | None = None):
    """Build an AsyncMock session that satisfies the POST /simulations path."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    # Mock scalar results
    def make_scalar_result(value):
        mock = MagicMock()
        mock.scalar_one_or_none.return_value = value
        mock.scalar.return_value = value
        mock.scalars.return_value.all.return_value = []
        return mock

    session.execute = AsyncMock(return_value=make_scalar_result(0))

    # Capture add calls so we can find the Simulation object
    added_objects: list = []
    original_add = session.add
    def track_add(obj):
        added_objects.append(obj)
    session.add.side_effect = track_add
    session._added_objects = added_objects

    return session


class TestPostSimulation:
    """Tests for POST /api/simulations."""

    def test_invalid_game_mode_returns_422(self, client, mock_celery):
        resp = client.post(
            "/api/simulations",
            json={"game_mode": "invalid", "deck_mode": "none"},
        )
        assert resp.status_code == 422

    def test_deck_locked_with_none_deck_mode_returns_422(self, client, mock_celery):
        resp = client.post(
            "/api/simulations",
            json={"deck_locked": True, "deck_mode": "none"},
        )
        assert resp.status_code == 422

    def test_matches_per_opponent_too_large_returns_422(self, client, mock_celery):
        resp = client.post(
            "/api/simulations",
            json={"matches_per_opponent": 9999, "deck_mode": "none"},
        )
        assert resp.status_code == 422

    def test_num_rounds_zero_returns_422(self, client, mock_celery):
        resp = client.post(
            "/api/simulations",
            json={"num_rounds": 0, "deck_mode": "none"},
        )
        assert resp.status_code == 422

    def test_deck_wrong_card_count_returns_422(self, client, mock_celery):
        """Deck with only 10 cards when deck_mode='full' must be rejected."""
        from app.api.simulations import get_db

        session = _make_mock_session()

        async def override_db():
            yield session

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_text": "4 Dragapult ex sv06-130\n3 Drakloak sv06-129",
                    "deck_mode": "full",
                    "game_mode": "hh",
                },
            )
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_valid_none_deck_mode_returns_201(self, client, mock_celery):
        """deck_mode='none' with no deck_text should create a simulation."""
        from app.api.simulations import get_db
        import uuid as _uuid

        sim_id = _uuid.uuid4()

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.delete = AsyncMock()

            # Track objects added to session so we can give them an id
            def track_add(obj):
                if hasattr(obj, "id") and obj.id is None:
                    obj.id = sim_id
                # Simulation gets id assigned
                if obj.__class__.__name__ == "Simulation":
                    obj.id = sim_id

            session.add = MagicMock(side_effect=track_add)
            session.flush = AsyncMock()

            # execute() returns something with scalar() = 0 for count queries
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar.return_value = 0
            mock_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(return_value=mock_result)

            yield session

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_mode": "none",
                    "game_mode": "hh",
                    "num_rounds": 1,
                    "matches_per_opponent": 5,
                },
            )
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert "simulation_id" in data
        assert data["status"] == "pending"

    def test_celery_task_enqueued_on_success(self, mock_celery):
        """Verify run_simulation.delay is called when a simulation is created."""
        from app.api.simulations import get_db
        import uuid as _uuid

        sim_id = _uuid.uuid4()

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.flush = AsyncMock()
            session.delete = AsyncMock()

            def track_add(obj):
                if obj.__class__.__name__ == "Simulation":
                    obj.id = sim_id

            session.add = MagicMock(side_effect=track_add)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar.return_value = 0
            mock_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(return_value=mock_result)

            yield session

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.post(
                "/api/simulations",
                json={"deck_mode": "none", "game_mode": "hh"},
            )
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        mock_celery.delay.assert_called_once()


class TestGetSimulation:
    """Tests for GET /api/simulations/{id}."""

    def test_nonexistent_id_returns_404(self, client, mock_celery):
        from app.api.simulations import get_db

        async def override_db():
            session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{uuid.uuid4()}")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_invalid_uuid_returns_422(self, client, mock_celery):
        resp = client.get("/api/simulations/not-a-uuid")
        assert resp.status_code == 422

    def test_existing_simulation_returns_200(self, client, mock_celery):
        from app.api.simulations import get_db
        import uuid as _uuid

        sim_id = _uuid.uuid4()

        # Build a mock Simulation object
        mock_sim = MagicMock()
        mock_sim.id = sim_id
        mock_sim.status = "pending"
        mock_sim.game_mode = "hh"
        mock_sim.deck_mode = "none"
        mock_sim.deck_locked = False
        mock_sim.num_rounds = 2
        mock_sim.rounds_completed = 0
        mock_sim.matches_per_opponent = 5
        mock_sim.total_matches = 0
        mock_sim.target_win_rate = 60
        mock_sim.final_win_rate = None
        mock_sim.user_deck_name = None
        mock_sim.starred = False
        mock_sim.error_message = None
        mock_sim.started_at = None
        mock_sim.completed_at = None
        mock_sim.created_at = None

        async def override_db():
            session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_sim
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(sim_id)
        assert data["status"] == "pending"
