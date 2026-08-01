from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.financial import FinancialMetric
from app.models.metadata import DataState, DataTiming


class ValuationRepository:
    def upsert_metric(
        self,
        session: Session,
        *,
        stock_id: int,
        metric_code: str,
        value: Decimal,
        period_end: date,
        rule_version: str,
        source_provider: str,
        source_function: str,
        collected_at: datetime,
        as_of_at: datetime,
        fs_div: str | None = None,
    ) -> FinancialMetric:
        row = session.scalar(
            select(FinancialMetric).where(
                FinancialMetric.stock_id == stock_id,
                FinancialMetric.metric_code == metric_code,
                FinancialMetric.period_end == period_end,
                FinancialMetric.fs_div == fs_div,
                FinancialMetric.rule_version == rule_version,
            )
        )
        if row is None:
            row = FinancialMetric(
                stock_id=stock_id,
                metric_code=metric_code,
                period_end=period_end,
                fs_div=fs_div,
                rule_version=rule_version,
            )
            session.add(row)
        row.value = value
        row.unit = "RATIO"
        row.period_start = None
        row.input_data_hash = sha256(
            (
                f"{stock_id}|{metric_code}|{period_end.isoformat()}|"
                f"{value}|{source_provider}|{rule_version}"
            ).encode()
        ).hexdigest()
        row.source_provider = source_provider
        row.source_function = source_function
        row.data_state = DataState.AVAILABLE.value
        row.as_of_at = as_of_at
        row.collected_at = collected_at
        row.data_timing = DataTiming.PREVIOUS_CLOSE.value
        session.flush()
        return row
