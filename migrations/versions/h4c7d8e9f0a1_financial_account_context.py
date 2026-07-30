"""preserve distinct nonstandard financial accounts

Revision ID: h4c7d8e9f0a1
Revises: g3b6c7d8e9f0
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "h4c7d8e9f0a1"
down_revision: str | None = "g3b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_constraint(
            "uq_financial_account_context",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_financial_account_context",
            [
                "statement_id",
                "account_id",
                "account_name",
                "account_detail",
                "statement_section",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_constraint(
            "uq_financial_account_context",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_financial_account_context",
            ["statement_id", "account_id", "account_detail"],
        )
