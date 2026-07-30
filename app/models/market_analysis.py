from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.metadata import DataState, DataTiming
from app.utils.dates import ensure_kst


class ShockClassification(StrEnum):
    SEMICONDUCTOR_LED = "SEMICONDUCTOR_LED"
    BROAD_SELLOFF = "BROAD_SELLOFF"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"


class MarketRegime(StrEnum):
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    UNCERTAIN = "UNCERTAIN"


class ProxyKind(StrEnum):
    OFFICIAL_INDEX = "OFFICIAL_INDEX"
    SELF_CALCULATED_PROXY = "SELF_CALCULATED_PROXY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SourceKind(StrEnum):
    OFFICIAL_API = "OFFICIAL_API"
    SELF_CALCULATED = "SELF_CALCULATED"


class KrxIndexDailyItem(BaseModel):
    """Fields confirmed in the KRX KOSPI daily-index contract."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    trade_date_raw: str = Field(alias="BAS_DD")
    index_class: str = Field(alias="IDX_CLSS")
    index_name: str = Field(alias="IDX_NM")
    close: Decimal = Field(alias="CLSPRC_IDX")
    previous_day_change: Decimal = Field(alias="CMPPREVDD_IDX")
    fluctuation_rate: Decimal = Field(alias="FLUC_RT")
    open: Decimal = Field(alias="OPNPRC_IDX")
    high: Decimal = Field(alias="HGPRC_IDX")
    low: Decimal = Field(alias="LWPRC_IDX")
    volume: Decimal = Field(alias="ACC_TRDVOL")
    trading_value: Decimal = Field(alias="ACC_TRDVAL")
    market_cap: Decimal = Field(alias="MKTCAP")

    @field_validator("trade_date_raw", "index_class", "index_name", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("KRX official index field must not be null")
        return str(value).strip()

    @field_validator("trade_date_raw")
    @classmethod
    def require_trade_date(cls, value: str) -> str:
        normalized = value.replace("-", "")
        if len(normalized) != 8 or not normalized.isdigit():
            raise ValueError("KRX BAS_DD must use YYYYMMDD")
        try:
            date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
        except ValueError as exc:
            raise ValueError("KRX BAS_DD is not a valid calendar date") from exc
        return normalized

    @field_validator("index_class", "index_name")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value:
            raise ValueError("required KRX index field must not be empty")
        return value

    @field_validator(
        "close",
        "previous_day_change",
        "fluctuation_rate",
        "open",
        "high",
        "low",
        "volume",
        "trading_value",
        "market_cap",
        mode="before",
    )
    @classmethod
    def parse_number(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("KRX index numeric field must not be null")
        normalized = str(value).strip().replace(",", "")
        if not normalized:
            raise ValueError("KRX index numeric field must not be empty")
        try:
            result = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError("KRX index numeric field is invalid") from exc
        if not result.is_finite():
            raise ValueError("KRX index numeric field must be finite")
        return result

    @model_validator(mode="after")
    def validate_values(self) -> KrxIndexDailyItem:
        if any(
            value < 0
            for value in (
                self.close,
                self.open,
                self.high,
                self.low,
                self.volume,
                self.trading_value,
                self.market_cap,
            )
        ):
            raise ValueError(
                "KRX index levels, quantities, and amounts must be non-negative"
            )
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("KRX index high is inconsistent with OHLC")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("KRX index low is inconsistent with OHLC")
        return self

    @property
    def trade_date(self) -> date:
        return date(
            int(self.trade_date_raw[:4]),
            int(self.trade_date_raw[4:6]),
            int(self.trade_date_raw[6:8]),
        )


class IndexRefreshSummary(BaseModel):
    state: str
    started_at: datetime
    finished_at: datetime
    as_of_date: date
    received: int = 0
    stored: int = 0
    errors: tuple[str, ...] = ()


class IndexPoint(BaseModel):
    trade_date: date
    close: Decimal = Field(gt=0)
    source_provider: str
    source_function: str
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class ConstituentObservation(BaseModel):
    stock_id: int
    symbol: str
    name: str
    start_date: date
    previous_date: date
    as_of_date: date
    start_close: Decimal = Field(gt=0)
    previous_close: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    start_market_cap: Decimal = Field(gt=0)
    previous_market_cap: Decimal = Field(gt=0)
    close_history: tuple[Decimal, ...]
    is_semiconductor: bool | None
    classification_source: str | None
    is_confirmed_dividend_payer: bool | None
    price_source_provider: str
    market_cap_source_provider: str
    collected_at: datetime

    @field_validator("close_history")
    @classmethod
    def require_positive_history(
        cls,
        values: tuple[Decimal, ...],
    ) -> tuple[Decimal, ...]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("constituent price history must be positive")
        return values

    @field_validator("collected_at")
    @classmethod
    def require_aware_collected_at(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class MetricEvidence(BaseModel):
    code: str
    label: str
    state: DataState
    value: Decimal | None = None
    text_value: str | None = None
    unit: str | None = None
    source_provider: str | None = None
    source_function: str | None = None
    as_of_at: datetime | None = None
    collected_at: datetime | None = None
    calculation_method: str
    data_quality: str
    data_timing: DataTiming
    source_kind: SourceKind
    proxy_kind: ProxyKind = ProxyKind.NOT_APPLICABLE

    @field_validator("as_of_at", "collected_at")
    @classmethod
    def require_aware_optional(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_kst(value) if value is not None else None

    @model_validator(mode="after")
    def require_available_value(self) -> MetricEvidence:
        if (
            self.state == DataState.AVAILABLE
            and self.value is None
            and self.text_value is None
        ):
            raise ValueError("available metric requires a numeric or text value")
        if self.state != DataState.AVAILABLE and self.value is not None:
            raise ValueError("unavailable metric cannot carry a numeric value")
        return self


class ContributionEvidence(BaseModel):
    stock_id: int
    symbol: str
    name: str
    return_rate: Decimal
    previous_weight: Decimal
    contribution: Decimal
    is_semiconductor: bool | None
    source_provider: str
    market_cap_source_provider: str
    classification_source: str | None
    as_of_date: date
    collected_at: datetime
    data_timing: DataTiming
    calculation_method: str
    data_quality: str
    source_kind: SourceKind
    proxy_kind: ProxyKind

    @field_validator("collected_at")
    @classmethod
    def require_aware_collected_at(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class SemiconductorAnalysis(BaseModel):
    state: DataState
    proxy_kind: ProxyKind
    cap_weighted_return: Decimal | None = None
    equal_weighted_return: Decimal | None = None
    non_semiconductor_cap_weighted_return: Decimal | None = None
    non_semiconductor_equal_weighted_return: Decimal | None = None
    non_semiconductor_median_return: Decimal | None = None
    semiconductor_negative_contribution_share: Decimal | None = None
    semiconductor_contribution: Decimal | None = None
    samsung_contribution: Decimal | None = None
    sk_hynix_contribution: Decimal | None = None
    contributions: tuple[ContributionEvidence, ...] = ()
    reason: str


class BreadthAnalysis(BaseModel):
    state: DataState
    equal_weighted_return: Decimal | None = None
    median_return: Decimal | None = None
    advancing_ratio: Decimal | None = None
    above_sma20_ratio: Decimal | None = None
    above_sma60_ratio: Decimal | None = None
    advancing_count: int | None = None
    declining_count: int | None = None
    sample_size: int
    reason: str


class DividendContagionAnalysis(BaseModel):
    state: DataState
    dividend_equal_weighted_return: Decimal | None = None
    relative_to_kospi: Decimal | None = None
    relative_to_non_semiconductor: Decimal | None = None
    sample_size: int
    recovery: bool | None = None
    reason: str


class MarketHighResult(BaseModel):
    horizon: int
    high_date: date
    high: Decimal
    current: Decimal
    drawdown: Decimal


class Phase3AnalysisResult(BaseModel):
    state: DataState
    as_of_at: datetime
    rule_version: str
    input_data_hash: str
    shock_classification: ShockClassification
    market_regime: MarketRegime
    data_confidence: Decimal | None
    proxy_kind: ProxyKind
    semiconductor_recovery: bool | None
    kospi_recovery: bool | None
    non_semiconductor_breadth: bool | None
    dividend_relative_strength_recovery: bool | None
    missing_core_data: tuple[str, ...]
    explanation: str
    metrics: tuple[MetricEvidence, ...]
    contributions: tuple[ContributionEvidence, ...]

    @field_validator("as_of_at")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return ensure_kst(value)
