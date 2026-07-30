from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class BacktestRun(Base, CreatedAtMixin):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint(
            "backtest_version",
            "rule_version",
            "config_hash",
            "input_data_hash",
            name="uq_backtest_run_reproducible",
        ),
        CheckConstraint(
            "end_date >= start_date",
            name="ck_backtest_date_order",
        ),
        CheckConstraint(
            "transaction_cost_bps >= 0",
            name="ck_backtest_transaction_cost_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    backtest_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recommendation_rule_versions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    market_rule_versions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    universe_construction_method: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )
    financial_availability_method: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    correction_availability_method: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    execution_price_method: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    adjusted_price_source: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    dividend_treatment_method: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    transaction_cost_bps: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
    )
    transaction_cost_assumption: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    benchmark_method: Mapped[str] = mapped_column(Text, nullable=False)
    walk_forward_method: Mapped[str] = mapped_column(Text, nullable=False)
    known_survival_bias: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    missing_data: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    config_payload: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    input_payload: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    result_payload: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
