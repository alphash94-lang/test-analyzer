from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import select

from app.config import Settings
from app.db.models.financial import FinancialMetric
from app.db.models.market import Stock
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.metadata import DataState
from app.providers.kis_reference import (
    KIS_CURRENT_VALUATION_ENDPOINT,
    KIS_CURRENT_VALUATION_FUNCTION,
    KisReferenceProvider,
)
from app.repositories.raw_response_repository import RawResponseRepository
from app.repositories.stock_repository import StockRepository
from app.repositories.valuation_repository import ValuationRepository
from app.utils.dates import SEOUL

_RULE_VERSION = "market-screen-valuation-v1"


@dataclass(frozen=True)
class MarketScreeningDataSummary:
    state: DataState
    total: int
    processed: int
    per_stored: int
    pbr_stored: int
    industries_stored: int
    failed: int


class MarketScreeningDataService:
    def __init__(self, settings: Settings) -> None:
        self._provider = KisReferenceProvider(settings)
        self._raw = RawResponseRepository(settings)
        self._valuations = ValuationRepository()
        self._stocks = StockRepository()
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    async def refresh(self, *, as_of_date: date) -> MarketScreeningDataSummary:
        with self._sessions() as session:
            stocks = list(
                session.scalars(
                    select(Stock)
                    .where(
                        Stock.is_active.is_(True),
                        Stock.is_kospi.is_(True),
                        Stock.security_type == "STOCK",
                        Stock.share_class == "COMMON",
                        Stock.listing_status == "LISTED",
                        Stock.data_state == DataState.AVAILABLE.value,
                    )
                    .order_by(Stock.symbol)
                ).all()
            )
            per_ids = set(
                session.scalars(
                    select(FinancialMetric.stock_id).where(
                        FinancialMetric.period_end == as_of_date,
                        FinancialMetric.rule_version == _RULE_VERSION,
                        FinancialMetric.metric_code == "CURRENT_PER",
                    )
                ).all()
            )
            pbr_ids = set(
                session.scalars(
                    select(FinancialMetric.stock_id).where(
                        FinancialMetric.period_end == as_of_date,
                        FinancialMetric.rule_version == _RULE_VERSION,
                        FinancialMetric.metric_code == "CURRENT_PBR",
                    )
                ).all()
            )
            completed_ids = per_ids & pbr_ids
        as_of_at = datetime.combine(as_of_date, time.max, tzinfo=SEOUL)
        per_stored = 0
        pbr_stored = 0
        industries_stored = 0
        failed = 0
        for stock in stocks:
            if stock.id in completed_ids:
                continue
            try:
                response = await self._provider.fetch_current_valuation(
                    symbol=stock.symbol
                )
            except (OSError, ValueError):
                failed += 1
                continue
            with self._sessions.begin() as session:
                self._raw.save(
                    session,
                    provider="한국투자증권",
                    function_name=KIS_CURRENT_VALUATION_FUNCTION,
                    endpoint=KIS_CURRENT_VALUATION_ENDPOINT,
                    request_parameters={"symbol": stock.symbol},
                    response=response,
                )
                if response.state != DataState.AVAILABLE or not response.payload:
                    failed += 1
                    continue
                item = response.payload[0]
                stored_stock = session.get(Stock, stock.id)
                if stored_stock is None:
                    failed += 1
                    continue
                for metric_code, value in (
                    ("CURRENT_PER", item.per),
                    ("CURRENT_PBR", item.pbr),
                ):
                    if value is None:
                        continue
                    self._valuations.upsert_metric(
                        session,
                        stock_id=stock.id,
                        metric_code=metric_code,
                        value=value,
                        period_end=as_of_date,
                        rule_version=_RULE_VERSION,
                        source_provider="한국투자증권",
                        source_function=KIS_CURRENT_VALUATION_FUNCTION,
                        collected_at=response.metadata.collected_at,
                        as_of_at=as_of_at,
                    )
                    if metric_code == "CURRENT_PER":
                        per_stored += 1
                    else:
                        pbr_stored += 1
                if item.industry_name:
                    self._stocks.upsert_kis_industry(
                        session,
                        stock=stored_stock,
                        industry_name=item.industry_name,
                        as_of_at=as_of_at,
                        collected_at=response.metadata.collected_at,
                    )
                    industries_stored += 1
        state = (
            DataState.AVAILABLE
            if stocks and failed < len(stocks)
            else DataState.MISSING
        )
        return MarketScreeningDataSummary(
            state=state,
            total=len(stocks),
            processed=len(stocks),
            per_stored=per_stored,
            pbr_stored=pbr_stored,
            industries_stored=industries_stored,
            failed=failed,
        )

    def close(self) -> None:
        dispose_db_engine(self._engine)
