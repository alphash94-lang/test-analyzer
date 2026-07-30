from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.dates import now_kst


class Base(DeclarativeBase):
    pass


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_kst,
        nullable=False,
    )


class SourceMetadataMixin:
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_function: Mapped[str] = mapped_column(String(160), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    data_timing: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
    )
