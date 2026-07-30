from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class FinancialStatement(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "financial_statements"
    __table_args__ = (
        CheckConstraint("fs_div IN ('CFS', 'OFS')", name="ck_fs_div"),
        UniqueConstraint(
            "receipt_no",
            "statement_kind",
            "fs_div",
            name="uq_financial_statement_receipt",
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
    corp_code: Mapped[str] = mapped_column(String(16), nullable=False)
    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False)
    original_receipt_no: Mapped[str | None] = mapped_column(String(32))
    report_name: Mapped[str | None] = mapped_column(String(400))
    report_code: Mapped[str] = mapped_column(String(16), nullable=False)
    business_year: Mapped[int] = mapped_column(Integer, nullable=False)
    statement_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    fs_div: Mapped[str] = mapped_column(String(3), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_label: Mapped[str | None] = mapped_column(String(120))
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_cumulative: Mapped[bool | None] = mapped_column(Boolean)
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str | None] = mapped_column(String(12))
    source_url: Mapped[str | None] = mapped_column(String(500))


class FinancialAccount(Base, CreatedAtMixin):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint(
            "statement_id",
            "account_id",
            "account_name",
            "account_detail",
            "statement_section",
            name="uq_financial_account_context",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("financial_statements.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str | None] = mapped_column(String(200))
    account_name: Mapped[str] = mapped_column(String(300), nullable=False)
    account_detail: Mapped[str | None] = mapped_column(String(300))
    statement_section: Mapped[str | None] = mapped_column(String(40))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    current_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    current_cumulative_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    prior_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    prior_quarter_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    prior_cumulative_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    before_prior_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    canonical_metric_code: Mapped[str | None] = mapped_column(String(80))
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_label: Mapped[str | None] = mapped_column(String(300))


class FinancialMetric(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "financial_metrics"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "metric_code",
            "period_end",
            "fs_div",
            "rule_version",
            name="uq_financial_metric_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    unit: Mapped[str | None] = mapped_column(String(40))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    fs_div: Mapped[str | None] = mapped_column(String(3))
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Dividend(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "dividends"
    __table_args__ = (
        Index("ix_dividends_stock_business_year", "stock_id", "business_year"),
        CheckConstraint(
            "data_state != 'AVAILABLE' OR filing_date IS NOT NULL",
            name="ck_dividend_available_filing_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    receipt_no: Mapped[str | None] = mapped_column(String(32))
    original_receipt_no: Mapped[str | None] = mapped_column(String(32))
    business_year: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_kind: Mapped[str | None] = mapped_column(String(80))
    dividend_type: Mapped[str | None] = mapped_column(String(80))
    dps: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    currency: Mapped[str | None] = mapped_column(String(12))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 2))
    fiscal_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    filing_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    is_estimate: Mapped[bool | None] = mapped_column(Boolean)
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DividendFact(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "dividend_facts"
    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "receipt_no",
            "label",
            "stock_kind",
            name="uq_dividend_fact_context",
        ),
        CheckConstraint(
            "data_state != 'AVAILABLE' OR filing_date IS NOT NULL",
            name="ck_dividend_fact_available_filing_date",
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
    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False)
    business_year: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    stock_kind: Mapped[str | None] = mapped_column(String(80))
    current_raw: Mapped[str | None] = mapped_column(String(200))
    prior_raw: Mapped[str | None] = mapped_column(String(200))
    before_prior_raw: Mapped[str | None] = mapped_column(String(200))
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    unit_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="NOT_VERIFIED",
    )
    source_url: Mapped[str | None] = mapped_column(String(500))


class AuditOpinion(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "audit_opinions"
    __table_args__ = (
        UniqueConstraint(
            "receipt_no",
            "business_year",
            name="uq_audit_opinion_receipt_year",
        ),
        CheckConstraint(
            "data_state != 'AVAILABLE' OR filing_date IS NOT NULL",
            name="ck_audit_available_filing_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False)
    original_receipt_no: Mapped[str | None] = mapped_column(String(32))
    business_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_date: Mapped[date | None] = mapped_column(Date)
    auditor: Mapped[str | None] = mapped_column(String(200))
    opinion: Mapped[str | None] = mapped_column(String(200))
    special_matter: Mapped[str | None] = mapped_column(Text)
    emphasis_matter: Mapped[str | None] = mapped_column(Text)
    core_audit_matter: Mapped[str | None] = mapped_column(Text)
    going_concern_risk: Mapped[bool | None] = mapped_column(Boolean)
    going_concern_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="NOT_VERIFIED",
    )
    emphasis_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="NOT_VERIFIED",
    )
    internal_control_issue: Mapped[bool | None] = mapped_column(Boolean)
    filing_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
