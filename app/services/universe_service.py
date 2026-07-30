from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.metadata import DataState
from app.models.stock import StockSearchResult, UniverseRefreshSummary
from app.providers.base import ApiResponse
from app.providers.dart import (
    DART_CORP_CODE_ENDPOINT,
    DART_CORP_CODE_FUNCTION,
    OpenDartProvider,
)
from app.providers.krx import (
    KRX_STOCK_MASTER_ENDPOINT,
    KRX_STOCK_MASTER_FUNCTION,
    KrxProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.repositories.stock_repository import StockRepository
from app.services.stock_classification import classify_krx_stock
from app.utils.dates import now_kst


class UniverseService:
    def __init__(
        self,
        settings: Settings,
        *,
        krx_provider: KrxProvider | None = None,
        dart_provider: OpenDartProvider | None = None,
        stock_repository: StockRepository | None = None,
    ) -> None:
        self._settings = settings
        self._krx = krx_provider or KrxProvider(settings)
        self._dart = dart_provider or OpenDartProvider(settings)
        self._quality = DataQualityRepository()
        self._stocks = stock_repository or StockRepository(self._quality)
        self._raw = RawResponseRepository(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, as_of_date: date) -> UniverseRefreshSummary:
        started_at = now_kst()
        errors: list[str] = []
        krx_response = await self._krx.fetch(as_of_date=as_of_date)
        if krx_response.state != DataState.AVAILABLE:
            if krx_response.error_message:
                errors.append(krx_response.error_message)
            with self._sessions.begin() as session:
                self._save_krx_raw(session, as_of_date, krx_response)
                self._quality.add(
                    session,
                    entity_type="universe_refresh",
                    entity_id=as_of_date.isoformat(),
                    provider="KRX",
                    issue_code=krx_response.state.value,
                    severity="ERROR",
                    data_state=krx_response.state,
                    message=(
                        krx_response.error_message
                        or "KRX 종목 마스터를 사용할 수 없습니다."
                    ),
                )
            return UniverseRefreshSummary(
                state=krx_response.state.value,
                started_at=started_at,
                finished_at=now_kst(),
                as_of_date=as_of_date,
                errors=tuple(errors),
            )

        dart_response = await self._dart.fetch()
        if dart_response.state != DataState.AVAILABLE and dart_response.error_message:
            errors.append(dart_response.error_message)

        classified = [
            classify_krx_stock(record) for record in (krx_response.payload or [])
        ]
        with self._sessions.begin() as session:
            self._save_krx_raw(session, as_of_date, krx_response)
            self._save_dart_raw(session, dart_response)
            upserted, review_required = self._stocks.upsert_krx_records(
                session,
                classified,
                as_of_at=krx_response.metadata.as_of_at
                or krx_response.metadata.collected_at,
                collected_at=krx_response.metadata.collected_at,
            )
            dart_mapped = 0
            if (
                dart_response.state == DataState.AVAILABLE
                and dart_response.payload is not None
            ):
                dart_mapped = self._stocks.apply_dart_codes(
                    session,
                    dart_response.payload,
                    collected_at=dart_response.metadata.collected_at,
                )
            else:
                self._stocks.mark_dart_unverified(
                    session,
                    dart_response.state,
                )
                self._quality.add(
                    session,
                    entity_type="universe_refresh",
                    entity_id=as_of_date.isoformat(),
                    provider="OpenDART",
                    issue_code=dart_response.state.value,
                    severity="WARNING",
                    data_state=dart_response.state,
                    message=(
                        dart_response.error_message
                        or "OpenDART 고유번호를 사용할 수 없습니다."
                    ),
                )

        return UniverseRefreshSummary(
            state=(
                DataState.AVAILABLE.value
                if dart_response.state == DataState.AVAILABLE
                else "PARTIAL"
            ),
            started_at=started_at,
            finished_at=now_kst(),
            as_of_date=as_of_date,
            krx_received=len(krx_response.payload or []),
            stocks_upserted=upserted,
            dart_received=len(dart_response.payload or []),
            dart_mapped=dart_mapped,
            review_required=review_required,
            errors=tuple(errors),
        )

    def search(self, query: str, *, limit: int = 50) -> list[StockSearchResult]:
        with self._sessions() as session:
            return self._stocks.search(session, query, limit=limit)

    def stock_count(self) -> int:
        with self._sessions() as session:
            return self._stocks.count(session)

    def close(self) -> None:
        self._engine.dispose()

    def _save_krx_raw(
        self,
        session: Session,
        as_of_date: date,
        response: ApiResponse[Any],
    ) -> None:
        self._raw.save(
            session,
            provider="KRX",
            function_name=KRX_STOCK_MASTER_FUNCTION,
            endpoint=KRX_STOCK_MASTER_ENDPOINT,
            request_parameters={"basDd": as_of_date.strftime("%Y%m%d")},
            response=response,
        )

    def _save_dart_raw(
        self,
        session: Session,
        response: ApiResponse[Any],
    ) -> None:
        self._raw.save(
            session,
            provider="OpenDART",
            function_name=DART_CORP_CODE_FUNCTION,
            endpoint=DART_CORP_CODE_ENDPOINT,
            request_parameters={},
            response=response,
        )
