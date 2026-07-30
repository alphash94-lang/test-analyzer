"""Backfill KOSPI membership from the stored official market value.

Revision ID: t6i9j0k1l2m3
Revises: s5h8i9j0k1l2
Create Date: 2026-07-30 17:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "t6i9j0k1l2m3"
down_revision: str | None = "s5h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stocks
        SET is_kospi = true
        WHERE source_provider = 'KRX'
          AND market_code = 'KOSPI'
          AND market_name = 'KOSPI'
          AND is_kospi IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE stocks
        SET is_kospi = NULL
        WHERE source_provider = 'KRX'
          AND market_code = 'KOSPI'
          AND market_name = 'KOSPI'
          AND is_kospi = true
        """
    )
