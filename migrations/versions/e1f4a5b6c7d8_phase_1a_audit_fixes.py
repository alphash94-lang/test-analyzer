"""phase 1a audit fixes

Revision ID: e1f4a5b6c7d8
Revises: d0e3f4a5b6c7
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f4a5b6c7d8"
down_revision: str | None = "d0e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stocks") as batch_op:
        batch_op.add_column(sa.Column("is_kospi", sa.Boolean()))
        batch_op.add_column(sa.Column("dart_collected_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "dart_data_state",
                sa.String(32),
                nullable=False,
                server_default="NOT_VERIFIED",
            )
        )
        batch_op.alter_column("dart_data_state", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("stocks") as batch_op:
        batch_op.drop_column("dart_data_state")
        batch_op.drop_column("dart_collected_at")
        batch_op.drop_column("is_kospi")
