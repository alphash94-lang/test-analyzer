from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, SourceMetadataMixin


class Stock(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "stocks"
    __table_args__ = (
        Index("ix_stocks_name_ko", "name_ko"),
        Index("ix_stocks_dart_corp_code", "dart_corp_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    issue_code: Mapped[str | None] = mapped_column(String(32))
    name_ko: Mapped[str] = mapped_column(String(200), nullable=False)
    abbreviated_name: Mapped[str | None] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(300))
    market_code: Mapped[str | None] = mapped_column(String(32))
    market_name: Mapped[str | None] = mapped_column(String(80))
    is_kospi: Mapped[bool | None] = mapped_column(Boolean)
    security_type: Mapped[str | None] = mapped_column(String(64))
    security_group_name: Mapped[str | None] = mapped_column(String(120))
    department_name: Mapped[str | None] = mapped_column(String(120))
    certificate_type_name: Mapped[str | None] = mapped_column(String(120))
    share_class: Mapped[str | None] = mapped_column(String(32))
    par_value_raw: Mapped[str | None] = mapped_column(String(80))
    listed_shares_raw: Mapped[str | None] = mapped_column(String(80))
    dart_corp_code: Mapped[str | None] = mapped_column(String(8))
    dart_modified_on: Mapped[date | None] = mapped_column(Date)
    dart_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dart_data_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="NOT_VERIFIED",
    )
    listing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
    )
    universe_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="REVIEW_REQUIRED",
    )
    quality_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="REVIEW_REQUIRED",
    )
    listed_on: Mapped[date | None] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool | None] = mapped_column(Boolean)


class StockClassification(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "stock_classifications"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "classification_system",
            "classification_code",
            "valid_from",
            name="uq_stock_classification_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    classification_system: Mapped[str] = mapped_column(String(80), nullable=False)
    classification_code: Mapped[str] = mapped_column(String(80), nullable=False)
    classification_name: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class MarketStatus(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "market_status"
    __table_args__ = (
        Index("ix_market_status_stock_effective", "stock_id", "effective_from"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE")
    )
    status_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status_value: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceDaily(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "price_daily"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "trade_date",
            "source_provider",
            name="uq_price_daily_source",
        ),
        Index("ix_price_daily_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(12))
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    previous_day_change: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    trading_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    listed_shares: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    is_adjusted: Mapped[bool | None] = mapped_column(Boolean)
    adjustment_status: Mapped[str | None] = mapped_column(String(40))
