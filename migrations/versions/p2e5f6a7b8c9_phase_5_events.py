"""Phase 5 disclosures, news, analyst and flow reference data

Revision ID: p2e5f6a7b8c9
Revises: o1d4e5f6a7b8
Create Date: 2026-07-29 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p2e5f6a7b8c9"
down_revision: str | None = "o1d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _source_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_function", sa.String(length=160), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "data_timing",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.add_column(
        "disclosures",
        sa.Column(
            "correction_link_state",
            sa.String(length=40),
            nullable=False,
            server_default="NOT_APPLICABLE",
        ),
    )
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("query", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(length=200)),
        sa.Column("original_url", sa.String(length=1000)),
        sa.Column("provider_url", sa.String(length=1000), nullable=False),
        sa.Column("canonical_url", sa.String(length=1000), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("used_text_scope", sa.String(length=64), nullable=False),
        *_source_columns(),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "content_hash",
            name="uq_news_article_stock_content",
        ),
    )
    op.create_table(
        "event_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer()),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_record_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("event_date", sa.Date()),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(length=1000)),
        sa.Column("sentiment", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("matched_rule", sa.String(length=120), nullable=False),
        sa.Column("used_text_scope", sa.String(length=64), nullable=False),
        sa.Column("used_text", sa.Text(), nullable=False),
        sa.Column("price_reflection_note", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column("is_correction", sa.Boolean(), nullable=False),
        sa.Column("original_source_key", sa.String(length=200)),
        sa.Column(
            "correction_link_state",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "source_provider",
            "source_record_key",
            "rule_version",
            name="uq_event_source_rule",
        ),
    )
    op.create_table(
        "analyst_opinions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("broker", sa.String(length=200), nullable=False),
        sa.Column("opinion", sa.String(length=120)),
        sa.Column("target_price", sa.Numeric(precision=24, scale=6)),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=1000)),
        sa.Column("is_estimate", sa.Boolean(), nullable=False),
        *_source_columns(),
        sa.CheckConstraint(
            "target_price IS NULL OR target_price > 0",
            name="ck_analyst_target_price_positive",
        ),
        sa.CheckConstraint(
            "is_estimate = true",
            name="ck_analyst_opinion_estimate",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "source_provider",
            "broker",
            "published_date",
            name="uq_analyst_opinion_source_date",
        ),
    )
    op.create_table(
        "earnings_estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("broker", sa.String(length=200), nullable=False),
        sa.Column("metric_code", sa.String(length=40), nullable=False),
        sa.Column("fiscal_period", sa.String(length=40), nullable=False),
        sa.Column("estimate_value", sa.Numeric(precision=30, scale=8)),
        sa.Column("unit", sa.String(length=40)),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=1000)),
        sa.Column("is_estimate", sa.Boolean(), nullable=False),
        *_source_columns(),
        sa.CheckConstraint(
            "is_estimate = true",
            name="ck_earnings_estimate_flag",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "source_provider",
            "broker",
            "metric_code",
            "fiscal_period",
            "published_date",
            name="uq_earnings_estimate_source_period",
        ),
    )
    op.create_table(
        "investor_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("investor_type", sa.String(length=40), nullable=False),
        sa.Column(
            "net_purchase_quantity",
            sa.Numeric(precision=30, scale=0),
        ),
        sa.Column(
            "net_purchase_amount",
            sa.Numeric(precision=30, scale=2),
        ),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("unit", sa.String(length=40)),
        *_source_columns(),
        sa.CheckConstraint(
            "net_purchase_quantity IS NOT NULL OR "
            "net_purchase_amount IS NOT NULL",
            name="ck_investor_flow_has_value",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "trade_date",
            "source_provider",
            "investor_type",
            name="uq_investor_flow_source_date",
        ),
    )
    op.create_table(
        "program_trading",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("market_code", sa.String(length=40), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column(
            "net_purchase_quantity",
            sa.Numeric(precision=30, scale=0),
        ),
        sa.Column(
            "net_purchase_amount",
            sa.Numeric(precision=30, scale=2),
        ),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("unit", sa.String(length=40)),
        *_source_columns(),
        sa.CheckConstraint(
            "net_purchase_quantity IS NOT NULL OR "
            "net_purchase_amount IS NOT NULL",
            name="ck_program_trading_has_value",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_code",
            "trade_date",
            "source_provider",
            name="uq_program_trading_source_date",
        ),
    )
    op.create_table(
        "short_selling",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer()),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("short_quantity", sa.Numeric(precision=30, scale=0)),
        sa.Column("short_amount", sa.Numeric(precision=30, scale=2)),
        sa.Column("short_ratio", sa.Numeric(precision=12, scale=8)),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("unit", sa.String(length=40)),
        *_source_columns(),
        sa.CheckConstraint(
            "short_quantity IS NOT NULL OR short_amount IS NOT NULL "
            "OR short_ratio IS NOT NULL",
            name="ck_short_selling_has_value",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["api_raw_responses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "trade_date",
            "source_provider",
            name="uq_short_selling_source_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("short_selling")
    op.drop_table("program_trading")
    op.drop_table("investor_flows")
    op.drop_table("earnings_estimates")
    op.drop_table("analyst_opinions")
    op.drop_table("event_records")
    op.drop_table("news_articles")
    op.drop_column("disclosures", "correction_link_state")
