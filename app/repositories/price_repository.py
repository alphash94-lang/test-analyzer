from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.market import PriceDaily, Stock
from app.models.metadata import DataState, DataTiming
from app.models.price import (
    KisAdjustedDailyPriceItem,
    KrxDailyPriceItem,
    LatestDailyPrice,
)
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
        if not records:
            return 0, 0

        requested_symbols = {item.symbol for item in records}
        stocks_by_symbol: dict[str, Stock] = {}
        for stock in session.scalars(
            select(Stock).where(
                Stock.is_active.is_(True),
                Stock.symbol.in_(requested_symbols),
            )
        ).all():
            stocks_by_symbol[stock.symbol] = stock
        stock_ids = [stock.id for stock in stocks_by_symbol.values()]
        trade_dates = {item.trade_date for item in records}
        existing_rows = {
            (row.stock_id, row.trade_date): row
            for row in session.scalars(
                select(PriceDaily).where(
                    PriceDaily.stock_id.in_(stock_ids),
                    PriceDaily.trade_date.in_(trade_dates),
                    PriceDaily.source_provider == "KRX",
                )
            ).all()
        }
        stored = 0
        unmatched = 0
        for item in records:
            stock = stocks_by_symbol.get(item.symbol)
            if stock is None:
                unmatched += 1
                self._quality.add(
                    session,
                    entity_type="price_daily",
                    entity_id=item.symbol,
                    provider="KRX",
                    issue_code="UNMATCHED_SYMBOL",
                    severity="WARNING",
                    data_state=DataState.MISSING,
                    message="KRX 일별가격의 단축코드를 종목 마스터에서 찾지 못했습니다.",
                    context={
                        "trade_date": item.trade_date.isoformat(),
                        "symbol": item.symbol,
                    },
                )
                continue
            row = existing_rows.get((stock.id, item.trade_date))
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
                existing_rows[(stock.id, item.trade_date)] = row
            row.currency = None
            row.open_price = item.open_price
            row.high_price = item.high_price
            row.low_price = item.low_price
            row.close_price = item.close_price
            row.previous_day_change = item.previous_day_change
            row.volume = item.volume
            row.trading_value = item.trading_value
            row.market_cap = item.market_cap
            row.listed_shares = item.listed_shares
            row.is_adjusted = False
            row.adjustment_status = "RAW_OFFICIAL"
            row.source_function = "유가증권 일별매매정보"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = as_of_at
            row.collected_at = collected_at
            row.data_timing = DataTiming.PREVIOUS_CLOSE.value
            stored += 1
        session.flush()
        return stored, unmatched

    def upsert_kis_adjusted_records(
        self,
        session: Session,
        symbol: str,
        records: list[KisAdjustedDailyPriceItem],
        *,
        as_of_at: datetime,
        collected_at: datetime,
    ) -> int:
        stock = session.scalar(
            select(Stock).where(
                Stock.symbol == symbol,
                Stock.is_active.is_(True),
            )
        )
        if stock is None:
            raise ValueError(f"active stock not found: {symbol}")
        trade_dates = {item.trade_date for item in records}
        existing_rows = {
            row.trade_date: row
            for row in session.scalars(
                select(PriceDaily).where(
                    PriceDaily.stock_id == stock.id,
                    PriceDaily.trade_date.in_(trade_dates),
                    PriceDaily.source_provider == "한국투자증권",
                )
            ).all()
        }
        stored = 0
        for item in records:
            row = existing_rows.get(item.trade_date)
            if row is None:
                row = PriceDaily(
                    stock_id=stock.id,
                    trade_date=item.trade_date,
                    source_provider="한국투자증권",
                    source_function="국내주식기간별시세(수정주가)",
                    data_state=DataState.AVAILABLE.value,
                    collected_at=collected_at,
                )
                session.add(row)
                existing_rows[item.trade_date] = row
            row.currency = "KRW"
            row.open_price = item.open_price
            row.high_price = item.high_price
            row.low_price = item.low_price
            row.close_price = item.close_price
            row.previous_day_change = None
            row.volume = item.volume
            row.trading_value = item.trading_value
            row.market_cap = None
            row.listed_shares = None
            row.is_adjusted = True
            row.adjustment_status = "VERIFIED"
            row.source_function = "국내주식기간별시세(수정주가)"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = as_of_at
            row.collected_at = collected_at
            row.data_timing = DataTiming.PREVIOUS_CLOSE.value
            stored += 1
        session.flush()
        return stored

    def latest_for_symbols(
        self,
        session: Session,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        if not symbols:
            return {}
        latest_dates = (
            select(
                PriceDaily.stock_id.label("stock_id"),
                func.max(PriceDaily.trade_date).label("trade_date"),
            )
            .join(Stock, PriceDaily.stock_id == Stock.id)
            .where(
                Stock.symbol.in_(symbols),
                PriceDaily.source_provider == "KRX",
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .group_by(PriceDaily.stock_id)
            .subquery()
        )
        rows = session.execute(
            select(Stock.symbol, PriceDaily)
            .join(PriceDaily, PriceDaily.stock_id == Stock.id)
            .join(
                latest_dates,
                (latest_dates.c.stock_id == PriceDaily.stock_id)
                & (latest_dates.c.trade_date == PriceDaily.trade_date),
            )
            .where(
                Stock.symbol.in_(symbols),
                PriceDaily.source_provider == "KRX",
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(Stock.symbol)
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

    def latest_adjusted_for_symbols(
        self,
        session: Session,
        symbols: list[str],
    ) -> dict[str, LatestDailyPrice]:
        if not symbols:
            return {}
        latest_dates = (
            select(
                PriceDaily.stock_id.label("stock_id"),
                func.max(PriceDaily.trade_date).label("trade_date"),
            )
            .join(Stock, PriceDaily.stock_id == Stock.id)
            .where(
                Stock.symbol.in_(symbols),
                PriceDaily.is_adjusted.is_(True),
                PriceDaily.adjustment_status == "VERIFIED",
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .group_by(PriceDaily.stock_id)
            .subquery()
        )
        rows = session.execute(
            select(Stock.symbol, PriceDaily)
            .join(PriceDaily, PriceDaily.stock_id == Stock.id)
            .join(
                latest_dates,
                (latest_dates.c.stock_id == PriceDaily.stock_id)
                & (latest_dates.c.trade_date == PriceDaily.trade_date),
            )
            .where(
                Stock.symbol.in_(symbols),
                PriceDaily.is_adjusted.is_(True),
                PriceDaily.adjustment_status == "VERIFIED",
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(
                Stock.symbol,
                PriceDaily.collected_at.desc(),
            )
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
                open=row.open_price,
                volume=row.volume,
            )
            for row in reversed(selected_rows)
            if row.high_price is not None
            and row.low_price is not None
            and row.close_price is not None
        ]
