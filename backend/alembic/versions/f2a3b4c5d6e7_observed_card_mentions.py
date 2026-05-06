"""Add observed_card_mentions and observed_card_resolution_rules tables (Phase 3).

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-06
"""

from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: str = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on observed_play_logs
    op.add_column("observed_play_logs",
        sa.Column("card_mention_count", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("observed_play_logs",
        sa.Column("card_resolution_status", sa.Text(), nullable=True))
    op.add_column("observed_play_logs",
        sa.Column("resolver_version", sa.Text(), nullable=True))

    # observed_card_mentions
    op.create_table(
        "observed_card_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_play_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_play_event_id", sa.BigInteger(), nullable=False),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mention_index", sa.Integer(), nullable=False),
        sa.Column("mention_role", sa.Text(), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("resolved_card_def_id", sa.Text(), nullable=True),
        sa.Column("resolved_card_name", sa.Text(), nullable=True),
        sa.Column("resolution_status", sa.Text(), nullable=False, server_default="unresolved"),
        sa.Column("resolution_confidence", sa.Float(), nullable=True),
        sa.Column("resolution_method", sa.Text(), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("candidates_json", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("source_event_type", sa.Text(), nullable=False),
        sa.Column("source_field", sa.Text(), nullable=False),
        sa.Column("source_payload_path", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("resolver_version", sa.Text(), nullable=False, server_default="1.0"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["observed_play_log_id"], ["observed_play_logs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observed_play_event_id"], ["observed_play_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_card_def_id"], ["cards.tcgdex_id"]),
        sa.UniqueConstraint("observed_play_event_id", "mention_index", name="uq_ocm_event_mention_index"),
    )
    op.create_index("idx_ocm_log_id", "observed_card_mentions", ["observed_play_log_id"])
    op.create_index("idx_ocm_event_id", "observed_card_mentions", ["observed_play_event_id"])
    op.create_index("idx_ocm_normalized_name", "observed_card_mentions", ["normalized_name"])
    op.create_index("idx_ocm_resolution_status", "observed_card_mentions", ["resolution_status"])
    op.create_index("idx_ocm_resolved_card_def_id", "observed_card_mentions", ["resolved_card_def_id"])
    op.create_index("idx_ocm_created_at", "observed_card_mentions", ["created_at"])

    # observed_card_resolution_rules
    op.create_table(
        "observed_card_resolution_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("target_card_def_id", sa.Text(), nullable=True),
        sa.Column("target_card_name", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="global"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["target_card_def_id"], ["cards.tcgdex_id"]),
    )
    op.create_index("idx_ocrr_normalized_name", "observed_card_resolution_rules", ["normalized_name"])
    op.create_index("idx_ocrr_action", "observed_card_resolution_rules", ["action"])


def downgrade() -> None:
    op.drop_index("idx_ocrr_action", table_name="observed_card_resolution_rules")
    op.drop_index("idx_ocrr_normalized_name", table_name="observed_card_resolution_rules")
    op.drop_table("observed_card_resolution_rules")

    op.drop_index("idx_ocm_created_at", table_name="observed_card_mentions")
    op.drop_index("idx_ocm_resolved_card_def_id", table_name="observed_card_mentions")
    op.drop_index("idx_ocm_resolution_status", table_name="observed_card_mentions")
    op.drop_index("idx_ocm_normalized_name", table_name="observed_card_mentions")
    op.drop_index("idx_ocm_event_id", table_name="observed_card_mentions")
    op.drop_index("idx_ocm_log_id", table_name="observed_card_mentions")
    op.drop_table("observed_card_mentions")

    op.drop_column("observed_play_logs", "resolver_version")
    op.drop_column("observed_play_logs", "card_resolution_status")
    op.drop_column("observed_play_logs", "card_mention_count")
