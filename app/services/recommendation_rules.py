from __future__ import annotations

from decimal import Decimal

from app.models.market_analysis import MarketRegime
from app.models.metadata import DataState
from app.models.recommendation import (
    CATEGORY_LABELS,
    HoldingAction,
    Phase4Rules,
    PortfolioSleeve,
    RecommendationCategory,
    RecommendationDecision,
    RecommendationInput,
)
from app.models.scoring import ComponentState, FilterState
from app.services.score_component_common import quantize_score

ENTRY_SCORE_SCOPE = "PHASE4_NO_FLOW_ENTRY_85"


def _entry_score(item: RecommendationInput) -> Decimal | None:
    phase2_entry = item.phase2.individual_entry_score
    market = item.market
    if (
        phase2_entry is None
        or market.state != DataState.AVAILABLE
        or market.market_regime == MarketRegime.UNCERTAIN
        or market.semiconductor_recovery is None
        or market.non_semiconductor_breadth is None
    ):
        return None
    regime_score = {
        MarketRegime.RED: Decimal(0),
        MarketRegime.ORANGE: Decimal(50),
        MarketRegime.YELLOW: Decimal(75),
        MarketRegime.GREEN: Decimal(100),
    }[market.market_regime]
    semiconductor_score = Decimal(100) if market.semiconductor_recovery else Decimal(0)
    breadth_score = Decimal(100) if market.non_semiconductor_breadth else Decimal(0)
    contribution = (
        regime_score * Decimal(25)
        + semiconductor_score * Decimal(20)
        + breadth_score * Decimal(20)
        + phase2_entry * Decimal(20)
    )
    return quantize_score(contribution / Decimal(85))


def _discount_score(item: RecommendationInput) -> Decimal | None:
    if item.market_shock_discount_score is not None:
        return item.market_shock_discount_score
    matches = [
        component.normalized_value
        for component in item.phase2.components
        if component.code == "MARKET_SHOCK_DISCOUNT"
        and component.state == ComponentState.AVAILABLE
        and component.normalized_value is not None
    ]
    return matches[0] if len(matches) == 1 else None


def _industry_code(item: RecommendationInput) -> str | None:
    if item.industry_code:
        return item.industry_code
    codes = {
        comparison.classification_code
        for comparison in item.phase2.valuation_comparisons
        if comparison.state == ComponentState.AVAILABLE
        and comparison.classification_code
    }
    return next(iter(codes)) if len(codes) == 1 else None


def _sleeve(item: RecommendationInput) -> PortfolioSleeve:
    if item.is_semiconductor is True:
        return PortfolioSleeve.GROWTH
    continuity = next(
        (
            component
            for component in item.phase2.components
            if component.code == "DIVIDEND_CONTINUITY"
        ),
        None,
    )
    if (
        continuity is not None
        and continuity.state == ComponentState.AVAILABLE
        and continuity.raw_value is not None
        and continuity.raw_value > 0
    ):
        return PortfolioSleeve.DIVIDEND
    return PortfolioSleeve.UNCLASSIFIED


def _raw_metrics(
    item: RecommendationInput,
    entry_score: Decimal | None,
    discount_score: Decimal | None,
) -> dict[str, object]:
    return {
        "phase2_input_hash": item.phase2.input_data_hash,
        "phase2_score_scope": item.phase2.score_scope,
        "phase2_investment_score": (
            str(item.phase2.investment_score)
            if item.phase2.investment_score is not None
            else None
        ),
        "phase2_individual_entry_score": (
            str(item.phase2.individual_entry_score)
            if item.phase2.individual_entry_score is not None
            else None
        ),
        "phase4_entry_score": (str(entry_score) if entry_score is not None else None),
        "phase4_entry_scope": ENTRY_SCORE_SCOPE,
        "phase2_data_confidence": str(item.phase2.data_confidence),
        "market_data_confidence": (
            str(item.market.data_confidence)
            if item.market.data_confidence is not None
            else None
        ),
        "market_rule_version": item.market.rule_version,
        "market_input_hash": item.market.input_data_hash,
        "market_regime": item.market.market_regime.value,
        "shock_classification": item.market.shock_classification.value,
        "market_shock_discount_score": (
            str(discount_score) if discount_score is not None else None
        ),
        "market_relative_return_gap": (
            str(item.market_relative_return_gap)
            if item.market_relative_return_gap is not None
            else None
        ),
        "reference_price": (
            str(item.reference_price)
            if item.reference_price is not None
            else None
        ),
        "reference_price_date": (
            item.reference_price_date.isoformat()
            if item.reference_price_date is not None
            else None
        ),
        "reference_price_provider": item.reference_price_provider,
        "reference_price_currency": item.reference_price_currency,
        "reference_price_collected_at": (
            item.reference_price_collected_at.isoformat()
            if item.reference_price_collected_at is not None
            else None
        ),
        "reference_price_timing": (
            item.reference_price_timing.value
            if item.reference_price_timing is not None
            else None
        ),
        "score_components": [
            {
                "code": component.code,
                "state": component.state.value,
                "raw_value": (
                    str(component.raw_value)
                    if component.raw_value is not None
                    else None
                ),
                "raw_text": component.raw_text,
                "normalized_value": (
                    str(component.normalized_value)
                    if component.normalized_value is not None
                    else None
                ),
                "weight": (
                    str(component.weight) if component.weight is not None else None
                ),
                "contribution": (
                    str(component.contribution)
                    if component.contribution is not None
                    else None
                ),
                "source_kind": component.source_kind,
            }
            for component in item.phase2.components
        ],
    }


