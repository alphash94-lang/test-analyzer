from __future__ import annotations

from decimal import Decimal

from app.models.scoring import (
    ComponentState,
    IndustryComparison,
    Phase2Rules,
    ScoreComponent,
    ValuationEvidence,
)
from app.services.score_component_common import (
    available_component,
    unavailable_component,
)
from app.services.valuation_service import (
    historical_comparison,
    select_industry_comparison,
    valuation_normalized_score,
)


def _valuation_component(
    comparison: IndustryComparison,
    *,
    code: str,
    weight: Decimal,
) -> ScoreComponent:
    reference = (
        comparison.industry_median
        if comparison.comparison_level in {"DETAILED", "PARENT"}
        else comparison.historical_median
    )
    if (
        comparison.state != ComponentState.AVAILABLE
        or comparison.current_value is None
        or reference is None
    ):
        return unavailable_component(
            score_name="INVESTMENT",
            code=code,
            weight=weight,
            explanation=comparison.explanation,
            state=comparison.state,
            raw_value=comparison.current_value,
            raw_text=(
                "N/M" if comparison.state == ComponentState.NOT_APPLICABLE else None
            ),
        )
    return available_component(
        score_name="INVESTMENT",
        code=code,
        raw_value=comparison.current_value,
        normalized_value=valuation_normalized_score(
            comparison.current_value,
            reference,
        ),
        weight=weight,
        explanation=comparison.explanation,
    )


def valuation_components(
    evidence: ValuationEvidence | None,
    rules: Phase2Rules,
) -> tuple[tuple[ScoreComponent, ...], tuple[IndustryComparison, ...]]:
    if evidence is None:
        definitions = (
            ("INDUSTRY_PER", rules.industry_per_weight),
            ("INDUSTRY_PBR", rules.industry_pbr_weight),
            ("HISTORICAL_PER", rules.historical_per_weight),
            ("HISTORICAL_PBR", rules.historical_pbr_weight),
        )
        return (
            tuple(
                unavailable_component(
                    score_name="INVESTMENT",
                    code=code,
                    weight=weight,
                    explanation="밸류에이션 입력이 없습니다.",
                )
                for code, weight in definitions
            ),
            (),
        )
    industry_per = select_industry_comparison(
        evidence,
        metric_code="PER",
        minimum_sample=rules.industry_minimum_sample,
    )
    industry_pbr = select_industry_comparison(
        evidence,
        metric_code="PBR",
        minimum_sample=rules.industry_minimum_sample,
    )
    history_per = historical_comparison(
        metric_code="PER",
        current_value=evidence.current_per,
        history=evidence.historical_per,
        minimum_sample=rules.history_minimum_sample,
    )
    history_pbr = historical_comparison(
        metric_code="PBR",
        current_value=evidence.current_pbr,
        history=evidence.historical_pbr,
        minimum_sample=rules.history_minimum_sample,
    )
    comparisons = industry_per, industry_pbr, history_per, history_pbr
    components = (
        _valuation_component(
            industry_per,
            code="INDUSTRY_PER",
            weight=rules.industry_per_weight,
        ),
        _valuation_component(
            industry_pbr,
            code="INDUSTRY_PBR",
            weight=rules.industry_pbr_weight,
        ),
        _valuation_component(
            history_per,
            code="HISTORICAL_PER",
            weight=rules.historical_per_weight,
        ),
        _valuation_component(
            history_pbr,
            code="HISTORICAL_PBR",
            weight=rules.historical_pbr_weight,
        ),
    )
    return components, comparisons
