from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from app.config import Settings
from app.models.market_analysis import (
    BreadthAnalysis,
    DividendContagionAnalysis,
    IndexPoint,
    MarketHighResult,
    MetricEvidence,
    ProxyKind,
    SemiconductorAnalysis,
    SourceKind,
)
from app.models.metadata import DataState, DataTiming
from app.repositories.phase3_input_repository import Phase3InputBundle


class MarketMetricBuilder:
    """Build displayable Phase 3 metrics with complete provenance."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build(
        self,
        *,
        bundle: Phase3InputBundle,
        as_of_at: datetime,
        highs: dict[int, MarketHighResult],
        kospi_return: Decimal | None,
        breadth: BreadthAnalysis,
        semiconductor: SemiconductorAnalysis,
        dividend: DividendContagionAnalysis,
        shock: str,
        regime: str,
        confidence: Decimal | None,
        semiconductor_recovery: bool | None,
        kospi_recovery: bool | None,
        non_semiconductor_breadth: bool | None,
        dividend_recovery: bool | None,
    ) -> list[MetricEvidence]:
        latest_index = bundle.index_points[-1] if bundle.index_points else None
        index_collected = latest_index.collected_at if latest_index else None
        stock_collected = (
            max(item.collected_at for item in bundle.observations)
            if bundle.observations
            else None
        )
        price_provider = (
            bundle.observations[0].price_source_provider
            if bundle.observations
            else self._settings.phase3_adjusted_price_provider
        )
        official_semiconductor_point = (
            bundle.official_semiconductor_index_points[-1]
            if semiconductor.proxy_kind == ProxyKind.OFFICIAL_INDEX
            and bundle.official_semiconductor_index_points
            else None
        )
        provider_names: list[str] = []
        if latest_index is not None:
            provider_names.append(latest_index.source_provider)
        if bundle.observations:
            provider_names.extend(["KRX", price_provider])
            if any(
                item.is_confirmed_dividend_payer is True for item in bundle.observations
            ):
                provider_names.append("OpenDART")
        combined_provider = "·".join(dict.fromkeys(provider_names)) or None
        index_as_of = (
            datetime.combine(
                latest_index.trade_date,
                time.min,
                tzinfo=as_of_at.tzinfo,
            )
            if latest_index
            else as_of_at
        )
        metrics: list[MetricEvidence] = []
        self._add_index_metrics(
            metrics,
            index_as_of=index_as_of,
            index_collected=index_collected,
            latest_close=latest_index.close if latest_index else None,
            highs=highs,
            kospi_return=kospi_return,
        )
        self._add_breadth_metrics(
            metrics,
            index_as_of=index_as_of,
            collected_at=stock_collected,
            price_provider=price_provider,
            breadth=breadth,
        )
        self._add_semiconductor_metrics(
            metrics,
            index_as_of=index_as_of,
            collected_at=stock_collected,
            price_provider=price_provider,
            semiconductor=semiconductor,
            official_index_point=official_semiconductor_point,
        )
        self._add_dividend_metrics(
            metrics,
            index_as_of=index_as_of,
            collected_at=stock_collected,
            price_provider=price_provider,
            dividend=dividend,
        )
        combined_collected = (
            max(
                value
                for value in (index_collected, stock_collected)
                if value is not None
            )
            if index_collected is not None or stock_collected is not None
            else None
        )
        self._append(
            metrics,
            index_as_of=index_as_of,
            code="DATA_CONFIDENCE",
            label="데이터 신뢰도",
            value=confidence,
            unit="score_0_100",
            source_provider=combined_provider if confidence is not None else None,
            source_function="Phase 3 입력 완전성 규칙",
            collected_at=combined_collected,
            method="지수 30%·구성종목 30%·분류 25%·배당 표본 15%",
            quality="RULE_BASED" if confidence is not None else "MISSING",
            source_kind=SourceKind.SELF_CALCULATED,
        )
        for code, label, text in (
            ("SHOCK_CLASSIFICATION", "시장충격 분류", shock),
            ("MARKET_REGIME", "시장국면", regime),
        ):
            self._append(
                metrics,
                index_as_of=index_as_of,
                code=code,
                label=label,
                text=text,
                source_provider=combined_provider,
                source_function="MarketShockAnalyzer",
                collected_at=stock_collected or index_collected,
                method=f"{self._settings.phase3_rule_version} 설정 임계값",
                quality="RULE_BASED",
                source_kind=SourceKind.SELF_CALCULATED,
                proxy=semiconductor.proxy_kind,
            )
        for code, label, value in (
            (
                "SEMICONDUCTOR_RECOVERY",
                "반도체 회복",
                semiconductor_recovery,
            ),
            ("KOSPI_RECOVERY", "KOSPI 회복", kospi_recovery),
            (
                "NON_SEMICONDUCTOR_BREADTH",
                "비반도체 시장 확산",
                non_semiconductor_breadth,
            ),
            (
                "DIVIDEND_RELATIVE_STRENGTH_RECOVERY",
                "배당주 상대강도 회복",
                dividend_recovery,
            ),
        ):
            self._append(
                metrics,
                index_as_of=index_as_of,
                code=code,
                label=label,
                text=(
                    "확인" if value is True else "미확인" if value is False else None
                ),
                source_provider=(combined_provider if value is not None else None),
                source_function="Phase 3 시장국면 규칙",
                collected_at=stock_collected or index_collected,
                method="각 회복 조건을 독립 판정",
                quality="RULE_BASED" if value is not None else "MISSING",
                source_kind=SourceKind.SELF_CALCULATED,
                proxy=(
                    semiconductor.proxy_kind
                    if code == "SEMICONDUCTOR_RECOVERY"
                    else (
                        ProxyKind.SELF_CALCULATED_PROXY
                        if code == "NON_SEMICONDUCTOR_BREADTH" and value is not None
                        else ProxyKind.NOT_APPLICABLE
                    )
                ),
            )
        return metrics

    def _add_index_metrics(
        self,
        metrics: list[MetricEvidence],
        *,
        index_as_of: datetime,
        index_collected: datetime | None,
        latest_close: Decimal | None,
        highs: dict[int, MarketHighResult],
        kospi_return: Decimal | None,
    ) -> None:
        self._append(
            metrics,
            index_as_of=index_as_of,
            code="KOSPI_CURRENT",
            label="KOSPI 종가",
            value=latest_close,
            unit="공식 명세 단위 미표기",
            source_provider="KRX" if latest_close is not None else None,
            source_function=(
                "KOSPI 시리즈 일별시세정보" if latest_close is not None else None
            ),
            collected_at=index_collected,
            method="KRX 공식 일별지수 종가",
            quality=(
                "AVAILABLE_UNIT_NOT_SPECIFIED"
                if latest_close is not None
                else "MISSING"
            ),
            source_kind=SourceKind.OFFICIAL_API,
        )
        for horizon in (21, 63, 126, 252):
            result = highs.get(horizon)
            source = "KRX" if result else None
            function = "KOSPI 시리즈 일별시세정보" if result else None
            quality = "CALCULATED_OFFICIAL_INPUT" if result else "MISSING"
            self._append(
                metrics,
                index_as_of=index_as_of,
                code=f"KOSPI_HIGH_{horizon}",
                label=f"KOSPI {horizon}거래일 고점",
                value=result.high if result else None,
                unit="공식 명세 단위 미표기",
                source_provider=source,
                source_function=function,
                collected_at=index_collected,
                method=f"최근 {horizon}개 거래일 종가의 최댓값",
                quality=quality,
                source_kind=SourceKind.SELF_CALCULATED,
            )
            self._append(
                metrics,
                index_as_of=index_as_of,
                code=f"KOSPI_HIGH_DATE_{horizon}",
                label=f"KOSPI {horizon}거래일 고점일",
                text=result.high_date.isoformat() if result else None,
                source_provider=source,
                source_function=function,
                collected_at=index_collected,
                method="동일 최고값이면 가장 최근 거래일",
                quality=quality,
                source_kind=SourceKind.SELF_CALCULATED,
            )
            self._append(
                metrics,
                index_as_of=index_as_of,
                code=f"KOSPI_DRAWDOWN_{horizon}",
                label=f"KOSPI {horizon}거래일 고점 대비 낙폭",
                value=result.drawdown if result else None,
                unit="rate",
                source_provider=source,
                source_function=function,
                collected_at=index_collected,
                method="현재 종가 / 기간 내 최고 종가 - 1",
                quality=quality,
                source_kind=SourceKind.SELF_CALCULATED,
            )
        self._append(
            metrics,
            index_as_of=index_as_of,
            code="KOSPI_RETURN",
            label=f"KOSPI {self._settings.phase3_return_lookback_days}거래일 수익률",
            value=kospi_return,
            unit="rate",
            source_provider="KRX" if kospi_return is not None else None,
            source_function=(
                "KOSPI 시리즈 일별시세정보" if kospi_return is not None else None
            ),
            collected_at=index_collected,
            method="기간 말 종가 / 기간 시작 종가 - 1",
            quality=(
                "CALCULATED_OFFICIAL_INPUT" if kospi_return is not None else "MISSING"
            ),
            source_kind=SourceKind.SELF_CALCULATED,
        )

    @staticmethod
    def _add_breadth_metrics(
        metrics: list[MetricEvidence],
        *,
        index_as_of: datetime,
        collected_at: datetime | None,
        price_provider: str,
        breadth: BreadthAnalysis,
    ) -> None:
        for code, label, value, method in (
            (
                "KOSPI_EQUAL_RETURN",
                "KOSPI 동일가중 수익률",
                breadth.equal_weighted_return,
                "구성종목 기간수익률의 산술평균",
            ),
            (
                "KOSPI_MEDIAN_RETURN",
                "KOSPI 종목 중앙수익률",
                breadth.median_return,
                "구성종목 기간수익률의 중앙값",
            ),
            (
                "ADVANCING_RATIO",
                "상승종목 비율",
                breadth.advancing_ratio,
                "직전 거래일보다 상승한 종목 수 / 비교 가능 종목 수",
            ),
            (
                "ABOVE_SMA20_RATIO",
                "20일선 위 종목 비율",
                breadth.above_sma20_ratio,
                "종가가 SMA20을 상회한 종목 비율",
            ),
            (
                "ABOVE_SMA60_RATIO",
                "60일선 위 종목 비율",
                breadth.above_sma60_ratio,
                "종가가 SMA60을 상회한 종목 비율",
            ),
        ):
            MarketMetricBuilder._append(
                metrics,
                index_as_of=index_as_of,
                code=code,
                label=label,
                value=value,
                unit="rate",
                source_provider=price_provider if value is not None else None,
                source_function="검증된 수정가격 구성종목 시계열",
                collected_at=collected_at,
                method=method,
                quality=(
                    "CALCULATED_VERIFIED_ADJUSTED_PRICE"
                    if value is not None
                    else "MISSING"
                ),
                source_kind=SourceKind.SELF_CALCULATED,
            )

    @staticmethod
    def _add_semiconductor_metrics(
        metrics: list[MetricEvidence],
        *,
        index_as_of: datetime,
        collected_at: datetime | None,
        price_provider: str,
        semiconductor: SemiconductorAnalysis,
        official_index_point: IndexPoint | None,
    ) -> None:
        values = (
            (
                "SEMICONDUCTOR_CAP_RETURN",
                "반도체 시가총액가중 수익률",
                semiconductor.cap_weighted_return,
                "공식 지수 우선, 없으면 시작일 시가총액 가중",
            ),
            (
                "SEMICONDUCTOR_EQUAL_RETURN",
                "반도체 동일가중 수익률",
                semiconductor.equal_weighted_return,
                "공식 산업분류 반도체 종목 기간수익률 산술평균",
            ),
            (
                "NON_SEMICONDUCTOR_CAP_RETURN",
                "비반도체 시가총액가중 수익률",
                semiconductor.non_semiconductor_cap_weighted_return,
                "반도체 제외 후 시작일 시가총액 가중",
            ),
            (
                "NON_SEMICONDUCTOR_EQUAL_RETURN",
                "비반도체 동일가중 수익률",
                semiconductor.non_semiconductor_equal_weighted_return,
                "반도체 제외 종목 기간수익률 산술평균",
            ),
            (
                "NON_SEMICONDUCTOR_MEDIAN_RETURN",
                "비반도체 종목 중앙수익률",
                semiconductor.non_semiconductor_median_return,
                "반도체 제외 종목 기간수익률 중앙값",
            ),
            (
                "SEMICONDUCTOR_NEGATIVE_CONTRIBUTION_SHARE",
                "반도체 음의 기여도 비중",
                semiconductor.semiconductor_negative_contribution_share,
                "반도체 음의 기여도 절댓값 / 전체 음의 기여도 절댓값",
            ),
            (
                "SEMICONDUCTOR_CONTRIBUTION",
                "반도체 전체 기여도 추정치",
                semiconductor.semiconductor_contribution,
                "반도체 종목의 전일 시가총액 비중×당일 수익률 합",
            ),
            (
                "SAMSUNG_CONTRIBUTION",
                "삼성전자 기여도 추정치",
                semiconductor.samsung_contribution,
                "전일 시가총액 비중×당일 수익률",
            ),
            (
                "SK_HYNIX_CONTRIBUTION",
                "SK하이닉스 기여도 추정치",
                semiconductor.sk_hynix_contribution,
                "전일 시가총액 비중×당일 수익률",
            ),
        )
        for code, label, value, method in values:
            official_source = (
                official_index_point
                if code == "SEMICONDUCTOR_CAP_RETURN"
                and semiconductor.proxy_kind == ProxyKind.OFFICIAL_INDEX
                else None
            )
            official_cap_return = official_source is not None
            contribution_metric = code in {
                "SEMICONDUCTOR_NEGATIVE_CONTRIBUTION_SHARE",
                "SEMICONDUCTOR_CONTRIBUTION",
                "SAMSUNG_CONTRIBUTION",
                "SK_HYNIX_CONTRIBUTION",
            }
            MarketMetricBuilder._append(
                metrics,
                index_as_of=index_as_of,
                code=code,
                label=label,
                value=value,
                unit="rate",
                source_provider=(
                    (
                        official_source.source_provider
                        if official_source is not None
                        else f"KRX·{price_provider}"
                    )
                    if value is not None
                    else None
                ),
                source_function=(
                    official_source.source_function
                    if official_source is not None
                    else "SemiconductorContributionAnalyzer"
                ),
                collected_at=(
                    official_source.collected_at
                    if official_source is not None
                    else collected_at
                ),
                method=method,
                quality=(
                    (
                        "CALCULATED_OFFICIAL_INDEX"
                        if official_cap_return
                        else (
                            "EXPLANATORY_ESTIMATE"
                            if contribution_metric
                            else "CALCULATED_VERIFIED_ADJUSTED_PRICE"
                        )
                    )
                    if value is not None
                    else "MISSING"
                ),
                source_kind=SourceKind.SELF_CALCULATED,
                proxy=(
                    ProxyKind.OFFICIAL_INDEX
                    if official_cap_return
                    else (
                        ProxyKind.SELF_CALCULATED_PROXY
                        if value is not None
                        else ProxyKind.NOT_AVAILABLE
                    )
                ),
            )

    @staticmethod
    def _add_dividend_metrics(
        metrics: list[MetricEvidence],
        *,
        index_as_of: datetime,
        collected_at: datetime | None,
        price_provider: str,
        dividend: DividendContagionAnalysis,
    ) -> None:
        for code, label, value, method in (
            (
                "DIVIDEND_EQUAL_RETURN",
                "확정 배당주 동일가중 수익률",
                dividend.dividend_equal_weighted_return,
                "기준일 이전 확정 DPS 종목의 기간수익률 산술평균",
            ),
            (
                "DIVIDEND_RELATIVE_TO_KOSPI",
                "배당주 KOSPI 대비 상대수익률",
                dividend.relative_to_kospi,
                "배당주 동일가중 수익률 - KOSPI 수익률",
            ),
            (
                "DIVIDEND_RELATIVE_TO_NONSEMICONDUCTOR",
                "배당주 비반도체 대비 상대수익률",
                dividend.relative_to_non_semiconductor,
                "배당주 동일가중 수익률 - 비반도체 동일가중 수익률",
            ),
        ):
            MarketMetricBuilder._append(
                metrics,
                index_as_of=index_as_of,
                code=code,
                label=label,
                value=value,
                unit="rate",
                source_provider=(
                    f"OpenDART·{price_provider}" if value is not None else None
                ),
                source_function="DividendContagionAnalyzer",
                collected_at=collected_at,
                method=method,
                quality=(
                    "CALCULATED_CONFIRMED_DIVIDEND_SAMPLE"
                    if value is not None
                    else "MISSING"
                ),
                source_kind=SourceKind.SELF_CALCULATED,
            )

    @staticmethod
    def _append(
        metrics: list[MetricEvidence],
        *,
        index_as_of: datetime,
        code: str,
        label: str,
        value: Decimal | None = None,
        text: str | None = None,
        unit: str | None = None,
        source_provider: str | None,
        source_function: str | None,
        collected_at: datetime | None,
        method: str,
        quality: str,
        source_kind: SourceKind,
        data_timing: DataTiming = DataTiming.PREVIOUS_CLOSE,
        proxy: ProxyKind = ProxyKind.NOT_APPLICABLE,
    ) -> None:
        state = (
            DataState.AVAILABLE
            if value is not None or text is not None
            else DataState.MISSING
        )
        metrics.append(
            MetricEvidence(
                code=code,
                label=label,
                state=state,
                value=value,
                text_value=text,
                unit=unit,
                source_provider=source_provider,
                source_function=source_function,
                as_of_at=index_as_of,
                collected_at=collected_at,
                calculation_method=method,
                data_quality=quality,
                data_timing=(
                    data_timing if state == DataState.AVAILABLE else DataTiming.UNKNOWN
                ),
                source_kind=source_kind,
                proxy_kind=proxy,
            )
        )
