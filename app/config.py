from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PositiveFloat, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/kospi_analyzer.db"
    timezone: str = "Asia/Seoul"
    raw_data_dir: Path = Path("data/raw")
    http_timeout_seconds: PositiveFloat = 20.0
    http_retries: int = Field(default=2, ge=0, le=5)
    http_backoff_seconds: PositiveFloat = 0.5
    data_freshness_warning_hours: int = Field(default=48, ge=1, le=8760)
    krx_requests_per_second: PositiveFloat = 2.0
    dart_requests_per_second: PositiveFloat = 2.0
    max_api_response_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1024,
    )
    phase2_score_version: str = "phase2-score-v1"
    phase2_rule_version: str = "phase2-rule-v2"
    phase2_audit_max_age_days: int = Field(default=365, ge=1)
    phase2_liquidity_days: int = Field(default=60, ge=20)
    phase2_zero_volume_days: int = Field(default=20, ge=1)
    phase2_order_median_days: int = Field(default=20, ge=1)
    phase2_minimum_median_trading_value: Decimal = Field(
        default=Decimal(1000000000),
        ge=0,
    )
    phase2_maximum_order_to_median_ratio: Decimal = Field(
        default=Decimal("0.005"),
        gt=0,
        le=1,
    )
    phase2_planned_order_amount_krw: Decimal | None = Field(
        default=None,
        ge=0,
    )
    phase2_minimum_interest_coverage: Decimal = Field(
        default=Decimal(1),
        ge=0,
    )
    phase2_repeated_loss_years: int = Field(default=2, ge=1)
    # Five comparable companies is enough to calculate a provisional sector
    # median.  Sample size is already penalized separately in data confidence.
    phase2_industry_minimum_sample: int = Field(default=5, ge=2)
    phase2_history_minimum_sample: int = Field(default=3, ge=2)
    phase2_confidence_minimum: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    phase2_freshness_full_score_days: int = Field(default=90, ge=0)
    phase2_freshness_zero_score_days: int = Field(default=365, ge=1)

    phase2_dividend_continuity_weight: Decimal = Decimal(10)
    phase2_dividend_stability_weight: Decimal = Decimal(5)
    phase2_payout_ratio_weight: Decimal = Decimal(5)
    phase2_fcf_payout_weight: Decimal = Decimal(5)
    phase2_operating_margin_weight: Decimal = Decimal("6.25")
    phase2_roe_weight: Decimal = Decimal("6.25")
    phase2_debt_ratio_weight: Decimal = Decimal("6.25")
    phase2_cash_conversion_weight: Decimal = Decimal("6.25")
    phase2_industry_per_weight: Decimal = Decimal(6)
    phase2_industry_pbr_weight: Decimal = Decimal(6)
    phase2_historical_per_weight: Decimal = Decimal(4)
    phase2_historical_pbr_weight: Decimal = Decimal(4)

    phase2_confidence_completeness_weight: Decimal = Decimal(20)
    phase2_confidence_freshness_weight: Decimal = Decimal(15)
    phase2_confidence_official_source_weight: Decimal = Decimal(15)
    phase2_confidence_cross_validation_weight: Decimal = Decimal(10)
    phase2_confidence_industry_sample_weight: Decimal = Decimal(15)
    phase2_confidence_adjusted_price_weight: Decimal = Decimal(10)
    phase2_confidence_mapping_weight: Decimal = Decimal(15)

    phase3_rule_version: str = "phase3-rule-v2"
    phase3_kospi_index_name: str = "코스피"
    phase3_official_semiconductor_index_name: str | None = None
    phase3_adjusted_price_provider: str = "KIS"
    phase3_semiconductor_classification_system: str = "KRX_INDUSTRY"
    phase3_semiconductor_classification_codes: str = ""
    phase3_return_lookback_days: int = Field(default=21, ge=2, le=252)
    phase3_index_history_days: int = Field(default=252, ge=60, le=500)
    phase3_minimum_constituents: int = Field(default=10, ge=2)
    phase3_minimum_semiconductor_sample: int = Field(default=3, ge=2)
    phase3_minimum_dividend_sample: int = Field(default=3, ge=2)
    phase3_minimum_constituent_coverage: Decimal = Field(
        default=Decimal("0.80"),
        gt=0,
        le=1,
    )
    phase3_semiconductor_contribution_share: Decimal = Field(
        default=Decimal("0.50"),
        ge=0,
        le=1,
    )
    phase3_semiconductor_underperformance: Decimal = Decimal("-0.03")
    phase3_broad_decline_ratio: Decimal = Field(
        default=Decimal("0.70"),
        ge=0,
        le=1,
    )
    phase3_broad_median_return: Decimal = Decimal("-0.03")
    phase3_red_drawdown: Decimal = Decimal("-0.10")
    phase3_red_advancing_ratio: Decimal = Field(
        default=Decimal("0.30"),
        ge=0,
        le=1,
    )
    phase3_yellow_breadth20: Decimal = Field(
        default=Decimal("0.50"),
        ge=0,
        le=1,
    )
    phase3_green_breadth20: Decimal = Field(
        default=Decimal("0.60"),
        ge=0,
        le=1,
    )
    phase3_green_breadth60: Decimal = Field(
        default=Decimal("0.50"),
        ge=0,
        le=1,
    )
    phase3_stabilization_days: int = Field(default=5, ge=3, le=20)
    phase3_samsung_symbol: str = "005930"
    phase3_sk_hynix_symbol: str = "000660"
    realtime_market_interval_seconds: int = Field(default=300, ge=60, le=3600)
    realtime_market_snapshot_path: Path = Path(
        "data/realtime_market_snapshot.json"
    )
    realtime_market_rule_version: str = "intraday-regime-v1"

    phase4_score_version: str = "phase4-score-v1"
    phase4_rule_version: str = "phase4-rule-v2"
    phase4_confidence_minimum: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    phase4_ready_confidence_minimum: Decimal = Field(
        default=Decimal(80),
        ge=0,
        le=100,
    )
    phase4_ready_investment_score: Decimal = Field(
        default=Decimal(75),
        ge=0,
        le=100,
    )
    phase4_ready_entry_score: Decimal = Field(
        default=Decimal(65),
        ge=0,
        le=100,
    )
    phase4_excessive_discount_investment_score: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    phase4_excessive_discount_score: Decimal = Field(
        default=Decimal(70),
        ge=0,
        le=100,
    )
    phase4_excessive_discount_full_score_gap: Decimal = Field(
        default=Decimal("0.10"),
        gt=0,
        le=1,
    )
    phase4_general_review_score: Decimal = Field(
        default=Decimal(60),
        ge=0,
        le=100,
    )
    phase4_default_target_stock_count: int = Field(default=12, ge=1, le=100)
    phase4_default_max_dividend_stock_weight: Decimal = Field(
        default=Decimal("0.08"),
        gt=0,
        le=1,
    )
    phase4_default_max_growth_stock_weight: Decimal = Field(
        default=Decimal("0.05"),
        gt=0,
        le=1,
    )
    phase4_default_max_industry_weight: Decimal = Field(
        default=Decimal("0.25"),
        gt=0,
        le=1,
    )
    phase4_default_max_company_group_weight: Decimal = Field(
        default=Decimal("0.15"),
        gt=0,
        le=1,
    )
    phase4_default_dividend_weight: Decimal = Field(
        default=Decimal("0.70"),
        ge=0,
        le=1,
    )
    phase4_default_growth_weight: Decimal = Field(
        default=Decimal("0.20"),
        ge=0,
        le=1,
    )
    phase4_default_cash_weight: Decimal = Field(
        default=Decimal("0.10"),
        ge=0,
        le=1,
    )
    phase4_red_dividend_weight: Decimal = Decimal("0.10")
    phase4_red_growth_weight: Decimal = Decimal(0)
    phase4_red_cash_weight: Decimal = Decimal("0.90")
    phase4_orange_dividend_weight: Decimal = Decimal("0.30")
    phase4_orange_growth_weight: Decimal = Decimal("0.05")
    phase4_orange_cash_weight: Decimal = Decimal("0.65")
    phase4_yellow_dividend_weight: Decimal = Decimal("0.55")
    phase4_yellow_growth_weight: Decimal = Decimal("0.15")
    phase4_yellow_cash_weight: Decimal = Decimal("0.30")
    phase4_green_dividend_weight: Decimal = Decimal("0.70")
    phase4_green_growth_weight: Decimal = Decimal("0.20")
    phase4_green_cash_weight: Decimal = Decimal("0.10")
    phase4_split_tranche_1: Decimal = Decimal("0.15")
    phase4_split_tranche_2: Decimal = Decimal("0.25")
    phase4_split_tranche_3: Decimal = Decimal("0.35")
    phase4_split_tranche_4: Decimal = Decimal("0.25")

    phase5_event_rule_version: str = "phase5-event-rule-v1"
    phase5_disclosure_lookback_days: int = Field(default=30, ge=1, le=365)
    phase5_news_display: int = Field(default=50, ge=1, le=100)
    phase5_news_title_similarity: float = Field(default=0.92, ge=0.5, le=1)
    phase5_naver_requests_per_second: PositiveFloat = 2.0
    phase5_kis_requests_per_second: PositiveFloat = 2.0
    phase5_analyst_window_days: int = Field(default=90, ge=1, le=365)
    phase5_analyst_minimum_sample: int = Field(default=3, ge=1, le=100)

    phase6_backtest_version: str = "phase6-backtest-v2"
    phase6_rule_version: str = "phase6-rule-v2"
    phase6_transaction_cost_bps: Decimal = Field(
        default=Decimal(15),
        ge=0,
        le=Decimal(1000),
    )
    phase6_adjusted_price_provider: str = "KIS"
    phase6_primary_benchmark: str = "코스피"
    phase6_high_dividend_benchmark: str | None = None
    phase6_primary_horizon_months: int = Field(
        default=1,
        ge=1,
        le=12,
    )
    phase6_minimum_walk_forward_folds: int = Field(
        default=2,
        ge=1,
        le=1200,
    )

    krx_api_key: SecretStr | None = None
    dart_api_key: SecretStr | None = None
    kis_app_key: SecretStr | None = None
    kis_app_secret: SecretStr | None = None
    kis_account_no: SecretStr | None = None
    ncp_apigw_api_key_id: SecretStr | None = None
    ncp_apigw_api_key: SecretStr | None = None
    naver_client_id: SecretStr | None = None
    naver_client_secret: SecretStr | None = None
    bok_api_key: SecretStr | None = None
    ecos_api_key: SecretStr | None = None

    db_pool_pre_ping: bool = Field(default=True)

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_v3_for_postgres(cls, value: object) -> object:
        """Normalize provider-issued Postgres URLs to the installed driver."""

        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
