"""enforce raw response truth

Revision ID: b8c1d2e3f4a5
Revises: 7f491f98f46e
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8c1d2e3f4a5"
down_revision: str | None = "7f491f98f46e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.create_check_constraint(
            "ck_api_raw_available_http_status",
            "data_state != 'AVAILABLE' OR (http_status >= 200 AND http_status <= 299)",
        )


def downgrade() -> None:
    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.drop_constraint(
            "ck_api_raw_available_http_status",
            type_="check",
        )
