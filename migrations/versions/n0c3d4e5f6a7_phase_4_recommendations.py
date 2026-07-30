"""phase 4 recommendations and portfolio

Revision ID: n0c3d4e5f6a7
Revises: m9b2c3d4e5f6
Create Date: 2026-07-29 16:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n0c3d4e5f6a7"
down_revision: str | None = "m9b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(length=120), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("total_capital", sa.Numeric(precision=30, scale=2)),
        sa.Column("current_cash", sa.Numeric(precision=30, scale=2)),
        sa.Column("risk_profile", sa.String(length=40), nullable=False),
        sa.Column(
            "target_dividend_yield",
            sa.Numeric(precision=12, scale=8),
        ),
        sa.Column("target_stock_count", sa.Integer(), nullable=False),
        sa.Column(
            "max_dividend_stock_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column(
            "max_growth_stock_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column(
            "max_industry_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column(
            "max_company_group_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column("include_preferred", sa.Boolean(), nullable=False),
        sa.Column("include_reits", sa.Boolean(), nullable=False),
        sa.Column(
            "minimum_trading_value",
            sa.Numeric(precision=30, scale=2),
        ),
        sa.Column("normal_target", sa.JSON(), nullable=False),
        sa.Column("regime_targets", sa.JSON(), nullable=False),
        sa.Column("config_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_capital IS NULL OR total_capital >= 0",
            name="ck_portfolio_total_capital_nonnegative",
        ),
        sa.CheckConstraint(
            "current_cash IS NULL OR current_cash >= 0",
            name="ck_portfolio_current_cash_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_hash",
            name="uq_portfolio_setting_hash",
        ),
    )
    op.create_table(
        "recommendation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_setting_id", sa.Integer(), nullable=False),
        sa.Column("market_regime_snapshot_id", sa.Integer()),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_basis_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_state", sa.String(length=32), nullable=False),
        sa.Column("score_version", sa.String(length=40), nullable=False),
        sa.Column("rule_version", sa.String(length=40), nullable=False),
        sa.Column(
            "market_rule_version",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column("market_regime", sa.String(length=32), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("input_data_hash", sa.String(length=64), nullable=False),
        sa.Column("source_snapshot_hashes", sa.JSON(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("recommended_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("insufficient_count", sa.Integer(), nullable=False),
        sa.Column("missing_core_data", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_count >= 0 AND processed_count >= 0 "
            "AND recommended_count >= 0 AND excluded_count >= 0 "
            "AND insufficient_count >= 0",
            name="ck_recommendation_run_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["market_regime_snapshot_id"],
            ["market_regime_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_setting_id"],
            ["portfolio_settings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "as_of_at",
            "score_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
            name="uq_recommendation_run_reproducible",
        ),
    )
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(sa.Column("recommendation_run_id", sa.Integer()))
        batch_op.add_column(sa.Column("market_regime_snapshot_id", sa.Integer()))
        batch_op.add_column(sa.Column("analyzed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("data_basis_date", sa.Date()))
        batch_op.add_column(sa.Column("rank", sa.Integer()))
        batch_op.add_column(sa.Column("recommendation_label", sa.String(length=120)))
        batch_op.add_column(sa.Column("market_rule_version", sa.String(length=40)))
        batch_op.add_column(sa.Column("config_hash", sa.String(length=64)))
        batch_op.add_column(sa.Column("score_scope", sa.String(length=80)))
        batch_op.add_column(sa.Column("entry_score_scope", sa.String(length=80)))
        batch_op.add_column(
            sa.Column(
                "investment_score",
                sa.Numeric(precision=7, scale=3),
            )
        )
        batch_op.add_column(sa.Column("entry_score", sa.Numeric(precision=7, scale=3)))
        batch_op.add_column(
            sa.Column(
                "data_confidence",
                sa.Numeric(precision=7, scale=3),
            )
        )
        batch_op.add_column(sa.Column("market_regime", sa.String(length=32)))
        batch_op.add_column(sa.Column("portfolio_sleeve", sa.String(length=32)))
        batch_op.add_column(sa.Column("industry_code", sa.String(length=80)))
        batch_op.add_column(sa.Column("company_group_code", sa.String(length=80)))
        batch_op.add_column(
            sa.Column(
                "company_group_check_state",
                sa.String(length=32),
            )
        )
        batch_op.add_column(
            sa.Column(
                "target_weight",
                sa.Numeric(precision=12, scale=8),
            )
        )
        batch_op.add_column(
            sa.Column(
                "initial_buy_weight",
                sa.Numeric(precision=12, scale=8),
            )
        )
        batch_op.add_column(sa.Column("holding_action", sa.String(length=40)))
        batch_op.add_column(sa.Column("raw_metrics", sa.JSON()))
        batch_op.add_column(sa.Column("filter_results", sa.JSON()))
        batch_op.add_column(sa.Column("positive_reasons", sa.JSON()))
        batch_op.add_column(sa.Column("risk_reasons", sa.JSON()))
        batch_op.add_column(sa.Column("exclusion_reasons", sa.JSON()))
        batch_op.add_column(sa.Column("missing_data", sa.JSON()))
        batch_op.create_foreign_key(
            "fk_recommendations_run",
            "recommendation_runs",
            ["recommendation_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_recommendations_market_snapshot",
            "market_regime_snapshots",
            ["market_regime_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_recommendation_investment_score_range",
            "investment_score IS NULL OR "
            "(investment_score >= 0 AND investment_score <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_recommendation_entry_score_range",
            "entry_score IS NULL OR (entry_score >= 0 AND entry_score <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_recommendation_confidence_range",
            "data_confidence IS NULL OR "
            "(data_confidence >= 0 AND data_confidence <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_recommendation_target_weight_range",
            "target_weight IS NULL OR (target_weight >= 0 AND target_weight <= 1)",
        )
        batch_op.create_check_constraint(
            "ck_recommendation_initial_weight_range",
            "initial_buy_weight IS NULL OR "
            "(initial_buy_weight >= 0 AND initial_buy_weight <= 1)",
        )
    op.create_table(
        "recommendation_reasons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("reason_type", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=100)),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id",
            "reason_type",
            "sequence",
            name="uq_recommendation_reason_sequence",
        ),
    )
    op.create_table(
        "split_buy_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "reference_price",
            sa.Numeric(precision=24, scale=6),
        ),
        sa.Column("reference_price_date", sa.Date()),
        sa.Column(
            "reference_price_provider",
            sa.String(length=120),
        ),
        sa.Column(
            "reference_price_currency",
            sa.String(length=12),
        ),
        sa.Column("tranches", sa.JSON(), nullable=False),
        sa.Column("cancellation_conditions", sa.JSON(), nullable=False),
        sa.Column(
            "is_order_executable",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "is_order_executable = false",
            name="ck_split_buy_read_only",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id",
            name="uq_split_buy_plan_recommendation",
        ),
    )
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_setting_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(precision=30, scale=6),
            nullable=False,
        ),
        sa.Column(
            "average_purchase_price",
            sa.Numeric(precision=24, scale=6),
        ),
        sa.Column("currency", sa.String(length=12)),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_portfolio_position_quantity_positive",
        ),
        sa.CheckConstraint(
            "average_purchase_price IS NULL OR average_purchase_price > 0",
            name="ck_portfolio_position_average_price_positive",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_setting_id"],
            ["portfolio_settings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_setting_id",
            "stock_id",
            name="uq_portfolio_position_profile_stock",
        ),
    )
    op.create_table(
        "portfolio_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_run_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("sleeve", sa.String(length=32), nullable=False),
        sa.Column(
            "target_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column(
            "initial_buy_weight",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column("industry_code", sa.String(length=80)),
        sa.Column("company_group_code", sa.String(length=80)),
        sa.Column(
            "company_group_check_state",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_run_id"],
            ["recommendation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_run_id",
            "stock_id",
            name="uq_portfolio_allocation_run_stock",
        ),
    )


def downgrade() -> None:
    op.drop_table("portfolio_allocations")
    op.drop_table("portfolio_positions")
    op.drop_table("split_buy_plans")
    op.drop_table("recommendation_reasons")
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_constraint(
            "ck_recommendation_initial_weight_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_recommendation_target_weight_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_recommendation_confidence_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_recommendation_entry_score_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_recommendation_investment_score_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_recommendations_market_snapshot",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_recommendations_run",
            type_="foreignkey",
        )
        for column in (
            "missing_data",
            "exclusion_reasons",
            "risk_reasons",
            "positive_reasons",
            "filter_results",
            "raw_metrics",
            "holding_action",
            "initial_buy_weight",
            "target_weight",
            "company_group_check_state",
            "company_group_code",
            "industry_code",
            "portfolio_sleeve",
            "market_regime",
            "data_confidence",
            "entry_score",
            "investment_score",
            "entry_score_scope",
            "score_scope",
            "config_hash",
            "market_rule_version",
            "recommendation_label",
            "rank",
            "data_basis_date",
            "analyzed_at",
            "market_regime_snapshot_id",
            "recommendation_run_id",
        ):
            batch_op.drop_column(column)
    op.drop_table("recommendation_runs")
    op.drop_table("portfolio_settings")
