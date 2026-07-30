from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.financial import (
    FinancialAccount,
    FinancialMetric,
    FinancialStatement,
)
from app.db.models.market import (
    MarketStatus,
    PriceDaily,
    Stock,
    StockClassification,
)
from app.models.metadata import DataState, FinancialScope
from app.models.scoring import CorporateEventEvidence, IndustryPeer
from app.repositories.financial_repository import FinancialRepository

INDUSTRY_KIND_SYSTEM = "KRX_INDUSTRY_KIND"
DETAILED_INDUSTRY_SYSTEM = "KRX_INDUSTRY"
PARENT_INDUSTRY_SYSTEM = "KRX_PARENT_INDUSTRY"
MARKET_STATUS_TYPES = {
    "TRADING_STATUS",
    "MANAGEMENT_STATUS",
    "DELISTING_RISK",
}
FLOW_METRICS = {
    "REVENUE",
    "OPERATING_PROFIT",
    "PARENT_OWNERS_NET_INCOME",
    "OPERATING_CASH_FLOW",
    "CAPEX_TANGIBLE",
    "CAPEX_INTANGIBLE",
    "FINANCE_COSTS",
}


class Phase2InputRepository:
    def __init__(
        self,
        financial_repository: FinancialRepository | None = None,
    ) -> None:
        self._financial = financial_repository or FinancialRepository()

    def classification(
        self,
        session: Session,
        stock_id: int,
        system: str,
        as_of_at: datetime,
    ) -> str | None:
        as_of_date = as_of_at.date()
        row = session.scalar(
            select(StockClassification)
            .where(
                StockClassification.stock_id == stock_id,
                StockClassification.classification_system == system,
                StockClassification.data_state == DataState.AVAILABLE.value,
                StockClassification.collected_at <= as_of_at,
                or_(
                    StockClassification.valid_from.is_(None),
                    StockClassification.valid_from <= as_of_date,
                ),
                or_(
                    StockClassification.valid_to.is_(None),
                    StockClassification.valid_to >= as_of_date,
                ),
            )
            .order_by(
                StockClassification.valid_from.desc(),
                StockClassification.id.desc(),
            )
        )
        return row.classification_code if row is not None else None

    def status_evidence(
        self,
        session: Session,
        stock_id: int,
        as_of_at: datetime,
    ) -> tuple[dict[str, str], CorporateEventEvidence]:
        rows = session.scalars(
            select(MarketStatus)
            .where(
                MarketStatus.stock_id == stock_id,
                MarketStatus.data_state == DataState.AVAILABLE.value,
                MarketStatus.collected_at <= as_of_at,
                MarketStatus.effective_from <= as_of_at,
                or_(
                    MarketStatus.effective_to.is_(None),
                    MarketStatus.effective_to >= as_of_at,
                ),
            )
            .order_by(
                MarketStatus.effective_from.desc(),
                MarketStatus.id.desc(),
            )
        ).all()
        latest: dict[str, str] = {}
        for row in rows:
            latest.setdefault(row.status_type, row.status_value)
        event_value = latest.get("CORPORATE_EVENT_SCREEN")
        return (
            latest,
            CorporateEventEvidence(
                coverage_verified=event_value in {"CLEAR", "SEVERE", "REVIEW"},
                severe_event=(
                    event_value == "SEVERE" if event_value is not None else None
                ),
                manual_review_event=(
                    event_value == "REVIEW" if event_value is not None else None
                ),
                latest_event=event_value,
            ),
        )

    def price_rows(
        self,
        session: Session,
        stock_id: int,
        as_of_at: datetime,
    ) -> list[PriceDaily]:
        as_of_date = as_of_at.date()
        rows = session.scalars(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.trade_date <= as_of_date,
                PriceDaily.collected_at <= as_of_at,
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(PriceDaily.trade_date.desc(), PriceDaily.id.desc())
            .limit(360)
        ).all()
        if not rows:
            return []
        provider = rows[0].source_provider
        return [row for row in rows if row.source_provider == provider]

    def financial_value_map(
        self,
        session: Session,
        stock_id: int,
        as_of_date: date,
    ) -> tuple[
        FinancialScope,
        dict[str, Decimal | None],
        str | None,
        list[date],
    ]:
        scope, accounts = self._financial.latest_mapped_accounts(
            session,
            stock_id,
            as_of_date=as_of_date,
        )
        values: dict[str, Decimal | None] = {}
        currencies: set[str] = set()
        filing_dates: list[date] = []
        for item in accounts:
            values[item.metric_code] = (
                item.ttm_value if item.metric_code in FLOW_METRICS else item.value
            )
            if item.currency is not None:
                currencies.add(item.currency)
            filing_dates.append(item.filing_date)
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        return scope, values, currency, filing_dates

    def repeated_operating_losses(
        self,
        session: Session,
        stock_id: int,
        *,
        scope: FinancialScope,
        as_of_date: date,
    ) -> int | None:
        if scope not in {
            FinancialScope.CONSOLIDATED,
            FinancialScope.SEPARATE,
        }:
            return None
        rows = session.execute(
            select(
                FinancialStatement.business_year,
                FinancialAccount.current_amount,
            )
            .join(
                FinancialStatement,
                FinancialAccount.statement_id == FinancialStatement.id,
            )
            .where(
                FinancialStatement.stock_id == stock_id,
                FinancialStatement.fs_div == scope.value,
                FinancialStatement.report_code == "11011",
                FinancialStatement.filing_date <= as_of_date,
                FinancialStatement.data_state == DataState.AVAILABLE.value,
                FinancialAccount.canonical_metric_code == "OPERATING_PROFIT",
                FinancialAccount.mapping_status == "MAPPED",
            )
            .order_by(
                FinancialStatement.business_year.desc(),
                FinancialStatement.filing_date.desc(),
                FinancialStatement.receipt_no.desc(),
            )
        ).all()
        annual: dict[int, Decimal | None] = {}
        for business_year, value in rows:
            annual.setdefault(business_year, value)
        if not annual:
            return None
        repeated = 0
        for value in annual.values():
            if value is None:
                return None
            if value >= 0:
                break
            repeated += 1
        return repeated

    def valuation_for_stock(
        self,
        session: Session,
        stock_id: int,
        as_of_at: datetime,
    ) -> tuple[Decimal | None, Decimal | None]:
        as_of_date = as_of_at.date()
        _, values, currency, _ = self.financial_value_map(
            session,
            stock_id,
            as_of_date,
        )
        price = session.scalar(
            select(PriceDaily)
            .where(
                PriceDaily.stock_id == stock_id,
                PriceDaily.trade_date <= as_of_date,
                PriceDaily.collected_at <= as_of_at,
                PriceDaily.data_state == DataState.AVAILABLE.value,
            )
            .order_by(PriceDaily.trade_date.desc(), PriceDaily.id.desc())
        )
        if (
            price is None
            or price.market_cap is None
            or price.currency != "KRW"
            or currency != "KRW"
        ):
            return None, None
        income = values.get("PARENT_OWNERS_NET_INCOME")
        equity = values.get("PARENT_OWNERS_EQUITY")
        current_per = (
            price.market_cap / income if income is not None and income != 0 else None
        )
        current_pbr = (
            price.market_cap / equity if equity is not None and equity != 0 else None
        )
        return current_per, current_pbr

    def industry_peers(
        self,
        session: Session,
        *,
        as_of_at: datetime,
        detailed_industry: str | None,
        parent_industry: str | None,
    ) -> tuple[IndustryPeer, ...]:
        if detailed_industry is None and parent_industry is None:
            return ()
        as_of_date = as_of_at.date()
        classifications = session.scalars(
            select(StockClassification)
            .where(
                StockClassification.classification_system.in_(
                    {
                        DETAILED_INDUSTRY_SYSTEM,
                        PARENT_INDUSTRY_SYSTEM,
                    }
                ),
                StockClassification.data_state == DataState.AVAILABLE.value,
                StockClassification.collected_at <= as_of_at,
                or_(
                    StockClassification.valid_from.is_(None),
                    StockClassification.valid_from <= as_of_date,
                ),
                or_(
                    StockClassification.valid_to.is_(None),
                    StockClassification.valid_to >= as_of_date,
                ),
            )
            .order_by(
                StockClassification.stock_id,
                StockClassification.classification_system,
                StockClassification.valid_from.desc(),
                StockClassification.id.desc(),
            )
        ).all()
        by_stock: dict[int, dict[str, str]] = {}
        for row in classifications:
            by_stock.setdefault(row.stock_id, {}).setdefault(
                row.classification_system,
                row.classification_code,
            )
        candidate_ids = {
            stock_id
            for stock_id, values in by_stock.items()
            if (
                detailed_industry is not None
                and values.get(DETAILED_INDUSTRY_SYSTEM) == detailed_industry
            )
            or (
                parent_industry is not None
                and values.get(PARENT_INDUSTRY_SYSTEM) == parent_industry
            )
        }
        stocks = session.scalars(
            select(Stock).where(
                Stock.id.in_(candidate_ids),
                Stock.is_active.is_(True),
            )
        ).all()
        peers: list[IndustryPeer] = []
        for peer_stock in stocks:
            per, pbr = self.valuation_for_stock(
                session,
                peer_stock.id,
                as_of_at,
            )
            _, values, _, _ = self.financial_value_map(
                session,
                peer_stock.id,
                as_of_date,
            )
            income = values.get("PARENT_OWNERS_NET_INCOME")
            equity = values.get("PARENT_OWNERS_EQUITY")
            roe = (
                income / equity
                if income is not None and equity is not None and equity > 0
                else None
            )
            classification = by_stock.get(peer_stock.id, {})
            peers.append(
                IndustryPeer(
                    symbol=peer_stock.symbol,
                    detailed_industry=classification.get(DETAILED_INDUSTRY_SYSTEM),
                    parent_industry=classification.get(PARENT_INDUSTRY_SYSTEM),
                    per=per,
                    pbr=pbr,
                    roe=roe,
                )
            )
        return tuple(peers)

    def historical_values(
        self,
        session: Session,
        stock_id: int,
        metric_code: str,
        as_of_at: datetime,
    ) -> tuple[Decimal, ...]:
        rows = session.scalars(
            select(FinancialMetric)
            .where(
                FinancialMetric.stock_id == stock_id,
                FinancialMetric.metric_code == metric_code,
                FinancialMetric.period_end <= as_of_at.date(),
                FinancialMetric.collected_at <= as_of_at,
                FinancialMetric.data_state == DataState.AVAILABLE.value,
                FinancialMetric.value.is_not(None),
            )
            .order_by(FinancialMetric.period_end.desc())
            .limit(5)
        ).all()
        return tuple(row.value for row in reversed(rows) if row.value is not None)
