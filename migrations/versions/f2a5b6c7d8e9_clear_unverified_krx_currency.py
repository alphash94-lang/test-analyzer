"""clear unverified KRX currency assumptions

Revision ID: f2a5b6c7d8e9
Revises: e1f4a5b6c7d8
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a5b6c7d8e9"
down_revision: str | None = "e1f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

price_daily = sa.table(
    "price_daily",
    sa.column("currency", sa.String()),
    sa.column("adjustment_status", sa.String()),
    sa.column("source_provider", sa.String()),
    sa.column("source_function", sa.String()),
)


def upgrade() -> None:
    op.execute(
        price_daily.update()
        .where(
            price_daily.c.source_provider == "KRX",
            price_daily.c.source_function == "유가증권 일별매매정보",
            price_daily.c.currency == "KRW",
            price_daily.c.adjustment_status == "NOT_VERIFIED",
        )
        .values(currency=None)
    )


def downgrade() -> None:
    # The previous value was an unsupported assumption, so it must not be restored.
    return None
