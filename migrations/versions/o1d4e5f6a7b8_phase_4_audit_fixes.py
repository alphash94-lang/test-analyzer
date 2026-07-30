"""Phase 4 independent-audit persistence fixes

Revision ID: o1d4e5f6a7b8
Revises: n0c3d4e5f6a7
Create Date: 2026-07-29 22:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o1d4e5f6a7b8"
down_revision: str | None = "n0c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "portfolio_settings",
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE portfolio_settings SET selected_at = created_at "
        "WHERE selected_at IS NULL"
    )
    with op.batch_alter_table("portfolio_settings") as batch_op:
        batch_op.alter_column(
            "selected_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.add_column(
        "split_buy_plans",
        sa.Column(
            "reference_price_collected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "split_buy_plans",
        sa.Column(
            "reference_price_timing",
            sa.String(length=32),
            nullable=True,
        ),
    )
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_constraint(
            "uq_recommendation_reproducible",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_recommendation_reproducible",
            [
                "stock_id",
                "as_of_at",
                "score_version",
                "rule_version",
                "config_hash",
                "input_data_hash",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_constraint(
            "uq_recommendation_reproducible",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_recommendation_reproducible",
            [
                "stock_id",
                "as_of_at",
                "score_version",
                "rule_version",
                "input_data_hash",
            ],
        )
    with op.batch_alter_table("split_buy_plans") as batch_op:
        batch_op.drop_column("reference_price_timing")
        batch_op.drop_column("reference_price_collected_at")
    with op.batch_alter_table("portfolio_settings") as batch_op:
        batch_op.drop_column("selected_at")
