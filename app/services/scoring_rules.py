from __future__ import annotations

from app.config import Settings
from app.models.scoring import Phase2Rules


def phase2_rules_from_settings(settings: Settings) -> Phase2Rules:
    return Phase2Rules(
        score_version=settings.phase2_score_version,
        rule_version=settings.phase2_rule_version,
        audit_max_age_days=settings.phase2_audit_max_age_days,
        liquidity_days=settings.phase2_liquidity_days,
        zero_volume_days=settings.phase2_zero_volume_days,
        order_median_days=settings.phase2_order_median_days,
        minimum_median_trading_value=(settings.phase2_minimum_median_trading_value),
        maximum_order_to_median_ratio=(settings.phase2_maximum_order_to_median_ratio),
        minimum_interest_coverage=(settings.phase2_minimum_interest_coverage),
        repeated_loss_years=settings.phase2_repeated_loss_years,
        industry_minimum_sample=settings.phase2_industry_minimum_sample,
        history_minimum_sample=settings.phase2_history_minimum_sample,
        confidence_minimum=settings.phase2_confidence_minimum,
        freshness_full_score_days=(settings.phase2_freshness_full_score_days),
        freshness_zero_score_days=(settings.phase2_freshness_zero_score_days),
        dividend_continuity_weight=(settings.phase2_dividend_continuity_weight),
        dividend_stability_weight=(settings.phase2_dividend_stability_weight),
        payout_ratio_weight=settings.phase2_payout_ratio_weight,
        fcf_payout_weight=settings.phase2_fcf_payout_weight,
        operating_margin_weight=settings.phase2_operating_margin_weight,
        roe_weight=settings.phase2_roe_weight,
        debt_ratio_weight=settings.phase2_debt_ratio_weight,
        cash_conversion_weight=settings.phase2_cash_conversion_weight,
        industry_per_weight=settings.phase2_industry_per_weight,
        industry_pbr_weight=settings.phase2_industry_pbr_weight,
        historical_per_weight=settings.phase2_historical_per_weight,
        historical_pbr_weight=settings.phase2_historical_pbr_weight,
        confidence_completeness_weight=(settings.phase2_confidence_completeness_weight),
        confidence_freshness_weight=(settings.phase2_confidence_freshness_weight),
        confidence_official_source_weight=(
            settings.phase2_confidence_official_source_weight
        ),
        confidence_cross_validation_weight=(
            settings.phase2_confidence_cross_validation_weight
        ),
        confidence_industry_sample_weight=(
            settings.phase2_confidence_industry_sample_weight
        ),
        confidence_adjusted_price_weight=(
            settings.phase2_confidence_adjusted_price_weight
        ),
        confidence_mapping_weight=(settings.phase2_confidence_mapping_weight),
    )
