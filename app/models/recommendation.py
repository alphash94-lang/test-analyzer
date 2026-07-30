from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.market_analysis import MarketRegime, ShockClassification
from app.models.metadata import DataState, DataTiming
from app.models.scoring import Phase2Result
from app.utils.dates import ensure_kst


class RecommendationCategory(StrEnum):
    READY_FOR_RECOVERY = "READY_FOR_RECOVERY"
    QUALITY_WAIT = "QUALITY_WAIT"
    EXCESSIVE_DISCOUNT = "EXCESSIVE_DISCOUNT"
    GENERAL_REVIEW = "GENERAL_REVIEW"
    EXCLUDED = "EXCLUDED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


CATEGORY_LABELS: dict[RecommendationCategory, str] = {
    RecommendationCategory.READY_FOR_RECOVERY: "회복 준비 완료",
    RecommendationCategory.QUALITY_WAIT: "우량하지만 관망",
    RecommendationCategory.EXCESSIVE_DISCOUNT: "과도할인 후보",
    RecommendationCategory.GENERAL_REVIEW: "일반 검토",
    RecommendationCategory.EXCLUDED: "투자배제",
    RecommendationCategory.INSUFFICIENT_DATA: "데이터 부족",
}


class PortfolioSleeve(StrEnum):
    DIVIDEND = "DIVIDEND"
    GROWTH = "GROWTH"
    UNCLASSIFIED = "UNCLASSIFIED"


class HoldingAction(StrEnum):
    HOLD_REVIEW = "HOLD_REVIEW"
    WAIT = "WAIT"
    REDUCE_REVIEW = "REDUCE_REVIEW"
    IMMEDIATE_REVIEW = "IMMEDIATE_REVIEW"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"


class SplitBuyStatus(StrEnum):
    CONDITIONAL_ACTIVE = "CONDITIONAL_ACTIVE"
    WAITING = "WAITING"
    HIDDEN_RISK_REVIEW = "HIDDEN_RISK_REVIEW"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class Phase4Rules(BaseModel):
    model_config = ConfigDict(frozen=True)

    score_version: str = "phase4-score-v1"
    rule_version: str = "phase4-rule-v1"
    confidence_minimum: Decimal = Field(default=Decimal(70), ge=0, le=100)
    ready_confidence_minimum: Decimal = Field(
        default=Decimal(80),
        ge=0,
        le=100,
    )
    ready_investment_score: Decimal = Field(
        default=Decimal(75),
        ge=0,
        le=100,
    )
    ready_entry_score: Decimal = Field(
        default=Decimal(65),
        ge=0,
        le=100,
    )
    excessive_discount_investment_score: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    excessive_discount_score: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    excessive_discount_full_score_gap: Decimal = Field(
        default=Decimal("0.10"),
        gt=0,
        le=1,
    )
    general_review_score: Decimal = Field(
        default=Decimal(60),
        ge=0,
        le=100,
    )
    tranche_weights: tuple[Decimal, Decimal, Decimal, Decimal] = (
        Decimal("0.15"),
        Decimal("0.25"),
        Decimal("0.35"),
        Decimal("0.25"),
    )

    @model_validator(mode="after")
    def validate_rules(self) -> Phase4Rules:
        if sum(self.tranche_weights, start=Decimal(0)) != Decimal(1):
            raise ValueError("split-buy tranche weights must total 1")
        if any(weight <= 0 for weight in self.tranche_weights):
            raise ValueError("split-buy tranche weights must be positive")
        if self.ready_confidence_minimum < self.confidence_minimum:
            raise ValueError(
                "ready confidence minimum cannot be below recommendation minimum"
            )
        if self.ready_investment_score < self.general_review_score:
            raise ValueError("ready score cannot be below general-review threshold")
        return self


class RegimeAllocationTarget(BaseModel):
    dividend_weight: Decimal = Field(ge=0, le=1)
    growth_weight: Decimal = Field(ge=0, le=1)
    cash_weight: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> RegimeAllocationTarget:
        if self.dividend_weight + self.growth_weight + self.cash_weight != Decimal(1):
            raise ValueError("regime allocation weights must total 1")
        return self


