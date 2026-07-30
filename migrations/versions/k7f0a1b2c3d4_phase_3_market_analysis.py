"""Add Phase 3 index and reproducible market-analysis tables.

Revision ID: k7f0a1b2c3d4
Revises: j6e9f0a1b2c3
Create Date: 2026-07-29 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k7f0a1b2c3d4"
down_revision: str | None = "j6e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "index_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("index_class", sa.String(length=120), nullable=False),
        sa.Column("index_name", sa.String(length=160), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column(
            "previous_day_change",
            sa.Numeric(precision=24, scale=8),
            nullable=False,
        ),
        sa.Column(
            "fluctuation_rate",
            sa.Numeric(precision=16, scale=8),
            nullable=False,
        ),
        sa.Column("open", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=30, scale=0), nullable=False),
        sa.Column(
            "trading_value",
            sa.Numeric(precision=30, scale=2),
            nullable=False,
        ),
        sa.Column(
            "market_cap",
            sa.Numeric(precision=30, scale=2),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_function", sa.String(length=160), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_timing", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_name",
            "trade_date",
            "source_provider",
            name="uq_index_daily_source",
        ),
    )
    op.create_index(
        "ix_index_daily_name_date",
        "index_daily",
        ["index_name", "trade_date"],
    )
    op.create_table(
        "market_regime_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False),
        sa.Column("input_data_hash", sa.String(length=64), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column(
            "shock_classification",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column("market_regime", sa.String(length=32), nullable=False),
        sa.Column("data_confidence", sa.Numeric(precision=7, scale=3)),
        sa.Column("proxy_kind", sa.String(length=40), nullable=False),
        sa.Column("semiconductor_recovery", sa.Boolean()),
        sa.Column("kospi_recovery", sa.Boolean()),
        sa.Column("non_semiconductor_breadth", sa.Boolean()),
        sa.Column("dividend_relative_strength_recovery", sa.Boolean()),
        sa.Column("missing_core_data", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "data_confidence IS NULL OR "
            "(data_confidence >= 0 AND data_confidence <= 100)",
            name="ck_market_regime_confidence_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "as_of_at",
            "rule_version",
            "input_data_hash",
            name="uq_market_regime_reproducible",
        ),
    )
    op.create_table(
        "market_metric_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_regime_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(length=100), nullable=False),
        sa.Column("metric_label", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(precision=30, scale=10)),
        sa.Column("text_value", sa.Text()),
        sa.Column("unit", sa.String(length=80)),
        sa.Column("source_provider", sa.String(length=120)),
        sa.Column("source_function", sa.String(length=200)),
        sa.Column("as_of_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("calculation_method", sa.Text(), nullable=False),
        sa.Column("data_quality", sa.String(length=80), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("proxy_kind", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_regime_snapshot_id"],
            ["market_regime_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_regime_snapshot_id",
            "metric_code",
            name="uq_market_metric_snapshot_code",
        ),
    )
    op.create_table(
        "market_contribution_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("market_regime_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "return_rate",
            sa.Numeric(precision=20, scale=10),
            nullable=False,
        ),
        sa.Column(
            "previous_weight",
            sa.Numeric(precision=20, scale=10),
            nullable=False,
        ),
        sa.Column(
            "contribution",
            sa.Numeric(precision=20, scale=10),
            nullable=False,
        ),
        sa.Column("is_semiconductor", sa.Boolean(), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["market_regime_snapshot_id"],
            ["market_regime_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_regime_snapshot_id",
            "stock_id",
            name="uq_market_contribution_snapshot_stock",
        ),
    )


def downgrade() -> None:
    op.drop_table("market_contribution_records")
    op.drop_table("market_metric_records")
    op.drop_table("market_regime_snapshots")
    op.drop_index("ix_index_daily_name_date", table_name="index_daily")
    op.drop_table("index_daily")
