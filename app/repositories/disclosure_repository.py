from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.disclosure import Disclosure
from app.db.models.market import Stock
from app.models.events import CorrectionLinkState, normalize_disclosure_base_title
from app.models.financial import DartDisclosureItem, DisclosureView
from app.models.metadata import DataState, DataTiming


class DisclosureRepository:
    def upsert(
        self,
        session: Session,
        *,
        stock: Stock,
        items: tuple[DartDisclosureItem, ...],
        raw_response_id: int | None,
        disclosure_type: str,
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in items:
            row = session.scalar(
                select(Disclosure).where(Disclosure.receipt_no == item.receipt_no)
            )
            if row is None:
                row = Disclosure(receipt_no=item.receipt_no)
                session.add(row)
            row.stock_id = stock.id
            row.raw_response_id = raw_response_id
            row.corp_code = item.corp_code
            if not item.is_correction:
                row.original_receipt_no = None
            row.report_name = item.report_name
            row.receipt_date = item.receipt_date
            row.filer_name = item.filer_name
            row.disclosure_type = disclosure_type
            row.correction_note = item.remark
            row.source_url = item.source_url
            row.is_correction = item.is_correction
            if not item.is_correction:
                row.correction_link_state = (
                    CorrectionLinkState.NOT_APPLICABLE.value
                )
            elif row.original_receipt_no is None:
                row.correction_link_state = (
                    CorrectionLinkState.ORIGINAL_NOT_FOUND.value
                )
            row.source_provider = "OpenDART"
            row.source_function = "공시검색"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = datetime.combine(
                item.receipt_date,
                time.min,
                tzinfo=ZoneInfo("Asia/Seoul"),
            )
            row.collected_at = collected_at
            row.data_timing = DataTiming.PERIODIC_DISCLOSURE.value
            stored += 1
        session.flush()
        return stored

    def latest_receipt_date(
        self,
        session: Session,
        stock_id: int,
        *,
        disclosure_type: str,
        as_of_date: date | None = None,
    ) -> date | None:
        criteria = [
            Disclosure.stock_id == stock_id,
            Disclosure.disclosure_type == disclosure_type,
            Disclosure.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(Disclosure.receipt_date <= as_of_date)
        return session.scalar(
            select(func.max(Disclosure.receipt_date)).where(*criteria)
        )

    def important_disclosures(
        self,
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[Disclosure, ...]:
        criteria = [
            Disclosure.stock_id == stock_id,
            Disclosure.disclosure_type == "IMPORTANT_EVENT",
            Disclosure.data_state == DataState.AVAILABLE.value,
        ]
        if as_of_date is not None:
            criteria.append(Disclosure.receipt_date <= as_of_date)
        return tuple(
            session.scalars(
                select(Disclosure)
                .where(*criteria)
                .order_by(
                    Disclosure.receipt_date.desc(),
                    Disclosure.receipt_no.desc(),
                )
            ).all()
        )

    def link_corrections(
        self,
        session: Session,
        *,
        stock_id: int,
        as_of_date: date | None = None,
    ) -> tuple[int, int]:
        rows = self.important_disclosures(
            session,
            stock_id,
            as_of_date=as_of_date,
        )
        originals_by_title: dict[str, list[Disclosure]] = {}
        for row in rows:
            if row.is_correction:
                continue
            originals_by_title.setdefault(
                normalize_disclosure_base_title(row.report_name),
                [],
            ).append(row)

        linked = 0
        ambiguous = 0
        for correction in (row for row in rows if row.is_correction):
            candidates = [
                row
                for row in originals_by_title.get(
                    normalize_disclosure_base_title(correction.report_name),
                    [],
                )
                if (
                    row.receipt_date < correction.receipt_date
                    or (
                        row.receipt_date == correction.receipt_date
                        and row.receipt_no < correction.receipt_no
                    )
                )
            ]
            if len(candidates) == 1:
                correction.original_receipt_no = candidates[0].receipt_no
                correction.correction_link_state = (
                    CorrectionLinkState.LINKED.value
                )
                linked += 1
            elif len(candidates) > 1:
                correction.original_receipt_no = None
                correction.correction_link_state = (
                    CorrectionLinkState.AMBIGUOUS.value
                )
                ambiguous += 1
            else:
                correction.original_receipt_no = None
                correction.correction_link_state = (
                    CorrectionLinkState.ORIGINAL_NOT_FOUND.value
                )
        session.flush()
        return linked, ambiguous

    def receipt_metadata(
        self,
        session: Session,
        stock_id: int,
        *,
        as_of_date: date,
    ) -> dict[str, Disclosure]:
        return {
            row.receipt_no: row
            for row in session.scalars(
                select(Disclosure).where(
                    Disclosure.stock_id == stock_id,
                    Disclosure.receipt_date <= as_of_date,
                )
            ).all()
        }

    def dividend_decisions(
        self,
        session: Session,
        stock_id: int,
    ) -> tuple[DisclosureView, ...]:
        rows = session.scalars(
            select(Disclosure)
            .where(
                Disclosure.stock_id == stock_id,
                Disclosure.disclosure_type == "DIVIDEND_DECISION",
            )
            .order_by(Disclosure.receipt_date.desc())
        ).all()
        return tuple(
            DisclosureView(
                report_name=row.report_name,
                receipt_no=row.receipt_no,
                receipt_date=row.receipt_date,
                disclosure_type=row.disclosure_type,
                is_correction=row.is_correction,
                source_url=row.source_url,
            )
            for row in rows
        )
