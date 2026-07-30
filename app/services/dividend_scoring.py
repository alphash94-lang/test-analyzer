from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from app.models.scoring import (
    DividendQualityEvidence,
    Phase2Rules,
    ScoreComponent,
)
from app.services.score_component_common import (
    available_component,
    unavailable_component,
)


def _payout_score(ratio: Decimal) -> Decimal:
    if ratio < 0:
        return Decimal(0)
    if ratio <= Decimal("0.70"):
        return Decimal(100)
    if ratio >= Decimal("1.20"):
        return Decimal(0)
    return (Decimal("1.20") - ratio) / Decimal("0.50") * Decimal(100)


def dividend_components(
    evidence: DividendQualityEvidence | None,
    rules: Phase2Rules,
) -> tuple[ScoreComponent, ...]:
    definitions = (
        ("DIVIDEND_CONTINUITY", rules.dividend_continuity_weight),
        ("DIVIDEND_STABILITY", rules.dividend_stability_weight),
        ("PAYOUT_RATIO", rules.payout_ratio_weight),
        ("FCF_PAYOUT", rules.fcf_payout_weight),
    )
    if evidence is None or evidence.currency is None:
        return tuple(
            unavailable_component(
                score_name="INVESTMENT",
                code=code,
                weight=weight,
                explanation="배당 지속가능성의 공식 입력 또는 단위가 없습니다.",
            )
            for code, weight in definitions
        )
    latest_by_year = {
        payment.business_year: payment
        for payment in sorted(
            evidence.payments,
            key=lambda item: item.business_year,
        )
    }
    payments = list(latest_by_year.values())[-5:]
    years = [payment.business_year for payment in payments]
    consecutive = len(years) == 5 and years == list(range(years[0], years[0] + 5))
    if not consecutive:
        continuity = unavailable_component(
            score_name="INVESTMENT",
            code="DIVIDEND_CONTINUITY",
            weight=rules.dividend_continuity_weight,
            explanation=(
                "연속된 최근 5개 사업연도의 확정 DPS가 없어 미지급과 "
                "데이터 누락을 구분할 수 없습니다."
            ),
        )
        stability = unavailable_component(
            score_name="INVESTMENT",
            code="DIVIDEND_STABILITY",
            weight=rules.dividend_stability_weight,
            explanation="최근 5개 사업연도 DPS 삭감 여부를 계산할 수 없습니다.",
        )
    else:
        positive_years = sum(payment.dps > 0 for payment in payments)
        continuity_ratio = Decimal(positive_years) / Decimal(5)
        continuity = available_component(
            score_name="INVESTMENT",
            code="DIVIDEND_CONTINUITY",
            raw_value=continuity_ratio,
            normalized_value=continuity_ratio * Decimal(100),
            weight=rules.dividend_continuity_weight,
            explanation=(
                f"최근 5개 사업연도 중 DPS가 양수인 연도는 {positive_years}개입니다."
            ),
        )
        non_cut_count = sum(
            current.dps >= previous.dps for previous, current in pairwise(payments)
        )
        stability_ratio = Decimal(non_cut_count) / Decimal(4)
        stability = available_component(
            score_name="INVESTMENT",
            code="DIVIDEND_STABILITY",
            raw_value=stability_ratio,
            normalized_value=stability_ratio * Decimal(100),
            weight=rules.dividend_stability_weight,
            explanation=(
                f"최근 4개 연도 전환 중 DPS 비삭감 구간은 {non_cut_count}개입니다."
            ),
        )
    if evidence.latest_total_dividend is None or evidence.parent_net_income_ttm is None:
        payout = unavailable_component(
            score_name="INVESTMENT",
            code="PAYOUT_RATIO",
            weight=rules.payout_ratio_weight,
            explanation="현금배당총액 또는 지배기업 소유주지분 순이익이 없습니다.",
        )
    elif evidence.parent_net_income_ttm <= 0:
        payout = available_component(
            score_name="INVESTMENT",
            code="PAYOUT_RATIO",
            raw_value=evidence.parent_net_income_ttm,
            normalized_value=Decimal(0),
            weight=rules.payout_ratio_weight,
            explanation=(
                "지배기업 소유주지분 순이익이 0 이하이므로 배당성향을 "
                "정상 비율로 표시하지 않고 위험 점수 0을 적용했습니다."
            ),
        )
    else:
        payout_ratio = evidence.latest_total_dividend / evidence.parent_net_income_ttm
        payout = available_component(
            score_name="INVESTMENT",
            code="PAYOUT_RATIO",
            raw_value=payout_ratio,
            normalized_value=_payout_score(payout_ratio),
            weight=rules.payout_ratio_weight,
            explanation="현금배당총액/지배기업 소유주지분 TTM 순이익입니다.",
        )
    fcf_inputs = (
        evidence.latest_total_dividend,
        evidence.operating_cash_flow_ttm,
        evidence.capex_tangible_ttm,
        evidence.capex_intangible_ttm,
    )
    if any(value is None for value in fcf_inputs):
        fcf_payout = unavailable_component(
            score_name="INVESTMENT",
            code="FCF_PAYOUT",
            weight=rules.fcf_payout_weight,
            explanation="FCF 배당성향의 현금흐름·CAPEX 입력이 부족합니다.",
        )
    else:
        total_dividend = evidence.latest_total_dividend
        operating_cash_flow = evidence.operating_cash_flow_ttm
        tangible = evidence.capex_tangible_ttm
        intangible = evidence.capex_intangible_ttm
        assert total_dividend is not None
        assert operating_cash_flow is not None
        assert tangible is not None
        assert intangible is not None
        fcf = operating_cash_flow - abs(tangible) - abs(intangible)
        if fcf <= 0:
            fcf_payout = available_component(
                score_name="INVESTMENT",
                code="FCF_PAYOUT",
                raw_value=fcf,
                normalized_value=Decimal(0),
                weight=rules.fcf_payout_weight,
                explanation=(
                    "FCF가 0 이하이므로 FCF 배당성향을 정상 숫자로 "
                    "표시하지 않고 위험 점수 0을 적용했습니다."
                ),
            )
        else:
            fcf_ratio = total_dividend / fcf
            fcf_payout = available_component(
                score_name="INVESTMENT",
                code="FCF_PAYOUT",
                raw_value=fcf_ratio,
                normalized_value=_payout_score(fcf_ratio),
                weight=rules.fcf_payout_weight,
                explanation=("현금배당총액/(영업현금흐름-유형CAPEX-무형CAPEX)입니다."),
            )
    return continuity, stability, payout, fcf_payout
