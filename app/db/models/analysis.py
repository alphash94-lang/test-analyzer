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


class ScoreSnapshot(Base, CreatedAtMixin):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "as_of_at",
            "score_version",
            "rule_version",
            "input_data_hash",
            name="uq_score_snapshot_reproducible",
        ),
        CheckConstraint(
            "investment_score IS NULL OR "
            "(investment_score >= 0 AND investment_score <= 100)",
            name="ck_investment_score_range",
        ),
        CheckConstraint(
            "entry_score IS NULL OR (entry_score >= 0 AND entry_score <= 100)",
            name="ck_entry_score_range",
        ),
        CheckConstraint(
            "individual_entry_score IS NULL OR "
            "(individual_entry_score >= 0 AND individual_entry_score <= 100)",
            name="ck_individual_entry_score_range",
        ),
        CheckConstraint(
            "data_confidence IS NULL OR "
            "(data_confidence >= 0 AND data_confidence <= 100)",
            name="ck_data_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    score_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    investment_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    entry_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    data_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    score_scope: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="PHASE2_CORE_ONLY",
    )
    individual_entry_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    filter_state: Mapped[str] = mapped_column(String(32), nullable=False)
    recommendation_computable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    missing_core_data: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class ForcedFilterResult(Base, CreatedAtMixin):
    __tablename__ = "forced_filter_results"
    __table_args__ = (
        UniqueConstraint(
            "score_snapshot_id",
            "filter_code",
            name="uq_forced_filter_snapshot_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("score_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    filter_code: Mapped[str] = mapped_column(String(80), nullable=False)
    filter_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    raw_text: Mapped[str | None] = mapped_column(Text)
    source_provider: Mapped[str | None] = mapped_column(String(120))
    evidence_date: Mapped[date | None] = mapped_column(Date)


class ScoreComponentRecord(Base, CreatedAtMixin):
    __tablename__ = "score_components"
    __table_args__ = (
        UniqueConstraint(
            "score_snapshot_id",
            "score_name",
            "component_code",
            name="uq_score_component_snapshot_code",
        ),
        CheckConstraint(
            "normalized_value IS NULL OR "
            "(normalized_value >= 0 AND normalized_value <= 100)",
            name="ck_score_component_normalized_range",
        ),
        CheckConstraint(
            "weight IS NULL OR weight > 0",
            name="ck_score_component_positive_weight",
        ),
        CheckConstraint(
            "contribution IS NULL OR contribution >= 0",
            name="ck_score_component_nonnegative_contribution",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("score_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_name: Mapped[str] = mapped_column(String(80), nullable=False)
    component_code: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    raw_text: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    contribution: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)


class ValuationComparisonRecord(Base, CreatedAtMixin):
    __tablename__ = "valuation_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "score_snapshot_id",
            "metric_code",
            name="uq_valuation_comparison_snapshot_metric",
        ),
        CheckConstraint(
            "industry_percentile IS NULL OR "
            "(industry_percentile >= 0 AND industry_percentile <= 100)",
            name="ck_valuation_industry_percentile_range",
        ),
        CheckConstraint(
            "historical_percentile IS NULL OR "
            "(historical_percentile >= 0 AND historical_percentile <= 100)",
            name="ck_valuation_historical_percentile_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("score_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    industry_median: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    historical_median: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    industry_percentile: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    historical_percentile: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    comparison_level: Mapped[str | None] = mapped_column(String(40))
    classification_code: Mapped[str | None] = mapped_column(String(80))
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class Recommendation(Base, CreatedAtMixin):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "as_of_at",
            "score_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
            name="uq_recommendation_reproducible",
        ),
        CheckConstraint(
            "investment_score IS NULL OR "
            "(investment_score >= 0 AND investment_score <= 100)",
            name="ck_recommendation_investment_score_range",
        ),
        CheckConstraint(
            "entry_score IS NULL OR (entry_score >= 0 AND entry_score <= 100)",
            name="ck_recommendation_entry_score_range",
        ),
        CheckConstraint(
            "data_confidence IS NULL OR "
            "(data_confidence >= 0 AND data_confidence <= 100)",
            name="ck_recommendation_confidence_range",
        ),
        CheckConstraint(
            "target_weight IS NULL OR (target_weight >= 0 AND target_weight <= 1)",
            name="ck_recommendation_target_weight_range",
        ),
        CheckConstraint(
            "initial_buy_weight IS NULL OR "
            "(initial_buy_weight >= 0 AND initial_buy_weight <= 1)",
            name="ck_recommendation_initial_weight_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_snapshots.id", ondelete="SET NULL")
    )
    recommendation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_runs.id", ondelete="CASCADE")
    )
    market_regime_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_regime_snapshots.id", ondelete="SET NULL")
    )
    as_of_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_basis_date: Mapped[date | None] = mapped_column(Date)
    rank: Mapped[int | None] = mapped_column(Integer)
    recommendation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    recommendation_label: Mapped[str | None] = mapped_column(String(120))
    reason_summary: Mapped[str | None] = mapped_column(Text)
    score_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    market_rule_version: Mapped[str | None] = mapped_column(String(40))
    config_hash: Mapped[str | None] = mapped_column(String(64))
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score_scope: Mapped[str | None] = mapped_column(String(80))
    entry_score_scope: Mapped[str | None] = mapped_column(String(80))
    investment_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    entry_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    data_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    market_regime: Mapped[str | None] = mapped_column(String(32))
    portfolio_sleeve: Mapped[str | None] = mapped_column(String(32))
    industry_code: Mapped[str | None] = mapped_column(String(80))
    company_group_code: Mapped[str | None] = mapped_column(String(80))
    company_group_check_state: Mapped[str | None] = mapped_column(String(32))
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    initial_buy_weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    holding_action: Mapped[str | None] = mapped_column(String(40))
    raw_metrics: Mapped[dict[str, object] | None] = mapped_column(JSON)
    filter_results: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    positive_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    risk_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    exclusion_reasons: Mapped[list[str] | None] = mapped_column(JSON)
    missing_data: Mapped[list[str] | None] = mapped_column(JSON)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
