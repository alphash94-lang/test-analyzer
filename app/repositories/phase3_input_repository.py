from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.financial import Dividend
from app.db.models.market import PriceDaily, Stock, StockClassification
from app.models.market_analysis import ConstituentObservation, IndexPoint, ProxyKind
from app.models.metadata import DataState, DataTiming
from app.repositories.index_repository import IndexRepository
from app.utils.dates import restore_database_kst


@dataclass(frozen=True)
class Phase3InputBundle:
    index_points: list[IndexPoint]
    official_semiconductor_index_points: list[IndexPoint]
    observations: list[ConstituentObservation]
    universe_size: int
    classification_count: int
    proxy_kind: ProxyKind


class Phase3InputRepository:
    def __init__(
        self,
        settings: Settings,
        index_repository: IndexRepository | None = None,
    ) -> None:
        self._settings = settings
        self._indexes = index_repository or IndexRepository()

    def load(
        self,
        session: Session,
        *,
        as_of_date: date,
        as_of_at: datetime,
    ) -> Phase3InputBundle:
        index_points = self._indexes.history(
            session,
            self._settings.phase3_kospi_index_name,
            as_of_date=as_of_date,
            as_of_at=as_of_at,
            limit=self._settings.phase3_index_history_days,
        )
        official_points: list[IndexPoint] = []
        if self._settings.phase3_official_semiconductor_index_name:
            official_points = self._indexes.history(
                session,
                self._settings.phase3_official_semiconductor_index_name,
                as_of_date=as_of_date,
                as_of_at=as_of_at,
                limit=self._settings.phase3_return_lookback_days + 1,
            )
        if not index_points:
            return Phase3InputBundle(
                index_points=[],
                official_semiconductor_index_points=official_points,
                observations=[],
                universe_size=0,
                classification_count=0,
                proxy_kind=ProxyKind.NOT_AVAILABLE,
            )

        market_date = index_points[-1].trade_date
        stocks = session.scalars(
            select(Stock).where(
                Stock.is_active.is_(True),
                Stock.is_kospi.is_(True),
                Stock.security_type == "STOCK",
                Stock.share_class == "COMMON",
                Stock.data_state == DataState.AVAILABLE.value,
                Stock.collected_at <= as_of_at,
            )
        ).all()
        if not stocks:
            return Phase3InputBundle(
                index_points=index_points,
                official_semiconductor_index_points=official_points,
                observations=[],
                universe_size=0,
                classification_count=0,
                proxy_kind=ProxyKind.NOT_AVAILABLE,
            )

        stock_ids = [stock.id for stock in stocks]
        date_limit = max(61, self._settings.phase3_return_lookback_days + 1)
        price_dates = list(
            reversed(
                session.scalars(
                    select(distinct(PriceDaily.trade_date))
                    .where(
                        PriceDaily.stock_id.in_(stock_ids),
                        PriceDaily.trade_date <= market_date,
                        PriceDaily.source_provider
                        == self._settings.phase3_adjusted_price_provider,
                        PriceDaily.is_adjusted.is_(True),
                        PriceDaily.adjustment_status == "VERIFIED",
                        PriceDaily.data_state == DataState.AVAILABLE.value,
                        PriceDaily.data_timing == DataTiming.PREVIOUS_CLOSE.value,
                        PriceDaily.collected_at <= as_of_at,
                    )
                    .order_by(PriceDaily.trade_date.desc())
                    .limit(date_limit)
                ).all()
            )
        )
        if (
            len(price_dates) < date_limit
            or not price_dates
            or price_dates[-1] != market_date
        ):
            return Phase3InputBundle(
                index_points=index_points,
                official_semiconductor_index_points=official_points,
                observations=[],
                universe_size=len(stocks),
                classification_count=0,
                proxy_kind=ProxyKind.NOT_AVAILABLE,
            )

        price_rows = session.scalars(
            select(PriceDaily).where(
                PriceDaily.stock_id.in_(stock_ids),
                PriceDaily.trade_date.in_(price_dates),
                PriceDaily.source_provider
                == self._settings.phase3_adjusted_price_provider,
                PriceDaily.is_adjusted.is_(True),
                PriceDaily.adjustment_status == "VERIFIED",
                PriceDaily.data_state == DataState.AVAILABLE.value,
                PriceDaily.data_timing == DataTiming.PREVIOUS_CLOSE.value,
                PriceDaily.collected_at <= as_of_at,
            )
        ).all()
        prices_by_stock: dict[int, dict[date, PriceDaily]] = {}
        for row in price_rows:
            prices_by_stock.setdefault(row.stock_id, {})[row.trade_date] = row

        start_date = price_dates[-(self._settings.phase3_return_lookback_days + 1)]
        previous_date = price_dates[-2]
        market_caps = self._market_caps(
            session,
            stock_ids=stock_ids,
            dates=(start_date, previous_date),
            as_of_at=as_of_at,
        )
        classifications = self._classifications(
            session,
            stock_ids=stock_ids,
            as_of_date=market_date,
            as_of_at=as_of_at,
        )
        dividend_payers = self._dividend_payers(
            session,
            stock_ids=stock_ids,
            as_of_date=market_date,
            as_of_at=as_of_at,
        )

        codes = {
            value.strip()
            for value in self._settings.phase3_semiconductor_classification_codes.split(
                ","
            )
            if value.strip()
        }
        proxy_kind = (
            ProxyKind.OFFICIAL_INDEX
            if official_points
            and len(official_points) >= self._settings.phase3_return_lookback_days + 1
            and len(index_points) >= self._settings.phase3_return_lookback_days + 1
            and official_points[-1].trade_date == index_points[-1].trade_date
            and official_points[
                -(self._settings.phase3_return_lookback_days + 1)
            ].trade_date
            == index_points[
                -(self._settings.phase3_return_lookback_days + 1)
            ].trade_date
            else (
                ProxyKind.SELF_CALCULATED_PROXY
                if codes and classifications
                else ProxyKind.NOT_AVAILABLE
            )
        )
        stock_by_id = {stock.id: stock for stock in stocks}
        observations: list[ConstituentObservation] = []
        for stock_id, stock_prices in prices_by_stock.items():
            required_rows = [
                stock_prices.get(start_date),
                stock_prices.get(previous_date),
                stock_prices.get(market_date),
            ]
            if any(row is None for row in required_rows):
                continue
            start_row, previous_row, current_row = required_rows
            if start_row is None or previous_row is None or current_row is None:
                continue
            history_rows = [
                stock_prices[trade_date]
                for trade_date in price_dates[-60:]
                if trade_date in stock_prices
            ]
            if (
                len(history_rows) < 60
                or start_row.close_price is None
                or previous_row.close_price is None
                or current_row.close_price is None
                or any(row.close_price is None for row in history_rows)
            ):
                continue
            start_cap_row = market_caps.get((stock_id, start_date))
            previous_cap_row = market_caps.get((stock_id, previous_date))
            if (
                start_cap_row is None
                or previous_cap_row is None
                or start_cap_row.market_cap is None
                or previous_cap_row.market_cap is None
                or start_cap_row.market_cap <= 0
                or previous_cap_row.market_cap <= 0
            ):
                continue
            classification = classifications.get(stock_id)
            is_semiconductor = (
                classification.classification_code in codes
                if classification is not None and codes
                else None
            )
            stock = stock_by_id[stock_id]
            observations.append(
                ConstituentObservation(
                    stock_id=stock_id,
                    symbol=stock.symbol,
                    name=stock.name_ko,
                    start_date=start_date,
                    previous_date=previous_date,
                    as_of_date=market_date,
                    start_close=start_row.close_price,
                    previous_close=previous_row.close_price,
                    close=current_row.close_price,
                    start_market_cap=start_cap_row.market_cap,
                    previous_market_cap=previous_cap_row.market_cap,
                    close_history=tuple(
                        row.close_price
                        for row in history_rows
                        if row.close_price is not None
                    ),
                    is_semiconductor=is_semiconductor,
                    classification_source=(
                        classification.source_provider
                        if classification is not None
                        else None
                    ),
                    is_confirmed_dividend_payer=(
                        True if stock_id in dividend_payers else None
                    ),
                    price_source_provider=current_row.source_provider,
                    market_cap_source_provider=start_cap_row.source_provider,
                    collected_at=max(
                        restore_database_kst(start_row.collected_at),
                        restore_database_kst(previous_row.collected_at),
                        restore_database_kst(current_row.collected_at),
                        restore_database_kst(start_cap_row.collected_at),
                        restore_database_kst(previous_cap_row.collected_at),
                    ),
                )
            )
        return Phase3InputBundle(
            index_points=index_points,
            official_semiconductor_index_points=official_points,
            observations=observations,
            universe_size=len(stocks),
            classification_count=sum(
                item.is_semiconductor is not None for item in observations
            ),
            proxy_kind=proxy_kind,
        )

    @staticmethod
    def _market_caps(
        session: Session,
        *,
        stock_ids: list[int],
        dates: tuple[date, date],
        as_of_at: datetime,
    ) -> dict[tuple[int, date], PriceDaily]:
        rows = session.scalars(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id.in_(stock_ids),
                PriceDaily.trade_date.in_(dates),
                PriceDaily.source_provider == "KRX",
                PriceDaily.market_cap.is_not(None),
                PriceDaily.data_state == DataState.AVAILABLE.value,
                PriceDaily.data_timing == DataTiming.PREVIOUS_CLOSE.value,
                PriceDaily.collected_at <= as_of_at,
            )
            .order_by(PriceDaily.collected_at.desc())
        ).all()
        result: dict[tuple[int, date], PriceDaily] = {}
        for row in rows:
            result.setdefault((row.stock_id, row.trade_date), row)
        return result

    def _classifications(
        self,
        session: Session,
        *,
        stock_ids: list[int],
        as_of_date: date,
        as_of_at: datetime,
    ) -> dict[int, StockClassification]:
        rows = session.scalars(
            select(StockClassification)
            .where(
                StockClassification.stock_id.in_(stock_ids),
                StockClassification.classification_system
                == self._settings.phase3_semiconductor_classification_system,
                StockClassification.source_provider == "KRX",
                StockClassification.data_state == DataState.AVAILABLE.value,
                StockClassification.collected_at <= as_of_at,
                (
                    StockClassification.valid_from.is_(None)
                    | (StockClassification.valid_from <= as_of_date)
                ),
                (
                    StockClassification.valid_to.is_(None)
                    | (StockClassification.valid_to >= as_of_date)
                ),
            )
            .order_by(
                StockClassification.valid_from.desc(),
                StockClassification.id.desc(),
            )
        ).all()
        candidates: dict[int, list[StockClassification]] = {}
        for row in rows:
            candidates.setdefault(row.stock_id, []).append(row)
        result: dict[int, StockClassification] = {}
        for stock_id, stock_rows in candidates.items():
            latest_valid_from = stock_rows[0].valid_from
            latest_rows = [
                row for row in stock_rows if row.valid_from == latest_valid_from
            ]
            if len({row.classification_code for row in latest_rows}) != 1:
                continue
            result[stock_id] = latest_rows[0]
        return result

    @staticmethod
    def _dividend_payers(
        session: Session,
        *,
        stock_ids: list[int],
        as_of_date: date,
        as_of_at: datetime,
    ) -> set[int]:
        rows = session.scalars(
            select(Dividend)
            .where(
                Dividend.stock_id.in_(stock_ids),
                Dividend.filing_date.is_not(None),
                Dividend.filing_date <= as_of_date,
                Dividend.collected_at <= as_of_at,
                Dividend.business_year >= as_of_date.year - 5,
            )
            .order_by(
                Dividend.stock_id,
                Dividend.business_year.desc(),
                Dividend.filing_date.desc(),
                Dividend.receipt_no.desc(),
                Dividend.id.desc(),
            )
        ).all()
        latest_by_context: dict[
            tuple[int, int, str | None, str | None],
            Dividend,
        ] = {}
        for row in rows:
            latest_by_context.setdefault(
                (
                    row.stock_id,
                    row.business_year,
                    row.stock_kind,
                    row.dividend_type,
                ),
                row,
            )
        return {
            row.stock_id
            for row in latest_by_context.values()
            if row.data_state == DataState.AVAILABLE.value
            and row.is_confirmed is True
            and row.is_estimate is False
            and row.dps is not None
            and row.dps > 0
        }
