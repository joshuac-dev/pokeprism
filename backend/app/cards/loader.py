"""Card-list parser and TCGDex card loader.

DEVIATIONS FROM BLUEPRINT (§7.3):
  1. SET_CODE_MAP values use actual TCGDex IDs (verified via /v2/en/sets):
       sv01 not sv1, sv03.5 not sv3pt5, sv08 not sv7pt5, etc.
  2. "DRI" maps to "sv10" (not "sv9" as blueprint had).
  3. "PFO" entry removed — blueprint's "PFO": "sv10" was both the wrong name
       (sv10 = Destined Rivals, not Perfect Order) and wrong ID. The correct
       entry for Perfect Order is "POR": "me03".
  4. Mega Evolution era sets added: MEG, PFL, MEE, WHT, ASC, POR.
  5. M4 (Chaos Rising) intentionally excluded — unreleased set.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.cards.models import (
    CardDefinition,
    AttackDef,
    AbilityDef,
    WeaknessDef,
    ResistanceDef,
)
from app.cards.tcgdex import TCGDexClient

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# PTCG set abbreviation → TCGDex set ID
# Verified against https://api.tcgdex.net/v2/en/sets  (2025-01)
# ──────────────────────────────────────────────────────────────────────────────
SET_CODE_MAP: dict[str, str] = {
    # Scarlet & Violet era
    "SVI":  "sv01",    # Scarlet & Violet Base
    "PAL":  "sv02",    # Paldea Evolved
    "OBF":  "sv03",    # Obsidian Flames
    "MEW":  "sv03.5",  # 151
    "PAR":  "sv04",    # Paradox Rift
    "PAF":  "sv04.5",  # Paldean Fates
    "TEF":  "sv05",    # Temporal Forces
    "TWM":  "sv06",    # Twilight Masquerade
    "SFA":  "sv06.5",  # Shrouded Fable
    "SCR":  "sv07",    # Stellar Crown
    "SSP":  "sv08",    # Surging Sparks      ← blueprint had "sv7pt5" (wrong)
    "PRE":  "sv08.5",  # Prismatic Evolutions ← blueprint had "sv8"    (wrong)
    "JTG":  "sv09",    # Journey Together    ← blueprint had "sv8pt5"  (wrong)
    "DRI":  "sv10",    # Destined Rivals     ← blueprint had "sv9"     (wrong)
    "WHT":  "sv10.5w", # White Flare         (new)
    "BLK":  "sv10.5b", # Black Bolt          (new)
    # Mega Evolution era
    "MEG":  "me01",    # Mega Evolution
    "PFL":  "me02",    # Phantasmal Flames
    "ASC":  "me02.5",  # Ascended Heroes
    "POR":  "me03",    # Perfect Order       ← blueprint had "PFO":"sv10" (wrong×2)
    "MEE":  "mee",     # Mega Evolution Energy
    "MEP":  "mep",     # MEP Black Star Promos
    # NOTE: "M4" (Chaos Rising) intentionally absent — not yet released.
    #       Cards with set_abbrev "M4" are silently skipped.
    # Promos
    "PR-SV": "svp",    # Scarlet & Violet promos (e.g. Pecharunt PR-SV 149 → svp-149)
}

# Sets we know exist in TCGDex but that also appear in CARDLIST via alternate IDs
_EXTRA_ALIASES: dict[str, str] = {
    "SVE": "sve",  # Scarlet & Violet Energy (base set energies)
}
SET_CODE_MAP.update(_EXTRA_ALIASES)

# Promo set codes that use a different TCGDex format
_PROMO_PREFIXES = {"PR-SV"}  # e.g. "Pecharunt PR-SV 149"


class CardListLoader:
    """Parse a project card list and resolve each entry against TCGDex.

    Phase 1 pipeline (no DB):
      1. Parse docs/POKEMON_MASTER_LIST.md → list of (name, set_abbrev, number) tuples
      2. Map set_abbrev to TCGDex set ID
      3. Fetch full card data from TCGDex
      4. Transform into CardDefinition objects
      5. Return dict keyed by tcgdex_id for in-memory use

    Phase 4 adds a DB upsert step via sync_to_database().
    """

    # Cards whose set is not in SET_CODE_MAP and should be skipped (not error)
    _KNOWN_EXCLUDED_SETS = {"M4"}

    def parse_cardlist(self, path: Path) -> list[dict]:
        """Parse a card-list markdown file into raw entry dicts.

        Handles:
          • Multi-word card names: "Boss's Orders MEG 114"
          • Promo codes: "Pecharunt PR-SV 149"
          • Blank/comment/header lines
          • Numbered list format (leading "123. ")
        """
        entries: list[dict] = []
        pattern = re.compile(
            r"^(?:\d+\.\s+)?(.+?)\s+([A-Z0-9][\w.-]*)\s+(\d+)$"
        )
        with open(path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                m = pattern.match(line)
                if m:
                    entries.append(
                        {
                            "name": m.group(1).strip(),
                            "set_abbrev": m.group(2),
                            "number": m.group(3),
                        }
                    )
                elif line.startswith("|") or line.startswith("-") or line.startswith(">"):
                    continue
                else:
                    logger.debug("Unrecognised CARDLIST line, skipping: %r", line)
        return entries

    async def load_all(
        self,
        cardlist_path: Path,
        tcgdex: TCGDexClient,
    ) -> dict[str, CardDefinition]:
        """Fetch every card in a project card-list file from TCGDex.

        Returns a dict[tcgdex_id → CardDefinition].
        Logs a warning and skips any card whose set is unknown or missing.
        Never raises on individual card failures (live-data-first principle).
        """
        entries = self.parse_cardlist(cardlist_path)
        card_defs: dict[str, CardDefinition] = {}

        for entry in entries:
            abbrev = entry["set_abbrev"]

            if abbrev in self._KNOWN_EXCLUDED_SETS:
                logger.info(
                    "Skipping %s %s %s — set excluded from Phase 1 pool",
                    entry["name"], abbrev, entry["number"],
                )
                continue

            set_id = SET_CODE_MAP.get(abbrev)
            if set_id is None:
                logger.warning(
                    "Unknown set abbreviation '%s' for card '%s %s'. "
                    "Add it to SET_CODE_MAP in loader.py.",
                    abbrev, entry["name"], entry["number"],
                )
                continue

            try:
                raw = await tcgdex.get_card(set_id, entry["number"])
                card_def = self._transform(raw, entry)
                card_defs[card_def.tcgdex_id] = card_def
                logger.debug("Loaded: %s (%s)", card_def.name, card_def.tcgdex_id)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch %s %s %s from TCGDex: %s",
                    entry["name"], abbrev, entry["number"], exc,
                )

        logger.info("Loaded %d card definitions from TCGDex", len(card_defs))
        return card_defs

    # ──────────────────────────────────────────────────────────────────────────
    # Transform raw TCGDex response → CardDefinition
    # ──────────────────────────────────────────────────────────────────────────

    def _transform(self, raw: dict, entry: dict) -> CardDefinition:
        """Map a raw TCGDex card dict to our internal CardDefinition."""
        category = (raw.get("category") or "").capitalize()
        stage = raw.get("stage") or ""
        subcategory = self._derive_subcategory(raw, category)

        attacks = [
            AttackDef(
                name=a.get("name", ""),
                cost=a.get("cost") or [],
                damage=str(a.get("damage") or ""),
                effect=a.get("effect") or "",
            )
            for a in (raw.get("attacks") or [])
        ]

        abilities = [
            AbilityDef(
                name=ab.get("name", ""),
                type=ab.get("type", "Ability"),
                effect=ab.get("effect") or "",
            )
            for ab in (raw.get("abilities") or [])
        ]

        weaknesses = [
            WeaknessDef(type=w.get("type", ""), value=w.get("value", ""))
            for w in (raw.get("weaknesses") or [])
        ]
        resistances = [
            ResistanceDef(type=r.get("type", ""), value=r.get("value", ""))
            for r in (raw.get("resistances") or [])
        ]

        retreat_raw = raw.get("retreat")
        retreat_cost = int(retreat_raw) if retreat_raw is not None else 0

        energy_provides = self._derive_energy_provides(raw, category, subcategory)

        return CardDefinition(
            tcgdex_id=raw.get("id", ""),
            name=raw.get("name", entry["name"]),
            set_abbrev=entry["set_abbrev"],
            set_number=entry["number"],
            category=category,
            subcategory=subcategory,
            hp=raw.get("hp"),
            types=raw.get("types") or [],
            evolve_from=raw.get("evolveFrom"),
            stage=stage,
            attacks=attacks,
            abilities=abilities,
            weaknesses=weaknesses,
            resistances=resistances,
            retreat_cost=retreat_cost,
            energy_provides=energy_provides,
            regulation_mark=raw.get("regulationMark"),
            rarity=raw.get("rarity"),
            image_url=raw.get("image"),
            raw_tcgdex=raw,
        )

    @staticmethod
    def _derive_subcategory(raw: dict, category: str) -> str:
        """Derive Trainer subcategory or Energy subcategory from TCGDex fields.

        TCGDex uses 'trainerType' for trainers (e.g. "Supporter", "Item", "Stadium", "Tool")
        and 'energyType' for energy ("Normal" = Basic, anything else = Special).
        Falls back to the 'stage' field for older sets that use it.
        """
        if category.lower() == "trainer":
            # Primary: trainerType field (me-era and sv-era sets)
            trainer_type = (raw.get("trainerType") or "").capitalize()
            if trainer_type in {"Item", "Supporter", "Stadium", "Tool"}:
                return trainer_type
            # Fallback: TCGDex puts subcategory in "stage" for some sets
            stage = (raw.get("stage") or "").lower()
            if stage in {"item", "supporter", "stadium", "tool"}:
                return stage.capitalize()
            return "Item"
        if category.lower() == "energy":
            energy_type = (raw.get("energyType") or "").lower()
            if energy_type == "special":
                return "Special"
            # For "Normal" energyType, confirm the name actually matches a basic type.
            # Cards like Prism Energy have energyType="Normal" but are Special in gameplay.
            basic_types = {
                "grass", "fire", "water", "lightning", "psychic",
                "fighting", "darkness", "metal", "dragon", "fairy",
            }
            name_lower = (raw.get("name") or "").lower()
            if any(t in name_lower for t in basic_types):
                return "Basic"
            # Fallback: check stage field (older data)
            stage = (raw.get("stage") or "").lower()
            name_lower_check = (raw.get("name") or "").lower()
            if "basic" in stage or "basic" in name_lower_check:
                return "Basic"
            return "Special"
        return ""

    @staticmethod
    def _derive_energy_provides(raw: dict, category: str, subcategory: str) -> list[str]:
        """Determine what energy type(s) a card provides when attached.

        Basic Energy: provides its own type (inferred from name/types).
        Special Energy: left empty here; Phase 2 effect handlers fill in the
                        actual logic (e.g. Prism Energy, Team Rocket's Energy).
        Non-energy cards: empty list.
        """
        if category.lower() != "energy":
            return []
        if subcategory == "Basic":
            name = (raw.get("name") or "").lower()
            for etype in (
                "Grass", "Fire", "Water", "Lightning", "Psychic",
                "Fighting", "Darkness", "Metal", "Dragon", "Fairy",
            ):
                if etype.lower() in name:
                    return [etype]
            # Fallback: use types list
            types = raw.get("types") or []
            if types:
                return [types[0]]
        # Special energy — populated by effect registry in Phase 2
        return []
