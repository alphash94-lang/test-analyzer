"""phase 1a stock universe

Revision ID: d0e3f4a5b6c7
Revises: c9d2e3f4a5b6
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e3f4a5b6c7"
down_revision: str | None = "c9d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stocks") as batch_op:
        batch_op.add_column(sa.Column("issue_code", sa.String(32)))
        batch_op.add_column(sa.Column("abbreviated_name", sa.String(200)))
        batch_op.add_column(sa.Column("name_en", sa.String(300)))
        batch_op.add_column(sa.Column("market_name", sa.String(80)))
        batch_op.add_column(sa.Column("security_group_name", sa.String(120)))
        batch_op.add_column(sa.Column("department_name", sa.String(120)))
        batch_op.add_column(sa.Column("certificate_type_name", sa.String(120)))
        batch_op.add_column(sa.Column("share_class", sa.String(32)))
        batch_op.add_column(sa.Column("par_value_raw", sa.String(80)))
        batch_op.add_column(sa.Column("listed_shares_raw", sa.String(80)))
        batch_op.add_column(sa.Column("dart_corp_code", sa.String(8)))
        batch_op.add_column(sa.Column("dart_modified_on", sa.Date()))
        batch_op.add_column(
            sa.Column(
                "listing_status",
                sa.String(32),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch_op.add_column(
            sa.Column(
                "universe_status",
                sa.String(32),
                nullable=False,
                server_default="REVIEW_REQUIRED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "quality_state",
                sa.String(32),
                nullable=False,
                server_default="REVIEW_REQUIRED",
            )
        )
        batch_op.create_index("ix_stocks_name_ko", ["name_ko"])
        batch_op.create_index(
            "ix_stocks_dart_corp_code",
            ["dart_corp_code"],
        )
        batch_op.alter_column("listing_status", server_default=None)
        batch_op.alter_column("universe_status", server_default=None)
        batch_op.alter_column("quality_state", server_default=None)

    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.add_column(sa.Column("raw_storage_path", sa.String(1000)))
        batch_op.add_column(sa.Column("content_type", sa.String(200)))
        batch_op.create_unique_constraint(
            "uq_api_raw_response_content",
            [
                "provider",
                "function_name",
                "request_params_hash",
                "response_hash",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("api_raw_responses") as batch_op:
        batch_op.drop_constraint(
            "uq_api_raw_response_content",
            type_="unique",
        )
        batch_op.drop_column("content_type")
        batch_op.drop_column("raw_storage_path")

    with op.batch_alter_table("stocks") as batch_op:
        batch_op.drop_index("ix_stocks_dart_corp_code")
        batch_op.drop_index("ix_stocks_name_ko")
        batch_op.drop_column("quality_state")
        batch_op.drop_column("universe_status")
        batch_op.drop_column("listing_status")
        batch_op.drop_column("dart_modified_on")
        batch_op.drop_column("dart_corp_code")
        batch_op.drop_column("listed_shares_raw")
        batch_op.drop_column("par_value_raw")
        batch_op.drop_column("share_class")
        batch_op.drop_column("certificate_type_name")
        batch_op.drop_column("department_name")
        batch_op.drop_column("security_group_name")
        batch_op.drop_column("market_name")
        batch_op.drop_column("name_en")
        batch_op.drop_column("abbreviated_name")
        batch_op.drop_column("issue_code")
