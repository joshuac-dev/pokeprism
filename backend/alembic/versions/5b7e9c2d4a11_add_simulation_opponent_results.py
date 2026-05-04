"""add_simulation_opponent_results

Revision ID: 5b7e9c2d4a11
Revises: d6b7f3c91a2e
Create Date: 2026-05-04 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5b7e9c2d4a11"
down_revision: Union[str, None] = "d6b7f3c91a2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulation_opponent_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("simulation_id", sa.UUID(), nullable=False),
        sa.Column("round_id", sa.UUID(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("opponent_deck_id", sa.UUID(), nullable=False),
        sa.Column("opponent_deck_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("matches_target", sa.Integer(), nullable=False),
        sa.Column("matches_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p1_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p2_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Integer(), nullable=True),
        sa.Column("graph_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["opponent_deck_id"], ["decks.id"]),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["simulation_id"], ["simulations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("simulation_id", "round_number", "opponent_deck_id"),
    )
    op.create_index(
        "idx_sim_opp_results_round_status",
        "simulation_opponent_results",
        ["simulation_id", "round_number", "status"],
    )
    op.create_index(
        "idx_sim_opp_results_sim_status",
        "simulation_opponent_results",
        ["simulation_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_sim_opp_results_sim_status", table_name="simulation_opponent_results")
    op.drop_index("idx_sim_opp_results_round_status", table_name="simulation_opponent_results")
    op.drop_table("simulation_opponent_results")
