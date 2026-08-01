from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models.market import PriceDaily, Stock
from app.models.metadata import DataState
from app.models.scoring import (
    AuditFilterEvidence,
    DataConfidenceEvidence,
    DividendPayment,
    DividendQualityEvidence,
    EntityKind,
    EntryEvidence,
    FinancialQualityEvidence,
    FinancialRiskEvidence,
    IndustryPeer,
    LiquidityEvidence,
    MarketFilterEvidence,
    Phase2Evidence,
    Phase2Rules,
    ValuationEvidence,
)
from app.repositories.financial_repository import FinancialRepository
from app.repositories.phase2_input_repository import (
    DART_DETAILED_INDUSTRY_SYSTEM,
    DART_INDUSTRY_KIND_SYSTEM,
    DART_PARENT_INDUSTRY_SYSTEM,
    DETAILED_INDUSTRY_SYSTEM,
    INDUSTRY_KIND_SYSTEM,
    MARKET_STATUS_TYPES,
    PARENT_INDUSTRY_SYSTEM,
    Phase2InputRepository,
)
from app.repositories.price_repository import PriceRepository
from app.utils.dates import restore_database_kst
from app.utils.technical_indicators import calculate_technical_snapshot

_CORE_FINANCIAL_METRICS = {
    "REVENUE",
    "OPERATING_PROFIT",
    "PARENT_OWNERS_NET_INCOME",
    "OPERATING_CASH_FLOW",
    "CAPEX_TANGIBLE",
    "CAPEX_INTANGIBLE",
    "FINANCE_COSTS",
    "ASSETS",
    "LIABILITIES",
    "PARENT_OWNERS_EQUITY",
}
_MARKET_STATUS_VALUES = {
    "TRADING_STATUS": frozenset({"NORMAL", "SUSPENDED"}),
    "MANAGEMENT_STATUS": frozenset({"NORMAL", "MANAGEMENT"}),
    "DELISTING_RISK": frozenset({"CLEAR", "RISK"}),
}


def _stock_snapshot_available(stock: Stock, as_of_at: datetime) -> bool:
    timestamps = (stock.collected_at, stock.as_of_at)
    return stock.data_state == DataState.AVAILABLE.value and all(
        value is None or restore_database_kst(value) <= as_of_at for value in timestamps
    )


def _entity_kind(value: str | None) -> EntityKind:
    if value == EntityKind.NON_FINANCIAL.value:
        return EntityKind.NON_FINANCIAL
    if value == EntityKind.FINANCIAL.value:
        return EntityKind.FINANCIAL
    return EntityKind.UNKNOWN


def _status_flag(
    values: dict[str, str],
    status_type: str,
    adverse_value: str,
) -> bool | None:
    value = values.get(status_type)
    if value not in _MARKET_STATUS_VALUES[status_type]:
        return None
    return value == adverse_value


def _effective_industry_sample_size(
    peers: tuple[IndustryPeer, ...],
    *,
    detailed_industry: str | None,
    parent_industry: str | None,
    minimum_sample: int,
) -> int:
    def selected_count(metric: str) -> int:
        detailed_count = sum(
            peer.detailed_industry == detailed_industry
            and (value := getattr(peer, metric)) is not None
            and value > 0
            for peer in peers
            if detailed_industry is not None
        )
        if detailed_count >= minimum_sample:
            return detailed_count
        return sum(
            peer.parent_industry == parent_industry
            and (value := getattr(peer, metric)) is not None
            and value > 0
            for peer in peers
            if parent_industry is not None
        )

    return min(selected_count("per"), selected_count("pbr"))


def _liquidity_evidence(
    rows: list[PriceDaily],
    *,
    planned_order_amount: Decimal | None,
    rules: Phase2Rules,
) -> LiquidityEvidence:
    trading_values = tuple(
        row.trading_value
        for row in reversed(rows[: rules.liquidity_days])
        if row.trading_value is not None
    )
    volumes = tuple(
        row.volume
        for row in reversed(rows[: rules.zero_volume_days])
        if row.volume is not None
    )
    currencies = {row.currency for row in rows if row.currency is not None}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return LiquidityEvidence(
        trading_values_60=trading_values,
        volumes_20=volumes,
        currency=currency,
        source_verified=(
            len(rows) >= rules.liquidity_days
            and currency == "KRW"
            and all(
                row.source_provider in {"KRX", "KIS", "한국투자증권"}
                for row in rows[: rules.liquidity_days]
            )
        ),
        planned_order_amount=planned_order_amount,
    )


