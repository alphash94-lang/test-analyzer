from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import PriceDaily, Stock
from app.models.metadata import DataState, DataTiming
from app.models.price import KrxDailyPriceItem, LatestDailyPrice
from app.repositories.data_quality_repository import DataQualityRepository
from app.utils.dates import restore_database_kst
from app.utils.technical_indicators import AdjustedPricePoint


class PriceRepository:
    def __init__(
        self,
        quality_repository: DataQualityRepository | None = None,
    ) -> None:
        self._quality = quality_repository or DataQualityRepository()

    def upsert_krx_records(
        self,
        session: Session,
        records: list[KrxDailyPriceItem],
        *,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> tuple[int, int]:
        stocks_by_issue_code: dict[str, list[Stock]] = {}
        for stock in session.scalars(
            select(Stock).where(
                Stock.is_active.is_(True),
                Stock.issue_code.is_not(None),
            )
        ).all():
            if stock.issue_code is not None:
                stocks_by_issue_code.setdefault(stock.issue_code, []).append(stock)
        stored = 0
        unmatched = 0
        for item in records:
            candidates = stocks_by_issue_code.get(item.issue_code, [])
            if len(candidates) != 1:
                unmatched += 1
                is_conflict = len(candidates) > 1
                self._quality.add(
                    session,
                    entity_type="price_daily",
                    entity_id=item.issue_code,
                    provider="KRX",
                    issue_code=(
                        "AMBIGUOUS_ISSUE_CODE"
                        if is_conflict
                        else "UNMATCHED_ISSUE_CODE"
                    ),
                    severity="ERROR" if is_conflict else "WARNING",
                    data_state=(
                        DataState.CONFLICT if is_conflict else DataState.MISSING
                    ),
                    message=(
                        "KRX 일별가격의 종목 식별자가 여러 종목과 충돌합니다."
                        if is_conflict
                        else "KRX 일별가격의 종목 식별자를 종목 마스터에서 찾지 못했습니다."
                    ),
                    context={
                        "trade_date": item.trade_date.isoformat(),
                        "candidate_symbols": [
                            candidate.symbol for candidate in candidates
                        ],
                    },
                )
                continue
            stock = candidates[0]
            row = session.scalar(
                select(PriceDaily).where(
                    PriceDaily.stock_id == stock.id,
                    PriceDaily.trade_date == item.trade_date,
                    PriceDaily.source_provider == "KRX",
                )
            )
            if row is None:
                row = PriceDaily(
                    stock_id=stock.id,
                    trade_date=item.trade_date,
                    source_provider="KRX",
                    source_function="유가증권 일별매매정보",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=collected_at,
                )
                session.add(row)
            row.currency = None
            row.open_price = item.open_price
            row.high_price = item.high_price
            row.low_price = item.low_price
            row.close_price = item.close_price
            row.volume = item.volume
            row.trading_value = item.trading_value
            row.market_cap = item.market_cap
            row.listed_shares = item.listed_shares
            row.is_adjusted = None
            row.adjustment_status = "NOT_VERIFIED"
            row.source_function = "유가증권 일별매매정보"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = as_of_at
            row.collected_at = collected_at
            row.data_timing = DataTiming.PREVIOUS_CLOSE.value
            stored += 1
        session.flush()
        return stored, unmatched

    def latest_for_symbols(
        self,
        session: Session,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        if not symbols:
            return {}
        rows = session.execute(
            select(Stock.symbol, PriceDaily)
            .join(PriceDaily, PriceDaily.stock_id == Stock.id)
            .where(
                Stock.symbol.in_(symbols),
                PriceDaily.source_provider == "KRX",
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(Stock.symbol, PriceDaily.trade_date.desc())
        ).all()
        result: dict[str, LatestDailyPrice] = {}
        for symbol, row in rows:
            if symbol in result or row.close_price is None:
                continue
            result[symbol] = LatestDailyPrice(
                symbol=symbol,
                trade_date=row.trade_date,
                close_price=row.close_price,
                currency=row.currency,
                volume=row.volume,
                trading_value=row.trading_value,
                market_cap=row.market_cap,
                is_adjusted=row.is_adjusted,
                source_provider=row.source_provider,
                state=DataState(row.data_state),
                as_of_at=restore_database_kst(row.as_of_at),
                collected_at=restore_database_kst(row.collected_at),
            )
        return result

    def history_for_symbol(
        self,
        session: Session,
        symbol: str,
        *,
        limit: int = 260,
        as_of_date: date | None = None,
        as_of_at: datetime | None = None,
    ) -> list[AdjustedPricePoint]:
        if limit < 1:
            raise ValueError("history limit must be positive")
        statement = (
            select(PriceDaily)
            .join(Stock, PriceDaily.stock_id == Stock.id)
            .where(
                Stock.symbol == symbol,
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(PriceDaily.trade_date.desc())
            .limit(limit * 3)
        )
        if as_of_date is not None:
            statement = statement.where(PriceDaily.trade_date <= as_of_date)
        if as_of_at is not None:
            statement = statement.where(PriceDaily.collected_at <= as_of_at)
        rows = session.scalars(statement).all()
        if not rows:
            return []
        verified_rows = [
            row
            for row in rows
            if row.is_adjusted is True and row.adjustment_status == "VERIFIED"
        ]
        selected_provider = (
            verified_rows[0].source_provider
            if verified_rows
            else rows[0].source_provider
        )
        selected_rows = [
            row for row in rows if row.source_provider == selected_provider
        ][:limit]
        return [
            AdjustedPricePoint(
                trade_date=row.trade_date,
                high=row.high_price,
                low=row.low_price,
                close=row.close_price,
                is_adjusted=row.is_adjusted,
                adjustment_status=row.adjustment_status,
                source_provider=row.source_provider,
            )
            for row in reversed(selected_rows)
            if row.high_price is not None
            and row.low_price is not None
            and row.close_price is not None
        ]
