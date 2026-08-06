from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models.financial import (
    FinancialAccount,
    FinancialMetric,
    FinancialStatement,
)
from app.db.models.market import PriceDaily, Stock, StockClassification
from app.db.session import (
    create_db_engine,
    create_session_factory,
    dispose_db_engine,
)
from app.models.metadata import DataState
from app.providers.base import ApiResponse
from app.providers.dart_analysis import (
    DART_COMPANY_ENDPOINT,
    DART_COMPANY_FUNCTION,
    OpenDartAnalysisProvider,
)
from app.providers.kis_reference import (
    KIS_CURRENT_VALUATION_ENDPOINT,
    KIS_CURRENT_VALUATION_FUNCTION,
    KisReferenceProvider,
)
from app.providers.krx_price import (
    KRX_DAILY_PRICE_ENDPOINT,
    KRX_DAILY_PRICE_FUNCTION,
    KRX_KOSDAQ_DAILY_PRICE_ENDPOINT,
    KRX_KOSDAQ_DAILY_PRICE_FUNCTION,
    KrxDailyPriceProvider,
)
from app.repositories.price_repository import PriceRepository
from app.repositories.raw_response_repository import RawResponseRepository
from app.repositories.stock_repository import StockRepository
from app.repositories.valuation_repository import ValuationRepository
from app.utils.dates import SEOUL, now_kst

_RULE_VERSION = "official-valuation-v1"
_CURRENT_METRICS = (("CURRENT_PER", "per"), ("CURRENT_PBR", "pbr"))
_ANNUAL_METRICS = {
    "PARENT_OWNERS_NET_INCOME",
    "PARENT_OWNERS_EQUITY",
}


@dataclass(frozen=True)
class AnnualValuationInput:
    business_year: int
    filing_date: date
    currency: str
    net_income: Decimal
    equity: Decimal
    fs_div: str


@dataclass(frozen=True)
class ValuationRefreshSummary:
    symbol: str
    state: DataState
    current_metrics_stored: int
    industry_samples: int
    historical_metrics_stored: int
    profiles_checked: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ValuationReference:
    comparison_label: str
    per_median: Decimal | None
    pbr_median: Decimal | None
    per_sample_count: int
    pbr_sample_count: int


