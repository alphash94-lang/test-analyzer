from __future__ import annotations

from datetime import date
from decimal import Decimal
from statistics import median

from app.models.scoring import (
    AuditFilterEvidence,
    CorporateEventEvidence,
    EntityKind,
    FilterResult,
    FilterState,
    FinancialRiskEvidence,
    LiquidityEvidence,
    MarketFilterEvidence,
    Phase2Rules,
)

_ACCEPTABLE_AUDIT_OPINIONS = frozenset({"적정", "적정의견"})
_REJECTED_AUDIT_OPINIONS = frozenset(
    {
        "한정",
        "한정의견",
        "부적정",
        "부적정의견",
        "의견거절",
        "감사의견거절",
    }
)
_UNKNOWN_CLASSIFICATION_VALUES = frozenset({"UNKNOWN", "NOT_VERIFIED"})


def _market_universe_filter(evidence: MarketFilterEvidence) -> FilterResult:
    known_values = (
        evidence.is_kospi,
        evidence.product_type,
        evidence.share_class,
        evidence.listing_status,
    )
    if any(value is None for value in known_values):
        return FilterResult(
            code="MARKET_UNIVERSE",
            name="코스피 일반주식",
            state=FilterState.MISSING,
            reason="공식 시장·상품·주식종류·상장상태 중 누락값이 있습니다.",
            source_provider="KRX",
        )
    if any(
        value in _UNKNOWN_CLASSIFICATION_VALUES
        for value in (
            evidence.product_type,
            evidence.share_class,
            evidence.listing_status,
        )
    ):
        return FilterResult(
            code="MARKET_UNIVERSE",
            name="코스피 일반주식",
            state=FilterState.MISSING,
            reason="공식 상품·주식종류·상장상태 중 미확인 값이 있습니다.",
            source_provider="KRX",
        )
    failures: list[str] = []
    if evidence.is_kospi is not True:
        failures.append("KOSPI 종목이 아님")
    if evidence.product_type != "STOCK":
        failures.append(f"상품구분={evidence.product_type}")
    if evidence.share_class != "COMMON":
        failures.append(f"주식종류={evidence.share_class}")
    if evidence.listing_status != "LISTED":
        failures.append(f"상장상태={evidence.listing_status}")
    if failures:
        return FilterResult(
            code="MARKET_UNIVERSE",
            name="코스피 일반주식",
            state=FilterState.FAIL,
            reason=", ".join(failures),
            raw_text=" / ".join(
                (
                    str(evidence.product_type),
                    str(evidence.share_class),
                    str(evidence.listing_status),
                )
            ),
            source_provider="KRX",
        )
    return FilterResult(
        code="MARKET_UNIVERSE",
        name="코스피 일반주식",
        state=FilterState.PASS,
        reason="공식 분류상 KOSPI 상장 보통주입니다.",
        raw_text="KOSPI / STOCK / COMMON / LISTED",
        source_provider="KRX",
    )


def _market_status_filter(evidence: MarketFilterEvidence) -> FilterResult:
    if not evidence.official_status_coverage:
        return FilterResult(
            code="MARKET_STATUS",
            name="시장상태",
            state=FilterState.MISSING,
            reason=("관리종목·거래정지·상장폐지 위험의 공식 확인 범위가 없습니다."),
            source_provider="KRX/KIND",
        )
    statuses = (
        evidence.trading_suspended,
        evidence.management_issue,
        evidence.delisting_risk,
    )
    if any(value is None for value in statuses):
        return FilterResult(
            code="MARKET_STATUS",
            name="시장상태",
            state=FilterState.MISSING,
            reason="공식 시장상태 중 확인되지 않은 항목이 있습니다.",
            source_provider="KRX/KIND",
        )
    failures: list[str] = []
    if evidence.trading_suspended:
        failures.append("거래정지")
    if evidence.management_issue:
        failures.append("관리종목")
    if evidence.delisting_risk:
        failures.append("상장폐지 위험")
    if failures:
        return FilterResult(
            code="MARKET_STATUS",
            name="시장상태",
            state=FilterState.FAIL,
            reason=", ".join(failures),
            raw_text=", ".join(failures),
            source_provider="KRX/KIND",
        )
    return FilterResult(
        code="MARKET_STATUS",
        name="시장상태",
        state=FilterState.PASS,
        reason="공식 확인 범위에서 배제 시장상태가 없습니다.",
        raw_text="CLEAR",
        source_provider="KRX/KIND",
    )


