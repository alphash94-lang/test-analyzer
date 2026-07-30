from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, SourceMetadataMixin


class Disclosure(Base, CreatedAtMixin, SourceMetadataMixin):
    __tablename__ = "disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocks.id", ondelete="SET NULL")
    )
    raw_response_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_raw_responses.id", ondelete="SET NULL")
    )
    corp_code: Mapped[str | None] = mapped_column(String(16))
    receipt_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    original_receipt_no: Mapped[str | None] = mapped_column(String(32))
    report_name: Mapped[str] = mapped_column(String(400), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    filer_name: Mapped[str | None] = mapped_column(String(200))
    disclosure_type: Mapped[str | None] = mapped_column(String(80))
    correction_note: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_link_state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="NOT_APPLICABLE",
        server_default="NOT_APPLICABLE",
    )
