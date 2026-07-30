from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from enum import StrEnum
from html import unescape

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.models.metadata import DataState
from app.utils.dates import ensure_kst

_HTML_TAG = re.compile(r"<[^>]*>")
_CORRECTION_PREFIX = re.compile(
    r"^\[(?:기재정정|첨부정정|첨부추가|변경등록|연장결정|"
    r"발행조건확정|정정명령부과|정정제출요구)\]\s*"
)


def normalize_naver_text(value: object) -> str:
    if value is None:
        raise ValueError("Naver news text field is null")
    normalized = _HTML_TAG.sub("", unescape(str(value))).strip()
    if not normalized:
        raise ValueError("Naver news text field is empty")
    return normalized


def parse_optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    normalized = str(value).strip().replace(",", "")
    if normalized in {"", "-"}:
        return None
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("numeric provider field is invalid") from exc
    if not result.is_finite():
        raise ValueError("numeric provider field must be finite")
    return result


def parse_optional_integral_decimal(value: object) -> Decimal | None:
    result = parse_optional_decimal(value)
    if result is not None and result != result.to_integral_value():
        raise ValueError("quantity provider field must be an integer")
    return result


def parse_kis_business_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    normalized = str(value).strip()
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("KIS business date must use YYYYMMDD")
    return date(
        int(normalized[:4]),
        int(normalized[4:6]),
        int(normalized[6:8]),
    )


def normalize_disclosure_base_title(title: str) -> str:
    return _CORRECTION_PREFIX.sub("", title.strip()).replace(" ", "")


def is_disclosure_correction_title(title: str) -> bool:
    return _CORRECTION_PREFIX.match(title.strip()) is not None


class EventSentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    UNCLASSIFIED = "UNCLASSIFIED"


class EventConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNVERIFIED = "UNVERIFIED"


class TextScope(StrEnum):
    DISCLOSURE_TITLE_ONLY = "DISCLOSURE_TITLE_ONLY"
    TITLE_AND_PROVIDED_SUMMARY = "TITLE_AND_PROVIDED_SUMMARY"
    STRUCTURED_PROVIDER_FIELDS = "STRUCTURED_PROVIDER_FIELDS"
    NOT_PROVIDED = "NOT_PROVIDED"


