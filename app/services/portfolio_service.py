from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.config import Settings
from app.models.market_analysis import MarketRegime
from app.models.recommendation import (
    Phase4Rules,
    PortfolioProfile,
    PortfolioSleeve,
    RecommendationCategory,
    RecommendationDecision,
    RecommendationInput,
    RegimeAllocationTarget,
    SplitBuyPlanResult,
    SplitBuyStatus,
    SplitBuyTranche,
)


def phase4_rules_from_settings(settings: Settings) -> Phase4Rules:
    return Phase4Rules(
        score_version=settings.phase4_score_version,
        rule_version=settings.phase4_rule_version,
        confidence_minimum=settings.phase4_confidence_minimum,
        ready_confidence_minimum=settings.phase4_ready_confidence_minimum,
        ready_investment_score=settings.phase4_ready_investment_score,
        ready_entry_score=settings.phase4_ready_entry_score,
        excessive_discount_investment_score=(
            settings.phase4_excessive_discount_investment_score
        ),
        excessive_discount_score=settings.phase4_excessive_discount_score,
        excessive_discount_full_score_gap=(
            settings.phase4_excessive_discount_full_score_gap
        ),
        general_review_score=settings.phase4_general_review_score,
        tranche_weights=(
            settings.phase4_split_tranche_1,
            settings.phase4_split_tranche_2,
            settings.phase4_split_tranche_3,
            settings.phase4_split_tranche_4,
        ),
    )


def default_portfolio_profile(settings: Settings) -> PortfolioProfile:
    return PortfolioProfile(
        target_stock_count=settings.phase4_default_target_stock_count,
        max_dividend_stock_weight=(settings.phase4_default_max_dividend_stock_weight),
        max_growth_stock_weight=(settings.phase4_default_max_growth_stock_weight),
        max_industry_weight=settings.phase4_default_max_industry_weight,
        max_company_group_weight=(settings.phase4_default_max_company_group_weight),
        minimum_trading_value=(settings.phase2_minimum_median_trading_value),
        normal_target=RegimeAllocationTarget(
            dividend_weight=settings.phase4_default_dividend_weight,
            growth_weight=settings.phase4_default_growth_weight,
            cash_weight=settings.phase4_default_cash_weight,
        ),
        regime_targets={
            MarketRegime.RED.value: RegimeAllocationTarget(
                dividend_weight=settings.phase4_red_dividend_weight,
                growth_weight=settings.phase4_red_growth_weight,
                cash_weight=settings.phase4_red_cash_weight,
            ),
            MarketRegime.ORANGE.value: RegimeAllocationTarget(
                dividend_weight=settings.phase4_orange_dividend_weight,
                growth_weight=settings.phase4_orange_growth_weight,
                cash_weight=settings.phase4_orange_cash_weight,
            ),
            MarketRegime.YELLOW.value: RegimeAllocationTarget(
                dividend_weight=settings.phase4_yellow_dividend_weight,
                growth_weight=settings.phase4_yellow_growth_weight,
                cash_weight=settings.phase4_yellow_cash_weight,
            ),
            MarketRegime.GREEN.value: RegimeAllocationTarget(
                dividend_weight=settings.phase4_green_dividend_weight,
                growth_weight=settings.phase4_green_growth_weight,
                cash_weight=settings.phase4_green_cash_weight,
            ),
        },
    )


def _merit(item: RecommendationDecision) -> Decimal:
    investment = item.investment_score or Decimal(0)
    entry = item.entry_score or Decimal(0)
    confidence = item.data_confidence or Decimal(0)
    return (
        investment * Decimal("0.50")
        + entry * Decimal("0.30")
        + confidence * Decimal("0.20")
    )


