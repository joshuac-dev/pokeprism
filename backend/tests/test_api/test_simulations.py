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
        assert obj.target_mode == "aggregate"

    def test_target_mode_per_opponent_accepted(self):
        obj = SimulationCreate(**self._valid_payload(target_mode="per_opponent"))
        assert obj.target_mode == "per_opponent"

    def test_invalid_target_mode_raises(self):
        with pytest.raises(Exception):
            SimulationCreate(**self._valid_payload(target_mode="by_prize_cards"))

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

    def test_no_deck_mode_builds_deck_and_enqueues(self, mock_celery):
        from app.api.simulations import get_db
        from app.coach.deck_builder import DeckBuildResult
        import uuid as _uuid

        sim_id = _uuid.uuid4()
        added_objects = []

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.flush = AsyncMock()
            session.delete = AsyncMock()

            def track_add(obj):
                if obj.__class__.__name__ == "Simulation":
                    obj.id = sim_id
                if obj.__class__.__name__ == "Deck" and obj.id is None:
                    obj.id = _uuid.uuid4()
                added_objects.append(obj)

            session.add = MagicMock(side_effect=track_add)
            mock_result = MagicMock()
            mock_result.scalar.return_value = 0
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        class FakeBuilder:
            def __init__(self, *args, **kwargs):
                pass

            def build_from_scratch(self):
                from app.cards.models import CardDefinition
                card = CardDefinition(
                    tcgdex_id="sv06-128", name="Dreepy", set_abbrev="TWM",
                    set_number="128", category="Pokemon", stage="Basic",
                )
                return DeckBuildResult(deck=[card], metadata={"mode": "none"})

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with (
            patch("app.api.simulations.ensure_deck_cards_in_db", new=AsyncMock()),
            patch("app.api.simulations._load_available_card_defs", new=AsyncMock(return_value=[])),
            patch("app.api.simulations.DeckBuilder", FakeBuilder),
            patch("app.api.simulations.count_deck_cards", side_effect=lambda text: 60 if text else 0),
            patch("app.api.simulations._check_deck_coverage", new=AsyncMock(return_value=[])),
            TestClient(app) as c,
        ):
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_mode": "none",
                    "game_mode": "hh",
                    "opponent_deck_texts": [_MINIMAL_DECK_60],
                },
            )
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        assert resp.json()["deck_build"]["mode"] == "none"
        created_sim = next(obj for obj in added_objects if obj.__class__.__name__ == "Simulation")
        assert created_sim.deck_mode == "none"
        assert created_sim.user_deck_id is not None
        mock_celery.delay.assert_called_once()

    def test_partial_deck_mode_builds_deck_and_enqueues(self, mock_celery):
        from app.api.simulations import get_db
        from app.coach.deck_builder import DeckBuildResult
        import uuid as _uuid

        sim_id = _uuid.uuid4()
        added_objects = []

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.flush = AsyncMock()
            session.delete = AsyncMock()

            def track_add(obj):
                if obj.__class__.__name__ == "Simulation":
                    obj.id = sim_id
                if obj.__class__.__name__ == "Deck" and obj.id is None:
                    obj.id = _uuid.uuid4()
                added_objects.append(obj)

            session.add = MagicMock(side_effect=track_add)
            mock_result = MagicMock()
            mock_result.scalar.return_value = 0
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        class FakeBuilder:
            def __init__(self, *args, **kwargs):
                pass

            def complete_deck(self, partial):
                from app.cards.models import CardDefinition
                card = CardDefinition(
                    tcgdex_id="sv06-128", name="Dreepy", set_abbrev="TWM",
                    set_number="128", category="Pokemon", stage="Basic",
                )
                return DeckBuildResult(deck=[card], metadata={"mode": "partial", "cards_preserved": ["sv06-128"]})

        partial_text = "4 Dreepy sv06-128"

        from app.main import create_app
        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        from fastapi.testclient import TestClient
        with (
            patch("app.api.simulations.ensure_deck_cards_in_db", new=AsyncMock()),
            patch("app.api.simulations._load_available_card_defs", new=AsyncMock(return_value=[])),
            patch("app.api.simulations._load_deck_defs_from_text", new=AsyncMock(return_value=[])),
            patch("app.api.simulations.DeckBuilder", FakeBuilder),
            patch("app.api.simulations.count_deck_cards", side_effect=lambda text: 4 if text == partial_text else (60 if text else 0)),
            patch("app.api.simulations._check_deck_coverage", new=AsyncMock(return_value=[])),
            patch("app.api.simulations._get_deck_name_from_gemma", new=AsyncMock(return_value=None)),
            TestClient(app) as c,
        ):
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_text": partial_text,
                    "deck_mode": "partial",
                    "game_mode": "hh",
                    "opponent_deck_texts": [_MINIMAL_DECK_60],
                },
            )
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        assert resp.json()["deck_build"]["mode"] == "partial"
        created_sim = next(obj for obj in added_objects if obj.__class__.__name__ == "Simulation")
        assert created_sim.deck_mode == "partial"
        mock_celery.delay.assert_called_once()

    def test_invalid_builder_request_does_not_enqueue(self, client, mock_celery):
        resp = client.post(
            "/api/simulations",
            json={"deck_mode": "partial", "game_mode": "hh", "deck_text": ""},
        )

        assert resp.status_code == 422
        mock_celery.delay.assert_not_called()

    def test_target_mode_is_persisted_from_create_payload(self, mock_celery):
        """The setup UI's target_mode control must reach the Simulation row."""
        from app.api.simulations import get_db
        import uuid as _uuid

        sim_id = _uuid.uuid4()
        added_objects = []

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.flush = AsyncMock()
            session.delete = AsyncMock()

            def track_add(obj):
                if obj.__class__.__name__ == "Simulation":
                    obj.id = sim_id
                added_objects.append(obj)

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
        with (
            patch("app.api.simulations.ensure_deck_cards_in_db", new=AsyncMock()),
            patch("app.api.simulations._check_deck_coverage", new=AsyncMock(return_value=[])),
            patch("app.api.simulations._get_deck_name_from_gemma", new=AsyncMock(return_value=None)),
            TestClient(app) as c,
        ):
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_text": _MINIMAL_DECK_60,
                    "opponent_deck_texts": [_MINIMAL_DECK_60],
                    "deck_mode": "full",
                    "game_mode": "hh",
                    "target_mode": "per_opponent",
                },
            )
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        created_sim = next(obj for obj in added_objects if obj.__class__.__name__ == "Simulation")
        assert created_sim.target_mode == "per_opponent"

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
        with (
            patch("app.api.simulations.ensure_deck_cards_in_db", new=AsyncMock()),
            patch("app.api.simulations._check_deck_coverage", new=AsyncMock(return_value=[])),
            patch("app.api.simulations._get_deck_name_from_gemma", new=AsyncMock(return_value=None)),
            TestClient(app) as c,
        ):
            resp = c.post(
                "/api/simulations",
                json={
                    "deck_text": _MINIMAL_DECK_60,
                    "opponent_deck_texts": [_MINIMAL_DECK_60],
                    "deck_mode": "full",
                    "game_mode": "hh",
                },
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


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/events
# ---------------------------------------------------------------------------

class TestGetSimulationEvents:
    """Tests for GET /api/simulations/:id/events."""

    def _make_events_session(self, sim_id, events, total):
        """Session mock that returns sim_id for existence check, events, and total."""
        import uuid as _uuid

        session = AsyncMock()
        session.commit = AsyncMock()

        call_count = {"n": 0}

        def make_result(value=None, rows=None):
            m = MagicMock()
            m.scalar_one_or_none.return_value = value
            m.scalar.return_value = value
            m.all.return_value = rows or []
            return m

        async def _execute(query, *a, **kw):
            call_count["n"] += 1
            n = call_count["n"]
            if n == 1:
                # existence check
                return make_result(sim_id)
            elif n == 2:
                # total count
                return make_result(total)
            elif n == 3:
                # events query
                return make_result(rows=events)
            else:
                # has_more count
                return make_result(0)

        session.execute = AsyncMock(side_effect=_execute)
        return session

    def test_missing_simulation_returns_404(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{uuid.uuid4()}/events")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_invalid_uuid_returns_422(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/not-a-uuid/events")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_empty_simulation_returns_empty_events(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()

        async def override_db():
            yield self._make_events_session(sim_id, [], 0)

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/events")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    def test_returns_events_with_expected_shape(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        match_id = uuid.uuid4()

        # Build a mock row that looks like a SQLAlchemy Row
        mock_row = MagicMock()
        mock_row.id = 999
        mock_row.event_type = "energy_attached"
        mock_row.turn = 3
        mock_row.player = "p1"
        mock_row.data = {"card": "sv06-130"}
        mock_row.round_number = 1
        mock_row.match_id = match_id
        mock_row.p1_deck_name = "Dragapult ex Deck"
        mock_row.p2_deck_name = "TR Mewtwo Deck"

        async def override_db():
            yield self._make_events_session(sim_id, [mock_row], 1)

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/events")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        ev = data["events"][0]
        assert ev["id"] == 999
        assert ev["type"] == "match_event"
        assert ev["event_type"] == "energy_attached"
        assert ev["round_number"] == 1
        assert ev["p1_deck_name"] == "Dragapult ex Deck"
        assert ev["turn"] == 3


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/decisions
# ---------------------------------------------------------------------------

class TestGetSimulationDecisions:
    """Tests for GET /api/simulations/:id/decisions."""

    def test_invalid_uuid_returns_422(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/not-a-uuid/decisions")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_no_decisions_returns_empty(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()

        async def override_db():
            session = AsyncMock()
            call_n = {"n": 0}

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                m.scalar.return_value = 0
                m.scalars.return_value.all.return_value = []
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/decisions")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["decisions"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/simulations/{id}/cancel
# ---------------------------------------------------------------------------

class TestCancelSimulation:
    """Tests for POST /api/simulations/:id/cancel."""

    def test_invalid_uuid_returns_422(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post("/api/simulations/not-a-uuid/cancel")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_missing_simulation_returns_404(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post(f"/api/simulations/{uuid.uuid4()}/cancel")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_cancel_running_simulation_succeeds(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        mock_sim = MagicMock()
        mock_sim.id = sim_id
        mock_sim.status = "running"

        async def override_db():
            session = AsyncMock()
            session.commit = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = mock_sim
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with patch("app.api.simulations.redis_module.Redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.from_url.return_value = mock_r
            with TestClient(app) as c:
                resp = c.post(f"/api/simulations/{sim_id}/cancel")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is True
        assert data["id"] == str(sim_id)
        assert mock_sim.status == "cancelled"

    def test_cancel_completed_simulation_returns_409(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        mock_sim = MagicMock()
        mock_sim.id = sim_id
        mock_sim.status = "complete"

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = mock_sim
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.post(f"/api/simulations/{sim_id}/cancel")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/matches
# ---------------------------------------------------------------------------

class TestGetSimulationMatches:
    """Tests for GET /api/simulations/:id/matches."""

    def test_invalid_uuid_returns_422(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/not-a-uuid/matches")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_missing_simulation_returns_404(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{uuid.uuid4()}/matches")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_simulation_with_no_matches_returns_empty_list(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    # existence check
                    m.scalar_one_or_none.return_value = sim_id
                else:
                    m.scalars.return_value.all.return_value = []
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/matches")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json() == []

    def test_matches_returned_with_expected_fields(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        match_id = uuid.uuid4()
        opp_id = uuid.uuid4()

        mock_match = MagicMock()
        mock_match.id = match_id
        mock_match.round_number = 1
        mock_match.winner = "p1"
        mock_match.win_condition = "prizes"
        mock_match.total_turns = 15
        mock_match.p1_prizes_taken = 6
        mock_match.p2_prizes_taken = 2
        mock_match.p1_deck_name = "Dragapult"
        mock_match.p2_deck_name = "TR Mewtwo"
        mock_match.opponent_deck_id = opp_id

        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar_one_or_none.return_value = sim_id
                else:
                    m.scalars.return_value.all.return_value = [mock_match]
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/matches")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        m = data[0]
        assert m["id"] == str(match_id)
        assert m["round_number"] == 1
        assert m["winner"] == "p1"
        assert m["win_condition"] == "prizes"
        assert m["total_turns"] == 15
        assert m["p1_prizes_taken"] == 6
        assert m["p2_prizes_taken"] == 2
        assert m["p1_deck_name"] == "Dragapult"
        assert m["p2_deck_name"] == "TR Mewtwo"
        assert m["opponent_deck_id"] == str(opp_id)


# ---------------------------------------------------------------------------
# GET /api/simulations/{id}/prize-race
# ---------------------------------------------------------------------------

class TestGetSimulationPrizeRace:
    """Tests for GET /api/simulations/:id/prize-race."""

    def test_invalid_uuid_returns_422(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/not-a-uuid/prize-race")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_missing_simulation_returns_404(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        async def override_db():
            session = AsyncMock()
            m = MagicMock()
            m.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=m)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{uuid.uuid4()}/prize-race")
        app.fastapi_app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_simulation_with_no_matches_returns_empty(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar_one_or_none.return_value = sim_id
                elif call_n["n"] == 2:
                    # match query returns empty
                    m.scalars.return_value.all.return_value = []
                else:
                    m.all.return_value = []
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/prize-race")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["matches"] == []
        assert data["average"] == []

    def test_prize_race_returns_expected_shape(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim_id = uuid.uuid4()
        match_id = uuid.uuid4()

        mock_match = MagicMock()
        mock_match.id = match_id
        mock_match.round_number = 1
        mock_match.p1_deck_name = "Dragapult"
        mock_match.p2_deck_name = "TR Mewtwo"
        mock_match.total_turns = 10
        mock_match.created_at = None

        mock_event = MagicMock()
        mock_event.match_id = match_id
        mock_event.turn = 4
        mock_event.data = {"count": 1, "taking_player": "p1", "remaining": 5}

        call_n = {"n": 0}

        async def override_db():
            session = AsyncMock()

            async def _exec(*a, **kw):
                call_n["n"] += 1
                m = MagicMock()
                if call_n["n"] == 1:
                    m.scalar_one_or_none.return_value = sim_id
                elif call_n["n"] == 2:
                    m.scalars.return_value.all.return_value = [mock_match]
                else:
                    m.all.return_value = [mock_event]
                return m

            session.execute = AsyncMock(side_effect=_exec)
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get(f"/api/simulations/{sim_id}/prize-race")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["matches"]) == 1
        pm = data["matches"][0]
        assert pm["match_id"] == str(match_id)
        assert pm["round_number"] == 1
        assert len(pm["turns"]) > 0
        assert "average" in data
        # Average should have entries up to max_turn
        assert len(data["average"]) > 0
        assert "turn" in data["average"][0]
        assert "p1_avg" in data["average"][0]
        assert "p2_avg" in data["average"][0]


# ---------------------------------------------------------------------------
# GET /api/simulations/ (paginated list)
# ---------------------------------------------------------------------------

class TestListSimulations:
    """Tests for GET /api/simulations/ with server-side pagination/filtering."""

    def _make_list_session(self, sims, total, opponents=None):
        """Build a mock DB session for list_simulations."""
        call_n = {"n": 0}

        def _make(value=None, rows=None):
            m = MagicMock()
            m.scalar.return_value = value
            m.scalars.return_value.all.return_value = rows or []
            return m

        async def _exec(*a, **kw):
            call_n["n"] += 1
            n = call_n["n"]
            if n == 1:
                return _make(value=total)      # COUNT query
            elif n == 2:
                return _make(rows=sims)        # SELECT sims
            else:
                return _make(rows=opponents or [])  # opponents join

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=_exec)
        return session

    def _make_sim(self, sim_id=None, status="complete", game_mode="hh",
                  deck_mode="none", user_deck_name="Test Deck",
                  final_win_rate=60, starred=False):
        import uuid as _uuid
        m = MagicMock()
        m.id = sim_id or _uuid.uuid4()
        m.status = status
        m.game_mode = game_mode
        m.deck_mode = deck_mode
        m.num_rounds = 3
        m.rounds_completed = 3
        m.total_matches = 30
        m.final_win_rate = final_win_rate
        m.user_deck_name = user_deck_name
        m.starred = starred
        m.created_at = None
        return m

    def test_returns_paginated_envelope(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim = self._make_sim()
        session = self._make_list_session([sim], total=1)

        async def override_db():
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_item_includes_opponents_field(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim = self._make_sim()
        session = self._make_list_session([sim], total=1)

        async def override_db():
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/")
        app.fastapi_app.dependency_overrides.clear()

        assert "opponents" in resp.json()["items"][0]

    def test_win_rate_returned_as_fraction(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        sim = self._make_sim(final_win_rate=65)
        session = self._make_list_session([sim], total=1)

        async def override_db():
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.json()["items"][0]["final_win_rate"] == pytest.approx(0.65)

    def test_empty_results_returns_zero_total(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        session = self._make_list_session([], total=0)

        async def override_db():
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/")
        app.fastapi_app.dependency_overrides.clear()

        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_per_page_capped_at_100(self):
        from app.api.simulations import get_db
        from app.main import create_app
        from fastapi.testclient import TestClient

        session = self._make_list_session([], total=0)

        async def override_db():
            yield session

        app = create_app()
        app.fastapi_app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            resp = c.get("/api/simulations/?per_page=9999")
        app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["per_page"] == 25  # capped to default
