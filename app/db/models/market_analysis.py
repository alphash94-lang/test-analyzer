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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, SourceMetadataMixin


class IndexDaily(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "index_daily"
    __table_args__ = (
        UniqueConstraint(
            "index_name",
            "trade_date",
            "source_provider",
            name="uq_index_daily_source",
        ),
        Index("ix_index_daily_name_date", "index_name", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_class: Mapped[str] = mapped_column(String(120), nullable=False)
    index_name: Mapped[str] = mapped_column(String(160), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    previous_day_change: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
    )
    fluctuation_rate: Mapped[Decimal] = mapped_column(
        Numeric(16, 8),
        nullable=False,
    )
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 0), nullable=False)
    trading_value: Mapped[Decimal] = mapped_column(
        Numeric(30, 2),
        nullable=False,
    )
    market_cap: Mapped[Decimal] = mapped_column(
        Numeric(30, 2),
        nullable=False,
    )


class MarketRegimeSnapshot(Base, CreatedAtMixin):
    __tablename__ = "market_regime_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "as_of_at",
            "rule_version",
            "input_data_hash",
            name="uq_market_regime_reproducible",
        ),
        CheckConstraint(
            "data_confidence IS NULL OR "
            "(data_confidence >= 0 AND data_confidence <= 100)",
            name="ck_market_regime_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    shock_classification: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    market_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    data_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    proxy_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    semiconductor_recovery: Mapped[bool | None] = mapped_column(Boolean)
    kospi_recovery: Mapped[bool | None] = mapped_column(Boolean)
    non_semiconductor_breadth: Mapped[bool | None] = mapped_column(Boolean)
    dividend_relative_strength_recovery: Mapped[bool | None] = mapped_column(Boolean)
    missing_core_data: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class MarketMetricRecord(Base, CreatedAtMixin):
    __tablename__ = "market_metric_records"
    __table_args__ = (
        UniqueConstraint(
            "market_regime_snapshot_id",
            "metric_code",
            name="uq_market_metric_snapshot_code",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_regime_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("market_regime_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_label: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    text_value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(80))
    source_provider: Mapped[str | None] = mapped_column(String(120))
    source_function: Mapped[str | None] = mapped_column(String(200))
    as_of_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculation_method: Mapped[str] = mapped_column(Text, nullable=False)
    data_quality: Mapped[str] = mapped_column(String(80), nullable=False)
    data_timing: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    proxy_kind: Mapped[str] = mapped_column(String(40), nullable=False)


class MarketContributionRecord(Base, CreatedAtMixin):
    __tablename__ = "market_contribution_records"
    __table_args__ = (
        UniqueConstraint(
            "market_regime_snapshot_id",
            "stock_id",
            name="uq_market_contribution_snapshot_stock",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_regime_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("market_regime_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    return_rate: Mapped[Decimal] = mapped_column(
        Numeric(20, 10),
        nullable=False,
    )
    previous_weight: Mapped[Decimal] = mapped_column(
        Numeric(20, 10),
        nullable=False,
    )
    contribution: Mapped[Decimal] = mapped_column(
        Numeric(20, 10),
        nullable=False,
    )
    is_semiconductor: Mapped[bool | None] = mapped_column(Boolean)
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    market_cap_source_provider: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    classification_source: Mapped[str | None] = mapped_column(String(120))
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_timing: Mapped[str] = mapped_column(String(32), nullable=False)
    calculation_method: Mapped[str] = mapped_column(Text, nullable=False)
    data_quality: Mapped[str] = mapped_column(String(80), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    proxy_kind: Mapped[str] = mapped_column(String(40), nullable=False)