class Phase2InputAssembler:
    def __init__(
        self,
        financial_repository: FinancialRepository | None = None,
        price_repository: PriceRepository | None = None,
        input_repository: Phase2InputRepository | None = None,
    ) -> None:
        self._financial = financial_repository or FinancialRepository()
        self._price = price_repository or PriceRepository()
        self._input = input_repository or Phase2InputRepository(self._financial)

    def assemble(
        self,
        session: Session,
        stock: Stock,
        *,
        as_of_at: datetime,
        rules: Phase2Rules,
        planned_order_amount: Decimal | None,
    ) -> Phase2Evidence:
        as_of_date = as_of_at.date()
        stock_snapshot_available = _stock_snapshot_available(stock, as_of_at)
        status_values, corporate_event = self._input.status_evidence(
            session,
            stock.id,
            as_of_at,
        )
        market_coverage = MARKET_STATUS_TYPES <= set(status_values) and all(
            status_values[status_type] in _MARKET_STATUS_VALUES[status_type]
            for status_type in MARKET_STATUS_TYPES
        )
        market = MarketFilterEvidence(
            is_kospi=stock.is_kospi if stock_snapshot_available else None,
            product_type=(stock.security_type if stock_snapshot_available else None),
            share_class=(stock.share_class if stock_snapshot_available else None),
            listing_status=(stock.listing_status if stock_snapshot_available else None),
            official_status_coverage=market_coverage,
            trading_suspended=_status_flag(
                status_values,
                "TRADING_STATUS",
                "SUSPENDED",
            ),
            management_issue=_status_flag(
                status_values,
                "MANAGEMENT_STATUS",
                "MANAGEMENT",
            ),
            delisting_risk=_status_flag(
                status_values,
                "DELISTING_RISK",
                "RISK",
            ),
        )
        audit_view = self._financial.latest_audit(
            session,
            stock.id,
            as_of_date=as_of_date,
        )
        audit = (
            AuditFilterEvidence(
                opinion=audit_view.opinion,
                filing_date=audit_view.filing_date,
                going_concern_risk=audit_view.going_concern_risk,
                going_concern_status=audit_view.going_concern_status,
            )
            if audit_view is not None
            else None
        )
        price_rows = self._input.price_rows(
            session,
            stock.id,
            as_of_at,
        )
        liquidity = _liquidity_evidence(
            price_rows,
            planned_order_amount=planned_order_amount,
            rules=rules,
        )
        scope, values, currency, filing_dates = self._input.financial_value_map(
            session,
            stock.id,
            as_of_date,
        )
        kind = _entity_kind(
            self._input.classification(
                session,
                stock.id,
                INDUSTRY_KIND_SYSTEM,
                as_of_at,
            )
            or self._input.classification(
                session,
                stock.id,
                DART_INDUSTRY_KIND_SYSTEM,
                as_of_at,
            )
        )
        repeated_losses = self._input.repeated_operating_losses(
            session,
            stock.id,
            scope=scope,
            as_of_date=as_of_date,
        )
        financial_risk = FinancialRiskEvidence(
            entity_kind=kind,
            operating_profit_ttm=values.get("OPERATING_PROFIT"),
            finance_costs_ttm=values.get("FINANCE_COSTS"),
            repeated_operating_loss_years=repeated_losses,
            currency=currency,
            financial_model_available=False,
        )
        dividend_rows = [
            row
            for row in self._financial.dividend_history(
                session,
                stock.id,
                limit_years=5,
                as_of_date=as_of_date,
            )
            if row.dps is not None
            and row.is_confirmed is True
            and row.is_estimate is False
            and row.stock_kind in {None, "보통주"}
        ]
        payments = tuple(
            DividendPayment(
                business_year=row.business_year,
                dps=row.dps,
            )
            for row in sorted(
                dividend_rows,
                key=lambda item: item.business_year,
            )
            if row.dps is not None
        )
        latest_dividend = dividend_rows[0] if dividend_rows else None
        dividend = DividendQualityEvidence(
            payments=payments,
            latest_total_dividend=(
                latest_dividend.total_amount if latest_dividend is not None else None
            ),
            parent_net_income_ttm=values.get("PARENT_OWNERS_NET_INCOME"),
            operating_cash_flow_ttm=values.get("OPERATING_CASH_FLOW"),
            capex_tangible_ttm=values.get("CAPEX_TANGIBLE"),
            capex_intangible_ttm=values.get("CAPEX_INTANGIBLE"),
            currency=currency,
        )
        financial_quality = FinancialQualityEvidence(
            revenue_ttm=values.get("REVENUE"),
            operating_profit_ttm=values.get("OPERATING_PROFIT"),
            parent_net_income_ttm=values.get("PARENT_OWNERS_NET_INCOME"),
            assets=values.get("ASSETS"),
            liabilities=values.get("LIABILITIES"),
            parent_equity=values.get("PARENT_OWNERS_EQUITY"),
            operating_cash_flow_ttm=values.get("OPERATING_CASH_FLOW"),
            currency=currency,
        )
        detailed_industry = self._input.classification(
            session,
            stock.id,
            DETAILED_INDUSTRY_SYSTEM,
            as_of_at,
        ) or self._input.classification(
            session,
            stock.id,
            DART_DETAILED_INDUSTRY_SYSTEM,
            as_of_at,
        )
        parent_industry = self._input.classification(
            session,
            stock.id,
            PARENT_INDUSTRY_SYSTEM,
            as_of_at,
        ) or self._input.classification(
            session,
            stock.id,
            DART_PARENT_INDUSTRY_SYSTEM,
            as_of_at,
        )
        current_per, current_pbr = self._input.valuation_for_stock(
            session,
            stock.id,
            as_of_at,
        )
        peers = self._input.industry_peers(
            session,
            as_of_at=as_of_at,
            detailed_industry=detailed_industry,
            parent_industry=parent_industry,
        )
        valuation = ValuationEvidence(
            current_per=current_per,
            current_pbr=current_pbr,
            detailed_industry=detailed_industry,
            parent_industry=parent_industry,
            peers=peers,
            historical_per=self._input.historical_values(
                session,
                stock.id,
                "PER",
                as_of_at,
            ),
            historical_pbr=self._input.historical_values(
                session,
                stock.id,
                "PBR",
                as_of_at,
            ),
            entity_kind=kind,
        )
        technical_history = self._price.history_for_symbol(
            session,
            stock.symbol,
            limit=260,
            as_of_date=as_of_date,
            as_of_at=as_of_at,
        )
        technical = calculate_technical_snapshot(technical_history)
        latest_close = (
            technical_history[-1].close
            if technical.state == DataState.AVAILABLE
            and technical_history
            and technical_history[-1].close > 0
            else None
        )
        entry = EntryEvidence(
            adjusted_price_verified=technical.state == DataState.AVAILABLE,
            close=latest_close,
            rsi_14=technical.rsi_14,
            sma_20=technical.sma_20,
            sma_60=technical.sma_60,
        )
        mapping_ratio = (
            Decimal(
                sum(
                    values.get(metric_code) is not None
                    for metric_code in _CORE_FINANCIAL_METRICS
                )
            )
            / Decimal(len(_CORE_FINANCIAL_METRICS))
            if values
            else None
        )
        adjusted_price_verified = (
            True
            if technical.state == DataState.AVAILABLE
            else (
                False
                if technical.state in {DataState.NOT_VERIFIED, DataState.CONFLICT}
                else None
            )
        )
        freshness_dates = [
            *(row.trade_date for row in price_rows[:1]),
            *(filing_dates[:1]),
            *(
                [audit_view.filing_date]
                if audit_view is not None and audit_view.filing_date is not None
                else []
            ),
            *(
                [latest_dividend.filing_date]
                if latest_dividend is not None
                and latest_dividend.filing_date is not None
                else []
            ),
        ]
        max_age_days = (
            max((as_of_date - value).days for value in freshness_dates)
            if freshness_dates
            else None
        )
        required_flags = (
            all(
                value is not None
                for value in (
                    market.is_kospi,
                    market.product_type,
                    market.share_class,
                    market.listing_status,
                )
            ),
            market.official_status_coverage,
            audit is not None,
            liquidity.source_verified,
            corporate_event.coverage_verified,
            kind != EntityKind.UNKNOWN,
            len(payments) == 5,
            currency is not None and bool(values),
            current_per is not None
            and current_pbr is not None
            and len(peers) >= rules.industry_minimum_sample,
            entry.adjusted_price_verified,
        )
        present_count = sum(required_flags)
        confidence = DataConfidenceEvidence(
            required_items_present=present_count,
            required_items_total=len(required_flags),
            max_age_days=max_age_days,
            official_source_ratio=(
                Decimal(present_count) / Decimal(len(required_flags))
            ),
            cross_validation_verified=None,
            industry_sample_size=(
                _effective_industry_sample_size(
                    peers,
                    detailed_industry=detailed_industry,
                    parent_industry=parent_industry,
                    minimum_sample=rules.industry_minimum_sample,
                )
                if peers
                else None
            ),
            adjusted_price_verified=adjusted_price_verified,
            account_mapping_ratio=mapping_ratio,
        )
        return Phase2Evidence(
            symbol=stock.symbol,
            as_of_at=as_of_at,
            market=market,
            audit=audit,
            liquidity=liquidity,
            corporate_event=corporate_event,
            financial_risk=financial_risk,
            dividend=dividend,
            financial_quality=financial_quality,
            valuation=valuation,
            confidence=confidence,
            entry=entry,
        )