def _allocate_sleeve(
    candidates: list[RecommendationDecision],
    *,
    target_weight: Decimal,
    stock_cap: Decimal,
    industry_cap: Decimal,
    company_group_cap: Decimal,
    industry_allocations: dict[str, Decimal],
    company_group_allocations: dict[str, Decimal],
) -> dict[int, Decimal]:
    if target_weight <= 0 or not candidates:
        return {}
    selected = candidates
    allocations = {item.stock_id: Decimal(0) for item in selected}
    remaining = target_weight
    active = list(selected)
    while remaining > Decimal("0.00000001") and active:
        merit_total = sum((_merit(item) for item in active), start=Decimal(0))
        if merit_total <= 0:
            break
        added = Decimal(0)
        next_active: list[RecommendationDecision] = []
        for item in active:
            industry = item.industry_code
            if industry is None:
                continue
            stock_room = stock_cap - allocations[item.stock_id]
            industry_room = industry_cap - industry_allocations.get(
                industry,
                Decimal(0),
            )
            group = item.company_group_code
            group_room = (
                company_group_cap
                - company_group_allocations.get(group, Decimal(0))
                if group is not None
                else Decimal(1)
            )
            room = min(stock_room, industry_room, group_room)
            if room <= 0:
                continue
            proposed = remaining * _merit(item) / merit_total
            amount = min(proposed, room)
            allocations[item.stock_id] += amount
            industry_allocations[industry] = (
                industry_allocations.get(industry, Decimal(0)) + amount
            )
            if group is not None:
                company_group_allocations[group] = (
                    company_group_allocations.get(group, Decimal(0)) + amount
                )
            added += amount
            if room - amount > Decimal("0.00000001"):
                next_active.append(item)
        if added <= Decimal("0.00000001"):
            break
        remaining -= added
        active = next_active
    return {
        stock_id: weight.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        for stock_id, weight in allocations.items()
        if weight > 0
    }


def _select_candidates(
    candidates: list[RecommendationDecision],
    *,
    target: RegimeAllocationTarget,
    target_stock_count: int,
) -> list[RecommendationDecision]:
    by_sleeve = {
        PortfolioSleeve.DIVIDEND: [
            item for item in candidates if item.sleeve == PortfolioSleeve.DIVIDEND
        ],
        PortfolioSleeve.GROWTH: [
            item for item in candidates if item.sleeve == PortfolioSleeve.GROWTH
        ],
    }
    target_by_sleeve = {
        PortfolioSleeve.DIVIDEND: target.dividend_weight,
        PortfolioSleeve.GROWTH: target.growth_weight,
    }
    active_sleeves = sorted(
        (
            sleeve
            for sleeve, items in by_sleeve.items()
            if items and target_by_sleeve[sleeve] > 0
        ),
        key=lambda sleeve: (-target_by_sleeve[sleeve], sleeve.value),
    )
    selected_ids: set[int] = set()
    if target_stock_count >= len(active_sleeves):
        for sleeve in active_sleeves:
            selected_ids.add(by_sleeve[sleeve][0].stock_id)
    else:
        for sleeve in active_sleeves[:target_stock_count]:
            selected_ids.add(by_sleeve[sleeve][0].stock_id)
    for item in candidates:
        if len(selected_ids) >= target_stock_count:
            break
        selected_ids.add(item.stock_id)
    return [item for item in candidates if item.stock_id in selected_ids]


def allocate_portfolio(
    decisions: tuple[RecommendationDecision, ...],
    profile: PortfolioProfile,
    regime: MarketRegime,
    rules: Phase4Rules,
) -> tuple[RecommendationDecision, ...]:
    target = profile.target_for(regime)
    if target is None:
        return decisions
    eligible = [
        item
        for item in decisions
        if item.category
        in {
            RecommendationCategory.READY_FOR_RECOVERY,
            RecommendationCategory.QUALITY_WAIT,
        }
        and item.industry_code is not None
        and item.sleeve != PortfolioSleeve.UNCLASSIFIED
    ]
    eligible.sort(
        key=lambda item: (
            item.category != RecommendationCategory.READY_FOR_RECOVERY,
            -_merit(item),
            item.symbol,
        )
    )
    eligible = _select_candidates(
        eligible,
        target=target,
        target_stock_count=profile.target_stock_count,
    )
    dividend = [item for item in eligible if item.sleeve == PortfolioSleeve.DIVIDEND]
    growth = [item for item in eligible if item.sleeve == PortfolioSleeve.GROWTH]
    industry_allocations: dict[str, Decimal] = {}
    company_group_allocations: dict[str, Decimal] = {}
    weights = _allocate_sleeve(
        dividend,
        target_weight=target.dividend_weight,
        stock_cap=profile.max_dividend_stock_weight,
        industry_cap=profile.max_industry_weight,
        company_group_cap=profile.max_company_group_weight,
        industry_allocations=industry_allocations,
        company_group_allocations=company_group_allocations,
    )
    weights.update(
        _allocate_sleeve(
            growth,
            target_weight=target.growth_weight,
            stock_cap=profile.max_growth_stock_weight,
            industry_cap=profile.max_industry_weight,
            company_group_cap=profile.max_company_group_weight,
            industry_allocations=industry_allocations,
            company_group_allocations=company_group_allocations,
        )
    )
    results: list[RecommendationDecision] = []
    for item in decisions:
        weight = weights.get(item.stock_id)
        initial = (
            weight * rules.tranche_weights[0]
            if weight is not None
            and item.category == RecommendationCategory.READY_FOR_RECOVERY
            else Decimal(0)
            if weight is not None
            else None
        )
        results.append(
            item.model_copy(
                update={
                    "target_weight": weight,
                    "initial_buy_weight": (
                        initial.quantize(
                            Decimal("0.00000001"),
                            rounding=ROUND_DOWN,
                        )
                        if initial is not None
                        else None
                    ),
                }
            )
        )
    return tuple(results)


