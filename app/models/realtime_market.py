from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.models.market_analysis import MarketRegime, ShockClassification
from app.utils.dates import ensure_kst


class RealtimeCollectorState(StrEnum):
    STARTING = "STARTING"
    LIVE = "LIVE"
    RECONNECTING = "RECONNECTING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class RealtimeIndexTick(BaseModel):
    as_of_at: datetime
    level: Decimal = Field(gt=0)
    change_rate: Decimal
    advancing_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    declining_count: int = Field(ge=0)

    @field_validator("as_of_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class RealtimeStockTick(BaseModel):
    symbol: str
    as_of_at: datetime
    price: Decimal = Field(gt=0)
    change_rate: Decimal

    @field_validator("as_of_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class RealtimeMarketSnapshot(BaseModel):
    as_of_at: datetime
    bucket_started_at: datetime
    market_regime: MarketRegime
    shock_classification: ShockClassification
    confidence: Decimal = Field(ge=0, le=100)
    kospi_level: Decimal
    kospi_change_rate: Decimal
    advancing_count: int
    unchanged_count: int
    declining_count: int
    advancing_ratio: Decimal = Field(ge=0, le=1)
    samsung_change_rate: Decimal | None = None
    sk_hynix_change_rate: Decimal | None = None
    stock_change_rates: dict[str, Decimal] = Field(default_factory=dict)
    rule_version: str
    explanation: str

    @field_validator("as_of_at", "bucket_started_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class RealtimeCollectorStatus(BaseModel):
    state: RealtimeCollectorState
    updated_at: datetime
    pid: int | None = Field(default=None, ge=1)
    detail: str

    @field_validator("updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return ensure_kst(value)