def _audit_filter(
    evidence: AuditFilterEvidence | None,
    *,
    as_of_date: date,
    rules: Phase2Rules,
) -> FilterResult:
    if evidence is None or evidence.opinion is None or evidence.filing_date is None:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.MISSING,
            reason="최신 감사의견 또는 보고서 제출일을 확인할 수 없습니다.",
            source_provider="OpenDART",
        )
    age_days = (as_of_date - evidence.filing_date).days
    if age_days < 0 or age_days > rules.audit_max_age_days:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.MISSING,
            reason="감사의견 제출일이 기준일 이후이거나 최신성 기준을 넘었습니다.",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    opinion = "".join(evidence.opinion.split())
    if opinion in _REJECTED_AUDIT_OPINIONS:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.FAIL,
            reason=f"투자배제 감사의견입니다: {evidence.opinion}",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    if opinion not in _ACCEPTABLE_AUDIT_OPINIONS:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.MISSING,
            reason="확인된 허용·배제 감사의견 값 집합에 없는 값입니다.",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    if evidence.going_concern_status != "VERIFIED":
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.MISSING,
            reason="계속기업 불확실성 확인 상태가 검증되지 않았습니다.",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    if evidence.going_concern_risk is True:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.FAIL,
            reason="계속기업 존속능력의 중대한 불확실성이 확인됐습니다.",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    if evidence.going_concern_risk is None:
        return FilterResult(
            code="AUDIT_OPINION",
            name="감사의견",
            state=FilterState.MISSING,
            reason="계속기업 불확실성 여부를 확인할 수 없습니다.",
            raw_text=evidence.opinion,
            source_provider="OpenDART",
            evidence_date=evidence.filing_date,
        )
    return FilterResult(
        code="AUDIT_OPINION",
        name="감사의견",
        state=FilterState.PASS,
        reason="최신 적정의견과 계속기업 위험 없음이 확인됐습니다.",
        raw_text=evidence.opinion,
        source_provider="OpenDART",
        evidence_date=evidence.filing_date,
    )


def _liquidity_filter(
    evidence: LiquidityEvidence | None,
    *,
    rules: Phase2Rules,
) -> FilterResult:
    if evidence is None or not evidence.source_verified:
        return FilterResult(
            code="LIQUIDITY",
            name="유동성",
            state=FilterState.MISSING,
            reason="공식 거래대금 원천과 단위를 확인할 수 없습니다.",
            source_provider="KRX",
        )
    if evidence.currency != "KRW":
        return FilterResult(
            code="LIQUIDITY",
            name="유동성",
            state=FilterState.MISSING,
            reason="거래대금의 KRW 단위가 검증되지 않았습니다.",
            raw_text=evidence.currency,
            source_provider="KRX",
        )
    if (
        len(evidence.trading_values_60) < rules.liquidity_days
        or len(evidence.trading_values_60) < rules.order_median_days
        or len(evidence.volumes_20) < rules.zero_volume_days
        or evidence.planned_order_amount is None
    ):
        return FilterResult(
            code="LIQUIDITY",
            name="유동성",
            state=FilterState.MISSING,
            reason=("60일 거래대금·20일 거래량 또는 예정 주문금액이 부족합니다."),
            source_provider="KRX",
        )
    values = evidence.trading_values_60[-rules.liquidity_days :]
    order_values = evidence.trading_values_60[-rules.order_median_days :]
    volumes = evidence.volumes_20[-rules.zero_volume_days :]
    if any(value < 0 for value in values) or any(value < 0 for value in volumes):
        return FilterResult(
            code="LIQUIDITY",
            name="유동성",
            state=FilterState.MISSING,
            reason="음수 거래대금 또는 거래량이 있어 입력을 신뢰할 수 없습니다.",
            source_provider="KRX",
        )
    median_value = Decimal(median(values))
    order_median = Decimal(median(order_values))
    zero_volume_count = sum(value == 0 for value in volumes)
    order_ratio = (
        evidence.planned_order_amount / order_median if order_median > 0 else None
    )
    failures: list[str] = []
    if median_value < rules.minimum_median_trading_value:
        failures.append("60일 중앙 거래대금 기준 미달")
    if zero_volume_count:
        failures.append(f"최근 20일 중 거래량 0인 날 {zero_volume_count}일")
    if order_ratio is None or order_ratio > rules.maximum_order_to_median_ratio:
        failures.append("예정 주문금액이 주문비율 기준일 중앙 거래대금 한도를 초과")
    return FilterResult(
        code="LIQUIDITY",
        name="유동성",
        state=FilterState.FAIL if failures else FilterState.PASS,
        reason=(
            ", ".join(failures)
            if failures
            else "거래대금·무거래일·예정 주문금액 기준을 통과했습니다."
        ),
        raw_value=median_value,
        raw_text=(
            f"zero_volume_days={zero_volume_count}; "
            f"order_median_{rules.order_median_days}={order_median}; "
            f"order_ratio={order_ratio}"
        ),
        source_provider="KRX",
    )