def evaluate_recommendation(
    item: RecommendationInput,
    rules: Phase4Rules,
) -> RecommendationDecision:
    entry_score = _entry_score(item)
    discount_score = _discount_score(item)
    market_confidence = item.market.data_confidence
    confidence = (
        min(item.phase2.data_confidence, market_confidence)
        if market_confidence is not None
        else None
    )
    failed = [
        result
        for result in item.phase2.filters
        if result.is_blocking and result.state == FilterState.FAIL
    ]
    blocked = [
        result
        for result in item.phase2.filters
        if result.is_blocking
        and result.state
        in {
            FilterState.MISSING,
            FilterState.REVIEW_REQUIRED,
            FilterState.NOT_APPLICABLE,
        }
    ]
    missing = list(item.phase2.missing_core_data)
    missing.extend(item.market.missing_core_data)
    if item.market.state != DataState.AVAILABLE:
        missing.append("PHASE3_MARKET")
    if market_confidence is None:
        missing.append("PHASE3_DATA_CONFIDENCE")
    if entry_score is None:
        missing.append("PHASE4_ENTRY_SCORE")
    industry_code = _industry_code(item)
    if industry_code is None:
        missing.append("OFFICIAL_INDUSTRY_CLASSIFICATION")

    investment = item.phase2.investment_score
    if failed:
        category = RecommendationCategory.EXCLUDED
    elif (
        blocked
        or investment is None
        or missing
        or confidence is None
        or confidence < rules.confidence_minimum
    ):
        category = RecommendationCategory.INSUFFICIENT_DATA
    elif investment < rules.general_review_score:
        category = RecommendationCategory.EXCLUDED
    elif (
        discount_score is not None
        and discount_score >= rules.excessive_discount_score
        and investment >= rules.excessive_discount_investment_score
        and entry_score is not None
        and entry_score < rules.ready_entry_score
    ):
        category = RecommendationCategory.EXCESSIVE_DISCOUNT
    elif (
        investment >= rules.ready_investment_score
        and entry_score is not None
        and entry_score >= rules.ready_entry_score
        and confidence >= rules.ready_confidence_minimum
    ):
        category = RecommendationCategory.READY_FOR_RECOVERY
    elif investment >= rules.ready_investment_score:
        category = RecommendationCategory.QUALITY_WAIT
    else:
        category = RecommendationCategory.GENERAL_REVIEW

    positives: list[str] = []
    risks: list[str] = []
    exclusions: list[str] = []
    if not failed and not blocked:
        positives.append(
            f"강제필터 {len(item.phase2.filters)}개를 상쇄 없이 통과했습니다."
        )
    positives.extend(
        component.explanation
        for component in item.phase2.components
        if component.state == ComponentState.AVAILABLE
        and component.normalized_value is not None
        and component.normalized_value >= Decimal(70)
    )
    if item.market.semiconductor_recovery:
        positives.append("저장된 Phase 3에서 반도체 회복 조건을 확인했습니다.")
    if item.market.non_semiconductor_breadth:
        positives.append("저장된 Phase 3에서 비반도체 시장 확산을 확인했습니다.")
    if item.market.dividend_relative_strength_recovery:
        positives.append("저장된 Phase 3에서 배당주 상대강도 회복을 확인했습니다.")

    exclusions.extend(result.reason for result in failed)
    risks.extend(result.reason for result in blocked)
    risks.extend(
        component.explanation
        for component in item.phase2.components
        if component.state == ComponentState.AVAILABLE
        and component.normalized_value is not None
        and component.normalized_value <= Decimal(40)
    )
    if item.market.market_regime in {MarketRegime.RED, MarketRegime.ORANGE}:
        risks.append(
            f"현재 시장국면은 {item.market.market_regime.value}이며 "
            "시장 안정화 조건을 계속 확인해야 합니다."
        )
    if category == RecommendationCategory.EXCESSIVE_DISCOUNT:
        risks.append(
            "과도한 하락에는 숨은 기업 고유 악재가 있을 수 있어 "
            "적극추천하지 않고 추가 공시 검토 대상으로 둡니다."
        )
        risks.append(
            "시장 대비 상대수익률 차이는 인과관계가 아니라 설명용 "
            "과도하락 후보 지표입니다."
        )
    if confidence is not None and confidence < rules.ready_confidence_minimum:
        risks.append(
            f"보수적 데이터 신뢰도 {confidence}점이 회복 준비 기준 "
            f"{rules.ready_confidence_minimum}점보다 낮습니다."
        )
    if item.is_semiconductor is None:
        risks.append("공식 반도체 분류 여부를 확인할 수 없습니다.")
    risks.append(
        "공식 기업집단 매핑이 없어 동일 기업집단 한도는 자동 검증하지 못했습니다."
    )
    if investment is not None and investment < rules.general_review_score:
        exclusions.append(
            f"Phase 2 핵심 점수 {investment}점이 일반 검토 기준 "
            f"{rules.general_review_score}점 미만입니다."
        )
    if confidence is not None and confidence < rules.confidence_minimum:
        risks.append(
            f"데이터 신뢰도 {confidence}점이 추천 기준 "
            f"{rules.confidence_minimum}점 미만입니다."
        )

    unique_missing = tuple(dict.fromkeys(missing))
    filter_results = tuple(
        {
            "code": result.code,
            "name": result.name,
            "state": result.state.value,
            "reason": result.reason,
            "raw_value": (
                str(result.raw_value) if result.raw_value is not None else None
            ),
            "raw_text": result.raw_text,
            "source_provider": result.source_provider,
            "evidence_date": (
                result.evidence_date.isoformat()
                if result.evidence_date is not None
                else None
            ),
        }
        for result in item.phase2.filters
    )
    holding_action = {
        RecommendationCategory.READY_FOR_RECOVERY: HoldingAction.HOLD_REVIEW,
        RecommendationCategory.QUALITY_WAIT: HoldingAction.WAIT,
        RecommendationCategory.EXCESSIVE_DISCOUNT: HoldingAction.WAIT,
        RecommendationCategory.GENERAL_REVIEW: HoldingAction.WAIT,
        RecommendationCategory.EXCLUDED: HoldingAction.IMMEDIATE_REVIEW,
        RecommendationCategory.INSUFFICIENT_DATA: HoldingAction.NOT_COMPUTABLE,
    }[category]
    return RecommendationDecision(
        stock_id=item.stock_id,
        symbol=item.symbol,
        name=item.name,
        category=category,
        category_label=CATEGORY_LABELS[category],
        score_scope=item.phase2.score_scope,
        investment_score=investment,
        entry_score=entry_score,
        entry_score_scope=ENTRY_SCORE_SCOPE,
        data_confidence=confidence,
        market_regime=item.market.market_regime,
        sleeve=_sleeve(item),
        industry_code=industry_code,
        company_group_code=None,
        company_group_check_state="NOT_AVAILABLE",
        market_shock_discount_score=discount_score,
        holding_action=holding_action,
        positive_reasons=tuple(dict.fromkeys(positives)),
        risk_reasons=tuple(dict.fromkeys(risks)),
        exclusion_reasons=tuple(dict.fromkeys(exclusions)),
        missing_data=unique_missing,
        raw_metrics=_raw_metrics(item, entry_score, discount_score),
        filter_results=filter_results,
    )
