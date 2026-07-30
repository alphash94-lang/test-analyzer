from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.event import EventWatchlistItem
from app.db.models.market import Stock

WATCHLIST_CATEGORY = "INTEREST"
WATCHLIST_MAX_ITEMS = 50


@dataclass(frozen=True)
class WatchlistStock:
    symbol: str
    name_ko: str
    created_at: datetime


class EventWatchlistRepository:
    @staticmethod
    def eligible_stocks(session: Session) -> tuple[tuple[str, str], ...]:
        rows = session.execute(
            select(Stock.symbol, Stock.name_ko)
            .where(
                Stock.is_kospi.is_(True),
                Stock.security_type == "STOCK",
                Stock.share_class == "COMMON",
                Stock.is_active.is_(True),
            )
            .order_by(Stock.name_ko, Stock.symbol)
        ).all()
        return tuple((symbol, name_ko) for symbol, name_ko in rows)

    @staticmethod
    def list_items(session: Session) -> tuple[WatchlistStock, ...]:
        rows = session.execute(
            select(
                Stock.symbol,
                Stock.name_ko,
                EventWatchlistItem.created_at,
            )
            .join(Stock, Stock.id == EventWatchlistItem.stock_id)
            .where(EventWatchlistItem.category == WATCHLIST_CATEGORY)
            .order_by(EventWatchlistItem.created_at, Stock.symbol)
        ).all()
        return tuple(
            WatchlistStock(
                symbol=symbol,
                name_ko=name_ko,
                created_at=created_at,
            )
            for symbol, name_ko, created_at in rows
        )

    def add_symbols(self, session: Session, symbols: list[str]) -> int:
        requested = tuple(dict.fromkeys(symbols))
        if not requested:
            return 0
        stocks = session.scalars(
            select(Stock).where(
                Stock.symbol.in_(requested),
                Stock.is_kospi.is_(True),
                Stock.security_type == "STOCK",
                Stock.share_class == "COMMON",
                Stock.is_active.is_(True),
            )
        ).all()
        stocks_by_symbol = {stock.symbol: stock for stock in stocks}
        invalid = sorted(set(requested) - set(stocks_by_symbol))
        if invalid:
            raise ValueError(
                "활성 KOSPI 보통주가 아닌 종목이 포함되어 있습니다: "
                + ", ".join(invalid)
            )
        existing_ids = set(
            session.scalars(
                select(EventWatchlistItem.stock_id).where(
                    EventWatchlistItem.category == WATCHLIST_CATEGORY
                )
            ).all()
        )
        additions = [
            stocks_by_symbol[symbol]
            for symbol in requested
            if stocks_by_symbol[symbol].id not in existing_ids
        ]
        current_count = session.scalar(
            select(func.count(EventWatchlistItem.id)).where(
                EventWatchlistItem.category == WATCHLIST_CATEGORY
            )
        )
        if int(current_count or 0) + len(additions) > WATCHLIST_MAX_ITEMS:
            raise ValueError(
                f"관심종목은 최대 {WATCHLIST_MAX_ITEMS}개까지 등록할 수 있습니다."
            )
        session.add_all(
            EventWatchlistItem(
                stock_id=stock.id,
                category=WATCHLIST_CATEGORY,
            )
            for stock in additions
        )
        session.flush()
        return len(additions)

    @staticmethod
    def remove_symbols(session: Session, symbols: list[str]) -> int:
        requested = tuple(dict.fromkeys(symbols))
        if not requested:
            return 0
        stock_ids = select(Stock.id).where(Stock.symbol.in_(requested))
        matching_count = session.scalar(
            select(func.count(EventWatchlistItem.id)).where(
                EventWatchlistItem.category == WATCHLIST_CATEGORY,
                EventWatchlistItem.stock_id.in_(stock_ids),
            )
        )
        session.execute(
            delete(EventWatchlistItem).where(
                EventWatchlistItem.category == WATCHLIST_CATEGORY,
                EventWatchlistItem.stock_id.in_(stock_ids),
            )
        )
        return int(matching_count or 0)
