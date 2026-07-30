from __future__ import annotations

from decimal import Decimal

from app.models.scoring import (
    DataConfidenceEvidence,
    EntryEvidence,
    Phase2Rules,
    ScoreComponent,
)
from app.services.score_component_common import (
    available_component,
    linear_lower_is_better,
    unavailable_component,
)


def confidence_components(
    evidence: DataConfidenceEvidence,
    rules: Phase2Rules,
) -> tuple[ScoreComponent, ...]:
    completeness_ratio = Decimal(evidence.required_items_present) / Decimal(
        evidence.required_items_total
    )
    completeness = available_component(
        score_name="DATA_CONFIDENCE",
        code="COMPLETENESS",
        raw_value=completeness_ratio,
        normalized_value=completeness_ratio * Decimal(100),
        weight=rules.confidence_completeness_weight,
        explanation="필수 입력 중 실제로 확인된 항목 비율입니다.",
    )
    if evidence.max_age_days is None:
        freshness = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="FRESHNESS",
            weight=rules.confidence_freshness_weight,
            explanation="핵심 데이터의 최대 경과일을 확인할 수 없습니다.",
        )
    else:
        age = Decimal(evidence.max_age_days)
        freshness = available_component(
            score_name="DATA_CONFIDENCE",
            code="FRESHNESS",
            raw_value=age,
            normalized_value=linear_lower_is_better(
                age,
                best=Decimal(rules.freshness_full_score_days),
                worst=Decimal(rules.freshness_zero_score_days),
            ),
            weight=rules.confidence_freshness_weight,
            explanation="기준일 대비 핵심 데이터의 최대 경과일입니다.",
        )
    if evidence.official_source_ratio is None:
        official = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="OFFICIAL_SOURCE",
            weight=rules.confidence_official_source_weight,
            explanation="공식 출처 비율을 확인할 수 없습니다.",
        )
    else:
        official = available_component(
            score_name="DATA_CONFIDENCE",
            code="OFFICIAL_SOURCE",
            raw_value=evidence.official_source_ratio,
            normalized_value=evidence.official_source_ratio * Decimal(100),
            weight=rules.confidence_official_source_weight,
            explanation="필수 입력 중 공식 출처가 확인된 비율입니다.",
        )
    if evidence.cross_validation_verified is None:
        cross_validation = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="CROSS_VALIDATION",
            weight=rules.confidence_cross_validation_weight,
            explanation="교차검증 결과가 없습니다.",
        )
    else:
        cross_raw = Decimal(1) if evidence.cross_validation_verified else Decimal(0)
        cross_validation = available_component(
            score_name="DATA_CONFIDENCE",
            code="CROSS_VALIDATION",
            raw_value=cross_raw,
            normalized_value=cross_raw * Decimal(100),
            weight=rules.confidence_cross_validation_weight,
            explanation="공식 원천 간 교차검증 일치 여부입니다.",
        )
    if evidence.industry_sample_size is None:
        industry_sample = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="INDUSTRY_SAMPLE",
            weight=rules.confidence_industry_sample_weight,
            explanation="산업 비교 표본 수가 없습니다.",
        )
    else:
        sample_ratio = min(
            Decimal(1),
            Decimal(evidence.industry_sample_size)
            / Decimal(rules.industry_minimum_sample),
        )
        industry_sample = available_component(
            score_name="DATA_CONFIDENCE",
            code="INDUSTRY_SAMPLE",
            raw_value=Decimal(evidence.industry_sample_size),
            normalized_value=sample_ratio * Decimal(100),
            weight=rules.confidence_industry_sample_weight,
            explanation="산업 비교 최소 표본 수 충족 정도입니다.",
        )
    if evidence.adjusted_price_verified is None:
        adjusted_price = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="ADJUSTED_PRICE",
            weight=rules.confidence_adjusted_price_weight,
            explanation="수정가격 확인 상태가 없습니다.",
        )
    else:
        adjusted_raw = Decimal(1) if evidence.adjusted_price_verified else Decimal(0)
        adjusted_price = available_component(
            score_name="DATA_CONFIDENCE",
            code="ADJUSTED_PRICE",
            raw_value=adjusted_raw,
            normalized_value=adjusted_raw * Decimal(100),
            weight=rules.confidence_adjusted_price_weight,
            explanation="기업행사를 반영한 수정가격 확인 여부입니다.",
        )
    if evidence.account_mapping_ratio is None:
        mapping = unavailable_component(
            score_name="DATA_CONFIDENCE",
            code="ACCOUNT_MAPPING",
            weight=rules.confidence_mapping_weight,
            explanation="핵심 재무 계정 매핑률을 확인할 수 없습니다.",
        )
    else:
        mapping = available_component(
            score_name="DATA_CONFIDENCE",
            code="ACCOUNT_MAPPING",
            raw_value=evidence.account_mapping_ratio,
            normalized_value=evidence.account_mapping_ratio * Decimal(100),
            weight=rules.confidence_mapping_weight,
            explanation="핵심 재무 계정 중 정확 매핑에 성공한 비율입니다.",
        )
    return (
        completeness,
        freshness,
        official,
        cross_validation,
        industry_sample,
        adjusted_price,
        mapping,
    )


def entry_components(
    evidence: EntryEvidence | None,
) -> tuple[ScoreComponent, ScoreComponent]:
    if (
        evidence is None
        or not evidence.adjusted_price_verified
        or evidence.rsi_14 is None
        or evidence.close is None
        or evidence.sma_20 is None
        or evidence.sma_60 is None
    ):
        return (
            unavailable_component(
                score_name="ENTRY_INDIVIDUAL",
                code="ENTRY_RSI",
                weight=Decimal(10),
                explanation="검증된 수정가격 기반 RSI가 없습니다.",
            ),
            unavailable_component(
                score_name="ENTRY_INDIVIDUAL",
                code="ENTRY_TREND",
                weight=Decimal(10),
                explanation="검증된 수정가격 기반 종목 추세가 없습니다.",
            ),
        )
    rsi = evidence.rsi_14
    if Decimal(40) <= rsi <= Decimal(60):
        rsi_score = Decimal(100)
    elif Decimal(30) <= rsi < Decimal(40) or Decimal(60) < rsi < Decimal(70):
        rsi_score = Decimal(70)
    elif rsi >= Decimal(80):
        rsi_score = Decimal(0)
    else:
        rsi_score = Decimal(30)
    if evidence.close >= evidence.sma_20 >= evidence.sma_60:
        trend_score = Decimal(100)
    elif evidence.close >= evidence.sma_20:
        trend_score = Decimal(70)
    else:
        trend_score = Decimal(30)
    return (
        available_component(
            score_name="ENTRY_INDIVIDUAL",
            code="ENTRY_RSI",
            raw_value=rsi,
            normalized_value=rsi_score,
            weight=Decimal(10),
            explanation="Wilder RSI 14 구간별 신규 진입 경고 규칙입니다.",
        ),
        available_component(
            score_name="ENTRY_INDIVIDUAL",
            code="ENTRY_TREND",
            raw_value=evidence.close / evidence.sma_60,
            normalized_value=trend_score,
            weight=Decimal(10),
            explanation="수정종가와 SMA 20·60의 상대 위치입니다.",
        ),
    )