_CANCELLATION_CONDITIONS = (
    "감사의견 악화 또는 감사보고서 확인 불가",
    "배당 삭감·중단 또는 배당 투자논리 훼손",
    "영업이익·영업현금흐름의 급격한 악화",
    "대규모 유상증자·반복 CB/BW 등 주주가치 희석",
    "거래정지·관리종목 지정",
    "중대한 횡령·배임·소송 또는 최초 투자논리 붕괴",
)

_TRANCHE_CONDITIONS = (
    (
        "강제필터 통과 상태 유지",
        "기본 투자매력 기준과 데이터 신뢰도 기준 유지",
        "기업가치 훼손 공시가 새로 확인되지 않음",
    ),
    (
        "개별 종목 신저가 갱신 중단",
        "검증된 수정가격 RSI 안정화",
        "거래량 정상화와 지지구간 확인",
    ),
    (
        "반도체와 KOSPI 안정화",
        "비반도체 시장 확산",
        "시장국면이 회복 단계에 진입",
    ),
    (
        "배당주 상대강도 회복",
        "중기 추세 확인",
        "실적·배당 투자논리 재확인",
    ),
)


def attach_split_buy_plans(
    decisions: tuple[RecommendationDecision, ...],
    inputs: dict[int, RecommendationInput],
    rules: Phase4Rules,
) -> tuple[RecommendationDecision, ...]:
    results: list[RecommendationDecision] = []
    for item in decisions:
        source = inputs[item.stock_id]
        if item.category in {
            RecommendationCategory.EXCLUDED,
            RecommendationCategory.INSUFFICIENT_DATA,
        }:
            plan = SplitBuyPlanResult(
                status=SplitBuyStatus.NOT_AVAILABLE,
                explanation=(
                    "투자배제 또는 핵심 데이터 부족 상태에서는 "
                    "분할매수 계획을 만들지 않습니다."
                ),
            )
        else:
            status = (
                SplitBuyStatus.CONDITIONAL_ACTIVE
                if item.category == RecommendationCategory.READY_FOR_RECOVERY
                else SplitBuyStatus.HIDDEN_RISK_REVIEW
                if item.category == RecommendationCategory.EXCESSIVE_DISCOUNT
                else SplitBuyStatus.WAITING
            )
            tranches = tuple(
                SplitBuyTranche(
                    sequence=index + 1,
                    fraction_of_target=fraction,
                    portfolio_weight=(
                        item.target_weight * fraction
                        if item.target_weight is not None
                        else None
                    ),
                    target_price=None,
                    execution_conditions=_TRANCHE_CONDITIONS[index],
                    eligible_now=(
                        index == 0
                        and status == SplitBuyStatus.CONDITIONAL_ACTIVE
                        and item.target_weight is not None
                    ),
                )
                for index, fraction in enumerate(rules.tranche_weights)
            )
            plan = SplitBuyPlanResult(
                status=status,
                reference_price=source.reference_price,
                reference_price_date=source.reference_price_date,
                reference_price_provider=source.reference_price_provider,
                reference_price_currency=source.reference_price_currency,
                reference_price_collected_at=(
                    source.reference_price_collected_at
                ),
                reference_price_timing=source.reference_price_timing,
                tranches=tranches,
                cancellation_conditions=_CANCELLATION_CONDITIONS,
                is_order_executable=False,
                explanation=(
                    "기준가격은 데이터 스냅샷의 검증된 수정종가이며 "
                    "회차별 목표가격은 검증된 지지구간이 없어 만들지 않았습니다. "
                    "이 계획은 주문이 아닌 조건부 읽기 전용 검토안입니다."
                ),
            )
        results.append(item.model_copy(update={"split_buy_plan": plan}))
    return tuple(results)
