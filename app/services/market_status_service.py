from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import Select, select

from app.config import Settings
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.kind_market_status import (
    KIND_DELISTING_REVIEW_ENDPOINT,
    KIND_DELISTING_REVIEW_FUNCTION,
    KIND_MANAGEMENT_ENDPOINT,
    KIND_MANAGEMENT_FUNCTION,
    KIND_TRADING_HALT_ENDPOINT,
    KIND_TRADING_HALT_FUNCTION,
    KindMarketStatusProvider,
)
from app.repositories.market_status_repository import MarketStatusRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.utils.dates import SEOUL, now_kst


@dataclass(frozen=True)
class MarketStatusRefreshSummary:
    symbol: str
    state: DataState
    statuses: dict[str, str]
    errors: tuple[str, ...]


class MarketStatusService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: KindMarketStatusProvider | None = None,
    ) -> None:
        self._provider = provider or KindMarketStatusProvider(settings)
        self._raw = RawResponseRepository(settings)
        self._statuses = MarketStatusRepository()
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(
        self,
        *,
        symbol: str,
        as_of_date: date,
    ) -> MarketStatusRefreshSummary:
        if as_of_date > now_kst().date():
            raise ValueError("as_of_date must not be in the future")
        with self._sessions() as session:
            stock = session.scalar(self._stock_query(symbol))
            if stock is None:
                return MarketStatusRefreshSummary(
                    symbol=symbol,
                    state=DataState.MISSING,
                    statuses={},
                    errors=("종목 레코드를 찾을 수 없습니다.",),
                )
            stock_id = stock.id
            names = tuple(
                dict.fromkeys(
                    name
                    for name in (stock.abbreviated_name, stock.name_ko)
                    if name
                )
            )

        calls = (
            (
                "MANAGEMENT_STATUS",
                await self._provider.fetch_management_issue(
                    symbol=symbol,
                    stock_names=names,
                ),
                KIND_MANAGEMENT_FUNCTION,
                KIND_MANAGEMENT_ENDPOINT,
                {"repIsuSrtCd": symbol, "marketType": "1"},
                ("MANAGEMENT", "NORMAL"),
            ),
            (
                "TRADING_STATUS",
                await self._provider.fetch_trading_halt(
                    symbol=symbol,
                    stock_names=names,
                ),
                KIND_TRADING_HALT_FUNCTION,
                KIND_TRADING_HALT_ENDPOINT,
                {"repIsuSrtCd": symbol, "marketType": "1"},
                ("SUSPENDED", "NORMAL"),
            ),
            (
                "DELISTING_RISK",
                await self._provider.fetch_delisting_review(symbol=symbol),
                KIND_DELISTING_REVIEW_FUNCTION,
                KIND_DELISTING_REVIEW_ENDPOINT,
                {"marketType": "1", "ProgDelistType": "1"},
                ("RISK", "CLEAR"),
            ),
        )
        effective_from = datetime.combine(as_of_date, time.min, tzinfo=SEOUL)
        statuses: dict[str, str] = {}
        errors: list[str] = []
        states: list[DataState] = []
        for (
            status_type,
            response,
            function_name,
            endpoint,
            parameters,
            values,
        ) in calls:
            states.append(response.state)
            self._save_raw(
                response=response,
                function_name=function_name,
                endpoint=endpoint,
                parameters=parameters,
            )
            if response.state == DataState.AVAILABLE:
                value = values[0] if response.payload else values[1]
                statuses[status_type] = value
                with self._sessions.begin() as session:
                    self._statuses.upsert_daily(
                        session,
                        stock_id=stock_id,
                        status_type=status_type,
                        status_value=value,
                        effective_from=effective_from,
                        source_provider="KIND",
                        source_function=function_name,
                        collected_at=response.metadata.collected_at,
                    )
            else:
                errors.append(
                    response.error_message or f"{function_name} 조회에 실패했습니다."
                )
        state = (
            DataState.AVAILABLE
            if states and all(item == DataState.AVAILABLE for item in states)
            else DataState.FETCH_FAILED
        )
        return MarketStatusRefreshSummary(
            symbol=symbol,
            state=state,
            statuses=statuses,
            errors=tuple(errors),
        )

    def _save_raw(
        self,
        *,
        response: ApiResponse[bool],
        function_name: str,
        endpoint: str,
        parameters: dict[str, str],
    ) -> None:
        with self._sessions.begin() as session:
            self._raw.save(
                session,
                provider="KIND",
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=parameters,
                response=response,
            )

    @staticmethod
    def _stock_query(symbol: str) -> Select[tuple[Stock]]:
        return select(Stock).where(Stock.symbol == symbol)

    def close(self) -> None:
        self._engine.dispose()
