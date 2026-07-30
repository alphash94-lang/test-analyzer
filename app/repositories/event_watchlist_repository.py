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
    abbreviated_name: str | None
    news_query: str | None
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
                Stock.abbreviated_name,
                EventWatchlistItem.news_query,
                EventWatchlistItem.created_at,
            )
            .join(Stock, Stock.id == EventWatchlistItem.stock_id)
            .where(EventWatchlistItem.category == WATCHLIST_CATEGORY)
            .order_by(Stock.symbol)
        ).all()
        return tuple(
            WatchlistStock(
                symbol=symbol,
                name_ko=name_ko,
                abbreviated_name=abbreviated_name,
                news_query=news_query,
                created_at=created_at,
            )
            for symbol, name_ko, abbreviated_name, news_query, created_at in rows
        )

    @staticmethod
    def set_news_query(
        session: Session,
        *,
        symbol: str,
        news_query: str | None,
    ) -> None:
        item = session.scalar(
            select(EventWatchlistItem)
            .join(Stock, Stock.id == EventWatchlistItem.stock_id)
            .where(
                Stock.symbol == symbol,
                EventWatchlistItem.category == WATCHLIST_CATEGORY,
            )
        )
        if item is None:
            raise ValueError("관심종목에 등록된 종목만 뉴스 검색 별칭을 설정할 수 있습니다.")
        normalized = news_query.strip() if news_query else None
        if normalized and len(normalized) < 2:
            raise ValueError("뉴스 검색 별칭은 2자 이상 입력해 주세요.")
        if normalized and len(normalized) > 200:
            raise ValueError("뉴스 검색 별칭은 200자 이하로 입력해 주세요.")
        item.news_query = normalized or None
        session.flush()

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
