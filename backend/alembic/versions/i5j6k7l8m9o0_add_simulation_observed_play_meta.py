"""Add observed_play_meta JSONB to simulations table.

Revision ID: i5j6k7l8m9o0
Revises: h4i5j6k7l8m9
Create Date: 2026-05-08

Stores per-round Coach observed-play injection state at the simulation level
so that coach-debug can surface evidence injection even when no deck mutations
were produced (e.g. Coach recommended 0 swaps).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "i5j6k7l8m9o0"
down_revision = "h4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulations",
        sa.Column("observed_play_meta", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulations", "observed_play_meta")
