from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models.scoring import ComponentState, ScoreComponent

_SCORE_QUANTUM = Decimal("0.001")
_RAW_QUANTUM = Decimal("0.0000000001")


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def available_component(
    *,
    score_name: str,
    code: str,
    raw_value: Decimal,
    normalized_value: Decimal,
    weight: Decimal,
    explanation: str,
) -> ScoreComponent:
    normalized = quantize_score(min(Decimal(100), max(Decimal(0), normalized_value)))
    return ScoreComponent(
        score_name=score_name,
        code=code,
        state=ComponentState.AVAILABLE,
        raw_value=raw_value.quantize(_RAW_QUANTUM, rounding=ROUND_HALF_UP),
        normalized_value=normalized,
        weight=weight,
        contribution=quantize_score(normalized / Decimal(100) * weight),
        explanation=explanation,
    )


def unavailable_component(
    *,
    score_name: str,
    code: str,
    weight: Decimal,
    explanation: str,
    state: ComponentState = ComponentState.MISSING,
    raw_value: Decimal | None = None,
    raw_text: str | None = None,
) -> ScoreComponent:
    return ScoreComponent(
        score_name=score_name,
        code=code,
        state=state,
        raw_value=raw_value,
        raw_text=raw_text,
        weight=weight,
        explanation=explanation,
    )


def linear_higher_is_better(
    value: Decimal,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    if value <= minimum:
        return Decimal(0)
    if value >= maximum:
        return Decimal(100)
    return (value - minimum) / (maximum - minimum) * Decimal(100)


def linear_lower_is_better(
    value: Decimal,
    *,
    best: Decimal,
    worst: Decimal,
) -> Decimal:
    if value <= best:
        return Decimal(100)
    if value >= worst:
        return Decimal(0)
    return (worst - value) / (worst - best) * Decimal(100)
