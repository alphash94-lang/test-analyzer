"""Store KRX previous-day changes for Phase 3 continuity verification.

Revision ID: v8k1l2m3n4o5
Revises: u7j0k1l2m3n4
"""

import sqlalchemy as sa
from alembic import op

revision = "v8k1l2m3n4o5"
down_revision = "u7j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_daily") as batch_op:
        batch_op.add_column(
            sa.Column(
                "previous_day_change",
                sa.Numeric(24, 6),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("price_daily") as batch_op:
        batch_op.drop_column("previous_day_change")
