"""Add observed_play_memory_ingestions and observed_play_memory_items tables (Phase 4).

Revision ID: g3h4i5j6k7l8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-06
"""

from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g3h4i5j6k7l8"
down_revision: str = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on observed_play_logs
    op.add_column("observed_play_logs",
        sa.Column("memory_item_count", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("observed_play_logs",
        sa.Column("last_memory_ingested_at", postgresql.TIMESTAMP(timezone=True), nullable=True))

    # observed_play_memory_ingestions
    op.create_table(
        "observed_play_memory_ingestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_play_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ingestion_version", sa.Text(), nullable=False),
        sa.Column("eligibility_status", sa.Text(), nullable=False),
        sa.Column("eligibility_reasons_json", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("config_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("summary_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("error_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("source_event_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("memory_item_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("skipped_event_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("blocked_reason_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["observed_play_log_id"], ["observed_play_logs.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_opmi_log_id", "observed_play_memory_ingestions", ["observed_play_log_id"])
    op.create_index("idx_opmi_import_batch_id", "observed_play_memory_ingestions", ["import_batch_id"])
    op.create_index("idx_opmi_status", "observed_play_memory_ingestions", ["status"])
    op.create_index("idx_opmi_created_at", "observed_play_memory_ingestions", ["created_at"])

    # observed_play_memory_items
    op.create_table(
        "observed_play_memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_play_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_play_event_id", sa.BigInteger(), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("memory_type", sa.Text(), nullable=False),
        sa.Column("memory_key", sa.Text(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=True),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("player_alias", sa.Text(), nullable=True),
        sa.Column("player_raw", sa.Text(), nullable=True),
        sa.Column("actor_card_raw", sa.Text(), nullable=True),
        sa.Column("actor_card_def_id", sa.Text(), nullable=True),
        sa.Column("actor_resolution_status", sa.Text(), nullable=True),
        sa.Column("target_card_raw", sa.Text(), nullable=True),
        sa.Column("target_card_def_id", sa.Text(), nullable=True),
        sa.Column("target_resolution_status", sa.Text(), nullable=True),
        sa.Column("related_card_raw", sa.Text(), nullable=True),
        sa.Column("related_card_def_id", sa.Text(), nullable=True),
        sa.Column("related_resolution_status", sa.Text(), nullable=True),
        sa.Column("action_name", sa.Text(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("damage", sa.Integer(), nullable=True),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("target_zone", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source_event_type", sa.Text(), nullable=False),
        sa.Column("source_raw_line", sa.Text(), nullable=False),
        sa.Column("source_payload_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ingestion_id"], ["observed_play_memory_ingestions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observed_play_log_id"], ["observed_play_logs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observed_play_event_id"], ["observed_play_events.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_opitem_log_id", "observed_play_memory_items", ["observed_play_log_id"])
    op.create_index("idx_opitem_event_id", "observed_play_memory_items", ["observed_play_event_id"])
    op.create_index("idx_opitem_ingestion_id", "observed_play_memory_items", ["ingestion_id"])
    op.create_index("idx_opitem_memory_type", "observed_play_memory_items", ["memory_type"])
    op.create_index("idx_opitem_memory_key", "observed_play_memory_items", ["memory_key"])
    op.create_index("idx_opitem_actor_card_def_id", "observed_play_memory_items", ["actor_card_def_id"])
    op.create_index("idx_opitem_target_card_def_id", "observed_play_memory_items", ["target_card_def_id"])
    op.create_index("idx_opitem_source_event_type", "observed_play_memory_items", ["source_event_type"])
    op.create_index("idx_opitem_created_at", "observed_play_memory_items", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_opitem_created_at", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_source_event_type", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_target_card_def_id", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_actor_card_def_id", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_memory_key", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_memory_type", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_ingestion_id", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_event_id", table_name="observed_play_memory_items")
    op.drop_index("idx_opitem_log_id", table_name="observed_play_memory_items")
    op.drop_table("observed_play_memory_items")

    op.drop_index("idx_opmi_created_at", table_name="observed_play_memory_ingestions")
    op.drop_index("idx_opmi_status", table_name="observed_play_memory_ingestions")
    op.drop_index("idx_opmi_import_batch_id", table_name="observed_play_memory_ingestions")
    op.drop_index("idx_opmi_log_id", table_name="observed_play_memory_ingestions")
    op.drop_table("observed_play_memory_ingestions")

    op.drop_column("observed_play_logs", "last_memory_ingested_at")
    op.drop_column("observed_play_logs", "memory_item_count")
