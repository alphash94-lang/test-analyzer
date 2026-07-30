from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.metadata import DataState
from app.utils.dates import ensure_kst


class UniverseMethod(StrEnum):
    POINT_IN_TIME_HISTORY = "POINT_IN_TIME_HISTORY"
    CURRENT_MASTER = "CURRENT_MASTER"
    UNKNOWN = "UNKNOWN"


class BacktestConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


class BacktestRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backtest_version: str = "phase6-backtest-v2"
    rule_version: str = "phase6-rule-v2"
    transaction_cost_bps: Decimal = Field(
        default=Decimal(15),
        ge=0,
        le=Decimal(1000),
    )
    adjusted_price_provider: str = "KIS"
    primary_benchmark: str = "코스피"
    high_dividend_benchmark: str | None = None
    horizon_months: tuple[int, ...] = (1, 3, 6, 12)
    primary_horizon_months: int = 1
    minimum_walk_forward_folds: int = Field(default=2, ge=1, le=1200)

    @field_validator(
        "backtest_version",
        "rule_version",
        "adjusted_price_provider",
        "primary_benchmark",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("backtest rule text must not be empty")
        return normalized

    @field_validator("high_dividend_benchmark")
    @classmethod
    def require_optional_benchmark(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("high dividend benchmark must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_horizons(self) -> BacktestRules:
        if (
            not self.horizon_months
            or tuple(sorted(set(self.horizon_months))) != self.horizon_months
            or any(item <= 0 for item in self.horizon_months)
        ):
            raise ValueError(
                "backtest horizons must be unique positive ascending months"
            )
        if self.primary_horizon_months not in self.horizon_months:
            raise ValueError("primary horizon must be included in horizon months")
        return self


class PriceObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_date: date
    open_price: Decimal | None = Field(default=None, gt=0)
    close_price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    source_provider: str
    source_function: str
    is_adjusted: bool | None = None
    adjustment_status: str | None = None
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def require_aware_collection(cls, value: datetime) -> datetime:
        return ensure_kst(value)

    @field_validator("source_provider", "source_function")
    @classmethod
    def require_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("price source must not be empty")
        return normalized

    @field_validator("currency")
    @classmethod
    def require_optional_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("price currency must not be empty")
        return normalized


class IndexObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_date: date
    open_price: Decimal = Field(gt=0)
    close_price: Decimal = Field(gt=0)
    source_provider: str
    source_function: str
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def require_aware_collection(cls, value: datetime) -> datetime:
        return ensure_kst(value)

    @field_validator("source_provider", "source_function")
    @classmethod
    def require_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("index source must not be empty")
        return normalized


class DividendPayment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    business_year: int = Field(ge=1900, le=9999)
    payment_date: date
    dps: Decimal = Field(ge=0)
    currency: str
    filing_date: date
    receipt_no: str
    correction_of_receipt_no: str | None = None
    is_confirmed: bool
    is_estimate: bool
    source_provider: str

    @field_validator("currency", "receipt_no", "source_provider")
    @classmethod
    def require_lineage_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("dividend lineage must not be empty")
        return normalized

    @field_validator("correction_of_receipt_no")
    @classmethod
    def normalize_optional_receipt(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("correction receipt lineage must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_confirmation(self) -> DividendPayment:
        if self.is_confirmed and self.is_estimate:
            raise ValueError("confirmed dividend cannot also be an estimate")
        if self.correction_of_receipt_no == self.receipt_no:
            raise ValueError("dividend correction cannot reference itself")
        return self


class PointInTimePosition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stock_id: int = Field(gt=0)
    symbol: str
    name: str
    target_weight: Decimal = Field(gt=0, le=1)
    industry_code: str | None = None
    recommendation_category: str
    listed_on: date
    delisted_on: date | None = None
    financial_filing_dates_used: tuple[date, ...]
    correction_filing_dates_used: tuple[date, ...] = ()
    financial_history_complete: bool
    correction_history_complete: bool
    dividend_history_complete: bool
    prices: tuple[PriceObservation, ...]
    dividends: tuple[DividendPayment, ...] = ()
    delisting_cash_per_share: Decimal | None = Field(default=None, ge=0)
    delisting_cash_currency: str | None = None
    delisting_cash_source: str | None = None

    @field_validator("symbol")
    @classmethod
    def require_symbol(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("position symbol must not be empty")
        return normalized

    @field_validator("name", "recommendation_category")
    @classmethod
    def require_position_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("position text must not be empty")
        return normalized

    @field_validator("delisting_cash_currency", "delisting_cash_source")
    @classmethod
    def normalize_optional_lineage(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("delisting cash lineage must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_position_history(self) -> PointInTimePosition:
        if self.delisted_on is not None and self.delisted_on < self.listed_on:
            raise ValueError("delisting date cannot precede listing date")
        if len({item.trade_date for item in self.prices}) != len(self.prices):
            raise ValueError("position price dates must be unique")
        if (
            self.delisting_cash_per_share is not None
            and (
                not self.delisting_cash_currency
                or not self.delisting_cash_source
            )
        ):
            raise ValueError(
                "delisting cash requires verified currency and source"
            )
        return self


class BacktestFoldInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_at: datetime
    universe_as_of: date
    universe_method: UniverseMethod
    universe_snapshot_source: str
    universe_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    universe_complete: bool
    includes_delisted: bool
    universe_symbols: tuple[str, ...]
    score_version: str
    recommendation_rule_version: str
    market_rule_version: str
    recommendation_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_regime: str
    positions: tuple[PointInTimePosition, ...]
    benchmarks: dict[str, tuple[IndexObservation, ...]]

    @field_validator("signal_at")
    @classmethod
    def require_aware_signal(cls, value: datetime) -> datetime:
        return ensure_kst(value)

    @field_validator(
        "universe_snapshot_source",
        "score_version",
        "recommendation_rule_version",
        "market_rule_version",
        "market_regime",
    )
    @classmethod
    def require_lineage_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("backtest fold lineage must not be empty")
        return normalized

    @field_validator("universe_symbols")
    @classmethod
    def require_universe_symbols(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values)
        if any(not item for item in normalized):
            raise ValueError("universe symbols must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_fold(self) -> BacktestFoldInput:
        if self.universe_as_of != self.signal_at.date():
            raise ValueError("universe snapshot date must equal signal date")
        if len(set(self.universe_symbols)) != len(self.universe_symbols):
            raise ValueError("universe symbols must be unique")
        position_symbols = {item.symbol for item in self.positions}
        if not position_symbols <= set(self.universe_symbols):
            raise ValueError("every position must belong to its point-in-time universe")
        if sum(
            (item.target_weight for item in self.positions),
            start=Decimal(0),
        ) > Decimal(1):
            raise ValueError("position target weights cannot exceed 1")
        for observations in self.benchmarks.values():
            if len({item.trade_date for item in observations}) != len(
                observations
            ):
                raise ValueError("benchmark dates must be unique")
        return self


class BacktestDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start_date: date
    end_date: date
    folds: tuple[BacktestFoldInput, ...]
    source_name: str
    known_survival_bias: tuple[str, ...]

    @field_validator("source_name")
    @classmethod
    def require_source_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("backtest source name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_dataset(self) -> BacktestDataset:
        if self.start_date > self.end_date:
            raise ValueError("backtest start date must not follow end date")
        dates = [item.signal_at.date() for item in self.folds]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("walk-forward folds must be unique and chronological")
        if any(
            item < self.start_date or item > self.end_date for item in dates
        ):
            raise ValueError("fold signal date must be inside the data period")
        return self


class BacktestHorizonResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    months: int
    exit_date: date
    exit_reason: str
    exit_value_per_share: Decimal
    dividend_per_share: Decimal
    gross_return: Decimal
    transaction_cost_return: Decimal
    net_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal


class BacktestPositionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stock_id: int
    symbol: str
    name: str
    target_weight: Decimal
    industry_code: str | None
    recommendation_category: str
    execution_date: date
    execution_price: Decimal
    currency: str
    was_delisted: bool
    horizons: tuple[BacktestHorizonResult, ...]


class BacktestFoldResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_date: date
    execution_date: date
    universe_count: int
    selected_count: int
    market_regime: str
    turnover: Decimal
    portfolio_returns: dict[str, Decimal]
    benchmark_returns: dict[str, Decimal]
    excess_returns: dict[str, Decimal]
    transaction_cost_returns: dict[str, Decimal]
    positions: tuple[BacktestPositionResult, ...]
    high_dividend_benchmark_returns: dict[str, Decimal] = Field(
        default_factory=dict
    )


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cumulative_total_return: Decimal
    annualized_return: Decimal | None
    benchmark_cumulative_return: Decimal
    benchmark_excess_return: Decimal
    maximum_drawdown: Decimal
    annualized_volatility: Decimal | None
    sharpe_ratio: Decimal | None
    win_rate: Decimal
    profit_loss_ratio: Decimal | None
    average_turnover: Decimal
    total_transaction_cost_return: Decimal
    recommendation_horizon_performance: dict[str, Decimal]
    market_regime_performance: dict[str, Decimal]
    industry_performance: dict[str, Decimal]
    dividend_cut_ratio: Decimal | None
    high_dividend_benchmark_cumulative_return: Decimal | None = None
    high_dividend_benchmark_excess_return: Decimal | None = None


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: int | None = None
    analyzed_at: datetime
    state: DataState
    confidence: BacktestConfidence
    start_date: date
    end_date: date
    backtest_version: str
    rule_version: str
    config_hash: str
    input_data_hash: str
    score_versions: tuple[str, ...]
    recommendation_rule_versions: tuple[str, ...]
    market_rule_versions: tuple[str, ...]
    universe_construction_method: str
    financial_availability_method: str
    correction_availability_method: str
    execution_price_method: str
    adjusted_price_source: str
    dividend_treatment_method: str
    transaction_cost_assumption: str
    benchmark_method: str
    walk_forward_method: str
    known_survival_bias: tuple[str, ...]
    missing_data: tuple[str, ...]
    folds: tuple[BacktestFoldResult, ...]
    metrics: BacktestMetrics | None
    input_source_name: str = "LEGACY_NOT_RECORDED"
    latest_input_collected_at: datetime | None = None
    drawdown_method: str = "WALK_FORWARD_PRIMARY_HORIZON_FOLD_ENDPOINTS"

    @field_validator("analyzed_at")
    @classmethod
    def require_aware_analysis(cls, value: datetime) -> datetime:
        return ensure_kst(value)

    @field_validator("latest_input_collected_at")
    @classmethod
    def require_aware_input_collection(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return None if value is None else ensure_kst(value)

    @model_validator(mode="after")
    def require_truthful_state(self) -> BacktestResult:
        if self.state == DataState.AVAILABLE and self.metrics is None:
            raise ValueError("available backtest requires metrics")
        if self.state != DataState.AVAILABLE and self.metrics is not None:
            raise ValueError("unavailable backtest must not contain metrics")
        if self.state == DataState.AVAILABLE and self.missing_data:
            raise ValueError("available backtest cannot have missing core data")
        return self
