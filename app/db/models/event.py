from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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

from app.db.base import Base, CreatedAtMixin, SourceMetadataMixin


class NewsArticle(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "content_hash",
            name="uq_news_article_stock_content",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(200))
    original_url: Mapped[str | None] = mapped_column(String(1000))
    provider_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    used_text_scope: Mapped[str] = mapped_column(String(64), nullable=False)


class EventWatchlistItem(Base, CreatedAtMixin):
    __tablename__ = "event_watchlist_items"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "category",
            name="uq_event_watchlist_stock_category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="INTEREST",
    )


class EventRecord(Base, CreatedAtMixin):
    __tablename__ = "event_records"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "source_provider",
            "source_record_key",
            "rule_version",
            name="uq_event_source_rule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE")
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(String(1000))
    sentiment: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    matched_rule: Mapped[str] = mapped_column(String(120), nullable=False)
    used_text_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    used_text: Mapped[str] = mapped_column(Text, nullable=False)
    price_reflection_note: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_correction: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    original_source_key: Mapped[str | None] = mapped_column(String(200))
    correction_link_state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )


class AnalystOpinion(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "analyst_opinions"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "source_provider",
            "broker",
            "published_date",
            name="uq_analyst_opinion_source_date",
        ),
        CheckConstraint(
            "target_price IS NULL OR target_price > 0",
            name="ck_analyst_target_price_positive",
        ),
        CheckConstraint(
            "is_estimate = true",
            name="ck_analyst_opinion_estimate",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    broker: Mapped[str] = mapped_column(String(200), nullable=False)
    opinion: Mapped[str | None] = mapped_column(String(120))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(12))
    published_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EarningsEstimate(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "earnings_estimates"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "source_provider",
            "broker",
            "metric_code",
            "fiscal_period",
            "published_date",
            name="uq_earnings_estimate_source_period",
        ),
        CheckConstraint(
            "is_estimate = true",
            name="ck_earnings_estimate_flag",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    broker: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(40), nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(40), nullable=False)
    estimate_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 8))
    unit: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(12))
    published_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InvestorFlow(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "investor_flows"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "trade_date",
            "source_provider",
            "investor_type",
            name="uq_investor_flow_source_date",
        ),
        CheckConstraint(
            "net_purchase_quantity IS NOT NULL OR net_purchase_amount IS NOT NULL",
            name="ck_investor_flow_has_value",
        ),
        CheckConstraint(
            "data_state <> 'AVAILABLE' OR net_purchase_quantity IS NULL "
            "OR net_purchase_quantity = ROUND(net_purchase_quantity, 0)",
            name="ck_investor_flow_available_quantity_integral",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    investor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    net_purchase_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    net_purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    unit: Mapped[str | None] = mapped_column(String(40))


class ProgramTrading(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "program_trading"
    __table_args__ = (
        UniqueConstraint(
            "market_code",
            "trade_date",
            "source_provider",
            name="uq_program_trading_source_date",
        ),
        CheckConstraint(
            "net_purchase_quantity IS NOT NULL OR net_purchase_amount IS NOT NULL",
            name="ck_program_trading_has_value",
        ),
        CheckConstraint(
            "data_state <> 'AVAILABLE' OR net_purchase_quantity IS NULL "
            "OR net_purchase_quantity = ROUND(net_purchase_quantity, 0)",
            name="ck_program_available_quantity_integral",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    market_code: Mapped[str] = mapped_column(String(40), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    net_purchase_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    net_purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    currency: Mapped[str | None] = mapped_column(String(12))
    unit: Mapped[str | None] = mapped_column(String(40))


class ShortSelling(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "short_selling"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "trade_date",
            "source_provider",
            name="uq_short_selling_source_date",
        ),
        CheckConstraint(
            "short_quantity IS NOT NULL OR short_amount IS NOT NULL "
            "OR short_ratio IS NOT NULL",
            name="ck_short_selling_has_value",
        ),
        CheckConstraint(
            "data_state <> 'AVAILABLE' OR short_quantity IS NULL OR "
            "(short_quantity >= 0 AND "
            "short_quantity = ROUND(short_quantity, 0))",
            name="ck_short_available_quantity_valid",
        ),
        CheckConstraint(
            "data_state <> 'AVAILABLE' OR short_amount IS NULL "
            "OR short_amount >= 0",
            name="ck_short_available_amount_nonnegative",
        ),
        CheckConstraint(
            "data_state <> 'AVAILABLE' OR short_ratio IS NULL "
            "OR (short_ratio >= 0 AND short_ratio <= 100)",
            name="ck_short_available_ratio_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    short_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 0))
    short_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    currency: Mapped[str | None] = mapped_column(String(12))
    unit: Mapped[str | None] = mapped_column(String(40))
