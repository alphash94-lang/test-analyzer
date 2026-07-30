"""require filing dates for available DART analysis rows

Revision ID: i5d8e9f0a1b2
Revises: h4c7d8e9f0a1
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "i5d8e9f0a1b2"
down_revision: str | None = "h4c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = (
    (
        "dividends",
        "ck_dividend_available_filing_date",
    ),
    (
        "dividend_facts",
        "ck_dividend_fact_available_filing_date",
    ),
    (
        "audit_opinions",
        "ck_audit_available_filing_date",
    ),
)


def upgrade() -> None:
    for table_name, constraint_name in _CONSTRAINTS:
        op.execute(
            f"UPDATE {table_name} SET data_state = 'MISSING' "
            "WHERE data_state = 'AVAILABLE' AND filing_date IS NULL"
        )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_check_constraint(
                constraint_name,
                "data_state != 'AVAILABLE' OR filing_date IS NOT NULL",
            )


def downgrade() -> None:
    for table_name, constraint_name in reversed(_CONSTRAINTS):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                constraint_name,
                type_="check",
            )