class PortfolioProfile(BaseModel):
    profile_name: str = "기본"
    total_capital: Decimal | None = Field(default=None, ge=0)
    current_cash: Decimal | None = Field(default=None, ge=0)
    risk_profile: str = "BALANCED"
    target_dividend_yield: Decimal | None = Field(default=None, ge=0)
    target_stock_count: int = Field(default=12, ge=1, le=100)
    max_dividend_stock_weight: Decimal = Field(
        default=Decimal("0.08"),
        gt=0,
        le=1,
    )
    max_growth_stock_weight: Decimal = Field(
        default=Decimal("0.05"),
        gt=0,
        le=1,
    )
    max_industry_weight: Decimal = Field(
        default=Decimal("0.25"),
        gt=0,
        le=1,
    )
    max_company_group_weight: Decimal = Field(
        default=Decimal("0.15"),
        gt=0,
        le=1,
    )
    include_preferred: bool = False
    include_reits: bool = False
    minimum_trading_value: Decimal | None = Field(default=None, ge=0)
    normal_target: RegimeAllocationTarget
    regime_targets: dict[str, RegimeAllocationTarget]

    @field_validator("profile_name")
    @classmethod
    def require_profile_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("profile name must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_all_regimes(self) -> PortfolioProfile:
        expected = {
            MarketRegime.RED.value,
            MarketRegime.ORANGE.value,
            MarketRegime.YELLOW.value,
            MarketRegime.GREEN.value,
        }
        if set(self.regime_targets) != expected:
            raise ValueError("portfolio profile requires all four market regimes")
        return self

    def target_for(self, regime: MarketRegime) -> RegimeAllocationTarget | None:
        if regime == MarketRegime.UNCERTAIN:
            return None
        return self.regime_targets.get(regime.value)


class MarketRecommendationContext(BaseModel):
    snapshot_id: int | None = None
    as_of_at: datetime
    rule_version: str
    input_data_hash: str
    state: DataState
    shock_classification: ShockClassification
    market_regime: MarketRegime
    data_confidence: Decimal | None = Field(default=None, ge=0, le=100)
    semiconductor_recovery: bool | None = None
    kospi_recovery: bool | None = None
    non_semiconductor_breadth: bool | None = None
    dividend_relative_strength_recovery: bool | None = None
    missing_core_data: tuple[str, ...] = ()

    @field_validator("as_of_at")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class RecommendationInput(BaseModel):
    stock_id: int
    symbol: str
    name: str
    phase2_snapshot_id: int
    phase2: Phase2Result
    market: MarketRecommendationContext
    industry_code: str | None = None
    is_semiconductor: bool | None = None
    reference_price: Decimal | None = Field(default=None, gt=0)
    reference_price_date: date | None = None
    reference_price_provider: str | None = None
    reference_price_currency: str | None = None
    reference_price_collected_at: datetime | None = None
    reference_price_timing: DataTiming | None = None
    market_relative_return_gap: Decimal | None = None
    market_shock_discount_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    @field_validator("reference_price_collected_at")
    @classmethod
    def require_aware_reference_collection(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_kst(value) if value is not None else None


class SplitBuyTranche(BaseModel):
    sequence: int = Field(ge=1, le=4)
    fraction_of_target: Decimal = Field(gt=0, le=1)
    portfolio_weight: Decimal | None = Field(default=None, ge=0, le=1)
    target_price: Decimal | None = Field(default=None, gt=0)
    execution_conditions: tuple[str, ...]
    eligible_now: bool = False


class SplitBuyPlanResult(BaseModel):
    status: SplitBuyStatus
    reference_price: Decimal | None = Field(default=None, gt=0)
    reference_price_date: date | None = None
    reference_price_provider: str | None = None
    reference_price_currency: str | None = None
    reference_price_collected_at: datetime | None = None
    reference_price_timing: DataTiming | None = None
    tranches: tuple[SplitBuyTranche, ...] = ()
    cancellation_conditions: tuple[str, ...] = ()
    is_order_executable: bool = False
    explanation: str

    @model_validator(mode="after")
    def prohibit_order_execution(self) -> SplitBuyPlanResult:
        if self.is_order_executable:
            raise ValueError("Phase 4 split-buy plans must remain read-only")
        return self

    @field_validator("reference_price_collected_at")
    @classmethod
    def require_aware_reference_collection(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return ensure_kst(value) if value is not None else None


class RecommendationDecision(BaseModel):
    stock_id: int
    symbol: str
    name: str
    category: RecommendationCategory
    category_label: str
    score_scope: str
    investment_score: Decimal | None = Field(default=None, ge=0, le=100)
    entry_score: Decimal | None = Field(default=None, ge=0, le=100)
    entry_score_scope: str
    data_confidence: Decimal | None = Field(default=None, ge=0, le=100)
    market_regime: MarketRegime
    sleeve: PortfolioSleeve
    industry_code: str | None = None
    company_group_code: str | None = None
    company_group_check_state: str = "NOT_AVAILABLE"
    market_shock_discount_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    target_weight: Decimal | None = Field(default=None, ge=0, le=1)
    initial_buy_weight: Decimal | None = Field(default=None, ge=0, le=1)
    holding_action: HoldingAction
    positive_reasons: tuple[str, ...]
    risk_reasons: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    missing_data: tuple[str, ...]
    raw_metrics: dict[str, object]
    filter_results: tuple[dict[str, object], ...]
    split_buy_plan: SplitBuyPlanResult | None = None


class RecommendationRunResult(BaseModel):
    run_id: int | None = None
    state: DataState
    analyzed_at: datetime
    as_of_at: datetime
    basis_date: date
    score_version: str
    rule_version: str
    market_rule_version: str
    config_hash: str
    input_data_hash: str
    total_count: int
    processed_count: int
    recommended_count: int
    excluded_count: int
    insufficient_count: int
    market_regime: MarketRegime
    missing_core_data: tuple[str, ...] = ()
    recommendations: tuple[RecommendationDecision, ...]

    @field_validator("analyzed_at", "as_of_at")
    @classmethod
    def require_aware_times(cls, value: datetime) -> datetime:
        return ensure_kst(value)
