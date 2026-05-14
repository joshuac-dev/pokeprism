"""Add status column to deck_mutations to distinguish applied/reverted mutations.

Revision ID: k7l8m9o0p1q2
Revises: j6k7l8m9o0p1
Create Date: 2026-05-14

Root cause: deck_mutations had no way to distinguish mutations actually applied
to the final deck from those that were proposed-but-skipped (e.g. card not in
candidate pool) or temporarily applied then reverted when two consecutive
regressions triggered a rollback to the best-known deck.

This migration adds a ``status`` column defaulting to ``'applied'`` so existing
rows keep their current (assumed-applied) semantics.  New rows written by the
fixed simulation task will carry one of:
  - ``'applied'``  – mutation was accepted by _apply_mutations and sticks.
  - ``'reverted'`` – mutation was applied temporarily then undone on reversion.
"""

from alembic import op
import sqlalchemy as sa

revision = "k7l8m9o0p1q2"
down_revision = "j6k7l8m9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deck_mutations",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="applied",
        ),
    )


def downgrade() -> None:
    op.drop_column("deck_mutations", "status")
