"""Card data models (Pydantic) for internal representation.

These mirror the TCGDex response shape but are typed and validated.
In Phase 1 these live in memory; Phase 4 moves them to PostgreSQL.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class AttackCost(BaseModel):
    """Energy cost for a single attack (parsed from TCGDex 'cost' list)."""
    types: list[str] = Field(default_factory=list)  # e.g. ["Psychic", "Colorless"]


class AttackDef(BaseModel):
    name: str = ""
    cost: list[str] = Field(default_factory=list)   # e.g. ["Psychic", "Colorless"]
    damage: str = ""                                 # "60", "60+", "30×", ""
    effect: str = ""                                 # Raw card text


class AbilityDef(BaseModel):
    name: str = ""
    type: str = ""    # "Ability", "Poké-Power", "Poké-Body"
    effect: str = ""  # Raw card text


class WeaknessDef(BaseModel):
    type: str = ""    # e.g. "Darkness"
    value: str = ""   # e.g. "×2"


class ResistanceDef(BaseModel):
    type: str = ""    # e.g. "Fighting"
    value: str = ""   # e.g. "-30"


# Hardcoded set of all Tera Pokémon ex card IDs in the pool
_TERA_POKEMON_IDS: frozenset[str] = frozenset({
    "sv05-060",    # Wugtrio ex
    "sv05-108",    # Farigiraf ex
    "sv06-025",    # Teal Mask Ogerpon ex
    "sv06-029",    # Magcargo ex
    "sv06-040",    # Hearthflame Mask Ogerpon ex
    "sv06-064",    # Wellspring Mask Ogerpon ex
    "sv06-106",    # Greninja ex
    "sv06-112",    # Cornerstone Mask Ogerpon ex
    "sv06-130",    # Dragapult ex
    "sv06.5-015",  # Revavroom ex
    "sv07-028",    # Cinderace ex
    "sv07-032",    # Lapras ex
    "sv07-041",    # Greninja ex (alt)
    "sv07-051",    # Galvantula ex
    "sv07-128",    # Terapagos ex
    "sv08-036",    # Ceruledge ex
    "sv08-057",    # Pikachu ex
    "sv08-086",    # Sylveon ex
    "sv08-091",    # Palossand ex
    "sv08-106",    # Flygon ex
    "sv08-119",    # Hydreigon ex
    "sv08-133",    # Alolan Exeggutor ex
    "sv08-142",    # Tatsugiri ex
    "sv08-159",    # Cyclizar ex
    "sv08.5-006",  # Leafeon ex
    "sv08.5-012",  # Teal Mask Ogerpon ex (alt)
    "sv08.5-014",  # Flareon ex
    "sv08.5-017",  # Hearthflame Mask Ogerpon ex (alt)
    "sv08.5-023",  # Vaporeon ex
    "sv08.5-026",  # Glaceon ex
    "sv08.5-027",  # Wellspring Mask Ogerpon ex (alt)
    "sv08.5-028",  # Pikachu ex (alt)
    "sv08.5-030",  # Jolteon ex
    "sv08.5-034",  # Espeon ex
    "sv08.5-041",  # Sylveon ex (alt)
    "sv08.5-058",  # Cornerstone Mask Ogerpon ex (alt)
    "sv08.5-060",  # Umbreon ex
    "sv08.5-073",  # Dragapult ex (alt)
    "sv08.5-075",  # Eevee ex
    "sv08.5-092",  # Terapagos ex (alt)
    "sv10.5w-067", # Hydreigon ex (alt)
    "svp-106",     # Pikachu ex (promo)
})


class CardDefinition(BaseModel):
    """Parsed card definition sourced from TCGDex.

    tcgdex_id is the canonical identifier: e.g. "sv06-130" (Dragapult ex TWM 130).
    """

    tcgdex_id: str                         # e.g. "sv06-130"
    name: str
    set_abbrev: str                        # e.g. "TWM"
    set_number: str                        # e.g. "130"

    # Broad category
    category: str = ""                     # "Pokemon", "Trainer", "Energy"
    subcategory: str = ""                  # "Item", "Supporter", "Stadium", "Tool",
                                           # "Basic", "Special"
    # Pokémon attributes
    hp: Optional[int] = None
    types: list[str] = Field(default_factory=list)     # ["Psychic"]
    evolve_from: Optional[str] = None
    stage: str = ""                        # "Basic", "Stage1", "Stage2", "ex", …

    attacks: list[AttackDef] = Field(default_factory=list)
    abilities: list[AbilityDef] = Field(default_factory=list)
    weaknesses: list[WeaknessDef] = Field(default_factory=list)
    resistances: list[ResistanceDef] = Field(default_factory=list)
    retreat_cost: int = 0

    # Energy-specific
    energy_provides: list[str] = Field(default_factory=list)  # ["Fire"], ["Any"], …

    # Meta
    regulation_mark: Optional[str] = None
    rarity: Optional[str] = None
    image_url: Optional[str] = None

    # Full raw response — kept for future use / debugging
    raw_tcgdex: dict = Field(default_factory=dict)

    # Derived helpers ──────────────────────────────────────────────────────────

    @property
    def is_pokemon(self) -> bool:
        return self.category.lower() == "pokemon"

    @property
    def is_trainer(self) -> bool:
        return self.category.lower() == "trainer"

    @property
    def is_energy(self) -> bool:
        return self.category.lower() == "energy"

    @property
    def is_basic_pokemon(self) -> bool:
        return self.is_pokemon and self.stage.lower() == "basic"

    @property
    def is_ex(self) -> bool:
        """True for ex, V, VSTAR, VMAX — cards that give 2 prizes on KO."""
        s = self.stage.lower()
        return s in {"ex", "v", "vstar", "vmax", "gx"} or " ex" in self.name.lower()

    @property
    def has_rule_box(self) -> bool:
        """True for rule-box Pokémon (ex/V/VSTAR/VMAX/GX).

        Used by Poké Pad (search non-rule-box), Lana's Aid (put non-rule-box),
        and Brave Bangle (+30 to ex for non-rule-box attackers).
        """
        return self.is_ex

    @property
    def is_tera(self) -> bool:
        return self.tcgdex_id in _TERA_POKEMON_IDS or "tera" in self.name.lower()

    @property
    def prize_value(self) -> int:
        return 2 if self.is_ex else 1
