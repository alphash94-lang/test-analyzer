"""require available HTTP status

Revision ID: c9d2e3f4a5b6
Revises: b8c1d2e3f4a5
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9d2e3f4a5b6"
down_revision: str | None = "b8c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.drop_constraint(
            "ck_api_raw_available_http_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_api_raw_available_http_status",
            "data_state != 'AVAILABLE' OR "
            "(http_status IS NOT NULL AND "
            "http_status >= 200 AND http_status <= 299)",
        )


def downgrade() -> None:
    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.drop_constraint(
            "ck_api_raw_available_http_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_api_raw_available_http_status",
            "data_state != 'AVAILABLE' OR (http_status >= 200 AND http_status <= 299)",
        )
