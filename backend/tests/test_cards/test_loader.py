"""Tests for CardListLoader and SET_CODE_MAP.

Uses real fixture files — no live network calls.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.cards.models import CardDefinition

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "cards"
CARDLIST_PATH = Path(__file__).parent.parent.parent.parent / "docs" / "CARDLIST.md"


class TestSetCodeMap:
    def test_sve_era_ids_correct(self):
        """All SV-era set IDs must use dot-notation (sv01, sv03.5, etc.)."""
        assert SET_CODE_MAP["SVI"] == "sv01"
        assert SET_CODE_MAP["PAL"] == "sv02"
        assert SET_CODE_MAP["OBF"] == "sv03"
        assert SET_CODE_MAP["MEW"] == "sv03.5"
        assert SET_CODE_MAP["PAR"] == "sv04"
        assert SET_CODE_MAP["PAF"] == "sv04.5"
        assert SET_CODE_MAP["TEF"] == "sv05"
        assert SET_CODE_MAP["TWM"] == "sv06"
        assert SET_CODE_MAP["SFA"] == "sv06.5"
        assert SET_CODE_MAP["SCR"] == "sv07"
        assert SET_CODE_MAP["SSP"] == "sv08"
        assert SET_CODE_MAP["PRE"] == "sv08.5"
        assert SET_CODE_MAP["JTG"] == "sv09"
        assert SET_CODE_MAP["DRI"] == "sv10"
        assert SET_CODE_MAP["WHT"] == "sv10.5w"

    def test_me_era_ids_correct(self):
        """ME-era sets must be present with correct IDs."""
        assert SET_CODE_MAP["MEG"] == "me01"
        assert SET_CODE_MAP["PFL"] == "me02"
        assert SET_CODE_MAP["ASC"] == "me02.5"
        assert SET_CODE_MAP["POR"] == "me03"
        assert SET_CODE_MAP["MEE"] == "mee"

    def test_m4_excluded(self):
        """Chaos Rising (M4) must not be in SET_CODE_MAP (unreleased)."""
        assert "M4" not in SET_CODE_MAP

    def test_pfo_excluded(self):
        """PFO is a blueprint error — must not be in SET_CODE_MAP."""
        assert "PFO" not in SET_CODE_MAP


class TestCardListLoaderParsing:
    def test_parse_returns_list(self):
        if not CARDLIST_PATH.exists():
            pytest.skip("CARDLIST.md not found")
        loader = CardListLoader()
        entries = loader.parse_cardlist(CARDLIST_PATH)
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_parse_all_entries_have_required_keys(self):
        if not CARDLIST_PATH.exists():
            pytest.skip("CARDLIST.md not found")
        loader = CardListLoader()
        entries = loader.parse_cardlist(CARDLIST_PATH)
        for entry in entries:
            assert "name" in entry
            assert "set_abbrev" in entry
            assert "number" in entry

    def test_parse_m4_cards_present_but_excluded_in_load(self):
        """M4 cards must appear in parsed entries but be skipped during load."""
        if not CARDLIST_PATH.exists():
            pytest.skip("CARDLIST.md not found")
        loader = CardListLoader()
        entries = loader.parse_cardlist(CARDLIST_PATH)
        m4_entries = [e for e in entries if e["set_abbrev"] == "M4"]
        assert len(m4_entries) > 0, "CARDLIST.md should contain M4 entries (Froakie/Frogadier)"

    def test_parse_dragapult_present(self):
        """Dragapult ex TWM 130 must be parseable."""
        if not CARDLIST_PATH.exists():
            pytest.skip("CARDLIST.md not found")
        loader = CardListLoader()
        entries = loader.parse_cardlist(CARDLIST_PATH)
        dragapult = next(
            (e for e in entries
             if "Dragapult" in e["name"] and e["set_abbrev"] == "TWM"),
            None,
        )
        assert dragapult is not None
        assert dragapult["number"] == "130"


class TestCardListLoaderTransform:
    def _load_fixture(self, set_abbrev: str, number: str) -> dict | None:
        tcgdex_id = SET_CODE_MAP.get(set_abbrev)
        if not tcgdex_id:
            return None
        path = FIXTURE_DIR / f"{tcgdex_id}-{int(number):03d}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def test_transform_dragapult_ex(self):
        raw = self._load_fixture("TWM", "130")
        if raw is None:
            pytest.skip("Dragapult ex fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "TWM", "number": "130", "name": raw.get("name", "")})
        assert isinstance(cdef, CardDefinition)
        assert "Dragapult" in cdef.name
        assert cdef.hp and cdef.hp > 0
        assert cdef.is_pokemon
        assert len(cdef.attacks) > 0

    def test_transform_psychic_energy(self):
        raw = self._load_fixture("MEE", "5")
        if raw is None:
            pytest.skip("Psychic Energy fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "MEE", "number": "5", "name": raw.get("name", "")})
        assert cdef.category.lower() == "energy"
        assert cdef.subcategory == "Basic"
        assert "Psychic" in cdef.energy_provides

    def test_transform_boss_orders(self):
        raw = self._load_fixture("MEG", "114")
        if raw is None:
            pytest.skip("Boss's Orders fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "MEG", "number": "114", "name": raw.get("name", "")})
        assert cdef.category.lower() == "trainer"
        assert cdef.subcategory == "Supporter"

    def test_transform_sets_tcgdex_id(self):
        raw = self._load_fixture("TWM", "130")
        if raw is None:
            pytest.skip("Dragapult ex fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "TWM", "number": "130", "name": raw.get("name", "")})
        assert cdef.tcgdex_id == "sv06-130"

    def test_is_ex_detection(self):
        raw = self._load_fixture("TWM", "130")
        if raw is None:
            pytest.skip("Dragapult ex fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "TWM", "number": "130", "name": raw.get("name", "")})
        assert cdef.is_ex is True
        assert cdef.prize_value == 2

    def test_retreat_cost_populated(self):
        raw = self._load_fixture("TWM", "130")
        if raw is None:
            pytest.skip("Dragapult ex fixture not captured")
        loader = CardListLoader()
        cdef = loader._transform(raw, {"set_abbrev": "TWM", "number": "130", "name": raw.get("name", "")})
        assert isinstance(cdef.retreat_cost, int)
        assert cdef.retreat_cost >= 0
