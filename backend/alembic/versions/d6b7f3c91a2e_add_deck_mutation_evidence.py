"""add_deck_mutation_evidence

Revision ID: d6b7f3c91a2e
Revises: c3e91f7a5b22
Create Date: 2026-05-03 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa


revision: str = "d6b7f3c91a2e"
down_revision: Union[str, None] = "c3e91f7a5b22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deck_mutations",
        sa.Column("evidence", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deck_mutations", "evidence")
