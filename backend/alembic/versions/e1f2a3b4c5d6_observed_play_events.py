"""Add observed_play_events table (Phase 2).

Revision ID: e1f2a3b4c5d6
Revises: b9f8e1d2c3a4
Create Date: 2025-08-02
"""

from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str = "b9f8e1d2c3a4"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "observed_play_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("observed_play_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=True),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("player_raw", sa.Text(), nullable=True),
        sa.Column("player_alias", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("raw_line", sa.Text(), nullable=False),
        sa.Column("raw_block", sa.Text(), nullable=True),
        sa.Column("card_name_raw", sa.Text(), nullable=True),
        sa.Column("target_card_name_raw", sa.Text(), nullable=True),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("target_zone", sa.Text(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("damage", sa.Integer(), nullable=True),
        sa.Column("base_damage", sa.Integer(), nullable=True),
        sa.Column("weakness_damage", sa.Integer(), nullable=True),
        sa.Column("resistance_delta", sa.Integer(), nullable=True),
        sa.Column("healing_amount", sa.Integer(), nullable=True),
        sa.Column("energy_type", sa.Text(), nullable=True),
        sa.Column("prize_count_delta", sa.Integer(), nullable=True),
        sa.Column("deck_count_delta", sa.Integer(), nullable=True),
        sa.Column("hand_count_delta", sa.Integer(), nullable=True),
        sa.Column("discard_count_delta", sa.Integer(), nullable=True),
        sa.Column("event_payload_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence_reasons_json", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("parser_version", sa.Text(), nullable=False, server_default="1.0"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["observed_play_log_id"], ["observed_play_logs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("observed_play_log_id", "event_index", name="uq_ope_log_event_index"),
    )
    op.create_index("idx_ope_log_id", "observed_play_events", ["observed_play_log_id"])
    op.create_index("idx_ope_import_batch_id", "observed_play_events", ["import_batch_id"])
    op.create_index("idx_ope_event_type", "observed_play_events", ["event_type"])
    op.create_index("idx_ope_player_alias", "observed_play_events", ["player_alias"])
    op.create_index("idx_ope_created_at", "observed_play_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ope_created_at", table_name="observed_play_events")
    op.drop_index("idx_ope_player_alias", table_name="observed_play_events")
    op.drop_index("idx_ope_event_type", table_name="observed_play_events")
    op.drop_index("idx_ope_import_batch_id", table_name="observed_play_events")
    op.drop_index("idx_ope_log_id", table_name="observed_play_events")
    op.drop_table("observed_play_events")
