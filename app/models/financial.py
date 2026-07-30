from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.metadata import DataState, FinancialScope
from app.utils.dates import ensure_kst

_RECEIPT_NUMBER = re.compile(r"^\d{14}$")
_CORP_CODE = re.compile(r"^\d{8}$")
_REPORT_CODES = {"11011", "11012", "11013", "11014"}
_DISCLOSURE_MODIFICATION_PREFIXES = (
    "[기재정정]",
    "[첨부정정]",
    "[첨부추가]",
    "[변경등록]",
    "[연장결정]",
    "[발행조건확정]",
    "[정정명령부과]",
    "[정정제출요구]",
)


def parse_dart_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    normalized = str(value).strip().replace(",", "")
    if normalized in {"", "-"}:
        return None
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1]
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("OpenDART amount is invalid") from exc
    if not result.is_finite():
        raise ValueError("OpenDART amount must be finite")
    return -result if negative else result


class DartDisclosureItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    corp_class: str = Field(alias="corp_cls")
    corp_name: str
    corp_code: str
    stock_code: str | None = None
    report_name: str = Field(alias="report_nm")
    receipt_no: str = Field(alias="rcept_no")
    filer_name: str = Field(alias="flr_nm")
    receipt_date_raw: str = Field(alias="rcept_dt")
    remark: str | None = Field(default=None, alias="rm")

    @field_validator(
        "corp_class",
        "corp_name",
        "corp_code",
        "report_name",
        "receipt_no",
        "filer_name",
        "receipt_date_raw",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("OpenDART required disclosure field is null")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("OpenDART required disclosure field is empty")
        return normalized

    @field_validator("stock_code", "remark", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("corp_code")
    @classmethod
    def validate_corp_code(cls, value: str) -> str:
        if not _CORP_CODE.fullmatch(value):
            raise ValueError("OpenDART corp_code must be eight digits")
        return value

    @field_validator("receipt_no")
    @classmethod
    def validate_receipt_no(cls, value: str) -> str:
        if not _RECEIPT_NUMBER.fullmatch(value):
            raise ValueError("OpenDART rcept_no must be fourteen digits")
        return value

    @field_validator("receipt_date_raw")
    @classmethod
    def validate_receipt_date(cls, value: str) -> str:
        if len(value) != 8 or not value.isdigit():
            raise ValueError("OpenDART rcept_dt must use YYYYMMDD")
        date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        return value

    @property
    def receipt_date(self) -> date:
        return date(
            int(self.receipt_date_raw[:4]),
            int(self.receipt_date_raw[4:6]),
            int(self.receipt_date_raw[6:8]),
        )

    @property
    def is_correction(self) -> bool:
        return self.report_name.startswith(_DISCLOSURE_MODIFICATION_PREFIXES)

    @property
    def source_url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.receipt_no}"


class DartDisclosurePage(BaseModel):
    items: tuple[DartDisclosureItem, ...]
    page_no: int = Field(ge=1)
    page_count: int = Field(ge=1, le=100)
    total_count: int = Field(ge=1)
    total_page: int = Field(ge=1)


class DartFinancialAccountItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    receipt_no: str = Field(alias="rcept_no")
    report_code: str = Field(alias="reprt_code")
    business_year: int = Field(alias="bsns_year")
    corp_code: str
    statement_section: str = Field(alias="sj_div")
    statement_name: str = Field(alias="sj_nm")
    account_id: str | None
    account_name: str = Field(alias="account_nm")
    account_detail: str | None = None
    current_period_name: str = Field(alias="thstrm_nm")
    current_amount: Decimal | None = Field(alias="thstrm_amount")
    current_cumulative_amount: Decimal | None = Field(alias="thstrm_add_amount")
    prior_period_name: str = Field(alias="frmtrm_nm")
    prior_amount: Decimal | None = Field(alias="frmtrm_amount")
    prior_quarter_name: str | None = Field(default=None, alias="frmtrm_q_nm")
    prior_quarter_amount: Decimal | None = Field(
        default=None,
        alias="frmtrm_q_amount",
    )
    prior_cumulative_amount: Decimal | None = Field(
        default=None,
        alias="frmtrm_add_amount",
    )
    before_prior_period_name: str | None = Field(
        default=None,
        alias="bfefrmtrm_nm",
    )
    before_prior_amount: Decimal | None = Field(
        default=None,
        alias="bfefrmtrm_amount",
    )
    order: int = Field(alias="ord")
    currency: str | None

    @field_validator(
        "current_amount",
        "current_cumulative_amount",
        "prior_amount",
        "prior_quarter_amount",
        "prior_cumulative_amount",
        "before_prior_amount",
        mode="before",
    )
    @classmethod
    def parse_amount(cls, value: object) -> Decimal | None:
        return parse_dart_decimal(value)

    @field_validator(
        "receipt_no",
        "report_code",
        "corp_code",
        "statement_section",
        "statement_name",
        "account_name",
        "current_period_name",
        "prior_period_name",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("OpenDART required financial field is null")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("OpenDART required financial field is empty")
        return normalized

    @field_validator(
        "account_id",
        "account_detail",
        "prior_quarter_name",
        "before_prior_period_name",
        "currency",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("receipt_no")
    @classmethod
    def validate_receipt_no(cls, value: str) -> str:
        if not _RECEIPT_NUMBER.fullmatch(value):
            raise ValueError("OpenDART rcept_no must be fourteen digits")
        return value

    @field_validator("report_code")
    @classmethod
    def validate_report_code(cls, value: str) -> str:
        if value not in _REPORT_CODES:
            raise ValueError("unsupported OpenDART report code")
        return value

    @field_validator("corp_code")
    @classmethod
    def validate_corp_code(cls, value: str) -> str:
        if not _CORP_CODE.fullmatch(value):
            raise ValueError("OpenDART corp_code must be eight digits")
        return value


class DartDividendFactItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    receipt_no: str = Field(alias="rcept_no")
    corp_class: str = Field(alias="corp_cls")
    corp_code: str
    corp_name: str
    label: str = Field(alias="se")
    stock_kind: str | None = Field(default=None, alias="stock_knd")
    current_raw: str | None = Field(default=None, alias="thstrm")
    prior_raw: str | None = Field(default=None, alias="frmtrm")
    before_prior_raw: str | None = Field(default=None, alias="lwfr")
    fiscal_date: date = Field(alias="stlm_dt")

    @field_validator(
        "receipt_no",
        "corp_class",
        "corp_code",
        "corp_name",
        "label",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("OpenDART required dividend field is null")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("OpenDART required dividend field is empty")
        return normalized

    @field_validator(
        "stock_kind",
        "current_raw",
        "prior_raw",
        "before_prior_raw",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("receipt_no")
    @classmethod
    def validate_receipt_no(cls, value: str) -> str:
        if not _RECEIPT_NUMBER.fullmatch(value):
            raise ValueError("OpenDART rcept_no must be fourteen digits")
        return value

    @field_validator("corp_code")
    @classmethod
    def validate_corp_code(cls, value: str) -> str:
        if not _CORP_CODE.fullmatch(value):
            raise ValueError("OpenDART corp_code must be eight digits")
        return value


class DartAuditOpinionItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    receipt_no: str = Field(alias="rcept_no")
    corp_class: str = Field(alias="corp_cls")
    corp_code: str
    corp_name: str
    business_year: int = Field(alias="bsns_year", ge=2015)
    auditor: str | None = Field(default=None, alias="adtor")
    opinion: str | None = Field(default=None, alias="adt_opinion")
    special_matter: str | None = Field(
        default=None,
        alias="adt_reprt_spcmnt_matter",
    )
    emphasis_matter: str | None = Field(default=None, alias="emphs_matter")
    core_audit_matter: str | None = Field(
        default=None,
        alias="core_adt_matter",
    )
    fiscal_date: date = Field(alias="stlm_dt")

    @field_validator(
        "receipt_no",
        "corp_class",
        "corp_code",
        "corp_name",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("OpenDART required audit field is null")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("OpenDART required audit field is empty")
        return normalized

    @field_validator(
        "auditor",
        "opinion",
        "special_matter",
        "emphasis_matter",
        "core_audit_matter",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("receipt_no")
    @classmethod
    def validate_receipt_no(cls, value: str) -> str:
        if not _RECEIPT_NUMBER.fullmatch(value):
            raise ValueError("OpenDART rcept_no must be fourteen digits")
        return value

    @field_validator("corp_code")
    @classmethod
    def validate_corp_code(cls, value: str) -> str:
        if not _CORP_CODE.fullmatch(value):
            raise ValueError("OpenDART corp_code must be eight digits")
        return value


class FinancialRefreshSummary(BaseModel):
    state: str
    symbol: str
    started_at: datetime
    finished_at: datetime
    requested_years: int
    disclosures_stored: int = 0
    statements_stored: int = 0
    accounts_stored: int = 0
    dividend_facts_stored: int = 0
    dividends_stored: int = 0
    audit_opinions_stored: int = 0
    financial_scope: FinancialScope = FinancialScope.UNKNOWN
    errors: tuple[str, ...] = ()

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class TechnicalSnapshot(BaseModel):
    state: DataState
    as_of_date: date | None = None
    rsi_14: Decimal | None = None
    sma_20: Decimal | None = None
    sma_60: Decimal | None = None
    sma_120: Decimal | None = None
    sma_200: Decimal | None = None
    atr_14: Decimal | None = None
    drawdown_52_week: Decimal | None = None
    source_kind: str = "SELF_CALCULATED"
    price_source: str | None = None
    rule_version: str = "technical-v1"
    error_message: str | None = None


class FinancialAccountView(BaseModel):
    metric_code: str
    account_name: str
    value: Decimal | None
    cumulative_value: Decimal | None
    ttm_value: Decimal | None
    currency: str | None
    statement_section: str | None
    business_year: int
    report_code: str
    fs_div: FinancialScope
    filing_date: date
    receipt_no: str
    source_url: str | None
    mapping_status: str
    calculation_source: str | None = None


class DividendView(BaseModel):
    business_year: int
    stock_kind: str | None
    dps: Decimal | None
    currency: str | None
    total_amount: Decimal | None
    fiscal_date: date | None
    filing_date: date | None
    receipt_no: str | None
    is_confirmed: bool | None
    is_estimate: bool | None
    source_url: str | None


class AuditOpinionView(BaseModel):
    business_year: int
    auditor: str | None
    opinion: str | None
    fiscal_date: date | None
    filing_date: date | None
    receipt_no: str
    special_matter: str | None
    emphasis_matter: str | None
    core_audit_matter: str | None
    going_concern_risk: bool | None
    going_concern_status: str
    emphasis_status: str
    source_url: str | None


class DisclosureView(BaseModel):
    report_name: str
    receipt_no: str
    receipt_date: date
    disclosure_type: str | None
    is_correction: bool
    source_url: str | None


class StockAnalysisSnapshot(BaseModel):
    symbol: str
    financial_scope: FinancialScope
    financial_accounts: tuple[FinancialAccountView, ...] = ()
    dividends: tuple[DividendView, ...] = ()
    latest_audit: AuditOpinionView | None = None
    dividend_decisions: tuple[DisclosureView, ...] = ()
    technical: TechnicalSnapshot
