from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.metadata import DataState
from app.utils.dates import ensure_kst


class FilterState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ComponentState(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class EntityKind(StrEnum):
    NON_FINANCIAL = "NON_FINANCIAL"
    FINANCIAL = "FINANCIAL"
    UNKNOWN = "UNKNOWN"


class Phase2Rules(BaseModel):
    model_config = ConfigDict(frozen=True)

    score_version: str = "phase2-score-v1"
    rule_version: str = "phase2-rule-v2"
    audit_max_age_days: int = Field(default=365, ge=1)
    liquidity_days: int = Field(default=60, ge=20)
    zero_volume_days: int = Field(default=20, ge=1)
    order_median_days: int = Field(default=20, ge=1)
    minimum_median_trading_value: Decimal = Field(
        default=Decimal(1000000000),
        ge=0,
    )
    maximum_order_to_median_ratio: Decimal = Field(
        default=Decimal("0.005"),
        gt=0,
        le=1,
    )
    minimum_interest_coverage: Decimal = Field(
        default=Decimal(1),
        ge=0,
    )
    repeated_loss_years: int = Field(default=2, ge=1)
    industry_minimum_sample: int = Field(default=10, ge=2)
    history_minimum_sample: int = Field(default=3, ge=2)
    confidence_minimum: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    freshness_full_score_days: int = Field(default=90, ge=0)
    freshness_zero_score_days: int = Field(default=365, ge=1)

    dividend_continuity_weight: Decimal = Decimal(10)
    dividend_stability_weight: Decimal = Decimal(5)
    payout_ratio_weight: Decimal = Decimal(5)
    fcf_payout_weight: Decimal = Decimal(5)
    operating_margin_weight: Decimal = Decimal("6.25")
    roe_weight: Decimal = Decimal("6.25")
    debt_ratio_weight: Decimal = Decimal("6.25")
    cash_conversion_weight: Decimal = Decimal("6.25")
    industry_per_weight: Decimal = Decimal(6)
    industry_pbr_weight: Decimal = Decimal(6)
    historical_per_weight: Decimal = Decimal(4)
    historical_pbr_weight: Decimal = Decimal(4)

    confidence_completeness_weight: Decimal = Decimal(20)
    confidence_freshness_weight: Decimal = Decimal(15)
    confidence_official_source_weight: Decimal = Decimal(15)
    confidence_cross_validation_weight: Decimal = Decimal(10)
    confidence_industry_sample_weight: Decimal = Decimal(15)
    confidence_adjusted_price_weight: Decimal = Decimal(10)
    confidence_mapping_weight: Decimal = Decimal(15)

    @model_validator(mode="after")
    def validate_weights(self) -> Phase2Rules:
        core_weights = (
            self.dividend_continuity_weight,
            self.dividend_stability_weight,
            self.payout_ratio_weight,
            self.fcf_payout_weight,
            self.operating_margin_weight,
            self.roe_weight,
            self.debt_ratio_weight,
            self.cash_conversion_weight,
            self.industry_per_weight,
            self.industry_pbr_weight,
            self.historical_per_weight,
            self.historical_pbr_weight,
        )
        confidence_weights = (
            self.confidence_completeness_weight,
            self.confidence_freshness_weight,
            self.confidence_official_source_weight,
            self.confidence_cross_validation_weight,
            self.confidence_industry_sample_weight,
            self.confidence_adjusted_price_weight,
            self.confidence_mapping_weight,
        )
        if any(weight <= 0 for weight in core_weights):
            raise ValueError("Phase 2 score weights must be positive")
        if sum(confidence_weights) != Decimal(100):
            raise ValueError("data-confidence weights must total 100")
        if self.freshness_zero_score_days <= self.freshness_full_score_days:
            raise ValueError("freshness zero-score age must exceed full-score age")
        if self.order_median_days > self.liquidity_days:
            raise ValueError("order-median days cannot exceed liquidity-history days")
        return self

    @property
    def core_weight_total(self) -> Decimal:
        return sum(
            (
                self.dividend_continuity_weight,
                self.dividend_stability_weight,
                self.payout_ratio_weight,
                self.fcf_payout_weight,
                self.operating_margin_weight,
                self.roe_weight,
                self.debt_ratio_weight,
                self.cash_conversion_weight,
                self.industry_per_weight,
                self.industry_pbr_weight,
                self.historical_per_weight,
                self.historical_pbr_weight,
            ),
            start=Decimal(0),
        )


class MarketFilterEvidence(BaseModel):
    is_kospi: bool | None = None
    product_type: str | None = None
    share_class: str | None = None
    listing_status: str | None = None
    official_status_coverage: bool = False
    trading_suspended: bool | None = None
    management_issue: bool | None = None
    delisting_risk: bool | None = None


class AuditFilterEvidence(BaseModel):
    opinion: str | None = None
    filing_date: date | None = None
    going_concern_risk: bool | None = None
    going_concern_status: str = "NOT_VERIFIED"


class LiquidityEvidence(BaseModel):
    trading_values_60: tuple[Decimal, ...] = ()
    volumes_20: tuple[Decimal, ...] = ()
    currency: str | None = None
    source_verified: bool = False
    planned_order_amount: Decimal | None = Field(default=None, ge=0)


class CorporateEventEvidence(BaseModel):
    coverage_verified: bool = False
    severe_event: bool | None = None
    manual_review_event: bool | None = None
    latest_event: str | None = None


class FinancialRiskEvidence(BaseModel):
    entity_kind: EntityKind = EntityKind.UNKNOWN
    operating_profit_ttm: Decimal | None = None
    finance_costs_ttm: Decimal | None = None
    repeated_operating_loss_years: int | None = Field(default=None, ge=0)
    currency: str | None = None
    financial_model_available: bool = False


class DividendPayment(BaseModel):
    business_year: int = Field(ge=1900, le=2200)
    dps: Decimal = Field(ge=0)


class DividendQualityEvidence(BaseModel):
    payments: tuple[DividendPayment, ...] = ()
    latest_total_dividend: Decimal | None = Field(default=None, ge=0)
    parent_net_income_ttm: Decimal | None = None
    operating_cash_flow_ttm: Decimal | None = None
    capex_tangible_ttm: Decimal | None = None
    capex_intangible_ttm: Decimal | None = None
    currency: str | None = None


class FinancialQualityEvidence(BaseModel):
    revenue_ttm: Decimal | None = None
    operating_profit_ttm: Decimal | None = None
    parent_net_income_ttm: Decimal | None = None
    assets: Decimal | None = None
    liabilities: Decimal | None = None
    parent_equity: Decimal | None = None
    operating_cash_flow_ttm: Decimal | None = None
    currency: str | None = None


class IndustryPeer(BaseModel):
    symbol: str
    detailed_industry: str | None = None
    parent_industry: str | None = None
    per: Decimal | None = None
    pbr: Decimal | None = None
    roe: Decimal | None = None


class ValuationEvidence(BaseModel):
    current_per: Decimal | None = None
    current_pbr: Decimal | None = None
    detailed_industry: str | None = None
    parent_industry: str | None = None
    peers: tuple[IndustryPeer, ...] = ()
    historical_per: tuple[Decimal, ...] = ()
    historical_pbr: tuple[Decimal, ...] = ()
    entity_kind: EntityKind = EntityKind.UNKNOWN


class DataConfidenceEvidence(BaseModel):
    required_items_present: int = Field(ge=0)
    required_items_total: int = Field(gt=0)
    max_age_days: int | None = Field(default=None, ge=0)
    official_source_ratio: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    cross_validation_verified: bool | None = None
    industry_sample_size: int | None = Field(default=None, ge=0)
    adjusted_price_verified: bool | None = None
    account_mapping_ratio: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    @model_validator(mode="after")
    def validate_completeness(self) -> DataConfidenceEvidence:
        if self.required_items_present > self.required_items_total:
            raise ValueError(
                "required_items_present cannot exceed required_items_total"
            )
        return self


class EntryEvidence(BaseModel):
    adjusted_price_verified: bool = False
    close: Decimal | None = Field(default=None, gt=0)
    rsi_14: Decimal | None = Field(default=None, ge=0, le=100)
    sma_20: Decimal | None = Field(default=None, gt=0)
    sma_60: Decimal | None = Field(default=None, gt=0)


class Phase2Evidence(BaseModel):
    symbol: str
    as_of_at: datetime
    market: MarketFilterEvidence
    audit: AuditFilterEvidence | None = None
    liquidity: LiquidityEvidence | None = None
    corporate_event: CorporateEventEvidence | None = None
    financial_risk: FinancialRiskEvidence | None = None
    dividend: DividendQualityEvidence | None = None
    financial_quality: FinancialQualityEvidence | None = None
    valuation: ValuationEvidence | None = None
    confidence: DataConfidenceEvidence
    entry: EntryEvidence | None = None

    @field_validator("as_of_at")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return ensure_kst(value)


class FilterResult(BaseModel):
    code: str
    name: str
    state: FilterState
    is_blocking: bool = True
    reason: str
    raw_value: Decimal | None = None
    raw_text: str | None = None
    source_provider: str | None = None
    evidence_date: date | None = None


class ScoreComponent(BaseModel):
    score_name: str
    code: str
    state: ComponentState
    raw_value: Decimal | None = None
    raw_text: str | None = None
    normalized_value: Decimal | None = Field(default=None, ge=0, le=100)
    weight: Decimal | None = Field(default=None, gt=0)
    contribution: Decimal | None = Field(default=None, ge=0)
    explanation: str
    source_kind: str = "SELF_CALCULATED"


class IndustryComparison(BaseModel):
    metric_code: str
    state: ComponentState
    current_value: Decimal | None = None
    industry_median: Decimal | None = None
    historical_median: Decimal | None = None
    industry_percentile: Decimal | None = Field(default=None, ge=0, le=100)
    historical_percentile: Decimal | None = Field(default=None, ge=0, le=100)
    comparison_level: str | None = None
    classification_code: str | None = None
    sample_size: int = Field(default=0, ge=0)
    explanation: str


class Phase2Result(BaseModel):
    symbol: str
    as_of_at: datetime
    score_version: str
    rule_version: str
    input_data_hash: str
    score_scope: str = "PHASE2_CORE_ONLY"
    filters: tuple[FilterResult, ...]
    components: tuple[ScoreComponent, ...]
    valuation_comparisons: tuple[IndustryComparison, ...]
    investment_score: Decimal | None = Field(default=None, ge=0, le=100)
    entry_score: Decimal | None = Field(default=None, ge=0, le=100)
    individual_entry_score: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    data_confidence: Decimal = Field(ge=0, le=100)
    recommendation_computable: bool
    missing_core_data: tuple[str, ...] = ()
    explanation: str
    data_state: DataState

    @field_validator("as_of_at")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return ensure_kst(value)
