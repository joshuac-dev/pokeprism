"""add_card_def_id_to_decisions

Revision ID: 8ac02d648b4f
Revises: 4afceada2d2a
Create Date: 2026-04-28 01:29:59.251863

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8ac02d648b4f'
down_revision: Union[str, None] = '4afceada2d2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('decisions', sa.Column('card_def_id', sa.Text(), nullable=True))
    op.create_index('idx_decisions_card_def', 'decisions', ['card_def_id'])


def downgrade() -> None:
    op.drop_index('idx_decisions_card_def', table_name='decisions')
    op.drop_column('decisions', 'card_def_id')
