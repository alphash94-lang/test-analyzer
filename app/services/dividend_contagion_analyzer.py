from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.models.market_analysis import (
    ConstituentObservation,
    DividendContagionAnalysis,
)
from app.models.metadata import DataState


class DividendContagionAnalyzer:
    """Compare confirmed dividend-payer returns with market benchmarks."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def analyze(
        self,
        observations: list[ConstituentObservation],
        *,
        kospi_return: Decimal | None,
        non_semiconductor_return: Decimal | None,
    ) -> DividendContagionAnalysis:
        dividend_stocks = [
            item for item in observations if item.is_confirmed_dividend_payer is True
        ]
        if (
            len(dividend_stocks) < self._settings.phase3_minimum_dividend_sample
            or kospi_return is None
            or non_semiconductor_return is None
        ):
            return DividendContagionAnalysis(
                state=DataState.MISSING,
                sample_size=len(dividend_stocks),
                reason=(
                    "기준일 이전 확정 DPS가 있는 종목 표본 또는 비교 시장 "
                    "수익률이 부족해 배당주 동반하락을 계산할 수 없습니다."
                ),
            )
        dividend_return = sum(
            (item.close / item.start_close - Decimal(1) for item in dividend_stocks),
            Decimal(0),
        ) / Decimal(len(dividend_stocks))
        relative_to_kospi = dividend_return - kospi_return
        return DividendContagionAnalysis(
            state=DataState.AVAILABLE,
            dividend_equal_weighted_return=dividend_return,
            relative_to_kospi=relative_to_kospi,
            relative_to_non_semiconductor=(dividend_return - non_semiconductor_return),
            sample_size=len(dividend_stocks),
            recovery=relative_to_kospi >= 0,
            reason=(
                "기준일 이전 공식 공시의 확정 DPS가 있는 종목만 동일가중하고 "
                "KOSPI 및 비반도체 자체 바스켓과 상대수익률을 비교했습니다."
            ),
        )
