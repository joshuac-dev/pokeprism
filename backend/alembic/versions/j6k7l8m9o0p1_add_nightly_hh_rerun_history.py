"""Add nightly_hh_rerun_history table for round-robin rerun tracking.

Revision ID: j6k7l8m9o0p1
Revises: i5j6k7l8m9o0
Create Date: 2026-05-11

Tracks which completed manual H/H simulations have been rerun by the nightly
scheduler, enabling deterministic round-robin selection across cycles.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "j6k7l8m9o0p1"
down_revision = "i5j6k7l8m9o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nightly_hh_rerun_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_simulation_id", UUID(as_uuid=True),
                  sa.ForeignKey("simulations.id"), nullable=False),
        sa.Column("generated_simulation_id", UUID(as_uuid=True),
                  sa.ForeignKey("simulations.id"), nullable=True),
        sa.Column("cycle_number", sa.Integer, nullable=False),
        sa.Column("source_user_deck_id", UUID(as_uuid=True),
                  sa.ForeignKey("decks.id"), nullable=False),
        sa.Column("source_user_deck_name", sa.Text, nullable=True),
        sa.Column("source_opponent_deck_ids", JSONB, nullable=True),
        sa.Column("source_opponent_deck_names", JSONB, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("triggered_by", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_rerun_history_source_sim",
                    "nightly_hh_rerun_history", ["source_simulation_id"])
    op.create_index("idx_rerun_history_generated_sim",
                    "nightly_hh_rerun_history", ["generated_simulation_id"])
    op.create_index("idx_rerun_history_cycle",
                    "nightly_hh_rerun_history", ["cycle_number"])
    op.create_index("idx_rerun_history_created_at",
                    "nightly_hh_rerun_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_rerun_history_created_at", "nightly_hh_rerun_history")
    op.drop_index("idx_rerun_history_cycle", "nightly_hh_rerun_history")
    op.drop_index("idx_rerun_history_generated_sim", "nightly_hh_rerun_history")
    op.drop_index("idx_rerun_history_source_sim", "nightly_hh_rerun_history")
    op.drop_table("nightly_hh_rerun_history")
