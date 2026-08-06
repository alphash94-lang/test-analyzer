"""Add indexes used by interactive stock search and status reads.

Revision ID: x1n4o5p6q7r8
Revises: w9l2m3n4o5p6
"""

from alembic import op

revision = "x1n4o5p6q7r8"
down_revision = "w9l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_price_daily_stock_trade",
        "price_daily",
        ["stock_id", "trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_api_raw_provider_received",
        "api_raw_responses",
        ["provider", "received_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_raw_provider_received",
        table_name="api_raw_responses",
    )
    op.drop_index(
        "ix_price_daily_stock_trade",
        table_name="price_daily",
    )