def _corporate_event_filter(
    evidence: CorporateEventEvidence | None,
) -> FilterResult:
    if evidence is None or not evidence.coverage_verified:
        return FilterResult(
            code="CORPORATE_EVENT",
            name="중대 기업 이벤트",
            state=FilterState.MISSING,
            reason="중대 기업 이벤트 공시의 확인 범위가 검증되지 않았습니다.",
            source_provider="OpenDART/KIND",
        )
    if evidence.severe_event is True:
        return FilterResult(
            code="CORPORATE_EVENT",
            name="중대 기업 이벤트",
            state=FilterState.FAIL,
            reason="투자배제 수준의 중대 기업 이벤트가 확인됐습니다.",
            raw_text=evidence.latest_event,
            source_provider="OpenDART/KIND",
        )
    if evidence.manual_review_event is True:
        return FilterResult(
            code="CORPORATE_EVENT",
            name="중대 기업 이벤트",
            state=FilterState.REVIEW_REQUIRED,
            reason="수동 검토가 필요한 기업 이벤트가 확인됐습니다.",
            raw_text=evidence.latest_event,
            source_provider="OpenDART/KIND",
        )
    if evidence.severe_event is None or evidence.manual_review_event is None:
        return FilterResult(
            code="CORPORATE_EVENT",
            name="중대 기업 이벤트",
            state=FilterState.MISSING,
            reason="기업 이벤트의 위험 판정이 완료되지 않았습니다.",
            source_provider="OpenDART/KIND",
        )
    return FilterResult(
        code="CORPORATE_EVENT",
        name="중대 기업 이벤트",
        state=FilterState.PASS,
        reason="검증된 확인 범위에서 투자배제 기업 이벤트가 없습니다.",
        raw_text="CLEAR",
        source_provider="OpenDART/KIND",
    )


def _financial_risk_filter(
    evidence: FinancialRiskEvidence | None,
    *,
    rules: Phase2Rules,
) -> FilterResult:
    if evidence is None or evidence.entity_kind == EntityKind.UNKNOWN:
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.MISSING,
            reason="공식 산업분류가 없어 금융업 여부를 구분할 수 없습니다.",
            source_provider="KRX/OpenDART",
        )
    if evidence.entity_kind == EntityKind.FINANCIAL:
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.MISSING,
            reason=(
                "금융업 별도 평가모형의 통과 판정값이 구현되지 않았습니다."
                if evidence.financial_model_available
                else "금융업 별도 평가모형의 공식 규제지표가 없습니다."
            ),
            source_provider="OpenDART",
        )
    if (
        evidence.operating_profit_ttm is None
        or evidence.finance_costs_ttm is None
        or evidence.repeated_operating_loss_years is None
        or evidence.currency is None
    ):
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.MISSING,
            reason="비금융업 이자보상·반복 영업손실 입력이 부족합니다.",
            source_provider="OpenDART",
        )
    if evidence.repeated_operating_loss_years >= rules.repeated_loss_years:
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.FAIL,
            reason="영업손실이 반복돼 배제 기준에 해당합니다.",
            raw_text=(f"operating_loss_years={evidence.repeated_operating_loss_years}"),
            source_provider="OpenDART",
        )
    if evidence.finance_costs_ttm < 0:
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.MISSING,
            reason="음수 이자비용은 이자보상비율 입력으로 사용하지 않습니다.",
            source_provider="OpenDART",
        )
    if evidence.finance_costs_ttm == 0:
        state = (
            FilterState.PASS if evidence.operating_profit_ttm >= 0 else FilterState.FAIL
        )
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=state,
            reason=(
                "이자비용이 0이므로 0으로 나누지 않고 저차입으로 표시합니다."
                if state == FilterState.PASS
                else "이자비용은 없지만 영업손실이 확인됐습니다."
            ),
            raw_text="LOW_DEBT",
            source_provider="OpenDART",
        )
    coverage = evidence.operating_profit_ttm / evidence.finance_costs_ttm
    if coverage < rules.minimum_interest_coverage:
        return FilterResult(
            code="FINANCIAL_RISK",
            name="재무위험",
            state=FilterState.REVIEW_REQUIRED,
            reason=(
                "현재 TTM 이자보상비율이 기준 미만이지만 지속 여부를 "
                "확인할 연속 기간 자료가 없어 수동 검토가 필요합니다."
            ),
            raw_value=coverage,
            source_provider="OpenDART",
        )
    return FilterResult(
        code="FINANCIAL_RISK",
        name="재무위험",
        state=FilterState.PASS,
        reason="이자보상비율 기준을 통과했습니다.",
        raw_value=coverage,
        source_provider="OpenDART",
    )


def evaluate_forced_filters(
    market: MarketFilterEvidence,
    audit: AuditFilterEvidence | None,
    liquidity: LiquidityEvidence | None,
    corporate_event: CorporateEventEvidence | None,
    financial_risk: FinancialRiskEvidence | None,
    *,
    as_of_date: date,
    rules: Phase2Rules,
) -> tuple[FilterResult, ...]:
    return (
        _market_universe_filter(market),
        _market_status_filter(market),
        _audit_filter(audit, as_of_date=as_of_date, rules=rules),
        _liquidity_filter(liquidity, rules=rules),
        _corporate_event_filter(corporate_event),
        _financial_risk_filter(financial_risk, rules=rules),
    )
