from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market_analysis import IndexDaily
from app.models.market_analysis import IndexPoint, KrxIndexDailyItem
from app.models.metadata import DataState, DataTiming
from app.utils.dates import restore_database_kst


class IndexRepository:
    def upsert_krx_records(
        self,
        session: Session,
        records: list[KrxIndexDailyItem],
        *,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in records:
            row = session.scalar(
                select(IndexDaily).where(
                    IndexDaily.index_name == item.index_name,
                    IndexDaily.trade_date == item.trade_date,
                    IndexDaily.source_provider == "KRX",
                )
            )
            if row is None:
                row = IndexDaily(
                    index_name=item.index_name,
                    trade_date=item.trade_date,
                    source_provider="KRX",
                    source_function="KOSPI 시리즈 일별시세정보",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=collected_at,
                )
                session.add(row)
            row.index_class = item.index_class
            row.close = item.close
            row.previous_day_change = item.previous_day_change
            row.fluctuation_rate = item.fluctuation_rate
            row.open = item.open
            row.high = item.high
            row.low = item.low
            row.volume = item.volume
            row.trading_value = item.trading_value
            row.market_cap = item.market_cap
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = as_of_at
            row.collected_at = collected_at
            row.data_timing = DataTiming.PREVIOUS_CLOSE.value
            stored += 1
        session.flush()
        return stored

    def history(
        self,
        session: Session,
        index_name: str,
        *,
        as_of_date: date,
        as_of_at: datetime,
        limit: int,
    ) -> list[IndexPoint]:
        rows = session.scalars(
            select(IndexDaily)
            .where(
                IndexDaily.index_name == index_name,
                IndexDaily.source_provider == "KRX",
                IndexDaily.trade_date <= as_of_date,
                IndexDaily.collected_at <= as_of_at,
                IndexDaily.data_state == DataState.AVAILABLE.value,
                IndexDaily.data_timing == DataTiming.PREVIOUS_CLOSE.value,
            )
            .order_by(IndexDaily.trade_date.desc())
            .limit(limit)
        ).all()
        return [
            IndexPoint(
                trade_date=row.trade_date,
                close=row.close,
                source_provider=row.source_provider,
                source_function=row.source_function,
                collected_at=restore_database_kst(row.collected_at),
            )
            for row in reversed(rows)
            if row.close > 0
        ]
