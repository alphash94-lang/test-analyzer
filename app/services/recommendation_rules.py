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
from app.services.market_screening_service import SCREEN_SCORE_SCOPE
from app.services.score_component_common import quantize_score

ENTRY_SCORE_SCOPE = "PHASE4_INDIVIDUAL80_MARKET20"


def calculate_entry_score(
    *,
    individual_entry_score: Decimal | None,
    market_state: DataState,
    market_regime: MarketRegime,
    semiconductor_recovery: bool | None,
    non_semiconductor_breadth: bool | None,
) -> Decimal | None:
    if (
        individual_entry_score is None
        or market_state != DataState.AVAILABLE
        or semiconductor_recovery is None
        or non_semiconductor_breadth is None
    ):
        return None
    regime_score = {
        MarketRegime.RED: Decimal(0),
        MarketRegime.ORANGE: Decimal(50),
        MarketRegime.YELLOW: Decimal(75),
        MarketRegime.GREEN: Decimal(100),
        # Complete inputs with no directional threshold are a neutral market,
        # not a data failure.
        MarketRegime.UNCERTAIN: Decimal(50),
    }[market_regime]
    # Semiconductor recovery and breadth already determine the Phase 3 regime.
    # Charging them again here previously made the configured 65-point entry
    # threshold mathematically unreachable in a neutral market.
    return quantize_score(
        individual_entry_score * Decimal("0.80")
        + regime_score * Decimal("0.20")
    )


def _entry_score(item: RecommendationInput) -> Decimal | None:
    return calculate_entry_score(
        individual_entry_score=item.phase2.individual_entry_score,
        market_state=item.market.state,
        market_regime=item.market.market_regime,
        semiconductor_recovery=item.market.semiconductor_recovery,
        non_semiconductor_breadth=item.market.non_semiconductor_breadth,
    )


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
    if item.phase2.score_scope == SCREEN_SCORE_SCOPE:
        # The full-market screen must remain allocatable even when dividend
        # history has not yet been collected. Non-semiconductors use the
        # diversified value sleeve; this does not assert that they pay dividends.
        return PortfolioSleeve.DIVIDEND
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
    is_market_screen = item.phase2.score_scope == SCREEN_SCORE_SCOPE
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
    if is_market_screen:
        blocked = []
    missing = [] if is_market_screen else list(item.phase2.missing_core_data)
    missing.extend(item.market.missing_core_data)
    if item.market.state != DataState.AVAILABLE:
        missing.append("PHASE3_MARKET")
    if market_confidence is None:
        missing.append("PHASE3_DATA_CONFIDENCE")
    if entry_score is None:
        missing.append("PHASE4_ENTRY_SCORE")
    industry_code = _industry_code(item)
    if industry_code is None and not is_market_screen:
        missing.append("OFFICIAL_INDUSTRY_CLASSIFICATION")

    investment = item.phase2.investment_score
    if failed:
        category = RecommendationCategory.EXCLUDED
    elif (
        blocked
        or investment is None
        or missing
        or confidence is None
        or (confidence < rules.confidence_minimum and not is_market_screen)
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
    blocking_filters = tuple(
        result for result in item.phase2.filters if result.is_blocking
    )
    if (
        not failed
        and not blocked
        and blocking_filters
        and all(result.state == FilterState.PASS for result in blocking_filters)
    ):
        positives.append(
            f"확인 가능한 강제 필터 {len(item.phase2.filters)}개에서 탈락 사유가 없습니다."
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
            f"현재 시장 국면은 {item.market.market_regime.value}입니다. "
            "개별 종목 점수가 높아도 분할 접근이 필요합니다."
        )
    elif item.market.market_regime == MarketRegime.UNCERTAIN:
        risks.append(
            "시장 입력은 정상이나 방향성 조건이 혼조 상태여서 진입준비도에 "
            "보수적인 중립 점수를 적용했습니다."
        )
    if category == RecommendationCategory.EXCESSIVE_DISCOUNT:
        risks.append(
            "큰 폭의 하락에는 아직 반영되지 않은 기업 고유 악재가 있을 수 있어 "
            "최근 공시와 실적을 추가로 확인해야 합니다."
        )
        risks.append(
            "시장 대비 상대수익률 차이는 원인을 증명하는 값이 아니라 "
            "가격 조정 정도를 비교하는 보조 지표입니다."
        )
    if confidence is not None and confidence < rules.ready_confidence_minimum:
        risks.append(
            f"데이터 신뢰도 {confidence}점이 적극 검토 기준 "
            f"{rules.ready_confidence_minimum}점보다 낮습니다."
        )
    if item.is_semiconductor is None:
        risks.append("반도체 업종 여부를 공식 분류로 확인하지 못했습니다.")
    risks.append(
        "공식 기업집단 매핑이 없는 경우 동일 기업집단 한도는 별도 확인이 필요합니다."
    )
    if investment is not None and investment < rules.general_review_score:
        exclusions.append(
            f"KOSPI 전체 비교 매력 점수 {investment}점이 검토 기준 "
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
