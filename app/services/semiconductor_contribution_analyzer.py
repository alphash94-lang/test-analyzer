from __future__ import annotations

from decimal import Decimal
from statistics import median

from app.config import Settings
from app.models.market_analysis import (
    ConstituentObservation,
    ContributionEvidence,
    ProxyKind,
    SemiconductorAnalysis,
    SourceKind,
)
from app.models.metadata import DataState, DataTiming


def _weighted_return(
    observations: list[ConstituentObservation],
) -> Decimal:
    total_weight = sum(
        (item.start_market_cap for item in observations),
        Decimal(0),
    )
    return (
        sum(
            (
                item.start_market_cap * (item.close / item.start_close - Decimal(1))
                for item in observations
            ),
            Decimal(0),
        )
        / total_weight
    )


def _equal_return(
    observations: list[ConstituentObservation],
) -> Decimal:
    return sum(
        (item.close / item.start_close - Decimal(1) for item in observations),
        Decimal(0),
    ) / Decimal(len(observations))


class SemiconductorContributionAnalyzer:
    """Calculate transparent baskets and one-day market-cap contributions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def analyze(
        self,
        observations: list[ConstituentObservation],
        *,
        proxy_kind: ProxyKind,
    ) -> SemiconductorAnalysis:
        classified = [
            item for item in observations if item.is_semiconductor is not None
        ]
        semiconductors = [item for item in classified if item.is_semiconductor is True]
        non_semiconductors = [
            item for item in classified if item.is_semiconductor is False
        ]
        if (
            proxy_kind == ProxyKind.NOT_AVAILABLE
            or len(semiconductors) < self._settings.phase3_minimum_semiconductor_sample
            or not non_semiconductors
        ):
            return SemiconductorAnalysis(
                state=DataState.MISSING,
                proxy_kind=ProxyKind.NOT_AVAILABLE,
                reason=(
                    "공식 반도체 지수 또는 설정된 공식 산업분류 코드와 "
                    "충분한 구성종목이 없어 반도체 프록시를 계산할 수 없습니다."
                ),
            )

        total_previous_market_cap = sum(
            (item.previous_market_cap for item in observations),
            Decimal(0),
        )
        if total_previous_market_cap <= 0:
            return SemiconductorAnalysis(
                state=DataState.MISSING,
                proxy_kind=proxy_kind,
                reason="전일 시가총액이 없어 종목별 기여도를 계산할 수 없습니다.",
            )

        contributions = tuple(
            ContributionEvidence(
                stock_id=item.stock_id,
                symbol=item.symbol,
                name=item.name,
                return_rate=item.close / item.previous_close - Decimal(1),
                previous_weight=(item.previous_market_cap / total_previous_market_cap),
                contribution=(
                    item.previous_market_cap
                    / total_previous_market_cap
                    * (item.close / item.previous_close - Decimal(1))
                ),
                is_semiconductor=item.is_semiconductor,
                source_provider=item.price_source_provider,
                market_cap_source_provider=item.market_cap_source_provider,
                classification_source=item.classification_source,
                as_of_date=item.as_of_date,
                collected_at=item.collected_at,
                data_timing=DataTiming.PREVIOUS_CLOSE,
                calculation_method=(
                    "전일 전체 비교종목 시가총액 비중 × 당일 수정가격 수익률"
                ),
                data_quality="EXPLANATORY_ESTIMATE",
                source_kind=SourceKind.SELF_CALCULATED,
                proxy_kind=ProxyKind.SELF_CALCULATED_PROXY,
            )
            for item in observations
        )
        negative_total = sum(
            (
                contribution.contribution
                for contribution in contributions
                if contribution.contribution < 0
            ),
            Decimal(0),
        )
        semiconductor_contribution = sum(
            (
                contribution.contribution
                for contribution in contributions
                if contribution.is_semiconductor is True
            ),
            Decimal(0),
        )
        semiconductor_negative = sum(
            (
                contribution.contribution
                for contribution in contributions
                if contribution.is_semiconductor is True
                and contribution.contribution < 0
            ),
            Decimal(0),
        )
        negative_share = (
            abs(semiconductor_negative) / abs(negative_total)
            if negative_total < 0
            else None
        )

        contribution_by_symbol = {
            contribution.symbol: contribution.contribution
            for contribution in contributions
        }
        non_semiconductor_returns = [
            item.close / item.start_close - Decimal(1) for item in non_semiconductors
        ]
        return SemiconductorAnalysis(
            state=DataState.AVAILABLE,
            proxy_kind=proxy_kind,
            cap_weighted_return=_weighted_return(semiconductors),
            equal_weighted_return=_equal_return(semiconductors),
            non_semiconductor_cap_weighted_return=_weighted_return(non_semiconductors),
            non_semiconductor_equal_weighted_return=_equal_return(non_semiconductors),
            non_semiconductor_median_return=Decimal(median(non_semiconductor_returns)),
            semiconductor_negative_contribution_share=negative_share,
            semiconductor_contribution=semiconductor_contribution,
            samsung_contribution=contribution_by_symbol.get(
                self._settings.phase3_samsung_symbol
            ),
            sk_hynix_contribution=contribution_by_symbol.get(
                self._settings.phase3_sk_hynix_symbol
            ),
            contributions=contributions,
            reason=(
                "공식 산업분류 구성종목과 검증된 수정가격으로 자체 바스켓을 "
                "계산하고 전일 시가총액 비중으로 설명 기여도를 추정했습니다."
            ),
        )
