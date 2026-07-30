from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin


class ApiRawResponse(Base):
    __tablename__ = "api_raw_responses"
    __table_args__ = (
        CheckConstraint(
            "data_state != 'AVAILABLE' OR "
            "(http_status IS NOT NULL AND "
            "http_status >= 200 AND http_status <= 299)",
            name="ck_api_raw_available_http_status",
        ),
        UniqueConstraint(
            "provider",
            "function_name",
            "request_params_hash",
            "response_hash",
            name="uq_api_raw_response_content",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    function_name: Mapped[str] = mapped_column(String(160), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(600))
    request_params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    as_of_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    raw_storage_path: Mapped[str | None] = mapped_column(String(1000))
    content_type: Mapped[str | None] = mapped_column(String(200))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    normalized_success: Mapped[bool | None] = mapped_column(Boolean)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)


class DataQualityLog(Base, CreatedAtMixin):
    __tablename__ = "data_quality_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(64))
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict[str, object] | None] = mapped_column(JSON)
