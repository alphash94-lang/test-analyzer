from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.price import LatestDailyPrice, PriceRefreshSummary
from app.providers.base import ApiResponse
from app.providers.krx_price import (
    KRX_DAILY_PRICE_ENDPOINT,
    KRX_DAILY_PRICE_FUNCTION,
    KrxDailyPriceProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.utils.dates import now_kst


class PriceService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: KrxDailyPriceProvider | None = None,
        repository: PriceRepository | None = None,
    ) -> None:
        self._quality = DataQualityRepository()
        self._provider = provider or KrxDailyPriceProvider(settings)
        self._prices = repository or PriceRepository(self._quality)
        self._raw = RawResponseRepository(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, as_of_date: date) -> PriceRefreshSummary:
        started_at = now_kst()
        response = await self._provider.fetch(as_of_date=as_of_date)
        errors = (response.error_message,) if response.error_message is not None else ()
        with self._sessions.begin() as session:
            self._save_raw(session, as_of_date, response)
            if response.state != DataState.AVAILABLE or response.payload is None:
                self._quality.add(
                    session,
                    entity_type="price_refresh",
                    entity_id=as_of_date.isoformat(),
                    provider="KRX",
                    issue_code=response.state.value,
                    severity="ERROR",
                    data_state=response.state,
                    message=(
                        response.error_message or "KRX 일별가격을 사용할 수 없습니다."
                    ),
                )
                return PriceRefreshSummary(
                    state=response.state.value,
                    started_at=started_at,
                    finished_at=now_kst(),
                    as_of_date=as_of_date,
                    errors=errors,
                )
            stored, unmatched = self._prices.upsert_krx_records(
                session,
                response.payload,
                as_of_at=(response.metadata.as_of_at or response.metadata.collected_at),
                collected_at=response.metadata.collected_at,
            )
        return PriceRefreshSummary(
            state=DataState.AVAILABLE.value,
            started_at=started_at,
            finished_at=now_kst(),
            as_of_date=as_of_date,
            received=len(response.payload),
            stored=stored,
            unmatched=unmatched,
            errors=errors,
        )

    def latest_for_symbols(
        self,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        with self._sessions() as session:
            return self._prices.latest_for_symbols(session, symbols)

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
            function_name=KRX_DAILY_PRICE_FUNCTION,
            endpoint=KRX_DAILY_PRICE_ENDPOINT,
            request_parameters={"basDd": as_of_date.strftime("%Y%m%d")},
            response=response,
        )
