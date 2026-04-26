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
        """True for Tera Pokémon. No Tera Pokémon are in the current card pool."""
        return "tera" in self.name.lower() or "tera" in self.stage.lower()

    @property
    def prize_value(self) -> int:
        return 2 if self.is_ex else 1
