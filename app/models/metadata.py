from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

from app.utils.dates import ensure_kst


class DataState(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_VERIFIED = "NOT_VERIFIED"
    FETCH_FAILED = "FETCH_FAILED"
    STALE = "STALE"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"


class DataTiming(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    PREVIOUS_CLOSE = "PREVIOUS_CLOSE"
    PERIODIC_DISCLOSURE = "PERIODIC_DISCLOSURE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class FinancialScope(StrEnum):
    CONSOLIDATED = "CFS"
    SEPARATE = "OFS"
    NOT_APPLICABLE = "N/A"
    UNKNOWN = "UNKNOWN"


class DataMetadata(BaseModel):
    """Provenance attached to provider and calculated data."""

    model_config = ConfigDict(frozen=True)

    provider: str
    function_name: str
    state: DataState
    as_of_at: datetime | None = None
    collected_at: datetime
    timing: DataTiming = DataTiming.UNKNOWN
    financial_scope: FinancialScope = FinancialScope.NOT_APPLICABLE
    is_estimate: bool | None = None
    disclosure_receipt_no: str | None = None
    source_url: HttpUrl | None = None

    @field_validator("as_of_at", "collected_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        return ensure_kst(value) if value is not None else None
