"""phase 1c analysis provenance and raw facts

Revision ID: g3b6c7d8e9f0
Revises: f2a5b6c7d8e9
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g3b6c7d8e9f0"
down_revision: str | None = "f2a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.add_column(sa.Column("raw_response_id", sa.Integer()))
        batch_op.add_column(sa.Column("report_name", sa.String(400)))
        batch_op.add_column(sa.Column("period_label", sa.String(120)))
        batch_op.add_column(sa.Column("source_url", sa.String(500)))
        batch_op.alter_column(
            "period_end",
            existing_type=sa.Date(),
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_financial_statements_raw_response",
            "api_raw_responses",
            ["raw_response_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.add_column(sa.Column("current_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("current_cumulative_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("prior_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("prior_quarter_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("prior_cumulative_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("before_prior_amount", sa.Numeric(30, 6)))
        batch_op.add_column(sa.Column("canonical_metric_code", sa.String(80)))

    with op.batch_alter_table("dividends") as batch_op:
        batch_op.add_column(sa.Column("fiscal_date", sa.Date()))
        batch_op.add_column(sa.Column("filing_date", sa.Date()))
        batch_op.add_column(sa.Column("source_url", sa.String(500)))

    with op.batch_alter_table("audit_opinions") as batch_op:
        batch_op.drop_constraint(
            "uq_audit_opinion_receipt",
            type_="unique",
        )
        batch_op.add_column(
            sa.Column(
                "going_concern_status",
                sa.String(32),
                nullable=False,
                server_default="NOT_VERIFIED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "emphasis_status",
                sa.String(32),
                nullable=False,
                server_default="NOT_VERIFIED",
            )
        )
        batch_op.add_column(sa.Column("filing_date", sa.Date()))
        batch_op.add_column(sa.Column("source_url", sa.String(500)))
        batch_op.create_unique_constraint(
            "uq_audit_opinion_receipt_year",
            ["receipt_no", "business_year"],
        )
        batch_op.alter_column(
            "going_concern_status",
            server_default=None,
        )
        batch_op.alter_column("emphasis_status", server_default=None)

    with op.batch_alter_table("disclosures") as batch_op:
        batch_op.add_column(sa.Column("source_url", sa.String(500)))

    op.create_table(
        "dividend_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raw_response_id",
            sa.Integer(),
            sa.ForeignKey("api_raw_responses.id", ondelete="SET NULL"),
        ),
        sa.Column("receipt_no", sa.String(32), nullable=False),
        sa.Column("business_year", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("stock_kind", sa.String(80)),
        sa.Column("current_raw", sa.String(200)),
        sa.Column("prior_raw", sa.String(200)),
        sa.Column("before_prior_raw", sa.String(200)),
        sa.Column("fiscal_date", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date()),
        sa.Column(
            "unit_status",
            sa.String(32),
            nullable=False,
            server_default="NOT_VERIFIED",
        ),
        sa.Column("source_url", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("source_provider", sa.String(64), nullable=False),
        sa.Column("source_function", sa.String(160), nullable=False),
        sa.Column("data_state", sa.String(32), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True)),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("data_timing", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "stock_id",
            "receipt_no",
            "label",
            "stock_kind",
            name="uq_dividend_fact_context",
        ),
    )


def downgrade() -> None:
    op.drop_table("dividend_facts")
    with op.batch_alter_table("disclosures") as batch_op:
        batch_op.drop_column("source_url")
    with op.batch_alter_table("audit_opinions") as batch_op:
        batch_op.drop_constraint(
            "uq_audit_opinion_receipt_year",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_audit_opinion_receipt",
            ["receipt_no"],
        )
        batch_op.drop_column("source_url")
        batch_op.drop_column("filing_date")
        batch_op.drop_column("emphasis_status")
        batch_op.drop_column("going_concern_status")
    with op.batch_alter_table("dividends") as batch_op:
        batch_op.drop_column("source_url")
        batch_op.drop_column("filing_date")
        batch_op.drop_column("fiscal_date")
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_column("canonical_metric_code")
        batch_op.drop_column("before_prior_amount")
        batch_op.drop_column("prior_cumulative_amount")
        batch_op.drop_column("prior_quarter_amount")
        batch_op.drop_column("prior_amount")
        batch_op.drop_column("current_cumulative_amount")
        batch_op.drop_column("current_amount")
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.drop_constraint(
            "fk_financial_statements_raw_response",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "period_end",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch_op.drop_column("source_url")
        batch_op.drop_column("period_label")
        batch_op.drop_column("report_name")
        batch_op.drop_column("raw_response_id")
