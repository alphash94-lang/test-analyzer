from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.metadata import DataState
from app.utils.dates import ensure_kst


class KrxDailyPriceItem(BaseModel):
    """Fields confirmed in the KRX daily-trading contract."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    trade_date_raw: str = Field(alias="BAS_DD")
    symbol: str = Field(alias="ISU_CD")
    name: str = Field(alias="ISU_NM")
    market_name: str = Field(alias="MKT_NM")
    department_name: str = Field(alias="SECT_TP_NM")
    close_price: Decimal = Field(alias="TDD_CLSPRC")
    previous_day_change: Decimal = Field(alias="CMPPREVDD_PRC")
    fluctuation_rate: Decimal = Field(alias="FLUC_RT")
    open_price: Decimal = Field(alias="TDD_OPNPRC")
    high_price: Decimal = Field(alias="TDD_HGPRC")
    low_price: Decimal = Field(alias="TDD_LWPRC")
    volume: Decimal = Field(alias="ACC_TRDVOL")
    trading_value: Decimal = Field(alias="ACC_TRDVAL")
    market_cap: Decimal = Field(alias="MKTCAP")
    listed_shares: Decimal = Field(alias="LIST_SHRS")

    @field_validator(
        "trade_date_raw",
        "symbol",
        "name",
        "market_name",
        "department_name",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> str:
        if value is None:
            raise ValueError("KRX official field must not be null")
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

    @field_validator("symbol", "name", "market_name")
    @classmethod
    def require_critical_text(cls, value: str) -> str:
        if not value:
            raise ValueError("required KRX official field must not be empty")
        return value

    @field_validator("symbol")
    @classmethod
    def require_six_character_symbol(cls, value: str) -> str:
        if (
            len(value) != 6
            or not value.isascii()
            or not value.isalnum()
            or value != value.upper()
        ):
            raise ValueError(
                "KRX price symbol must contain exactly six uppercase "
                "alphanumeric characters"
            )
        return value

    @field_validator(
        "close_price",
        "previous_day_change",
        "fluctuation_rate",
        "open_price",
        "high_price",
        "low_price",
        "volume",
        "trading_value",
        "market_cap",
        "listed_shares",
        mode="before",
    )
    @classmethod
    def parse_official_number(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("KRX numeric field must not be null")
        normalized = str(value).strip().replace(",", "")
        if not normalized:
            raise ValueError("KRX numeric field must not be empty")
        try:
            result = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError("KRX numeric field is invalid") from exc
        if not result.is_finite():
            raise ValueError("KRX numeric field must be finite")
        return result

    @model_validator(mode="after")
    def validate_price_relationships(self) -> KrxDailyPriceItem:
        non_negative = (
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.volume,
            self.trading_value,
            self.market_cap,
            self.listed_shares,
        )
        if any(value < 0 for value in non_negative):
            raise ValueError("KRX prices, quantities, and amounts must be non-negative")
        if (
            self.volume == 0
            and self.open_price == 0
            and self.high_price == 0
            and self.low_price == 0
        ):
            return self
        if self.high_price < max(
            self.open_price,
            self.low_price,
            self.close_price,
        ):
            raise ValueError("KRX high price is inconsistent with OHLC")
        if self.low_price > min(
            self.open_price,
            self.high_price,
            self.close_price,
        ):
            raise ValueError("KRX low price is inconsistent with OHLC")
        return self

    @property
    def trade_date(self) -> date:
        return date(
            int(self.trade_date_raw[:4]),
            int(self.trade_date_raw[4:6]),
            int(self.trade_date_raw[6:8]),
        )


class LatestDailyPrice(BaseModel):
    symbol: str
    trade_date: date
    close_price: Decimal
    currency: str | None
    volume: Decimal | None
    trading_value: Decimal | None
    market_cap: Decimal | None
    is_adjusted: bool | None
    source_provider: str
    state: DataState
    as_of_at: datetime
    collected_at: datetime

    @field_validator("as_of_at", "collected_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class PriceRefreshSummary(BaseModel):
    state: str
    started_at: datetime
    finished_at: datetime
    as_of_date: date
    received: int = 0
    stored: int = 0
    unmatched: int = 0
    errors: tuple[str, ...] = ()
