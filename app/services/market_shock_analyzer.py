from __future__ import annotations

from decimal import Decimal
from statistics import median

from app.config import Settings
from app.models.market_analysis import (
    BreadthAnalysis,
    ConstituentObservation,
    DividendContagionAnalysis,
    IndexPoint,
    MarketHighResult,
    MarketRegime,
    SemiconductorAnalysis,
    ShockClassification,
)
from app.models.metadata import DataState


class MarketShockAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def calculate_highs(
        points: list[IndexPoint],
        horizons: tuple[int, ...] = (21, 63, 126, 252),
    ) -> dict[int, MarketHighResult]:
        if not points:
            return {}
        current = points[-1].close
        results: dict[int, MarketHighResult] = {}
        for horizon in horizons:
            if len(points) < horizon:
                continue
            window = points[-horizon:]
            high_point = max(window, key=lambda point: (point.close, point.trade_date))
            results[horizon] = MarketHighResult(
                horizon=horizon,
                high_date=high_point.trade_date,
                high=high_point.close,
                current=current,
                drawdown=current / high_point.close - Decimal(1),
            )
        return results

    def calculate_breadth(
        self,
        observations: list[ConstituentObservation],
    ) -> BreadthAnalysis:
        if len(observations) < self._settings.phase3_minimum_constituents:
            return BreadthAnalysis(
                state=DataState.MISSING,
                sample_size=len(observations),
                reason="검증된 수정가격을 가진 KOSPI 보통주 표본이 부족합니다.",
            )
        horizon_returns = [
            item.close / item.start_close - Decimal(1) for item in observations
        ]
        daily_returns = [
            item.close / item.previous_close - Decimal(1) for item in observations
        ]
        sma20_observations = [
            item for item in observations if len(item.close_history) >= 20
        ]
        sma60_observations = [
            item for item in observations if len(item.close_history) >= 60
        ]
        if not sma20_observations or not sma60_observations:
            return BreadthAnalysis(
                state=DataState.MISSING,
                sample_size=len(observations),
                reason="20일선·60일선 시장 폭을 계산할 가격 이력이 부족합니다.",
            )
        advancing_count = sum(value > 0 for value in daily_returns)
        declining_count = sum(value < 0 for value in daily_returns)
        return BreadthAnalysis(
            state=DataState.AVAILABLE,
            equal_weighted_return=(
                sum(horizon_returns, Decimal(0)) / Decimal(len(horizon_returns))
            ),
            median_return=Decimal(median(horizon_returns)),
            advancing_ratio=(Decimal(advancing_count) / Decimal(len(daily_returns))),
            above_sma20_ratio=(
                Decimal(
                    sum(
                        item.close
                        > sum(item.close_history[-20:], Decimal(0)) / Decimal(20)
                        for item in sma20_observations
                    )
                )
                / Decimal(len(sma20_observations))
            ),
            above_sma60_ratio=(
                Decimal(
                    sum(
                        item.close
                        > sum(item.close_history[-60:], Decimal(0)) / Decimal(60)
                        for item in sma60_observations
                    )
                )
                / Decimal(len(sma60_observations))
            ),
            advancing_count=advancing_count,
            declining_count=declining_count,
            sample_size=len(observations),
            reason=(
                "검증된 수정가격의 기간수익률·직전 거래일 대비 수익률과 "
                "개별 종목 이동평균으로 시장 폭을 계산했습니다."
            ),
        )

    def classify_shock(
        self,
        *,
        kospi_return: Decimal | None,
        breadth: BreadthAnalysis,
        semiconductor: SemiconductorAnalysis,
    ) -> ShockClassification:
        if (
            kospi_return is None
            or kospi_return >= 0
            or breadth.state != DataState.AVAILABLE
            or semiconductor.state != DataState.AVAILABLE
            or semiconductor.semiconductor_negative_contribution_share is None
            or semiconductor.cap_weighted_return is None
            or semiconductor.non_semiconductor_equal_weighted_return is None
            or breadth.advancing_ratio is None
            or breadth.median_return is None
        ):
            return ShockClassification.UNCERTAIN
        semiconductor_led = (
            semiconductor.semiconductor_negative_contribution_share
            >= self._settings.phase3_semiconductor_contribution_share
            and (
                semiconductor.cap_weighted_return
                - semiconductor.non_semiconductor_equal_weighted_return
            )
            <= self._settings.phase3_semiconductor_underperformance
        )
        broad = (
            Decimal(1) - breadth.advancing_ratio
            >= self._settings.phase3_broad_decline_ratio
            and breadth.median_return <= self._settings.phase3_broad_median_return
            and semiconductor.non_semiconductor_equal_weighted_return < 0
        )
        if semiconductor_led and broad:
            return ShockClassification.MIXED
        if semiconductor_led:
            return ShockClassification.SEMICONDUCTOR_LED
        if broad:
            return ShockClassification.BROAD_SELLOFF
        return ShockClassification.UNCERTAIN

    def classify_regime(
        self,
        *,
        index_points: list[IndexPoint],
        highs: dict[int, MarketHighResult],
        breadth: BreadthAnalysis,
        semiconductor: SemiconductorAnalysis,
        dividend: DividendContagionAnalysis,
    ) -> tuple[MarketRegime, bool | None, bool | None, bool | None, bool | None]:
        if (
            len(index_points) < 60
            or 252 not in highs
            or breadth.state != DataState.AVAILABLE
            or semiconductor.state != DataState.AVAILABLE
            or dividend.state != DataState.AVAILABLE
            or breadth.advancing_ratio is None
            or breadth.above_sma20_ratio is None
            or breadth.above_sma60_ratio is None
            or semiconductor.cap_weighted_return is None
            or semiconductor.non_semiconductor_equal_weighted_return is None
            or dividend.recovery is None
        ):
            return (MarketRegime.UNCERTAIN, None, None, None, None)

        current = index_points[-1].close
        sma20 = sum(
            (point.close for point in index_points[-20:]),
            Decimal(0),
        ) / Decimal(20)
        sma60 = sum(
            (point.close for point in index_points[-60:]),
            Decimal(0),
        ) / Decimal(60)
        kospi_recovery = current >= sma20
        semiconductor_recovery = semiconductor.cap_weighted_return >= 0
        non_semiconductor_breadth = (
            breadth.above_sma20_ratio >= self._settings.phase3_yellow_breadth20
            and semiconductor.non_semiconductor_equal_weighted_return >= 0
        )
        dividend_recovery = dividend.recovery
        green = (
            current >= sma60
            and semiconductor_recovery
            and breadth.above_sma20_ratio >= self._settings.phase3_green_breadth20
            and breadth.above_sma60_ratio >= self._settings.phase3_green_breadth60
            and non_semiconductor_breadth
            and dividend_recovery
        )
        yellow = (
            kospi_recovery
            and semiconductor_recovery
            and non_semiconductor_breadth
            and dividend_recovery
        )
        red = (
            highs[252].drawdown <= self._settings.phase3_red_drawdown
            and breadth.advancing_ratio <= self._settings.phase3_red_advancing_ratio
        )
        stabilization_window = index_points[-self._settings.phase3_stabilization_days :]
        stabilized = len(
            stabilization_window
        ) == self._settings.phase3_stabilization_days and stabilization_window[
            -1
        ].close > min(point.close for point in stabilization_window[:-1])
        if green:
            regime = MarketRegime.GREEN
        elif yellow:
            regime = MarketRegime.YELLOW
        elif red:
            regime = MarketRegime.RED
        elif stabilized:
            regime = MarketRegime.ORANGE
        else:
            regime = MarketRegime.UNCERTAIN
        return (
            regime,
            semiconductor_recovery,
            kospi_recovery,
            non_semiconductor_breadth,
            dividend_recovery,
        )
