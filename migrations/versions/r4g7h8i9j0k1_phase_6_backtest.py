"""Phase 6 point-in-time backtest result storage

Revision ID: r4g7h8i9j0k1
Revises: q3f6a7b8c9d0
Create Date: 2026-07-30 01:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r4g7h8i9j0k1"
down_revision: str | None = "q3f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("backtest_version", sa.String(length=40), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("input_data_hash", sa.String(length=64), nullable=False),
        sa.Column("score_versions", sa.JSON(), nullable=False),
        sa.Column(
            "recommendation_rule_versions",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column("market_rule_versions", sa.JSON(), nullable=False),
        sa.Column(
            "universe_construction_method",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "financial_availability_method",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "correction_availability_method",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "execution_price_method",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "adjusted_price_source",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "dividend_treatment_method",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "transaction_cost_bps",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
        ),
        sa.Column(
            "transaction_cost_assumption",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("benchmark_method", sa.Text(), nullable=False),
        sa.Column("walk_forward_method", sa.Text(), nullable=False),
        sa.Column("known_survival_bias", sa.JSON(), nullable=False),
        sa.Column("missing_data", sa.JSON(), nullable=False),
        sa.Column("config_payload", sa.JSON(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_backtest_date_order",
        ),
        sa.CheckConstraint(
            "transaction_cost_bps >= 0",
            name="ck_backtest_transaction_cost_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "backtest_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
            name="uq_backtest_run_reproducible",
        ),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
