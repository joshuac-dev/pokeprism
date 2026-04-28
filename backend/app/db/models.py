"""SQLAlchemy ORM models — matches Appendix B schema in PROJECT.md."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, Column, ForeignKey, Integer, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Cards ──────────────────────────────────────────────────────────────────────

class Card(Base):
    __tablename__ = "cards"

    tcgdex_id       = Column(Text, primary_key=True)
    name            = Column(Text, nullable=False)
    set_abbrev      = Column(Text, nullable=False)
    set_number      = Column(Text, nullable=False)
    category        = Column(Text, nullable=False)  # pokemon / trainer / energy
    subcategory     = Column(Text)
    hp              = Column(Integer)
    types           = Column(JSONB, default=list)
    evolve_from     = Column(Text)
    stage           = Column(Text)
    attacks         = Column(JSONB, default=list)
    abilities       = Column(JSONB, default=list)
    weaknesses      = Column(JSONB, default=list)
    resistances     = Column(JSONB, default=list)
    retreat_cost    = Column(Integer, default=0)
    regulation_mark = Column(Text)
    rarity          = Column(Text)
    image_url       = Column(Text)
    raw_tcgdex      = Column(JSONB)
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                             onupdate=func.now())

    deck_cards      = relationship("DeckCard", back_populates="card")


# ── Decks ──────────────────────────────────────────────────────────────────────

class Deck(Base):
    __tablename__ = "decks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name        = Column(Text)
    archetype   = Column(Text)
    deck_text   = Column(Text, nullable=False)
    card_count  = Column(Integer, nullable=False, default=60)
    source      = Column(Text, default="user")
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())

    deck_cards  = relationship("DeckCard", back_populates="deck",
                               cascade="all, delete-orphan")
    simulations = relationship("Simulation",
                               foreign_keys="Simulation.user_deck_id",
                               back_populates="user_deck")


class DeckCard(Base):
    __tablename__ = "deck_cards"

    deck_id         = Column(UUID(as_uuid=True), ForeignKey("decks.id",
                             ondelete="CASCADE"), primary_key=True)
    card_tcgdex_id  = Column(Text, ForeignKey("cards.tcgdex_id"),
                             primary_key=True)
    quantity        = Column(Integer, nullable=False, default=1)

    deck            = relationship("Deck", back_populates="deck_cards")
    card            = relationship("Card", back_populates="deck_cards")


# ── Simulations ────────────────────────────────────────────────────────────────

class Simulation(Base):
    __tablename__ = "simulations"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    status               = Column(Text, nullable=False, default="pending")
    game_mode            = Column(Text, nullable=False)  # hh / ai_h / ai_ai
    deck_mode            = Column(Text, nullable=False)  # full / partial / none
    deck_locked          = Column(Boolean, default=False)

    user_deck_id         = Column(UUID(as_uuid=True), ForeignKey("decks.id"))

    matches_per_opponent = Column(Integer, nullable=False, default=10)
    num_rounds           = Column(Integer, nullable=False, default=5)
    target_win_rate      = Column(Integer, nullable=False, default=60)  # stored as %
    target_mode          = Column(Text, nullable=False, default="aggregate")
    excluded_cards       = Column(JSONB, default=list)

    final_win_rate       = Column(Integer)
    rounds_completed     = Column(Integer, default=0)
    total_matches        = Column(Integer, default=0)

    user_deck_name       = Column(Text)

    started_at           = Column(TIMESTAMP(timezone=True))
    completed_at         = Column(TIMESTAMP(timezone=True))
    error_message        = Column(Text)
    starred              = Column(Boolean, default=False)

    created_at           = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at           = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                                  onupdate=func.now())

    user_deck            = relationship("Deck",
                                        foreign_keys=[user_deck_id],
                                        back_populates="simulations")
    rounds               = relationship("Round", back_populates="simulation",
                                        cascade="all, delete-orphan")
    matches              = relationship("Match", back_populates="simulation",
                                        cascade="all, delete-orphan")


class SimulationOpponent(Base):
    __tablename__ = "simulation_opponents"

    simulation_id = Column(UUID(as_uuid=True),
                           ForeignKey("simulations.id", ondelete="CASCADE"),
                           primary_key=True)
    deck_id       = Column(UUID(as_uuid=True), ForeignKey("decks.id"),
                           primary_key=True)
    deck_name     = Column(Text)


# ── Rounds ─────────────────────────────────────────────────────────────────────

class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("simulation_id", "round_number"),)

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    simulation_id = Column(UUID(as_uuid=True),
                           ForeignKey("simulations.id", ondelete="CASCADE"),
                           nullable=False)
    round_number  = Column(Integer, nullable=False)
    deck_snapshot = Column(JSONB, nullable=False)
    win_rate      = Column(Integer)
    total_matches = Column(Integer, default=0)
    started_at    = Column(TIMESTAMP(timezone=True))
    completed_at  = Column(TIMESTAMP(timezone=True))

    simulation    = relationship("Simulation", back_populates="rounds")
    matches       = relationship("Match", back_populates="round",
                                 cascade="all, delete-orphan")


# ── Matches ────────────────────────────────────────────────────────────────────

class Match(Base):
    __tablename__ = "matches"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    simulation_id    = Column(UUID(as_uuid=True),
                              ForeignKey("simulations.id", ondelete="CASCADE"),
                              nullable=False)
    round_id         = Column(UUID(as_uuid=True),
                              ForeignKey("rounds.id", ondelete="CASCADE"),
                              nullable=False)
    round_number     = Column(Integer, nullable=False)
    opponent_deck_id = Column(UUID(as_uuid=True), ForeignKey("decks.id"))

    winner           = Column(Text, nullable=False)        # p1 / p2
    win_condition    = Column(Text, nullable=False)        # prizes / deck_out / no_bench
    total_turns      = Column(Integer, nullable=False)
    p1_prizes_taken  = Column(Integer, nullable=False)
    p2_prizes_taken  = Column(Integer, nullable=False)

    prize_progression = Column(JSONB)
    p1_deck_name     = Column(Text)
    p2_deck_name     = Column(Text)

    created_at       = Column(TIMESTAMP(timezone=True), server_default=func.now())

    simulation       = relationship("Simulation", back_populates="matches")
    round            = relationship("Round", back_populates="matches")
    events           = relationship("MatchEvent", back_populates="match",
                                    cascade="all, delete-orphan")
    decisions        = relationship("Decision", back_populates="match",
                                    cascade="all, delete-orphan")


class MatchEvent(Base):
    __tablename__ = "match_events"
    __table_args__ = (UniqueConstraint("match_id", "sequence"),)

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    match_id   = Column(UUID(as_uuid=True),
                        ForeignKey("matches.id", ondelete="CASCADE"),
                        nullable=False)
    sequence   = Column(Integer, nullable=False)
    event_type = Column(Text, nullable=False)
    turn       = Column(Integer)
    player     = Column(Text)
    data       = Column(JSONB, nullable=False)

    match      = relationship("Match", back_populates="events")


# ── AI Decisions ───────────────────────────────────────────────────────────────

class Decision(Base):
    __tablename__ = "decisions"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    match_id           = Column(UUID(as_uuid=True),
                                ForeignKey("matches.id", ondelete="CASCADE"))
    simulation_id      = Column(UUID(as_uuid=True),
                                ForeignKey("simulations.id", ondelete="CASCADE"))
    turn_number        = Column(Integer, nullable=False)
    player_id          = Column(Text, nullable=False)
    action_type        = Column(Text, nullable=False)
    card_played        = Column(Text)   # game-instance UUID
    card_def_id        = Column(Text)   # tcgdex_id (e.g. "sv06-130"); populated for all new AI decisions
    target             = Column(Text)
    reasoning          = Column(Text)
    legal_action_count = Column(Integer)
    game_state_summary = Column(Text)
    created_at         = Column(TIMESTAMP(timezone=True), server_default=func.now())

    match              = relationship("Match", back_populates="decisions")


# ── Coach mutations ────────────────────────────────────────────────────────────

class DeckMutation(Base):
    __tablename__ = "deck_mutations"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    simulation_id = Column(UUID(as_uuid=True),
                           ForeignKey("simulations.id", ondelete="CASCADE"))
    round_number  = Column(Integer, nullable=False)
    card_removed  = Column(Text, nullable=False)
    card_added    = Column(Text, nullable=False)
    reasoning     = Column(Text)
    created_at    = Column(TIMESTAMP(timezone=True), server_default=func.now())


# ── Card performance ───────────────────────────────────────────────────────────

class CardPerformance(Base):
    __tablename__ = "card_performance"

    card_tcgdex_id  = Column(Text, ForeignKey("cards.tcgdex_id"), primary_key=True)
    games_included  = Column(Integer, default=0)
    games_won       = Column(Integer, default=0)
    total_kos       = Column(Integer, default=0)
    total_damage    = Column(BigInteger, default=0)
    total_prizes    = Column(Integer, default=0)
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                             onupdate=func.now())


# ── Embeddings (pgvector) ──────────────────────────────────────────────────────

class Embedding(Base):
    __tablename__ = "embeddings"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_type  = Column(Text, nullable=False)  # decision / game_state / card / coach_analysis
    source_id    = Column(Text, nullable=False)
    content_text = Column(Text)
    embedding    = Column(Vector(768))           # nomic-embed-text outputs 768-dim vectors
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
