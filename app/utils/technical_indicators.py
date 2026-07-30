from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from app.models.financial import TechnicalSnapshot
from app.models.metadata import DataState


@dataclass(frozen=True)
class AdjustedPricePoint:
    trade_date: date
    high: Decimal
    low: Decimal
    close: Decimal
    is_adjusted: bool | None
    adjustment_status: str | None
    source_provider: str | None = None


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _sma(closes: list[Decimal], period: int) -> Decimal | None:
    if len(closes) < period:
        return None
    return _mean(closes[-period:])


def _wilder_rsi(closes: list[Decimal], period: int = 14) -> Decimal | None:
    if len(closes) <= period:
        return None
    changes = [current - previous for previous, current in pairwise(closes)]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    average_gain = _mean(gains[:period])
    average_loss = _mean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * Decimal(period - 1) + gain) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + loss) / Decimal(period)
    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def _wilder_atr(
    points: list[AdjustedPricePoint],
    period: int = 14,
) -> Decimal | None:
    if len(points) < period:
        return None
    true_ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for point in points:
        candidates = [point.high - point.low]
        if previous_close is not None:
            candidates.extend(
                (
                    abs(point.high - previous_close),
                    abs(point.low - previous_close),
                )
            )
        true_ranges.append(max(candidates))
        previous_close = point.close
    average = _mean(true_ranges[:period])
    for true_range in true_ranges[period:]:
        average = (average * Decimal(period - 1) + true_range) / Decimal(period)
    return average


def calculate_technical_snapshot(
    price_points: list[AdjustedPricePoint],
) -> TechnicalSnapshot:
    if not price_points:
        return TechnicalSnapshot(
            state=DataState.MISSING,
            error_message="가격 데이터가 없습니다.",
        )
    ordered = sorted(price_points, key=lambda item: item.trade_date)
    if len({item.trade_date for item in ordered}) != len(ordered):
        raise ValueError("duplicate trade dates are not allowed")
    price_sources = {item.source_provider for item in ordered}
    if len(price_sources) != 1 or None in price_sources:
        return TechnicalSnapshot(
            state=DataState.CONFLICT,
            as_of_date=ordered[-1].trade_date,
            error_message=(
                "단일 가격 원천을 확인할 수 없어 기술지표를 계산하지 않습니다."
            ),
        )
    if any(
        item.is_adjusted is not True or item.adjustment_status != "VERIFIED"
        for item in ordered
    ):
        return TechnicalSnapshot(
            state=DataState.NOT_VERIFIED,
            as_of_date=ordered[-1].trade_date,
            price_source=ordered[-1].source_provider,
            error_message=(
                "수정가격 확인 상태가 VERIFIED가 아니므로 기술지표를 계산하지 않습니다."
            ),
        )
    if any(
        item.high < item.low
        or item.high < item.close
        or item.low > item.close
        or item.close < 0
        for item in ordered
    ):
        raise ValueError("adjusted OHLC values are inconsistent")

    closes = [item.close for item in ordered]
    drawdown: Decimal | None = None
    if len(closes) >= 252:
        high_52_week = max(item.high for item in ordered[-252:])
        if high_52_week > 0:
            drawdown = closes[-1] / high_52_week - Decimal(1)
    return TechnicalSnapshot(
        state=DataState.AVAILABLE,
        as_of_date=ordered[-1].trade_date,
        rsi_14=_wilder_rsi(closes),
        sma_20=_sma(closes, 20),
        sma_60=_sma(closes, 60),
        sma_120=_sma(closes, 120),
        sma_200=_sma(closes, 200),
        atr_14=_wilder_atr(ordered),
        drawdown_52_week=drawdown,
        price_source=ordered[-1].source_provider,
    )
