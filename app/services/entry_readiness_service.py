from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.models.market_analysis import MarketRegime
from app.models.metadata import DataState
from app.repositories.market_analysis_repository import MarketAnalysisRepository
from app.services.recommendation_rules import calculate_entry_score
from app.utils.dates import restore_database_kst


@dataclass(frozen=True)
class EntryReadiness:
    score: Decimal | None
    state: DataState
    market_regime: MarketRegime
    as_of_at: datetime
    missing_core_data: tuple[str, ...]
    explanation: str


class EntryReadinessService:
    def __init__(self, settings: Settings) -> None:
        self._repository = MarketAnalysisRepository()
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    def latest(self, individual_entry_score: Decimal | None) -> EntryReadiness | None:
        with self._sessions() as session:
            snapshot, _, _ = self._repository.latest(session)
        if snapshot is None:
            return None
        state = DataState(snapshot.data_state)
        regime = MarketRegime(snapshot.market_regime)
        score = calculate_entry_score(
            individual_entry_score=individual_entry_score,
            market_state=state,
            market_regime=regime,
            semiconductor_recovery=snapshot.semiconductor_recovery,
            non_semiconductor_breadth=snapshot.non_semiconductor_breadth,
        )
        return EntryReadiness(
            score=score,
            state=state,
            market_regime=regime,
            as_of_at=restore_database_kst(snapshot.as_of_at),
            missing_core_data=tuple(snapshot.missing_core_data),
            explanation=snapshot.explanation,
        )

    def close(self) -> None:
        self._engine.dispose()
