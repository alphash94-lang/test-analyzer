from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.models.scoring import (
    ComponentState,
    IndustryComparison,
    IndustryPeer,
    ValuationEvidence,
)

_PERCENTILE_QUANTUM = Decimal("0.001")


def _metric_value(peer: IndustryPeer, metric_code: str) -> Decimal | None:
    if metric_code == "PER":
        return peer.per
    if metric_code == "PBR":
        return peer.pbr
    if metric_code == "ROE":
        return peer.roe
    raise ValueError(f"unsupported valuation metric: {metric_code}")


def _valid_metric_values(
    peers: tuple[IndustryPeer, ...],
    metric_code: str,
) -> list[Decimal]:
    values = [
        value
        for peer in peers
        if (value := _metric_value(peer, metric_code)) is not None
    ]
    if metric_code in {"PER", "PBR"}:
        return [value for value in values if value > 0]
    return values


def _quartiles(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    lower = ordered[:midpoint]
    upper = ordered[midpoint:] if len(ordered) % 2 == 0 else ordered[midpoint + 1 :]
    return Decimal(median(lower)), Decimal(median(upper))


def _iqr_filtered(values: list[Decimal]) -> list[Decimal]:
    if len(values) < 4:
        return values
    q1, q3 = _quartiles(values)
    iqr = q3 - q1
    lower_bound = q1 - Decimal("1.5") * iqr
    upper_bound = q3 + Decimal("1.5") * iqr
    filtered = [value for value in values if lower_bound <= value <= upper_bound]
    return filtered or values


def _current_value(
    evidence: ValuationEvidence,
    metric_code: str,
) -> Decimal | None:
    if metric_code == "PER":
        return evidence.current_per
    if metric_code == "PBR":
        return evidence.current_pbr
    raise ValueError(f"unsupported current valuation metric: {metric_code}")


def select_industry_comparison(
    evidence: ValuationEvidence,
    *,
    metric_code: str,
    minimum_sample: int,
) -> IndustryComparison:
    current = _current_value(evidence, metric_code)
    if current is None:
        return IndustryComparison(
            metric_code=metric_code,
            state=ComponentState.MISSING,
            explanation=f"현재 {metric_code}를 계산할 입력이 없습니다.",
        )
    if current <= 0:
        return IndustryComparison(
            metric_code=metric_code,
            state=ComponentState.NOT_APPLICABLE,
            current_value=current,
            explanation=(
                f"{metric_code}가 0 이하이므로 저평가 점수를 부여하지 않습니다."
            ),
        )
    detailed_peers = tuple(
        peer
        for peer in evidence.peers
        if evidence.detailed_industry is not None
        and peer.detailed_industry == evidence.detailed_industry
    )
    detailed_values = _valid_metric_values(detailed_peers, metric_code)
    if len(detailed_values) >= minimum_sample:
        selected_peers = detailed_peers
        comparison_level = "DETAILED"
        classification_code = evidence.detailed_industry
    else:
        selected_peers = tuple(
            peer
            for peer in evidence.peers
            if evidence.parent_industry is not None
            and peer.parent_industry == evidence.parent_industry
        )
        comparison_level = "PARENT"
        classification_code = evidence.parent_industry
    values = _valid_metric_values(selected_peers, metric_code)
    if len(values) < minimum_sample:
        return IndustryComparison(
            metric_code=metric_code,
            state=ComponentState.MISSING,
            current_value=current,
            comparison_level=comparison_level,
            classification_code=classification_code,
            sample_size=len(values),
            explanation=(
                f"{comparison_level} 산업의 유효 {metric_code} 표본이 "
                f"{minimum_sample}개 미만입니다."
            ),
        )
    filtered = _iqr_filtered(values)
    industry_median = Decimal(median(filtered))
    cheaper_or_equal = sum(value >= current for value in filtered)
    percentile = (
        Decimal(cheaper_or_equal) / Decimal(len(filtered)) * Decimal(100)
    ).quantize(_PERCENTILE_QUANTUM, rounding=ROUND_HALF_UP)
    return IndustryComparison(
        metric_code=metric_code,
        state=ComponentState.AVAILABLE,
        current_value=current,
        industry_median=industry_median,
        industry_percentile=percentile,
        comparison_level=comparison_level,
        classification_code=classification_code,
        sample_size=len(values),
        explanation=(
            f"{comparison_level} 산업 {metric_code} 유효 표본 "
            f"{len(values)}개를 IQR 방식으로 완화해 중앙값을 계산했습니다."
        ),
    )


def historical_comparison(
    *,
    metric_code: str,
    current_value: Decimal | None,
    history: tuple[Decimal, ...],
    minimum_sample: int,
) -> IndustryComparison:
    if current_value is None:
        return IndustryComparison(
            metric_code=f"HISTORICAL_{metric_code}",
            state=ComponentState.MISSING,
            explanation=f"현재 {metric_code}가 없습니다.",
        )
    if current_value <= 0:
        return IndustryComparison(
            metric_code=f"HISTORICAL_{metric_code}",
            state=ComponentState.NOT_APPLICABLE,
            current_value=current_value,
            explanation=(
                f"{metric_code}가 0 이하이므로 자체 역사 저평가 점수를 "
                "부여하지 않습니다."
            ),
        )
    valid_history = [value for value in history if value > 0]
    if len(valid_history) < minimum_sample:
        return IndustryComparison(
            metric_code=f"HISTORICAL_{metric_code}",
            state=ComponentState.MISSING,
            current_value=current_value,
            sample_size=len(valid_history),
            explanation=(
                f"자체 역사 {metric_code} 표본이 {minimum_sample}개 미만입니다."
            ),
        )
    filtered = _iqr_filtered(valid_history)
    history_median = Decimal(median(filtered))
    cheaper_or_equal = sum(value >= current_value for value in filtered)
    percentile = (
        Decimal(cheaper_or_equal) / Decimal(len(filtered)) * Decimal(100)
    ).quantize(_PERCENTILE_QUANTUM, rounding=ROUND_HALF_UP)
    return IndustryComparison(
        metric_code=f"HISTORICAL_{metric_code}",
        state=ComponentState.AVAILABLE,
        current_value=current_value,
        historical_median=history_median,
        historical_percentile=percentile,
        comparison_level="HISTORY",
        sample_size=len(valid_history),
        explanation=(
            f"자체 역사 {metric_code} 유효 표본 {len(valid_history)}개를 "
            "IQR 방식으로 완화해 중앙값을 계산했습니다."
        ),
    )


def valuation_normalized_score(
    current: Decimal,
    reference_median: Decimal,
) -> Decimal:
    if current <= 0 or reference_median <= 0:
        raise ValueError("valuation score requires positive values")
    relative_discount = reference_median / current
    lower = Decimal("0.75")
    upper = Decimal("1.50")
    if relative_discount <= lower:
        return Decimal(0)
    if relative_discount >= upper:
        return Decimal(100)
    return (relative_discount - lower) / (upper - lower) * Decimal(100)
