"""Add the persistent event watchlist.

Revision ID: s5h8i9j0k1l2
Revises: r4g7h8i9j0k1
Create Date: 2026-07-30 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s5h8i9j0k1l2"
down_revision: str | None = "r4g7h8i9j0k1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_watchlist_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "category",
            name="uq_event_watchlist_stock_category",
        ),
    )


def downgrade() -> None:
    op.drop_table("event_watchlist_items")
