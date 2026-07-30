from __future__ import annotations

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.repositories.event_watchlist_repository import (
    EventWatchlistRepository,
    WatchlistStock,
)


class EventWatchlistService:
    def __init__(self, settings: Settings) -> None:
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)
        self._repository = EventWatchlistRepository()

    def eligible_stocks(self) -> tuple[tuple[str, str], ...]:
        with self._sessions() as session:
            return self._repository.eligible_stocks(session)

    def list_items(self) -> tuple[WatchlistStock, ...]:
        with self._sessions() as session:
            return self._repository.list_items(session)

    def symbols(self) -> list[str]:
        return [item.symbol for item in self.list_items()]

    def add_symbols(self, symbols: list[str]) -> int:
        with self._sessions.begin() as session:
            return self._repository.add_symbols(session, symbols)

    def remove_symbols(self, symbols: list[str]) -> int:
        with self._sessions.begin() as session:
            return self._repository.remove_symbols(session, symbols)

    def close(self) -> None:
        self._engine.dispose()