class CorrectionLinkState(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    LINKED = "LINKED"
    AMBIGUOUS = "AMBIGUOUS"
    ORIGINAL_NOT_FOUND = "ORIGINAL_NOT_FOUND"


class NaverNewsItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    title: str
    original_url: HttpUrl | None = Field(default=None, alias="originallink")
    provider_url: HttpUrl = Field(alias="link")
    summary: str = Field(alias="description")
    published_at: datetime = Field(alias="pubDate")
    text_scope: TextScope = TextScope.TITLE_AND_PROVIDED_SUMMARY

    @field_validator("title", "summary", mode="before")
    @classmethod
    def clean_provided_text(cls, value: object) -> str:
        return normalize_naver_text(value)

    @field_validator("original_url", mode="before")
    @classmethod
    def empty_original_url_is_missing(cls, value: object) -> object | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("published_at", mode="before")
    @classmethod
    def parse_rfc2822_timestamp(cls, value: object) -> datetime:
        if isinstance(value, datetime):
            return ensure_kst(value)
        try:
            parsed = parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Naver pubDate must be RFC 2822") from exc
        return ensure_kst(parsed)


class NaverNewsPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    last_build_at: datetime = Field(alias="lastBuildDate")
    total: int = Field(ge=0)
    start: int = Field(ge=1, le=1000)
    display: int = Field(ge=0, le=100)
    items: tuple[NaverNewsItem, ...]

    @field_validator("last_build_at", mode="before")
    @classmethod
    def parse_last_build_at(cls, value: object) -> datetime:
        if isinstance(value, datetime):
            return ensure_kst(value)
        try:
            parsed = parsedate_to_datetime(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Naver lastBuildDate must be RFC 2822") from exc
        return ensure_kst(parsed)


class KisAnalystOpinionItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)

    published_date: date = Field(alias="stck_bsop_date")
    opinion: str | None = Field(default=None, alias="invt_opnn")
    target_price: Decimal | None = Field(default=None, alias="hts_goal_prc")
    currency: str | None = None

    @field_validator("published_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date:
        return parse_kis_business_date(value)

    @field_validator("opinion", mode="before")
    @classmethod
    def optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("target_price", mode="before")
    @classmethod
    def parse_price(cls, value: object) -> Decimal | None:
        result = parse_optional_decimal(value)
        if result is not None and result <= 0:
            raise ValueError("KIS target price must be positive")
        return result

    @model_validator(mode="after")
    def require_opinion_or_target(self) -> KisAnalystOpinionItem:
        if self.opinion is None and self.target_price is None:
            raise ValueError("KIS opinion record has no usable value")
        return self


class KisInvestorFlowItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)

    trade_date: date = Field(alias="stck_bsop_date")
    foreign_net_quantity: Decimal | None = Field(
        default=None,
        alias="frgn_ntby_qty",
    )
    individual_net_quantity: Decimal | None = Field(
        default=None,
        alias="prsn_ntby_qty",
    )
    institution_net_quantity: Decimal | None = Field(
        default=None,
        alias="orgn_ntby_qty",
    )

    @field_validator("trade_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date:
        return parse_kis_business_date(value)

    @field_validator(
        "foreign_net_quantity",
        "individual_net_quantity",
        "institution_net_quantity",
        mode="before",
    )
    @classmethod
    def parse_quantity(cls, value: object) -> Decimal | None:
        return parse_optional_integral_decimal(value)

    @model_validator(mode="after")
    def require_quantity(self) -> KisInvestorFlowItem:
        if all(
            value is None
            for value in (
                self.foreign_net_quantity,
                self.individual_net_quantity,
                self.institution_net_quantity,
            )
        ):
            raise ValueError("KIS investor flow record has no usable quantity")
        return self


class KisProgramTradingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)

    trade_date: date = Field(alias="stck_bsop_date")
    whole_entrusted_net_quantity: Decimal | None = Field(
        default=None,
        alias="whol_entm_ntby_qty",
    )

    @field_validator("trade_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date:
        return parse_kis_business_date(value)

    @field_validator("whole_entrusted_net_quantity", mode="before")
    @classmethod
    def parse_quantity(cls, value: object) -> Decimal | None:
        return parse_optional_integral_decimal(value)

    @model_validator(mode="after")
    def require_value(self) -> KisProgramTradingItem:
        if self.whole_entrusted_net_quantity is None:
            raise ValueError("KIS program trading record has no usable quantity")
        return self


class KisShortSellingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)

    trade_date: date = Field(alias="stck_bsop_date")
    short_quantity: Decimal | None = Field(default=None, alias="ssts_cntg_qty")
    short_amount: Decimal | None = Field(default=None, alias="ssts_tr_pbmn")
    short_ratio_percent: Decimal | None = Field(
        default=None,
        alias="ssts_vol_rlim",
    )

    @field_validator("trade_date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> date:
        return parse_kis_business_date(value)

    @field_validator("short_quantity", mode="before")
    @classmethod
    def parse_quantity(cls, value: object) -> Decimal | None:
        result = parse_optional_integral_decimal(value)
        if result is not None and result < 0:
            raise ValueError("KIS short-selling quantity must not be negative")
        return result

    @field_validator("short_amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal | None:
        result = parse_optional_decimal(value)
        if result is not None and result < 0:
            raise ValueError("KIS short-selling amount must not be negative")
        return result

    @field_validator("short_ratio_percent", mode="before")
    @classmethod
    def parse_ratio(cls, value: object) -> Decimal | None:
        result = parse_optional_decimal(value)
        if result is not None and not Decimal(0) <= result <= Decimal(100):
            raise ValueError(
                "KIS short-selling volume ratio must be between 0 and 100"
            )
        return result

    @model_validator(mode="after")
    def require_value(self) -> KisShortSellingItem:
        if all(
            value is None
            for value in (
                self.short_quantity,
                self.short_amount,
                self.short_ratio_percent,
            )
        ):
            raise ValueError("KIS short-selling record has no usable value")
        return self


class ClassifiedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    sentiment: EventSentiment
    confidence: EventConfidence
    rationale: str
    matched_rule: str
    text_scope: TextScope
    used_text: str
    price_reflection_note: str
    rule_version: str


class EventView(BaseModel):
    title: str
    event_type: str
    event_date: date | None
    published_at: datetime
    source_provider: str
    source_kind: str
    source_url: str | None
    sentiment: EventSentiment
    confidence: EventConfidence
    rationale: str
    used_text_scope: TextScope
    price_reflection_note: str
    is_correction: bool
    original_source_key: str | None
    correction_link_state: CorrectionLinkState
    collected_at: datetime
    data_state: DataState

    @field_validator("published_at", "collected_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class AnalystOpinionView(BaseModel):
    provider: str
    broker: str
    opinion: str | None
    target_price: Decimal | None
    currency: str | None
    published_date: date
    source_url: str | None
    is_estimate: bool


class EarningsEstimateView(BaseModel):
    provider: str
    broker: str
    metric_code: str
    fiscal_period: str
    estimate_value: Decimal | None
    unit: str | None
    currency: str | None
    published_date: date
    source_url: str | None
    is_estimate: bool


class InvestorFlowView(BaseModel):
    provider: str
    trade_date: date
    investor_type: str
    net_purchase_quantity: Decimal | None
    net_purchase_amount: Decimal | None
    currency: str | None
    unit: str | None


class ProgramTradingView(BaseModel):
    provider: str
    market_code: str
    trade_date: date
    net_purchase_quantity: Decimal | None
    net_purchase_amount: Decimal | None
    currency: str | None
    unit: str | None
    provider_field: str


class ShortSellingView(BaseModel):
    provider: str
    trade_date: date
    short_quantity: Decimal | None
    short_amount: Decimal | None
    short_ratio_percent: Decimal | None
    currency: str | None
    unit: str | None


class ReferenceAvailability(BaseModel):
    label: str
    provider: str
    state: DataState
    reason: str
    official_function: str | None = None


class Phase5Snapshot(BaseModel):
    symbol: str | None = None
    events: tuple[EventView, ...] = ()
    analyst_opinions: tuple[AnalystOpinionView, ...] = ()
    earnings_estimates: tuple[EarningsEstimateView, ...] = ()
    investor_flows: tuple[InvestorFlowView, ...] = ()
    program_trading: tuple[ProgramTradingView, ...] = ()
    short_selling: tuple[ShortSellingView, ...] = ()
    availability: tuple[ReferenceAvailability, ...] = ()


class Phase5RefreshSummary(BaseModel):
    state: DataState
    symbol: str
    started_at: datetime
    finished_at: datetime
    disclosures_stored: int = 0
    disclosure_events_stored: int = 0
    corrections_linked: int = 0
    corrections_ambiguous: int = 0
    news_stored: int = 0
    news_deduplicated: int = 0
    analyst_opinions_stored: int = 0
    investor_flows_stored: int = 0
    program_trading_stored: int = 0
    short_selling_stored: int = 0
    errors: tuple[str, ...] = ()

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        return ensure_kst(value)
