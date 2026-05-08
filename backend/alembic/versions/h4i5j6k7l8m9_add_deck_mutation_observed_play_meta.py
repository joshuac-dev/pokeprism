"""add_deck_mutation_observed_play_meta

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-05-08 00:00:00.000000

Adds observed_play_meta JSONB to deck_mutations so the Coach can persist
whether the observed-play evidence block was injected, which evidence IDs
were available, and what the LLM acknowledged (citations used or not-used reason).
Nullable — null for all pre-6.1 rows.
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa


revision: str = "h4i5j6k7l8m9"
down_revision: Union[str, None] = "g3h4i5j6k7l8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deck_mutations",
        sa.Column("observed_play_meta", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deck_mutations", "observed_play_meta")
