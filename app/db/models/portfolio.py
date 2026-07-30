from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class PortfolioSetting(Base, CreatedAtMixin):
    __tablename__ = "portfolio_settings"
    __table_args__ = (
        UniqueConstraint("profile_hash", name="uq_portfolio_setting_hash"),
        CheckConstraint(
            "total_capital IS NULL OR total_capital >= 0",
            name="ck_portfolio_total_capital_nonnegative",
        ),
        CheckConstraint(
            "current_cash IS NULL OR current_cash >= 0",
            name="ck_portfolio_current_cash_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    profile_name: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    total_capital: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    current_cash: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    risk_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    target_dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    target_stock_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_dividend_stock_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    max_growth_stock_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    max_industry_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    max_company_group_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    include_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False)
    include_reits: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minimum_trading_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    normal_target: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    regime_targets: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    config_payload: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )


class RecommendationRun(Base, CreatedAtMixin):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        UniqueConstraint(
            "as_of_at",
            "score_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
            name="uq_recommendation_run_reproducible",
        ),
        CheckConstraint(
            "total_count >= 0 AND processed_count >= 0 "
            "AND recommended_count >= 0 AND excluded_count >= 0 "
            "AND insufficient_count >= 0",
            name="ck_recommendation_run_counts_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_setting_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_settings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    market_regime_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_regime_snapshots.id", ondelete="SET NULL")
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    as_of_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    data_basis_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    score_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    market_rule_version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    market_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_hashes: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    insufficient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_core_data: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class RecommendationReason(Base, CreatedAtMixin):
    __tablename__ = "recommendation_reasons"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "reason_type",
            "sequence",
            name="uq_recommendation_reason_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)


class SplitBuyPlan(Base, CreatedAtMixin):
    __tablename__ = "split_buy_plans"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            name="uq_split_buy_plan_recommendation",
        ),
        CheckConstraint(
            "is_order_executable = false",
            name="ck_split_buy_read_only",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    reference_price_date: Mapped[date | None] = mapped_column(Date)
    reference_price_provider: Mapped[str | None] = mapped_column(String(120))
    reference_price_currency: Mapped[str | None] = mapped_column(String(12))
    reference_price_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    reference_price_timing: Mapped[str | None] = mapped_column(String(32))
    tranches: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    cancellation_conditions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    is_order_executable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class PortfolioPosition(Base, CreatedAtMixin):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_setting_id",
            "stock_id",
            name="uq_portfolio_position_profile_stock",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_portfolio_position_quantity_positive",
        ),
        CheckConstraint(
            "average_purchase_price IS NULL OR average_purchase_price > 0",
            name="ck_portfolio_position_average_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_setting_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    average_purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(12))
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="USER_INPUT",
    )


class PortfolioAllocation(Base, CreatedAtMixin):
    __tablename__ = "portfolio_allocations"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_run_id",
            "stock_id",
            name="uq_portfolio_allocation_run_stock",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    sleeve: Mapped[str] = mapped_column(String(32), nullable=False)
    target_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    initial_buy_weight: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        nullable=False,
    )
    industry_code: Mapped[str | None] = mapped_column(String(80))
    company_group_code: Mapped[str | None] = mapped_column(String(80))
    company_group_check_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
