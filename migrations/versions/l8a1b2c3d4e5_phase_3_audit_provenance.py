"""Preserve Phase 3 timing and contribution provenance.

Revision ID: l8a1b2c3d4e5
Revises: k7f0a1b2c3d4
Create Date: 2026-07-29 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l8a1b2c3d4e5"
down_revision: str | None = "k7f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_metric_records",
        sa.Column(
            "data_timing",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
    )
    with op.batch_alter_table("market_metric_records") as batch_op:
        batch_op.alter_column("data_timing", server_default=None)

    op.add_column(
        "market_contribution_records",
        sa.Column(
            "market_cap_source_provider",
            sa.String(length=120),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column("classification_source", sa.String(length=120)),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column("collected_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column(
            "data_timing",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'UNKNOWN'"),
        ),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column(
            "calculation_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text(
                "'전일 전체 비교종목 시가총액 비중 × 당일 수정가격 수익률'"
            ),
        ),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column(
            "data_quality",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'EXPLANATORY_ESTIMATE'"),
        ),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column(
            "source_kind",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'SELF_CALCULATED'"),
        ),
    )
    op.add_column(
        "market_contribution_records",
        sa.Column(
            "proxy_kind",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'SELF_CALCULATED_PROXY'"),
        ),
    )
    with op.batch_alter_table("market_contribution_records") as batch_op:
        batch_op.alter_column(
            "is_semiconductor",
            existing_type=sa.Boolean(),
            nullable=True,
        )
        for column_name in (
            "market_cap_source_provider",
            "data_timing",
            "calculation_method",
            "data_quality",
            "source_kind",
            "proxy_kind",
        ):
            batch_op.alter_column(column_name, server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE market_contribution_records "
            "SET is_semiconductor = 0 WHERE is_semiconductor IS NULL"
        )
    )
    with op.batch_alter_table("market_contribution_records") as batch_op:
        batch_op.alter_column(
            "is_semiconductor",
            existing_type=sa.Boolean(),
            nullable=False,
        )
        batch_op.drop_column("proxy_kind")
        batch_op.drop_column("source_kind")
        batch_op.drop_column("data_quality")
        batch_op.drop_column("calculation_method")
        batch_op.drop_column("data_timing")
        batch_op.drop_column("collected_at")
        batch_op.drop_column("classification_source")
        batch_op.drop_column("market_cap_source_provider")
    op.drop_column("market_metric_records", "data_timing")
