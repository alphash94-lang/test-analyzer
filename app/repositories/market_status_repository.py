from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import MarketStatus
from app.models.metadata import DataState, DataTiming


class MarketStatusRepository:
    def upsert_daily(
        self,
        session: Session,
        *,
        stock_id: int,
        status_type: str,
        status_value: str,
        effective_from: datetime,
        source_provider: str,
        source_function: str,
        collected_at: datetime,
    ) -> MarketStatus:
        row = session.scalar(
            select(MarketStatus).where(
                MarketStatus.stock_id == stock_id,
                MarketStatus.status_type == status_type,
                MarketStatus.effective_from == effective_from,
            )
        )
        if row is None:
            prior_rows = session.scalars(
                select(MarketStatus).where(
                    MarketStatus.stock_id == stock_id,
                    MarketStatus.status_type == status_type,
                    MarketStatus.effective_to.is_(None),
                    MarketStatus.effective_from < effective_from,
                )
            ).all()
            for prior in prior_rows:
                prior.effective_to = effective_from - timedelta(microseconds=1)
            row = MarketStatus(
                stock_id=stock_id,
                status_type=status_type,
                effective_from=effective_from,
            )
            session.add(row)
        row.status_value = status_value
        row.effective_to = None
        row.source_provider = source_provider
        row.source_function = source_function
        row.data_state = DataState.AVAILABLE.value
        row.as_of_at = effective_from
        row.collected_at = collected_at
        row.data_timing = DataTiming.DELAYED.value
        session.flush()
        return row
