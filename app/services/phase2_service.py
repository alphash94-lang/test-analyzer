from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.config import Settings
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.scoring import Phase2Result
from app.repositories.scoring_repository import ScoringRepository
from app.services.phase2_input_service import Phase2InputAssembler
from app.services.scoring_rules import phase2_rules_from_settings
from app.services.scoring_service import evaluate_phase2
from app.utils.dates import ensure_kst


class Phase2ScoringService:
    def __init__(
        self,
        settings: Settings,
        *,
        assembler: Phase2InputAssembler | None = None,
        repository: ScoringRepository | None = None,
    ) -> None:
        self._settings = settings
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)
        self._assembler = assembler or Phase2InputAssembler()
        self._repository = repository or ScoringRepository()
        self._rules = phase2_rules_from_settings(settings)

    def evaluate(
        self,
        symbol: str,
        *,
        as_of_at: datetime,
        planned_order_amount: Decimal | None = None,
    ) -> Phase2Result | None:
        normalized_as_of = ensure_kst(as_of_at)
        order_amount = (
            planned_order_amount
            if planned_order_amount is not None
            else self._settings.phase2_planned_order_amount_krw
        )
        with self._sessions.begin() as session:
            stock = session.scalar(
                select(Stock).where(
                    Stock.symbol == symbol,
                    Stock.is_active.is_(True),
                )
            )
            if stock is None:
                return None
            evidence = self._assembler.assemble(
                session,
                stock,
                as_of_at=normalized_as_of,
                rules=self._rules,
                planned_order_amount=order_amount,
            )
            result = evaluate_phase2(evidence, self._rules)
            self._repository.save(session, stock.id, result)
            return result

    def latest(self, symbol: str) -> Phase2Result | None:
        with self._sessions() as session:
            stock_id = session.scalar(select(Stock.id).where(Stock.symbol == symbol))
            if stock_id is None:
                return None
            return self._repository.latest(session, stock_id)

    def close(self) -> None:
        self._engine.dispose()
