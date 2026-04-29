"""add_best_deck_snapshot

Revision ID: c3e91f7a5b22
Revises: 4feeaff15b4d
Create Date: 2026-04-29 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'c3e91f7a5b22'
down_revision: Union[str, None] = '4feeaff15b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'simulations',
        sa.Column('best_deck_snapshot', JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('simulations', 'best_deck_snapshot')
