"""Phase 5 independent-audit data truth constraints

Revision ID: q3f6a7b8c9d0
Revises: p2e5f6a7b8c9
Create Date: 2026-07-30 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q3f6a7b8c9d0"
down_revision: str | None = "p2e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE investor_flows
            SET data_state = 'CONFLICT'
            WHERE data_state = 'AVAILABLE'
              AND net_purchase_quantity IS NOT NULL
              AND net_purchase_quantity <> ROUND(net_purchase_quantity, 0)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE program_trading
            SET data_state = 'CONFLICT'
            WHERE data_state = 'AVAILABLE'
              AND net_purchase_quantity IS NOT NULL
              AND net_purchase_quantity <> ROUND(net_purchase_quantity, 0)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE short_selling
            SET data_state = 'CONFLICT'
            WHERE data_state = 'AVAILABLE'
              AND (
                (
                  short_quantity IS NOT NULL
                  AND (
                    short_quantity < 0
                    OR short_quantity <> ROUND(short_quantity, 0)
                  )
                )
                OR (short_amount IS NOT NULL AND short_amount < 0)
                OR (
                  short_ratio IS NOT NULL
                  AND (short_ratio < 0 OR short_ratio > 100)
                )
              )
            """
        )
    )

    with op.batch_alter_table("investor_flows") as batch_op:
        batch_op.create_check_constraint(
            "ck_investor_flow_available_quantity_integral",
            "data_state <> 'AVAILABLE' OR net_purchase_quantity IS NULL "
            "OR net_purchase_quantity = ROUND(net_purchase_quantity, 0)",
        )
    with op.batch_alter_table("program_trading") as batch_op:
        batch_op.create_check_constraint(
            "ck_program_available_quantity_integral",
            "data_state <> 'AVAILABLE' OR net_purchase_quantity IS NULL "
            "OR net_purchase_quantity = ROUND(net_purchase_quantity, 0)",
        )
    with op.batch_alter_table("short_selling") as batch_op:
        batch_op.create_check_constraint(
            "ck_short_available_quantity_valid",
            "data_state <> 'AVAILABLE' OR short_quantity IS NULL OR "
            "(short_quantity >= 0 AND "
            "short_quantity = ROUND(short_quantity, 0))",
        )
        batch_op.create_check_constraint(
            "ck_short_available_amount_nonnegative",
            "data_state <> 'AVAILABLE' OR short_amount IS NULL "
            "OR short_amount >= 0",
        )
        batch_op.create_check_constraint(
            "ck_short_available_ratio_range",
            "data_state <> 'AVAILABLE' OR short_ratio IS NULL "
            "OR (short_ratio >= 0 AND short_ratio <= 100)",
        )


def downgrade() -> None:
    with op.batch_alter_table("short_selling") as batch_op:
        batch_op.drop_constraint(
            "ck_short_available_ratio_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_short_available_amount_nonnegative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_short_available_quantity_valid",
            type_="check",
        )
    with op.batch_alter_table("program_trading") as batch_op:
        batch_op.drop_constraint(
            "ck_program_available_quantity_integral",
            type_="check",
        )
    with op.batch_alter_table("investor_flows") as batch_op:
        batch_op.drop_constraint(
            "ck_investor_flow_available_quantity_integral",
            type_="check",
        )
