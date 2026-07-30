from __future__ import annotations

from decimal import Decimal

from app.models.scoring import (
    EntityKind,
    FinancialQualityEvidence,
    Phase2Rules,
    ScoreComponent,
)
from app.services.score_component_common import (
    available_component,
    linear_higher_is_better,
    linear_lower_is_better,
    unavailable_component,
)


def financial_components(
    evidence: FinancialQualityEvidence | None,
    entity_kind: EntityKind,
    rules: Phase2Rules,
) -> tuple[ScoreComponent, ...]:
    definitions = (
        ("OPERATING_MARGIN", rules.operating_margin_weight),
        ("ROE", rules.roe_weight),
        ("DEBT_RATIO", rules.debt_ratio_weight),
        ("CASH_CONVERSION", rules.cash_conversion_weight),
    )
    if entity_kind == EntityKind.FINANCIAL:
        return tuple(
            unavailable_component(
                score_name="INVESTMENT",
                code=code,
                weight=weight,
                explanation=(
                    "금융업에는 일반 제조업 재무비율을 적용하지 않습니다. "
                    "별도 금융업 평가모형 입력이 필요합니다."
                ),
            )
            for code, weight in definitions
        )
    if evidence is None or evidence.currency is None:
        return tuple(
            unavailable_component(
                score_name="INVESTMENT",
                code=code,
                weight=weight,
                explanation="비금융업 재무건전성 입력 또는 단위가 없습니다.",
            )
            for code, weight in definitions
        )
    if (
        evidence.revenue_ttm is None
        or evidence.operating_profit_ttm is None
        or evidence.revenue_ttm <= 0
    ):
        operating_margin = unavailable_component(
            score_name="INVESTMENT",
            code="OPERATING_MARGIN",
            weight=rules.operating_margin_weight,
            explanation="양수 매출과 영업이익 TTM 입력이 필요합니다.",
        )
    else:
        margin = evidence.operating_profit_ttm / evidence.revenue_ttm
        operating_margin = available_component(
            score_name="INVESTMENT",
            code="OPERATING_MARGIN",
            raw_value=margin,
            normalized_value=linear_higher_is_better(
                margin,
                minimum=Decimal(0),
                maximum=Decimal("0.20"),
            ),
            weight=rules.operating_margin_weight,
            explanation="TTM 영업이익/TTM 매출액입니다.",
        )
    if (
        evidence.parent_net_income_ttm is None
        or evidence.parent_equity is None
        or evidence.parent_equity <= 0
    ):
        roe = unavailable_component(
            score_name="INVESTMENT",
            code="ROE",
            weight=rules.roe_weight,
            explanation="지배기업 순이익 또는 양수 지배기업 자본이 없습니다.",
        )
    else:
        roe_value = evidence.parent_net_income_ttm / evidence.parent_equity
        roe = available_component(
            score_name="INVESTMENT",
            code="ROE",
            raw_value=roe_value,
            normalized_value=linear_higher_is_better(
                roe_value,
                minimum=Decimal(0),
                maximum=Decimal("0.15"),
            ),
            weight=rules.roe_weight,
            explanation="지배기업 소유주지분 TTM 순이익/지배기업 자본입니다.",
        )
    if (
        evidence.liabilities is None
        or evidence.parent_equity is None
        or evidence.parent_equity <= 0
    ):
        debt_ratio = unavailable_component(
            score_name="INVESTMENT",
            code="DEBT_RATIO",
            weight=rules.debt_ratio_weight,
            explanation="부채 또는 양수 지배기업 자본이 없습니다.",
        )
    else:
        debt_value = evidence.liabilities / evidence.parent_equity
        debt_ratio = available_component(
            score_name="INVESTMENT",
            code="DEBT_RATIO",
            raw_value=debt_value,
            normalized_value=linear_lower_is_better(
                debt_value,
                best=Decimal("0.50"),
                worst=Decimal("2.00"),
            ),
            weight=rules.debt_ratio_weight,
            explanation="부채/지배기업 자본입니다.",
        )
    if (
        evidence.operating_cash_flow_ttm is None
        or evidence.parent_net_income_ttm is None
    ):
        cash_conversion = unavailable_component(
            score_name="INVESTMENT",
            code="CASH_CONVERSION",
            weight=rules.cash_conversion_weight,
            explanation="영업현금흐름 또는 지배기업 순이익 TTM이 없습니다.",
        )
    elif evidence.parent_net_income_ttm <= 0:
        cash_conversion = available_component(
            score_name="INVESTMENT",
            code="CASH_CONVERSION",
            raw_value=evidence.parent_net_income_ttm,
            normalized_value=Decimal(0),
            weight=rules.cash_conversion_weight,
            explanation=(
                "지배기업 순이익이 0 이하이므로 현금전환율을 정상 비율로 "
                "표시하지 않고 위험 점수 0을 적용했습니다."
            ),
        )
    else:
        conversion = evidence.operating_cash_flow_ttm / evidence.parent_net_income_ttm
        cash_conversion = available_component(
            score_name="INVESTMENT",
            code="CASH_CONVERSION",
            raw_value=conversion,
            normalized_value=linear_higher_is_better(
                conversion,
                minimum=Decimal(0),
                maximum=Decimal(1),
            ),
            weight=rules.cash_conversion_weight,
            explanation="TTM 영업현금흐름/지배기업 소유주지분 TTM 순이익입니다.",
        )
    return operating_margin, roe, debt_ratio, cash_conversion
