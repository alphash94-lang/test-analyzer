from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.utils.dates import now_kst


class KisAccessToken(Base):
    """Encrypted, short-lived KIS access token shared by server instances."""

    __tablename__ = "kis_access_tokens"

    credential_fingerprint: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_kst,
        onupdate=now_kst,
        nullable=False,
    )