class ValuationDataService:
    def __init__(
        self,
        settings: Settings,
        *,
        dart_provider: OpenDartAnalysisProvider | None = None,
        kis_provider: KisReferenceProvider | None = None,
        krx_provider: KrxDailyPriceProvider | None = None,
        kosdaq_krx_provider: KrxDailyPriceProvider | None = None,
    ) -> None:
        self._settings = settings
        self._dart = dart_provider or OpenDartAnalysisProvider(settings)
        self._kis = kis_provider or KisReferenceProvider(settings)
        self._krx_by_market = {
            True: krx_provider or KrxDailyPriceProvider(settings, market="KOSPI"),
            False: kosdaq_krx_provider
            or KrxDailyPriceProvider(settings, market="KOSDAQ"),
        }
        self._raw = RawResponseRepository(settings)
        self._stocks = StockRepository()
        self._prices = PriceRepository()
        self._valuations = ValuationRepository()
        self._engine = create_db_engine(settings)
        self._sessions = create_session_factory(self._engine)

    def reference_for_symbol(
        self,
        symbol: str,
        *,
        as_of_date: date,
    ) -> ValuationReference | None:
        """Return a display-only peer reference independent of Phase 2 eligibility.

        The recommendation engine keeps its configured minimum sample rule.  The
        individual-stock screen may still show the median of the peers already
        verified by DART and KIS, with the sample count exposed to the user.
        """
        with self._sessions() as session:
            target = session.scalar(
                select(Stock).where(
                    Stock.symbol == symbol,
                    Stock.is_active.is_(True),
                )
            )
            if target is None:
                return None
            classification_rows = session.scalars(
                select(StockClassification)
                .where(
                    StockClassification.stock_id == target.id,
                    StockClassification.classification_system.in_(
                        {"DART_INDUSTRY", "DART_PARENT_INDUSTRY"}
                    ),
                    StockClassification.data_state == DataState.AVAILABLE.value,
                )
                .order_by(
                    StockClassification.valid_from.desc(),
                    StockClassification.id.desc(),
                )
            ).all()
            classifications: dict[str, str] = {}
            for row in classification_rows:
                classifications.setdefault(
                    row.classification_system,
                    row.classification_code,
                )
            groups = (
                ("DART_INDUSTRY", "세부 동종업종"),
                ("DART_PARENT_INDUSTRY", "동종업종"),
            )
            for system, label in groups:
                code = classifications.get(system)
                if code is None:
                    continue
                peer_ids = list(
                    session.scalars(
                        select(Stock.id)
                        .distinct()
                        .join(
                            StockClassification,
                            StockClassification.stock_id == Stock.id,
                        )
                        .where(
                            StockClassification.classification_system == system,
                            StockClassification.classification_code == code,
                            StockClassification.data_state == DataState.AVAILABLE.value,
                            Stock.is_active.is_(True),
                            Stock.share_class == "COMMON",
                            Stock.id != target.id,
                        )
                    ).all()
                )
                per_values = self._latest_positive_metrics(
                    session,
                    peer_ids,
                    metric_code="CURRENT_PER",
                    as_of_date=as_of_date,
                )
                pbr_values = self._latest_positive_metrics(
                    session,
                    peer_ids,
                    metric_code="CURRENT_PBR",
                    as_of_date=as_of_date,
                )
                if per_values or pbr_values:
                    return ValuationReference(
                        comparison_label=label,
                        per_median=(median(per_values) if per_values else None),
                        pbr_median=(median(pbr_values) if pbr_values else None),
                        per_sample_count=len(per_values),
                        pbr_sample_count=len(pbr_values),
                    )
        return None

    @staticmethod
    def _latest_positive_metrics(
        session: Session,
        stock_ids: list[int],
        *,
        metric_code: str,
        as_of_date: date,
    ) -> list[Decimal]:
        if not stock_ids:
            return []
        ranked = (
            select(
                FinancialMetric.value.label("value"),
                func.row_number()
                .over(
                    partition_by=FinancialMetric.stock_id,
                    order_by=(
                        FinancialMetric.period_end.desc(),
                        FinancialMetric.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .where(
                FinancialMetric.stock_id.in_(stock_ids),
                FinancialMetric.metric_code == metric_code,
                FinancialMetric.period_end <= as_of_date,
                FinancialMetric.data_state == DataState.AVAILABLE.value,
                FinancialMetric.value.is_not(None),
                FinancialMetric.value > 0,
            )
            .subquery()
        )
        return list(session.scalars(select(ranked.c.value).where(ranked.c.rank == 1)))

    async def refresh(
        self,
        *,
        symbol: str,
        as_of_date: date,
    ) -> ValuationRefreshSummary:
        if as_of_date > now_kst().date():
            raise ValueError("as_of_date must not be in the future")
        errors: list[str] = []
        profiles_checked = 0
        with self._sessions() as session:
            target = session.scalar(
                select(Stock).where(
                    Stock.symbol == symbol,
                    Stock.is_active.is_(True),
                )
            )
            if target is None:
                return ValuationRefreshSummary(
                    symbol=symbol,
                    state=DataState.MISSING,
                    current_metrics_stored=0,
                    industry_samples=0,
                    historical_metrics_stored=0,
                    profiles_checked=0,
                    errors=("활성 종목을 찾을 수 없습니다.",),
                )
            target_id = target.id
            target_is_kospi = target.is_kospi
        if target_is_kospi is None:
            return self._summary(
                symbol,
                DataState.MISSING,
                profiles_checked=0,
                errors=["공식 시장구분을 확인할 수 없습니다."],
            )

        target_parent = self._classification(target_id, "DART_PARENT_INDUSTRY")
        if target_parent is None:
            target_parent, checked, profile_errors = await self._classify_stock(
                target_id
            )
            profiles_checked += checked
            errors.extend(profile_errors)
        if target_parent is None:
            return self._summary(
                symbol,
                DataState.MISSING,
                profiles_checked=profiles_checked,
                errors=errors or ["OpenDART 산업분류를 확인할 수 없습니다."],
            )

        desired_samples = self._settings.phase2_industry_minimum_sample
        peer_ids = self._matching_peer_ids(
            target_parent,
            is_kospi=target_is_kospi,
        )
        if len(peer_ids) < desired_samples:
            for candidate_id in self._candidate_stock_ids(
                exclude_ids=set(peer_ids),
                is_kospi=target_is_kospi,
            ):
                parent, checked, profile_errors = await self._classify_stock(
                    candidate_id
                )
                profiles_checked += checked
                errors.extend(profile_errors)
                if parent == target_parent:
                    peer_ids.append(candidate_id)
                if len(set(peer_ids)) >= desired_samples:
                    break
                if profiles_checked >= 200:
                    break
        peer_ids = list(dict.fromkeys([target_id, *peer_ids]))

        current_stored = 0
        usable_samples = 0
        as_of_at = datetime.combine(as_of_date, time.max, tzinfo=SEOUL)
        for peer_id in peer_ids:
            with self._sessions() as session:
                peer = session.get(Stock, peer_id)
                if peer is None:
                    continue
                peer_symbol = peer.symbol
            response = await self._kis.fetch_current_valuation(symbol=peer_symbol)
            self._save_raw(
                provider="한국투자증권",
                function_name=KIS_CURRENT_VALUATION_FUNCTION,
                endpoint=KIS_CURRENT_VALUATION_ENDPOINT,
                parameters={"symbol": peer_symbol},
                response=response,
            )
            if response.state != DataState.AVAILABLE or not response.payload:
                if peer_id == target_id:
                    errors.append(
                        response.error_message
                        or "대상 종목의 KIS PER·PBR 조회에 실패했습니다."
                    )
                continue
            item = response.payload[0]
            if item.per is not None and item.pbr is not None:
                usable_samples += 1
            with self._sessions.begin() as session:
                for metric_code, attribute in _CURRENT_METRICS:
                    value = getattr(item, attribute)
                    if value is None:
                        continue
                    self._valuations.upsert_metric(
                        session,
                        stock_id=peer_id,
                        metric_code=metric_code,
                        value=value,
                        period_end=as_of_date,
                        rule_version=_RULE_VERSION,
                        source_provider="한국투자증권",
                        source_function=KIS_CURRENT_VALUATION_FUNCTION,
                        collected_at=response.metadata.collected_at,
                        as_of_at=as_of_at,
                    )
                    current_stored += 1
            if (
                usable_samples >= self._settings.phase2_industry_minimum_sample
                and peer_id != target_id
            ):
                break

        historical_stored = await self._refresh_historical(
            stock_id=target_id,
            symbol=symbol,
            as_of_date=as_of_date,
            is_kospi=target_is_kospi,
            errors=errors,
        )
        target_current = self._current_metric_count(target_id, as_of_date)
        state = (
            DataState.AVAILABLE
            if target_current == 2
            and usable_samples >= self._settings.phase2_industry_minimum_sample
            and historical_stored >= self._settings.phase2_history_minimum_sample * 2
            else DataState.MISSING
        )
        return ValuationRefreshSummary(
            symbol=symbol,
            state=state,
            current_metrics_stored=current_stored,
            industry_samples=usable_samples,
            historical_metrics_stored=historical_stored,
            profiles_checked=profiles_checked,
            errors=tuple(dict.fromkeys(errors)),
        )

    async def _classify_stock(
        self,
        stock_id: int,
    ) -> tuple[str | None, int, list[str]]:
        with self._sessions() as session:
            stock = session.get(Stock, stock_id)
            if stock is None or not stock.dart_corp_code:
                return None, 0, []
            corp_code = stock.dart_corp_code
        response = await self._dart.fetch_company_profile(corp_code=corp_code)
        raw_id = self._save_raw(
            provider="OpenDART",
            function_name=DART_COMPANY_FUNCTION,
            endpoint=DART_COMPANY_ENDPOINT,
            parameters={"corp_code": corp_code},
            response=response,
        )
        if response.state != DataState.AVAILABLE or response.payload is None:
            return (
                None,
                1,
                [response.error_message or f"OpenDART 기업개황 조회 실패: {corp_code}"],
            )
        with self._sessions.begin() as session:
            stock = session.get(Stock, stock_id)
            if stock is None:
                return None, 1, ["산업분류 저장 중 종목이 사라졌습니다."]
            self._stocks.upsert_dart_industry(
                session,
                stock=stock,
                industry_code=response.payload.industry_code,
                as_of_at=(response.metadata.as_of_at or response.metadata.collected_at),
                collected_at=response.metadata.collected_at,
            )
            RawResponseRepository.set_normalization_result(
                session,
                raw_id,
                success=True,
            )
        return response.payload.industry_code[:2], 1, []

    def _classification(self, stock_id: int, system: str) -> str | None:
        with self._sessions() as session:
            return session.scalar(
                select(StockClassification.classification_code)
                .where(
                    StockClassification.stock_id == stock_id,
                    StockClassification.classification_system == system,
                    StockClassification.data_state == DataState.AVAILABLE.value,
                )
                .order_by(
                    StockClassification.valid_from.desc(),
                    StockClassification.id.desc(),
                )
            )

    def _matching_peer_ids(
        self,
        parent_code: str,
        *,
        is_kospi: bool,
    ) -> list[int]:
        with self._sessions() as session:
            return list(
                dict.fromkeys(
                    session.scalars(
                        select(StockClassification.stock_id)
                        .join(Stock, Stock.id == StockClassification.stock_id)
                        .where(
                            StockClassification.classification_system
                            == "DART_PARENT_INDUSTRY",
                            StockClassification.classification_code == parent_code,
                            StockClassification.data_state == DataState.AVAILABLE.value,
                            Stock.is_active.is_(True),
                            Stock.is_kospi.is_(is_kospi),
                            Stock.share_class == "COMMON",
                        )
                    ).all()
                )
            )

    def _candidate_stock_ids(
        self,
        *,
        exclude_ids: set[int],
        is_kospi: bool,
    ) -> list[int]:
        with self._sessions() as session:
            stocks = session.scalars(
                select(Stock).where(
                    Stock.is_active.is_(True),
                    Stock.is_kospi.is_(is_kospi),
                    Stock.share_class == "COMMON",
                    Stock.dart_corp_code.is_not(None),
                )
            ).all()
            rows = session.execute(
                select(PriceDaily.stock_id, PriceDaily.market_cap)
                .where(
                    PriceDaily.source_provider == "KRX",
                    PriceDaily.data_state == DataState.AVAILABLE.value,
                    PriceDaily.market_cap.is_not(None),
                )
                .order_by(
                    PriceDaily.trade_date.desc(),
                    PriceDaily.id.desc(),
                )
            ).all()
        latest_caps: dict[int, Decimal] = {}
        for stock_id, market_cap in rows:
            latest_caps.setdefault(stock_id, market_cap)
        return [
            stock.id
            for stock in sorted(
                stocks,
                key=lambda item: latest_caps.get(item.id, Decimal(0)),
                reverse=True,
            )
            if stock.id not in exclude_ids
            and self._classification(stock.id, "DART_PARENT_INDUSTRY") is None
        ]

    async def _refresh_historical(
        self,
        *,
        stock_id: int,
        symbol: str,
        as_of_date: date,
        is_kospi: bool,
        errors: list[str],
    ) -> int:
        krx_provider = self._krx_by_market[is_kospi]
        krx_function = (
            KRX_DAILY_PRICE_FUNCTION if is_kospi else KRX_KOSDAQ_DAILY_PRICE_FUNCTION
        )
        krx_endpoint = (
            KRX_DAILY_PRICE_ENDPOINT if is_kospi else KRX_KOSDAQ_DAILY_PRICE_ENDPOINT
        )
        annual_inputs = self._annual_inputs(stock_id, as_of_date)
        stored = 0
        for annual in annual_inputs:
            target_date = date(annual.business_year, 12, 31)
            record = None
            for offset in range(11):
                trade_date = target_date - timedelta(days=offset)
                record = self._stored_krx_record(stock_id, trade_date)
                if record is not None:
                    break
                response = await krx_provider.fetch(as_of_date=trade_date)
                self._save_raw(
                    provider="KRX",
                    function_name=krx_function,
                    endpoint=krx_endpoint,
                    parameters={"basDd": trade_date.strftime("%Y%m%d")},
                    response=response,
                )
                if response.state != DataState.AVAILABLE or response.payload is None:
                    continue
                with self._sessions.begin() as session:
                    self._prices.upsert_krx_records(
                        session,
                        response.payload,
                        as_of_at=(
                            response.metadata.as_of_at or response.metadata.collected_at
                        ),
                        collected_at=response.metadata.collected_at,
                    )
                record = self._stored_krx_record(stock_id, trade_date)
                if record is not None:
                    break
            if (
                record is None
                or record.market_cap is None
                or record.close_price is None
                or record.listed_shares is None
                or record.market_cap <= 0
                or record.listed_shares <= 0
            ):
                errors.append(
                    f"{annual.business_year}년 KRX 연말 시가총액을 확인하지 못했습니다."
                )
                continue
            calculated_cap = record.close_price * record.listed_shares
            relative_gap = abs(record.market_cap - calculated_cap) / record.market_cap
            if relative_gap > Decimal("0.000001"):
                errors.append(
                    f"{annual.business_year}년 KRX 시가총액 교차검증에 실패했습니다."
                )
                continue
            values = {
                "PER": (
                    record.market_cap / annual.net_income
                    if annual.net_income > 0
                    else None
                ),
                "PBR": (
                    record.market_cap / annual.equity if annual.equity > 0 else None
                ),
            }
            with self._sessions.begin() as session:
                for metric_code, value in values.items():
                    if value is None:
                        continue
                    self._valuations.upsert_metric(
                        session,
                        stock_id=stock_id,
                        metric_code=metric_code,
                        value=value,
                        period_end=target_date,
                        rule_version=_RULE_VERSION,
                        source_provider="KRX/OpenDART",
                        source_function="연말 시가총액/연간 재무 실적",
                        collected_at=now_kst(),
                        as_of_at=datetime.combine(
                            annual.filing_date,
                            time.min,
                            tzinfo=SEOUL,
                        ),
                        fs_div=annual.fs_div,
                    )
                    stored += 1
        return stored

    def _annual_inputs(
        self,
        stock_id: int,
        as_of_date: date,
    ) -> tuple[AnnualValuationInput, ...]:
        with self._sessions() as session:
            rows = session.execute(
                select(
                    FinancialStatement.business_year,
                    FinancialStatement.filing_date,
                    FinancialStatement.currency,
                    FinancialStatement.fs_div,
                    FinancialAccount.canonical_metric_code,
                    FinancialAccount.current_amount,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.statement_id == FinancialStatement.id,
                )
                .where(
                    FinancialStatement.stock_id == stock_id,
                    FinancialStatement.report_code == "11011",
                    FinancialStatement.filing_date <= as_of_date,
                    FinancialStatement.data_state == DataState.AVAILABLE.value,
                    FinancialAccount.canonical_metric_code.in_(_ANNUAL_METRICS),
                    FinancialAccount.mapping_status == "MAPPED",
                    FinancialAccount.current_amount.is_not(None),
                )
                .order_by(
                    FinancialStatement.business_year.desc(),
                    case((FinancialStatement.fs_div == "CFS", 0), else_=1),
                    FinancialStatement.filing_date.desc(),
                    FinancialStatement.receipt_no.desc(),
                )
            ).all()
        grouped: dict[
            tuple[int, str],
            dict[str, object],
        ] = {}
        for year, filing, currency, fs_div, metric, value in rows:
            key = (year, fs_div)
            group = grouped.setdefault(
                key,
                {
                    "filing": filing,
                    "currency": currency,
                    "values": {},
                },
            )
            values = group["values"]
            if isinstance(values, dict):
                values.setdefault(metric, value)
        result: list[AnnualValuationInput] = []
        used_years: set[int] = set()
        for (year, fs_div), group in grouped.items():
            if year in used_years or group["currency"] != "KRW":
                continue
            values = group["values"]
            if not isinstance(values, dict):
                continue
            net_income = values.get("PARENT_OWNERS_NET_INCOME")
            equity = values.get("PARENT_OWNERS_EQUITY")
            filing = group["filing"]
            if not (
                isinstance(net_income, Decimal)
                and isinstance(equity, Decimal)
                and isinstance(filing, date)
            ):
                continue
            result.append(
                AnnualValuationInput(
                    business_year=year,
                    filing_date=filing,
                    currency="KRW",
                    net_income=net_income,
                    equity=equity,
                    fs_div=fs_div,
                )
            )
            used_years.add(year)
            if len(result) >= 5:
                break
        return tuple(result)

    def _stored_krx_record(
        self,
        stock_id: int,
        trade_date: date,
    ) -> PriceDaily | None:
        with self._sessions() as session:
            return session.scalar(
                select(PriceDaily).where(
                    PriceDaily.stock_id == stock_id,
                    PriceDaily.trade_date == trade_date,
                    PriceDaily.source_provider == "KRX",
                    PriceDaily.data_state == DataState.AVAILABLE.value,
                )
            )

    def _current_metric_count(self, stock_id: int, as_of_date: date) -> int:
        with self._sessions() as session:
            return len(
                {
                    row.metric_code
                    for row in session.scalars(
                        select(FinancialMetric).where(
                            FinancialMetric.stock_id == stock_id,
                            FinancialMetric.metric_code.in_(
                                {"CURRENT_PER", "CURRENT_PBR"}
                            ),
                            FinancialMetric.period_end <= as_of_date,
                            FinancialMetric.data_state == DataState.AVAILABLE.value,
                        )
                    ).all()
                }
            )

    def _save_raw(
        self,
        *,
        provider: str,
        function_name: str,
        endpoint: str,
        parameters: dict[str, object],
        response: ApiResponse[Any],
    ) -> int | None:
        with self._sessions.begin() as session:
            row = self._raw.save(
                session,
                provider=provider,
                function_name=function_name,
                endpoint=endpoint,
                request_parameters=parameters,
                response=response,
            )
            return row.id if row is not None else None

    @staticmethod
    def _summary(
        symbol: str,
        state: DataState,
        *,
        profiles_checked: int,
        errors: list[str],
    ) -> ValuationRefreshSummary:
        return ValuationRefreshSummary(
            symbol=symbol,
            state=state,
            current_metrics_stored=0,
            industry_samples=0,
            historical_metrics_stored=0,
            profiles_checked=profiles_checked,
            errors=tuple(dict.fromkeys(errors)),
        )

    def close(self) -> None:
        dispose_db_engine(self._engine)
