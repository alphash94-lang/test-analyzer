from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import (
    BreadthAnalysis,
    DividendContagionAnalysis,
    IndexPoint,
    Phase3AnalysisResult,
    ProxyKind,
    SemiconductorAnalysis,
)
from app.models.metadata import DataState
from app.repositories.market_analysis_repository import MarketAnalysisRepository
from app.repositories.phase3_input_repository import (
    Phase3InputBundle,
    Phase3InputRepository,
)
from app.services.dividend_contagion_analyzer import DividendContagionAnalyzer
from app.services.market_metric_builder import MarketMetricBuilder
from app.services.market_shock_analyzer import MarketShockAnalyzer
from app.services.semiconductor_contribution_analyzer import (
    SemiconductorContributionAnalyzer,
)


class MarketRegimeService:
    def __init__(
        self,
        settings: Settings,
        *,
        inputs: Phase3InputRepository | None = None,
        repository: MarketAnalysisRepository | None = None,
    ) -> None:
        self._settings = settings
        self._inputs = inputs or Phase3InputRepository(settings)
        self._repository = repository or MarketAnalysisRepository()
        self._market = MarketShockAnalyzer(settings)
        self._semiconductors = SemiconductorContributionAnalyzer(settings)
        self._dividends = DividendContagionAnalyzer(settings)
        self._metric_builder = MarketMetricBuilder(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    def analyze_and_store(
        self,
        *,
        as_of_date: date,
        as_of_at: datetime,
    ) -> Phase3AnalysisResult:
        with self._sessions.begin() as session:
            bundle = self._inputs.load(
                session,
                as_of_date=as_of_date,
                as_of_at=as_of_at,
            )
            result = self._analyze(bundle, as_of_at=as_of_at)
            self._repository.save(session, result)
        return result

    def close(self) -> None:
        self._engine.dispose()

    def _analyze(
        self,
        bundle: Phase3InputBundle,
        *,
        as_of_at: datetime,
    ) -> Phase3AnalysisResult:
        points = bundle.index_points
        highs = self._market.calculate_highs(points)
        coverage = (
            Decimal(len(bundle.observations)) / Decimal(bundle.universe_size)
            if bundle.universe_size
            else None
        )
        classification_coverage = (
            Decimal(bundle.classification_count) / Decimal(len(bundle.observations))
            if bundle.observations
            else None
        )
        kospi_return = (
            points[-1].close
            / points[-(self._settings.phase3_return_lookback_days + 1)].close
            - Decimal(1)
            if len(points) >= self._settings.phase3_return_lookback_days + 1
            else None
        )
        breadth = self._market.calculate_breadth(bundle.observations)
        if (
            coverage is None
            or coverage < self._settings.phase3_minimum_constituent_coverage
        ):
            breadth = BreadthAnalysis(
                state=DataState.MISSING,
                sample_size=len(bundle.observations),
                reason=(
                    "검증된 수정가격 구성종목 커버리지가 설정 기준보다 "
                    "낮아 시장 폭을 확정하지 않았습니다."
                ),
            )
        official_window = self._official_semiconductor_window(bundle)
        analysis_proxy_kind = bundle.proxy_kind
        if analysis_proxy_kind == ProxyKind.OFFICIAL_INDEX and official_window is None:
            configured_codes = {
                value.strip()
                for value in (
                    self._settings.phase3_semiconductor_classification_codes
                ).split(",")
                if value.strip()
            }
            analysis_proxy_kind = (
                ProxyKind.SELF_CALCULATED_PROXY
                if configured_codes and bundle.classification_count
                else ProxyKind.NOT_AVAILABLE
            )
        semiconductor = self._semiconductors.analyze(
            bundle.observations,
            proxy_kind=analysis_proxy_kind,
        )
        if (
            classification_coverage is None
            or classification_coverage
            < self._settings.phase3_minimum_constituent_coverage
        ):
            semiconductor = SemiconductorAnalysis(
                state=DataState.MISSING,
                proxy_kind=bundle.proxy_kind,
                reason=(
                    "공식 산업분류 커버리지가 설정 기준보다 낮아 "
                    "반도체·비반도체 결과를 확정하지 않았습니다."
                ),
            )
        if (
            semiconductor.state == DataState.AVAILABLE
            and analysis_proxy_kind == ProxyKind.OFFICIAL_INDEX
            and official_window is not None
        ):
            official_start, official_end = official_window
            semiconductor = semiconductor.model_copy(
                update={
                    "cap_weighted_return": (
                        official_end.close / official_start.close - Decimal(1)
                    ),
                    "reason": (
                        "공식 반도체 지수 수익률을 우선 사용했습니다. "
                        "동일가중·비반도체·종목 기여도는 공식 산업분류 "
                        "구성종목으로 자체 계산했습니다."
                    ),
                }
            )
        dividend = self._dividends.analyze(
            bundle.observations,
            kospi_return=kospi_return,
            non_semiconductor_return=(
                semiconductor.non_semiconductor_equal_weighted_return
            ),
        )
        shock = self._market.classify_shock(
            kospi_return=kospi_return,
            breadth=breadth,
            semiconductor=semiconductor,
        )
        (
            regime,
            semiconductor_recovery,
            kospi_recovery,
            non_semiconductor_breadth,
            dividend_recovery,
        ) = self._market.classify_regime(
            index_points=points,
            highs=highs,
            breadth=breadth,
            semiconductor=semiconductor,
            dividend=dividend,
        )
        confidence = self._confidence(
            index_count=len(points),
            coverage=coverage,
            classification_coverage=classification_coverage,
            dividend=dividend,
        )
        missing = self._missing_core_data(
            highs=highs,
            coverage=coverage,
            breadth=breadth,
            semiconductor=semiconductor,
            dividend=dividend,
        )
        state = DataState.AVAILABLE if not missing else DataState.MISSING
        input_hash = self._input_hash(bundle)
        metrics = self._metric_builder.build(
            bundle=bundle,
            as_of_at=as_of_at,
            highs=highs,
            kospi_return=kospi_return,
            breadth=breadth,
            semiconductor=semiconductor,
            dividend=dividend,
            shock=shock.value,
            regime=regime.value,
            confidence=confidence,
            semiconductor_recovery=semiconductor_recovery,
            kospi_recovery=kospi_recovery,
            non_semiconductor_breadth=non_semiconductor_breadth,
            dividend_recovery=dividend_recovery,
        )
        explanation = (
            "핵심 데이터가 부족해 시장충격 또는 시장국면을 확정하지 않았습니다: "
            + ", ".join(missing)
            if missing
            else (
                "설정된 임계값과 동일 입력 해시로 시장충격·시장 폭·반도체 "
                "기여도·배당주 상대강도를 재현 가능하게 계산했습니다. "
                "기여도는 인과관계가 아니라 전일 시가총액 비중 기반 설명 추정치입니다."
            )
        )
        return Phase3AnalysisResult(
            state=state,
            as_of_at=as_of_at,
            rule_version=self._settings.phase3_rule_version,
            input_data_hash=input_hash,
            shock_classification=shock,
            market_regime=regime,
            data_confidence=confidence,
            proxy_kind=semiconductor.proxy_kind,
            semiconductor_recovery=semiconductor_recovery,
            kospi_recovery=kospi_recovery,
            non_semiconductor_breadth=non_semiconductor_breadth,
            dividend_relative_strength_recovery=dividend_recovery,
            missing_core_data=tuple(missing),
            explanation=explanation,
            metrics=tuple(metrics),
            contributions=semiconductor.contributions,
        )

    def _official_semiconductor_window(
        self,
        bundle: Phase3InputBundle,
    ) -> tuple[IndexPoint, IndexPoint] | None:
        required = self._settings.phase3_return_lookback_days + 1
        if (
            bundle.proxy_kind != ProxyKind.OFFICIAL_INDEX
            or len(bundle.index_points) < required
            or len(bundle.official_semiconductor_index_points) < required
        ):
            return None
        start_date = bundle.index_points[-required].trade_date
        end_date = bundle.index_points[-1].trade_date
        official_by_date = {
            point.trade_date: point
            for point in bundle.official_semiconductor_index_points
        }
        start = official_by_date.get(start_date)
        end = official_by_date.get(end_date)
        if start is None or end is None:
            return None
        return start, end

    def _confidence(
        self,
        *,
        index_count: int,
        coverage: Decimal | None,
        classification_coverage: Decimal | None,
        dividend: DividendContagionAnalysis,
    ) -> Decimal | None:
        if index_count == 0 and coverage is None:
            return None
        index_ratio = min(
            Decimal(index_count) / Decimal(self._settings.phase3_index_history_days),
            Decimal(1),
        )
        coverage_ratio = min(coverage or Decimal(0), Decimal(1))
        classification_ratio = min(
            classification_coverage or Decimal(0),
            Decimal(1),
        )
        dividend_ratio = min(
            Decimal(dividend.sample_size)
            / Decimal(self._settings.phase3_minimum_dividend_sample),
            Decimal(1),
        )
        return (
            index_ratio * Decimal(30)
            + coverage_ratio * Decimal(30)
            + classification_ratio * Decimal(25)
            + dividend_ratio * Decimal(15)
        ).quantize(Decimal("0.001"))

    def _missing_core_data(
        self,
        *,
        highs: Mapping[int, object],
        coverage: Decimal | None,
        breadth: BreadthAnalysis,
        semiconductor: SemiconductorAnalysis,
        dividend: DividendContagionAnalysis,
    ) -> list[str]:
        missing: list[str] = []
        if {21, 63, 126, 252} - set(highs):
            missing.append("KOSPI 252거래일 지수 이력")
        if (
            coverage is None
            or coverage < self._settings.phase3_minimum_constituent_coverage
        ):
            missing.append("검증된 수정가격 KOSPI 구성종목 커버리지")
        if breadth.state != DataState.AVAILABLE:
            missing.append("시장 폭 20일선·60일선 입력")
        if semiconductor.state != DataState.AVAILABLE:
            missing.append("공식 분류 기반 반도체 구성종목·기여도")
        if dividend.state != DataState.AVAILABLE:
            missing.append("확정 DPS 배당주 표본")
        return missing

    def _input_hash(self, bundle: Phase3InputBundle) -> str:
        payload = {
            "rule_version": self._settings.phase3_rule_version,
            "thresholds": {
                "kospi_index_name": self._settings.phase3_kospi_index_name,
                "official_semiconductor_index_name": (
                    self._settings.phase3_official_semiconductor_index_name
                ),
                "adjusted_price_provider": (
                    self._settings.phase3_adjusted_price_provider
                ),
                "classification_system": (
                    self._settings.phase3_semiconductor_classification_system
                ),
                "classification_codes": sorted(
                    value.strip()
                    for value in (
                        self._settings.phase3_semiconductor_classification_codes
                    ).split(",")
                    if value.strip()
                ),
                "return_days": self._settings.phase3_return_lookback_days,
                "index_history_days": (self._settings.phase3_index_history_days),
                "minimum_constituents": (self._settings.phase3_minimum_constituents),
                "minimum_semiconductor_sample": (
                    self._settings.phase3_minimum_semiconductor_sample
                ),
                "minimum_dividend_sample": (
                    self._settings.phase3_minimum_dividend_sample
                ),
                "minimum_constituent_coverage": str(
                    self._settings.phase3_minimum_constituent_coverage
                ),
                "semiconductor_share": str(
                    self._settings.phase3_semiconductor_contribution_share
                ),
                "semiconductor_underperformance": str(
                    self._settings.phase3_semiconductor_underperformance
                ),
                "broad_decline_ratio": str(self._settings.phase3_broad_decline_ratio),
                "broad_median_return": str(self._settings.phase3_broad_median_return),
                "red_drawdown": str(self._settings.phase3_red_drawdown),
                "red_advancing_ratio": str(self._settings.phase3_red_advancing_ratio),
                "yellow_breadth20": str(self._settings.phase3_yellow_breadth20),
                "green_breadth20": str(self._settings.phase3_green_breadth20),
                "green_breadth60": str(self._settings.phase3_green_breadth60),
                "stabilization_days": (self._settings.phase3_stabilization_days),
                "samsung_symbol": self._settings.phase3_samsung_symbol,
                "sk_hynix_symbol": self._settings.phase3_sk_hynix_symbol,
            },
            "bundle": {
                "universe_size": bundle.universe_size,
                "classification_count": bundle.classification_count,
                "proxy_kind": bundle.proxy_kind.value,
            },
            "indexes": [
                {
                    "date": point.trade_date.isoformat(),
                    "close": str(point.close),
                    "source": point.source_provider,
                    "function": point.source_function,
                    "collected_at": point.collected_at.isoformat(),
                }
                for point in bundle.index_points
            ],
            "official_semiconductor_indexes": [
                {
                    "date": point.trade_date.isoformat(),
                    "close": str(point.close),
                    "source": point.source_provider,
                    "function": point.source_function,
                    "collected_at": point.collected_at.isoformat(),
                }
                for point in bundle.official_semiconductor_index_points
            ],
            "constituents": [
                {
                    "stock_id": item.stock_id,
                    "symbol": item.symbol,
                    "name": item.name,
                    "start_date": item.start_date.isoformat(),
                    "previous_date": item.previous_date.isoformat(),
                    "as_of_date": item.as_of_date.isoformat(),
                    "start": str(item.start_close),
                    "previous": str(item.previous_close),
                    "close": str(item.close),
                    "start_market_cap": str(item.start_market_cap),
                    "previous_market_cap": str(item.previous_market_cap),
                    "close_history": [str(value) for value in item.close_history],
                    "semiconductor": item.is_semiconductor,
                    "classification_source": item.classification_source,
                    "dividend": item.is_confirmed_dividend_payer,
                    "price_source": item.price_source_provider,
                    "market_cap_source": item.market_cap_source_provider,
                    "collected_at": item.collected_at.isoformat(),
                }
                for item in sorted(
                    bundle.observations,
                    key=lambda observation: observation.symbol,
                )
            ],
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
