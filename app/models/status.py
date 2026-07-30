from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from app.utils.dates import ensure_kst


class ConnectionState(StrEnum):
    CONNECTED = "연결됨"
    STALE = "데이터 지연"
    NOT_CONFIGURED = "키 미설정"
    NOT_VERIFIED = "연결 미검증"
    FAILED = "연결 실패"
    DEFERRED = "지원 보류"


class ConnectionStatusItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    state: ConnectionState
    detail: str
    checked_at: datetime
    live_check_performed: bool = False

    @field_validator("checked_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        return ensure_kst(value)
