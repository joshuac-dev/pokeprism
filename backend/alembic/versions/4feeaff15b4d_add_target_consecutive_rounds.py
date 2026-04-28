"""add_target_consecutive_rounds

Revision ID: 4feeaff15b4d
Revises: 8ac02d648b4f
Create Date: 2026-04-28 17:50:31.162524

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4feeaff15b4d'
down_revision: Union[str, None] = '8ac02d648b4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'simulations',
        sa.Column('target_consecutive_rounds', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    op.drop_column('simulations', 'target_consecutive_rounds')
