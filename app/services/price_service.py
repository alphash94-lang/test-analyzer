from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.price import LatestDailyPrice, PriceRefreshSummary
from app.providers.base import ApiResponse
from app.providers.kis_reference import (
    KIS_ADJUSTED_PRICE_ENDPOINT,
    KIS_ADJUSTED_PRICE_FUNCTION,
    KisReferenceProvider,
)
from app.providers.krx_price import (
    KRX_DAILY_PRICE_ENDPOINT,
    KrxDailyPriceProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.utils.dates import now_kst
from app.utils.technical_indicators import AdjustedPricePoint


@dataclass(frozen=True)
class CurrentStockQuote:
    symbol: str
    as_of_at: datetime
    price: Decimal
    previous_day_change: Decimal | None
    change_rate: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    volume: Decimal | None
    trading_value: Decimal | None
    per: Decimal | None
    pbr: Decimal | None
    industry_name: str | None
    forward_per: Decimal | None = None
    forward_eps: Decimal | None = None
    forward_period: str | None = None
    source_provider: str = "한국투자증권"


class PriceService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: KrxDailyPriceProvider | None = None,
        kosdaq_provider: KrxDailyPriceProvider | None = None,
        kis_provider: KisReferenceProvider | None = None,
        repository: PriceRepository | None = None,
    ) -> None:
        self._quality = DataQualityRepository()
        self._providers = (
            (provider,)
            if provider is not None and kosdaq_provider is None
            else (
                provider
                or KrxDailyPriceProvider(settings, market="KOSPI"),
                kosdaq_provider
                or KrxDailyPriceProvider(settings, market="KOSDAQ"),
            )
        )
        self._kis = kis_provider or KisReferenceProvider(settings)
        self._prices = repository or PriceRepository(self._quality)
        self._raw = RawResponseRepository(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, as_of_date: date) -> PriceRefreshSummary:
        started_at = now_kst()
        responses = [
            await provider.fetch(as_of_date=as_of_date)
            for provider in self._providers
        ]
        errors = tuple(
            f"{response.metadata.function_name}: {response.error_message}"
            for response in responses
            if response.state != DataState.AVAILABLE
            and response.error_message is not None
        )
        received = 0
        stored = 0
        unmatched = 0
        available_count = 0
        with self._sessions.begin() as session:
            for response in responses:
                self._save_raw(session, as_of_date, response)
                if (
                    response.state == DataState.AVAILABLE
                    and response.payload is not None
                ):
                    available_count += 1
                    received += len(response.payload)
                    market_stored, market_unmatched = (
                        self._prices.upsert_krx_records(
                            session,
                            response.payload,
                            as_of_at=(
                                response.metadata.as_of_at
                                or response.metadata.collected_at
                            ),
                            collected_at=response.metadata.collected_at,
                        )
                    )
                    stored += market_stored
                    unmatched += market_unmatched
                    continue
                self._quality.add(
                    session,
                    entity_type="price_refresh",
                    entity_id=(
                        f"{as_of_date.isoformat()}:"
                        f"{response.metadata.function_name}"
                    ),
                    provider="KRX",
                    issue_code=response.state.value,
                    severity="ERROR",
                    data_state=response.state,
                    message=(
                        response.error_message
                        or "KRX 일별가격을 사용할 수 없습니다."
                    ),
                )
        if available_count == 0:
            state = responses[0].state.value
        elif available_count == len(responses):
            state = DataState.AVAILABLE.value
        else:
            state = "PARTIAL"
        return PriceRefreshSummary(
            state=state,
            started_at=started_at,
            finished_at=now_kst(),
            as_of_date=as_of_date,
            received=received,
            stored=stored,
            unmatched=unmatched,
            errors=errors,
        )

    async def refresh_adjusted_history(
        self,
        *,
        symbol: str,
        as_of_date: date,
        lookback_days: int = 420,
    ) -> PriceRefreshSummary:
        if lookback_days < 1:
            raise ValueError("lookback_days must be positive")
        started_at = now_kst()
        first_date = as_of_date - timedelta(days=lookback_days)
        window_end = as_of_date
        received = 0
        stored = 0
        errors: list[str] = []
        states: list[DataState] = []
        while window_end >= first_date:
            window_start = max(first_date, window_end - timedelta(days=99))
            response = await self._kis.fetch_adjusted_daily_prices(
                symbol=symbol,
                begin_date=window_start,
                end_date=window_end,
            )
            states.append(response.state)
            with self._sessions.begin() as session:
                self._raw.save(
                    session,
                    provider="한국투자증권",
                    function_name=KIS_ADJUSTED_PRICE_FUNCTION,
                    endpoint=KIS_ADJUSTED_PRICE_ENDPOINT,
                    request_parameters={
                        "symbol": symbol,
                        "begin_date": window_start.isoformat(),
                        "end_date": window_end.isoformat(),
                        "period": "D",
                        "adjusted": True,
                    },
                    response=response,
                )
                if (
                    response.state == DataState.AVAILABLE
                    and response.payload is not None
                ):
                    received += len(response.payload)
                    stored += self._prices.upsert_kis_adjusted_records(
                        session,
                        symbol,
                        response.payload,
                        as_of_at=(
                            response.metadata.as_of_at
                            or response.metadata.collected_at
                        ),
                        collected_at=response.metadata.collected_at,
                    )
                elif response.state != DataState.MISSING:
                    errors.append(
                        response.error_message
                        or f"KIS adjusted price failed: {response.state.value}"
                    )
            window_end = window_start - timedelta(days=1)
        state = (
            DataState.AVAILABLE
            if stored
            else (
                DataState.NOT_CONFIGURED
                if states and all(item == DataState.NOT_CONFIGURED for item in states)
                else DataState.FETCH_FAILED
            )
        )
        return PriceRefreshSummary(
            state=state.value,
            started_at=started_at,
            finished_at=now_kst(),
            as_of_date=as_of_date,
            received=received,
            stored=stored,
            errors=tuple(errors),
        )

    def latest_for_symbols(
        self,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        with self._sessions() as session:
            return self._prices.latest_for_symbols(session, symbols)

    def latest_adjusted_for_symbols(
        self,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        with self._sessions() as session:
            return self._prices.latest_adjusted_for_symbols(session, symbols)

    def history_for_symbol(
        self,
        symbol: str,
        *,
        limit: int = 260,
    ) -> list[AdjustedPricePoint]:
        with self._sessions() as session:
            return self._prices.history_for_symbol(
                session,
                symbol,
                limit=limit,
            )

    async def current_quote_for_symbol(
        self,
        symbol: str,
    ) -> CurrentStockQuote | None:
        response, forward_response = await asyncio.gather(
            self._kis.fetch_current_valuation(symbol=symbol),
            self._kis.fetch_forward_valuation(
                symbol=symbol,
                as_of_date=now_kst().date(),
            ),
        )
        if response.state != DataState.AVAILABLE or not response.payload:
            return None
        item = response.payload[0]
        forward = (
            forward_response.payload
            if forward_response.state == DataState.AVAILABLE
            else None
        )
        return CurrentStockQuote(
            symbol=symbol,
            as_of_at=response.metadata.collected_at,
            price=item.current_price,
            previous_day_change=item.previous_day_change,
            change_rate=item.change_rate,
            open_price=item.open_price,
            high_price=item.high_price,
            low_price=item.low_price,
            volume=item.volume,
            trading_value=item.trading_value,
            per=item.per,
            pbr=item.pbr,
            industry_name=item.industry_name,
            forward_per=(
                item.current_price / forward.forward_eps
                if forward is not None
                else None
            ),
            forward_eps=forward.forward_eps if forward is not None else None,
            forward_period=(
                forward.fiscal_period if forward is not None else None
            ),
        )

    def close(self) -> None:
        self._engine.dispose()

    def _save_raw(
        self,
        session: Session,
        as_of_date: date,
        response: ApiResponse[Any],
    ) -> None:
        self._raw.save(
            session,
            provider="KRX",
            function_name=response.metadata.function_name,
            endpoint=str(
                response.metadata.source_url or KRX_DAILY_PRICE_ENDPOINT
            ),
            request_parameters={"basDd": as_of_date.strftime("%Y%m%d")},
            response=response,
        )
