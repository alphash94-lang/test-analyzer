from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select

from app.config import Settings
from app.db.models.market import PriceDaily, Stock, StockClassification
from app.db.models.market_analysis import IndexDaily
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.kis_master import (
    KIS_KOSPI_MASTER_ENDPOINT,
    KIS_KOSPI_MASTER_FUNCTION,
    KisKospiMasterProvider,
)
from app.providers.krx_index import (
    KRX_KOSPI_INDEX_ENDPOINT,
    KRX_KOSPI_INDEX_FUNCTION,
    KrxIndexDailyProvider,
)
from app.providers.krx_price import (
    KRX_DAILY_PRICE_ENDPOINT,
    KRX_DAILY_PRICE_FUNCTION,
    KrxDailyPriceProvider,
)
from app.repositories.index_repository import IndexRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.repositories.stock_repository import StockRepository


@dataclass(frozen=True)
class Phase3DataRefreshSummary:
    state: DataState
    as_of_date: date
    classifications_stored: int
    index_dates: int
    price_dates: int
    errors: tuple[str, ...]


class Phase3DataService:
    def __init__(
        self,
        settings: Settings,
        *,
        master_provider: KisKospiMasterProvider | None = None,
        index_provider: KrxIndexDailyProvider | None = None,
        price_provider: KrxDailyPriceProvider | None = None,
    ) -> None:
        self._settings = settings
        self._master = master_provider or KisKospiMasterProvider(settings)
        self._index_provider = index_provider or KrxIndexDailyProvider(settings)
        self._price_provider = price_provider or KrxDailyPriceProvider(settings)
        self._raw = RawResponseRepository(settings)
        self._stocks = StockRepository()
        self._indexes = IndexRepository()
        self._prices = PriceRepository()
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, *, as_of_date: date) -> Phase3DataRefreshSummary:
        classifications, master_errors = await self._refresh_classifications()
        errors = list(master_errors)
        required_index_dates = self._settings.phase3_index_history_days
        required_price_dates = max(
            61,
            self._settings.phase3_return_lookback_days + 1,
        )
        trading_dates: list[date] = []
        candidate = as_of_date
        max_calendar_days = required_index_dates * 2 + 30
        for _ in range(max_calendar_days):
            include_prices = len(trading_dates) < required_price_dates
            has_index = await self._ensure_history_date(
                candidate,
                include_prices=include_prices,
                errors=errors,
            )
            if has_index:
                trading_dates.append(candidate)
            if len(trading_dates) >= required_index_dates:
                break
            candidate -= timedelta(days=1)
        index_dates = len(trading_dates)
        price_dates = sum(
            self._has_continuity_prices(value)
            for value in trading_dates[:required_price_dates]
        )
        state = (
            DataState.AVAILABLE
            if classifications > 0
            and index_dates >= required_index_dates
            and price_dates >= required_price_dates
            else DataState.MISSING
        )
        return Phase3DataRefreshSummary(
            state=state,
            as_of_date=as_of_date,
            classifications_stored=classifications,
            index_dates=index_dates,
            price_dates=price_dates,
            errors=tuple(dict.fromkeys(errors)),
        )

    async def refresh_window(
        self,
        *,
        as_of_date: date,
        offset_days: int,
        calendar_days: int = 30,
        recent_price_calendar_days: int = 120,
    ) -> Phase3DataRefreshSummary:
        """Persist one bounded calendar window of Phase 3 history."""

        if offset_days < 0:
            raise ValueError("offset_days must be non-negative")
        if calendar_days < 1:
            raise ValueError("calendar_days must be positive")

        classifications = 0
        errors: list[str] = []
        if offset_days == 0:
            classifications, master_errors = await self._refresh_classifications()
            errors.extend(master_errors)

        trading_dates: list[date] = []
        price_dates = 0
        include_prices = offset_days < recent_price_calendar_days
        candidate = as_of_date - timedelta(days=offset_days)
        for _ in range(calendar_days):
            has_index = await self._ensure_history_date(
                candidate,
                include_prices=include_prices,
                errors=errors,
            )
            if has_index:
                trading_dates.append(candidate)
                if include_prices and self._has_continuity_prices(candidate):
                    price_dates += 1
            candidate -= timedelta(days=1)

        state = (
            DataState.AVAILABLE
            if trading_dates
            and (not include_prices or price_dates == len(trading_dates))
            else DataState.MISSING
        )
        return Phase3DataRefreshSummary(
            state=state,
            as_of_date=as_of_date,
            classifications_stored=classifications,
            index_dates=len(trading_dates),
            price_dates=price_dates,
            errors=tuple(dict.fromkeys(errors)),
        )

    async def _ensure_history_date(
        self,
        trade_date: date,
        *,
        include_prices: bool,
        errors: list[str],
    ) -> bool:
        has_index = self._has_index(trade_date)
        if not has_index:
            response = await self._index_provider.fetch(as_of_date=trade_date)
            self._save_raw(
                provider="KRX",
                function_name=KRX_KOSPI_INDEX_FUNCTION,
                endpoint=KRX_KOSPI_INDEX_ENDPOINT,
                parameters={"basDd": trade_date.strftime("%Y%m%d")},
                response=response,
            )
            if response.state == DataState.AVAILABLE and response.payload:
                with self._sessions.begin() as session:
                    self._indexes.upsert_krx_records(
                        session,
                        response.payload,
                        as_of_at=(
                            response.metadata.as_of_at
                            or response.metadata.collected_at
                        ),
                        collected_at=response.metadata.collected_at,
                    )
                has_index = self._has_index(trade_date)
            elif response.state not in {DataState.MISSING}:
                errors.append(
                    response.error_message or f"{trade_date} KRX 지수 조회 실패"
                )

        if (
            has_index
            and include_prices
            and not self._has_continuity_prices(trade_date)
        ):
            price_response = await self._price_provider.fetch(
                as_of_date=trade_date
            )
            self._save_raw(
                provider="KRX",
                function_name=KRX_DAILY_PRICE_FUNCTION,
                endpoint=KRX_DAILY_PRICE_ENDPOINT,
                parameters={"basDd": trade_date.strftime("%Y%m%d")},
                response=price_response,
            )
            if price_response.state == DataState.AVAILABLE and price_response.payload:
                with self._sessions.begin() as session:
                    self._prices.upsert_krx_records(
                        session,
                        price_response.payload,
                        as_of_at=(
                            price_response.metadata.as_of_at
                            or price_response.metadata.collected_at
                        ),
                        collected_at=price_response.metadata.collected_at,
                    )
            else:
                errors.append(
                    price_response.error_message
                    or f"{trade_date} KRX 종목가격 조회 실패"
                )
        return has_index

    async def _refresh_classifications(self) -> tuple[int, list[str]]:
        response = await self._master.fetch()
        self._save_raw(
            provider="한국투자증권",
            function_name=KIS_KOSPI_MASTER_FUNCTION,
            endpoint=KIS_KOSPI_MASTER_ENDPOINT,
            parameters={},
            response=response,
        )
        if response.state != DataState.AVAILABLE or response.payload is None:
            return 0, [
                response.error_message or "KIS KOSPI 종목마스터 조회 실패"
            ]
        with self._sessions.begin() as session:
            stocks = {
                stock.symbol: stock
                for stock in session.scalars(
                    select(Stock).where(Stock.is_active.is_(True))
                ).all()
            }
            as_of_at = (
                response.metadata.as_of_at or response.metadata.collected_at
            )
            stock_ids = [stock.id for stock in stocks.values()]
            existing_classifications = {
                (
                    row.stock_id,
                    row.classification_system,
                    row.classification_code,
                    row.valid_from,
                ): row
                for row in session.scalars(
                    select(StockClassification).where(
                        StockClassification.stock_id.in_(stock_ids),
                        StockClassification.classification_system
                        == "KIS_SEMICONDUCTOR_FLAG",
                        StockClassification.valid_from == as_of_at.date(),
                    )
                ).all()
                if row.valid_from is not None
            }
            stored = 0
            for item in response.payload:
                stock = stocks.get(item.symbol)
                if stock is None:
                    continue
                self._stocks.upsert_kis_semiconductor_flag(
                    session,
                    stock=stock,
                    flag=item.semiconductor_flag,
                    as_of_at=as_of_at,
                    collected_at=response.metadata.collected_at,
                    existing_rows=existing_classifications,
                )
                stored += 1
        return stored, []

    def _has_index(self, trade_date: date) -> bool:
        with self._sessions() as session:
            return (
                session.scalar(
                    select(func.count(IndexDaily.id)).where(
                        IndexDaily.index_name
                        == self._settings.phase3_kospi_index_name,
                        IndexDaily.trade_date == trade_date,
                        IndexDaily.source_provider == "KRX",
                        IndexDaily.data_state == DataState.AVAILABLE.value,
                    )
                )
                or 0
            ) > 0

    def _has_continuity_prices(self, trade_date: date) -> bool:
        with self._sessions() as session:
            return (
                session.scalar(
                    select(func.count(PriceDaily.id)).where(
                        PriceDaily.trade_date == trade_date,
                        PriceDaily.source_provider == "KRX",
                        PriceDaily.previous_day_change.is_not(None),
                        PriceDaily.data_state == DataState.AVAILABLE.value,
                    )
                )
                or 0
            ) >= self._settings.phase3_minimum_constituents

    def _save_raw[PayloadT](
        self,
        *,
        provider: str,
        function_name: str,
        endpoint: str,
        parameters: dict[str, object],
        response: ApiResponse[PayloadT],
    ) -> None:
        with self._sessions.begin() as session:
            self._raw.save(
                session,
                provider=provider,
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=parameters,
                response=response,
            )

    def close(self) -> None:
        dispose_db_engine(self._engine)
