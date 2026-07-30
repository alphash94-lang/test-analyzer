from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.quality import DataQualityLog
from app.models.metadata import DataState
from app.utils.dates import now_kst


class DataQualityRepository:
    def add(
        self,
        session: Session,
        *,
        entity_type: str,
        entity_id: str | None,
        provider: str | None,
        issue_code: str,
        severity: str,
        data_state: DataState,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        session.add(
            DataQualityLog(
                entity_type=entity_type,
                entity_id=entity_id,
                provider=provider,
                issue_code=issue_code,
                severity=severity,
                data_state=data_state.value,
                message=message,
                detected_at=now_kst(),
                context=context,
            )
        )
