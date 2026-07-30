"""Add per-watchlist news search query.

Revision ID: u7j0k1l2m3n4
Revises: t6i9j0k1l2m3
"""

import sqlalchemy as sa
from alembic import op

revision: str = "u7j0k1l2m3n4"
down_revision: str | None = "t6i9j0k1l2m3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "event_watchlist_items",
        sa.Column("news_query", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_watchlist_items", "news_query")
