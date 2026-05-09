from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.observed_play.schemas import ArchetypeLabel, DeckArchetypeLabelPreview


def _client():
    from app.main import create_app
    return TestClient(create_app())


class TestDeckArchetypeLabelPreview:
    def test_deck_preview_returns_labels(self):
        from app.api.decks import get_db

        client = _client()
        deck_id = str(uuid.uuid4())
        preview = DeckArchetypeLabelPreview(
            deck_id=deck_id,
            deck_name="Dragapult",
            labels=[
                ArchetypeLabel(
                    label="Dragapult ex",
                    canonical_key="dragapult-ex",
                    label_type="archetype",
                    source="deck_cards",
                    confidence=0.92,
                )
            ],
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
                "app.api.decks.preview_deck_archetype_labels",
                new=AsyncMock(return_value=preview),
            ) as mock_preview:
                resp = client.get(f"/api/decks/{deck_id}/archetype-label-preview")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["deck_id"] == deck_id
        assert data["labels"][0]["canonical_key"] == "dragapult-ex"
        assert data["source"] == "deck_cards"
        mock_preview.assert_awaited_once()
        session.add.assert_not_called()
        session.commit.assert_not_awaited()
        session.flush.assert_not_awaited()

    def test_deck_preview_returns_404_for_missing_deck(self):
        from app.api.decks import get_db

        client = _client()
        deck_id = str(uuid.uuid4())

        async def override_db():
            yield AsyncMock()

        client.app.fastapi_app.dependency_overrides[get_db] = override_db
        try:
            with patch(
                "app.api.decks.preview_deck_archetype_labels",
                new=AsyncMock(return_value=None),
            ):
                resp = client.get(f"/api/decks/{deck_id}/archetype-label-preview")
        finally:
            client.app.fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Deck not found"
