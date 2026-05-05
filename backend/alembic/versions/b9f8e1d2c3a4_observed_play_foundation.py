"""Add Observed Play Memory tables (Phase 1).

Revision ID: b9f8e1d2c3a4
Revises: 5b7e9c2d4a11
Create Date: 2025-08-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b9f8e1d2c3a4"
down_revision: str = "5b7e9c2d4a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observed_play_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="upload_single"),
        sa.Column("uploaded_filename", sa.Text()),
        sa.Column("celery_task_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("original_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("summary_json", postgresql.JSONB()),
        sa.Column("errors_json", postgresql.JSONB()),
        sa.Column("warnings_json", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "observed_play_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "import_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observed_play_import_batches.id"),
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="ptcgl_export"),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text()),
        sa.Column("sha256_hash", sa.Text(), nullable=False),
        sa.Column("raw_content", sa.Text()),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "parse_status",
            sa.Text(),
            nullable=False,
            server_default="raw_archived",
        ),
        sa.Column(
            "memory_status",
            sa.Text(),
            nullable=False,
            server_default="not_ingested",
        ),
        sa.Column("parser_version", sa.Text()),
        sa.Column("player_1_name_raw", sa.Text()),
        sa.Column("player_2_name_raw", sa.Text()),
        sa.Column("player_1_alias", sa.Text()),
        sa.Column("player_2_alias", sa.Text()),
        sa.Column("self_player_index", sa.Integer()),
        sa.Column("winner_raw", sa.Text()),
        sa.Column("winner_alias", sa.Text()),
        sa.Column("win_condition", sa.Text()),
        sa.Column("game_date_detected", sa.Text()),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "recognized_card_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "unresolved_card_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "ambiguous_card_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("confidence_score", sa.Float()),
        sa.Column("errors_json", postgresql.JSONB()),
        sa.Column("warnings_json", postgresql.JSONB()),
        sa.Column("metadata_json", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256_hash", name="uq_observed_play_logs_sha256"),
    )

    op.create_index(
        "idx_opl_import_batch_id",
        "observed_play_logs",
        ["import_batch_id"],
    )
    op.create_index(
        "idx_opl_parse_status",
        "observed_play_logs",
        ["parse_status"],
    )
    op.create_index(
        "idx_opl_memory_status",
        "observed_play_logs",
        ["memory_status"],
    )
    op.create_index(
        "idx_opl_created_at",
        "observed_play_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_opl_created_at", table_name="observed_play_logs")
    op.drop_index("idx_opl_memory_status", table_name="observed_play_logs")
    op.drop_index("idx_opl_parse_status", table_name="observed_play_logs")
    op.drop_index("idx_opl_import_batch_id", table_name="observed_play_logs")
    op.drop_table("observed_play_logs")
    op.drop_table("observed_play_import_batches")
