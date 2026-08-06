from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.market_analysis import IndexPoint, IndexRefreshSummary
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.krx_index import (
    KRX_KOSPI_INDEX_ENDPOINT,
    KRX_KOSPI_INDEX_FUNCTION,
    KrxIndexDailyProvider,
)
from app.repositories.data_quality_repository import DataQualityRepository
from app.repositories.index_repository import IndexRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.utils.dates import now_kst


class IndexService:
    def __init__(
        self,
        settings: Settings,
        *,
        provider: KrxIndexDailyProvider | None = None,
        repository: IndexRepository | None = None,
    ) -> None:
        self._provider = provider or KrxIndexDailyProvider(settings)
        self._indexes = repository or IndexRepository()
        self._quality = DataQualityRepository()
        self._raw = RawResponseRepository(settings)
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, as_of_date: date) -> IndexRefreshSummary:
        started_at = now_kst()
        response = await self._provider.fetch(as_of_date=as_of_date)
        errors = (response.error_message,) if response.error_message is not None else ()
        with self._sessions.begin() as session:
            self._save_raw(session, as_of_date, response)
            if response.state != DataState.AVAILABLE or response.payload is None:
                self._quality.add(
                    session,
                    entity_type="index_refresh",
                    entity_id=as_of_date.isoformat(),
                    provider="KRX",
                    issue_code=response.state.value,
                    severity="ERROR",
                    data_state=response.state,
                    message=(
                        response.error_message or "KRX KOSPI 지수를 사용할 수 없습니다."
                    ),
                )
                return IndexRefreshSummary(
                    state=response.state.value,
                    started_at=started_at,
                    finished_at=now_kst(),
                    as_of_date=as_of_date,
                    errors=errors,
                )
            stored = self._indexes.upsert_krx_records(
                session,
                response.payload,
                as_of_at=(response.metadata.as_of_at or response.metadata.collected_at),
                collected_at=response.metadata.collected_at,
            )
        return IndexRefreshSummary(
            state=DataState.AVAILABLE.value,
            started_at=started_at,
            finished_at=now_kst(),
            as_of_date=as_of_date,
            received=len(response.payload),
            stored=stored,
            errors=errors,
        )

    def history(
        self,
        *,
        index_name: str = "코스피",
        limit: int = 100,
    ) -> list[IndexPoint]:
        if limit < 1:
            raise ValueError("history limit must be positive")
        as_of_at = now_kst()
        with self._sessions() as session:
            return self._indexes.history(
                session,
                index_name,
                as_of_date=as_of_at.date(),
                as_of_at=as_of_at,
                limit=limit,
            )

    def close(self) -> None:
        dispose_db_engine(self._engine)

    def _save_raw(
        self,
        session: Session,
        as_of_date: date,
        response: ApiResponse[Any],
    ) -> None:
        self._raw.save(
            session,
            provider="KRX",
            function_name=KRX_KOSPI_INDEX_FUNCTION,
            endpoint=KRX_KOSPI_INDEX_ENDPOINT,
            request_parameters={"basDd": as_of_date.strftime("%Y%m%d")},
            response=response,
        )
