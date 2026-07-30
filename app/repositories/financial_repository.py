from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models.disclosure import Disclosure
from app.db.models.financial import (
    AuditOpinion,
    Dividend,
    DividendFact,
    FinancialAccount,
    FinancialStatement,
)
from app.db.models.market import Stock
from app.models.financial import (
    AuditOpinionView,
    DartAuditOpinionItem,
    DartDividendFactItem,
    DartFinancialAccountItem,
    DividendView,
    FinancialAccountView,
    parse_dart_decimal,
)
from app.models.metadata import DataState, DataTiming, FinancialScope
from app.services.account_mapping import map_xbrl_account
from app.services.dividend_service import parse_confirmed_dividend_fact
from app.utils.financial_math import ttm_from_annual_and_interim

_TOTAL_DIVIDEND_LABELS = {
    "현금배당금총액(백만원)",
    "현금배당금총액 (백만원)",
}
_REPORT_PERIOD_RANK = {
    "11013": 1,
    "11012": 2,
    "11014": 3,
    "11011": 4,
}


class FinancialRepository:
    def get_stock(self, session: Session, symbol: str) -> Stock | None:
        return session.scalar(select(Stock).where(Stock.symbol == symbol))

    def upsert_financial_accounts(
        self,
        session: Session,
        *,
        stock: Stock,
        records: list[DartFinancialAccountItem],
        scope: FinancialScope,
        disclosure: Disclosure,
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> tuple[int, int]:
        records_by_section: dict[str, list[DartFinancialAccountItem]] = defaultdict(
            list
        )
        for record in records:
            records_by_section[record.statement_section].append(record)

        statements = 0
        accounts = 0
        for section, section_records in records_by_section.items():
            first = section_records[0]
            statement = session.scalar(
                select(FinancialStatement).where(
                    FinancialStatement.receipt_no == first.receipt_no,
                    FinancialStatement.statement_kind == section,
                    FinancialStatement.fs_div == scope.value,
                )
            )
            if statement is None:
                statement = FinancialStatement(
                    stock_id=stock.id,
                    receipt_no=first.receipt_no,
                    statement_kind=section,
                    fs_div=scope.value,
                )
                session.add(statement)
            statement.raw_response_id = raw_response_id
            statement.corp_code = first.corp_code
            statement.original_receipt_no = disclosure.original_receipt_no
            statement.report_name = disclosure.report_name
            statement.report_code = first.report_code
            statement.business_year = first.business_year
            statement.period_start = None
            statement.period_end = None
            statement.period_label = first.current_period_name
            statement.filing_date = disclosure.receipt_date
            statement.is_cumulative = None
            statement.is_correction = disclosure.is_correction
            section_currencies = {
                record.currency
                for record in section_records
                if record.currency is not None
            }
            statement.currency = (
                next(iter(section_currencies)) if len(section_currencies) == 1 else None
            )
            statement.source_url = disclosure.source_url
            statement.source_provider = "OpenDART"
            statement.source_function = "단일회사 전체 재무제표"
            statement.data_state = DataState.AVAILABLE.value
            statement.as_of_at = None
            statement.collected_at = collected_at
            statement.data_timing = DataTiming.PERIODIC_DISCLOSURE.value
            session.flush()
            statements += 1

            for record in section_records:
                account_detail = record.account_detail or ""
                account = session.scalar(
                    select(FinancialAccount).where(
                        FinancialAccount.statement_id == statement.id,
                        FinancialAccount.account_id == record.account_id,
                        FinancialAccount.account_name == record.account_name,
                        FinancialAccount.account_detail == account_detail,
                        FinancialAccount.statement_section == record.statement_section,
                    )
                )
                if account is None:
                    account = FinancialAccount(
                        statement_id=statement.id,
                        account_id=record.account_id,
                        account_detail=account_detail,
                        account_name=record.account_name,
                        mapping_status="UNMAPPED",
                    )
                    session.add(account)
                metric_code = map_xbrl_account(
                    record.account_id,
                    record.account_detail,
                )
                account.account_name = record.account_name
                account.statement_section = record.statement_section
                account.amount = record.current_amount
                account.current_amount = record.current_amount
                account.current_cumulative_amount = record.current_cumulative_amount
                account.prior_amount = record.prior_amount
                account.prior_quarter_amount = record.prior_quarter_amount
                account.prior_cumulative_amount = record.prior_cumulative_amount
                account.before_prior_amount = record.before_prior_amount
                account.unit = record.currency
                account.canonical_metric_code = metric_code
                account.mapping_status = (
                    "MAPPED" if metric_code is not None else "UNMAPPED"
                )
                account.raw_label = record.account_name
                accounts += 1
        session.flush()
        return statements, accounts

    def upsert_dividends(
        self,
        session: Session,
        *,
        stock: Stock,
        business_year: int,
        records: list[DartDividendFactItem],
        disclosures: dict[str, Disclosure],
        raw_response_id: int | None,
        collected_at: datetime,
    ) -> tuple[int, int]:
        fact_count = 0
        for item in records:
            fact = session.scalar(
                select(DividendFact).where(
                    DividendFact.stock_id == stock.id,
                    DividendFact.receipt_no == item.receipt_no,
                    DividendFact.label == item.label,
                    DividendFact.stock_kind == item.stock_kind,
                )
            )
            if fact is None:
                fact = DividendFact(
                    stock_id=stock.id,
                    receipt_no=item.receipt_no,
                    label=item.label,
                    stock_kind=item.stock_kind,
                )
                session.add(fact)
            disclosure = disclosures.get(item.receipt_no)
            parsed_dps = parse_confirmed_dividend_fact(
                label=item.label,
                raw_value=item.current_raw,
            )
            fact.raw_response_id = raw_response_id
            fact.business_year = business_year
            fact.current_raw = item.current_raw
            fact.prior_raw = item.prior_raw
            fact.before_prior_raw = item.before_prior_raw
            fact.fiscal_date = item.fiscal_date
            fact.filing_date = (
                disclosure.receipt_date if disclosure is not None else None
            )
            fact.unit_status = (
                "VERIFIED_FROM_LABEL"
                if parsed_dps is not None
                or item.label.strip() in _TOTAL_DIVIDEND_LABELS
                else "NOT_VERIFIED"
            )
            fact.source_url = (
                disclosure.source_url
                if disclosure is not None
                else (f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.receipt_no}")
            )
            fact.source_provider = "OpenDART"
            fact.source_function = "배당에 관한 사항"
            fact.data_state = DataState.AVAILABLE.value
            fact.as_of_at = None
            fact.collected_at = collected_at
            fact.data_timing = DataTiming.PERIODIC_DISCLOSURE.value
            fact_count += 1

        total_by_receipt: dict[str, Decimal | None] = {}
        for item in records:
            if item.label.strip() in _TOTAL_DIVIDEND_LABELS:
                total = parse_dart_decimal(item.current_raw)
                total_by_receipt[item.receipt_no] = (
                    None if total is None else total * 1_000_000
                )

        dividend_count = 0
        for item in records:
            parsed = parse_confirmed_dividend_fact(
                label=item.label,
                raw_value=item.current_raw,
            )
            if parsed is None:
                continue
            dps, currency = parsed
            dividend = session.scalar(
                select(Dividend).where(
                    Dividend.stock_id == stock.id,
                    Dividend.receipt_no == item.receipt_no,
                    Dividend.business_year == business_year,
                    Dividend.stock_kind == item.stock_kind,
                    Dividend.dividend_type == "CASH_DPS",
                )
            )
            if dividend is None:
                dividend = Dividend(
                    stock_id=stock.id,
                    business_year=business_year,
                    receipt_no=item.receipt_no,
                    stock_kind=item.stock_kind,
                    dividend_type="CASH_DPS",
                )
                session.add(dividend)
            disclosure = disclosures.get(item.receipt_no)
            dividend.original_receipt_no = (
                disclosure.original_receipt_no if disclosure is not None else None
            )
            dividend.dps = dps
            dividend.currency = currency
            dividend.total_amount = total_by_receipt.get(item.receipt_no)
            dividend.fiscal_date = item.fiscal_date
            dividend.record_date = None
            dividend.payment_date = None
            dividend.filing_date = (
                disclosure.receipt_date if disclosure is not None else None
            )
            dividend.source_url = (
                disclosure.source_url
                if disclosure is not None
                else (f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.receipt_no}")
            )
            dividend.is_confirmed = True
            dividend.is_estimate = False
            dividend.is_correction = (
                disclosure.is_correction if disclosure is not None else False
            )
            dividend.source_provider = "OpenDART"
            dividend.source_function = "배당에 관한 사항"
            dividend.data_state = DataState.AVAILABLE.value
            dividend.as_of_at = None
            dividend.collected_at = collected_at
            dividend.data_timing = DataTiming.PERIODIC_DISCLOSURE.value
            dividend_count += 1
        session.flush()
        return fact_count, dividend_count

    def upsert_audit_opinions(
        self,
        session: Session,
        *,
        stock: Stock,
        records: list[DartAuditOpinionItem],
        disclosures: dict[str, Disclosure],
        collected_at: datetime,
    ) -> int:
        stored = 0
        for item in records:
            row = session.scalar(
                select(AuditOpinion).where(
                    AuditOpinion.receipt_no == item.receipt_no,
                    AuditOpinion.business_year == item.business_year,
                )
            )
            if row is None:
                row = AuditOpinion(
                    stock_id=stock.id,
                    receipt_no=item.receipt_no,
                    business_year=item.business_year,
                )
                session.add(row)
            disclosure = disclosures.get(item.receipt_no)
            row.original_receipt_no = (
                disclosure.original_receipt_no if disclosure is not None else None
            )
            row.fiscal_date = item.fiscal_date
            row.auditor = item.auditor
            row.opinion = item.opinion
            row.special_matter = item.special_matter
            row.emphasis_matter = item.emphasis_matter
            row.core_audit_matter = item.core_audit_matter
            row.going_concern_risk = None
            row.going_concern_status = "NOT_VERIFIED"
            row.emphasis_status = (
                "AVAILABLE" if item.emphasis_matter is not None else "NOT_VERIFIED"
            )
            row.internal_control_issue = None
            row.filing_date = (
                disclosure.receipt_date if disclosure is not None else None
            )
            row.source_url = (
                disclosure.source_url
                if disclosure is not None
                else (f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.receipt_no}")
            )
            row.is_correction = (
                disclosure.is_correction if disclosure is not None else False
            )
            row.source_provider = "OpenDART"
            row.source_function = "회계감사인의 명칭 및 감사의견"
            row.data_state = DataState.AVAILABLE.value
            row.as_of_at = None
            row.collected_at = collected_at
            row.data_timing = DataTiming.PERIODIC_DISCLOSURE.value
            stored += 1
        session.flush()
        return stored

    def latest_mapped_accounts(
        self,
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> tuple[FinancialScope, tuple[FinancialAccountView, ...]]:
        statement = (
            select(FinancialAccount, FinancialStatement)
            .join(
                FinancialStatement,
                FinancialAccount.statement_id == FinancialStatement.id,
            )
            .where(
                FinancialStatement.stock_id == stock_id,
                FinancialStatement.data_state == DataState.AVAILABLE.value,
                FinancialAccount.canonical_metric_code.is_not(None),
                FinancialAccount.mapping_status == "MAPPED",
            )
            .order_by(
                FinancialStatement.business_year.desc(),
                case(
                    (FinancialStatement.report_code == "11011", 4),
                    (FinancialStatement.report_code == "11014", 3),
                    (FinancialStatement.report_code == "11012", 2),
                    (FinancialStatement.report_code == "11013", 1),
                    else_=0,
                ).desc(),
                FinancialStatement.filing_date.desc(),
                FinancialStatement.receipt_no.desc(),
                case(
                    (FinancialStatement.statement_kind == "IS", 0),
                    (FinancialStatement.statement_kind == "CIS", 1),
                    (FinancialStatement.statement_kind == "CF", 2),
                    (FinancialStatement.statement_kind == "BS", 3),
                    else_=4,
                ),
            )
        )
        if as_of_date is not None:
            statement = statement.where(FinancialStatement.filing_date <= as_of_date)
        rows = session.execute(statement).all()
        latest_report_period = max(
            (
                (
                    statement.business_year,
                    _REPORT_PERIOD_RANK.get(statement.report_code, 0),
                )
                for _, statement in rows
            ),
            default=None,
        )
        available_scopes = {
            statement.fs_div
            for _, statement in rows
            if (
                statement.business_year,
                _REPORT_PERIOD_RANK.get(statement.report_code, 0),
            )
            == latest_report_period
        }
        if FinancialScope.CONSOLIDATED.value in available_scopes:
            scope = FinancialScope.CONSOLIDATED
        elif FinancialScope.SEPARATE.value in available_scopes:
            scope = FinancialScope.SEPARATE
        else:
            scope = FinancialScope.UNKNOWN
        annual_values: dict[
            tuple[int, str],
            tuple[Decimal | None, str | None],
        ] = {}
        for account, statement in rows:
            if (
                statement.fs_div == scope.value
                and statement.report_code == "11011"
                and account.canonical_metric_code is not None
            ):
                annual_values.setdefault(
                    (
                        statement.business_year,
                        account.canonical_metric_code,
                    ),
                    (account.current_amount, account.unit),
                )
        result: list[FinancialAccountView] = []
        seen: set[str] = set()
        for account, statement in rows:
            metric_code = account.canonical_metric_code
            if metric_code is None or metric_code in seen:
                continue
            if statement.fs_div != scope.value:
                continue
            if (
                statement.business_year,
                _REPORT_PERIOD_RANK.get(statement.report_code, 0),
            ) != latest_report_period:
                continue
            seen.add(metric_code)
            ttm_value = None
            if account.statement_section in {"IS", "CIS", "CF"}:
                if statement.report_code == "11011":
                    ttm_value = account.current_amount
                else:
                    prior_annual = annual_values.get(
                        (statement.business_year - 1, metric_code)
                    )
                    if prior_annual is not None and prior_annual[1] == account.unit:
                        ttm_value = ttm_from_annual_and_interim(
                            prior_annual=prior_annual[0],
                            current_cumulative=(account.current_cumulative_amount),
                            prior_cumulative=(account.prior_cumulative_amount),
                        )
            result.append(
                FinancialAccountView(
                    metric_code=metric_code,
                    account_name=account.account_name,
                    value=account.current_amount,
                    cumulative_value=account.current_cumulative_amount,
                    ttm_value=ttm_value,
                    currency=account.unit,
                    statement_section=account.statement_section,
                    business_year=statement.business_year,
                    report_code=statement.report_code,
                    fs_div=FinancialScope(statement.fs_div),
                    filing_date=statement.filing_date,
                    receipt_no=statement.receipt_no,
                    source_url=statement.source_url,
                    mapping_status=account.mapping_status,
                    calculation_source=(
                        "SELF_CALCULATED" if ttm_value is not None else None
                    ),
                )
            )
        return scope, tuple(result)

    def dividend_history(
        self,
        session: Session,
        stock_id: int,
        *,
        limit_years: int = 5,
        as_of_date: date | None = None,
    ) -> tuple[DividendView, ...]:
        statement = (
            select(Dividend)
            .where(
                Dividend.stock_id == stock_id,
                Dividend.data_state == DataState.AVAILABLE.value,
            )
            .order_by(
                Dividend.business_year.desc(),
                Dividend.filing_date.desc(),
                Dividend.receipt_no.desc(),
            )
        )
        if as_of_date is not None:
            statement = statement.where(Dividend.filing_date <= as_of_date)
        rows = session.scalars(statement).all()
        years: list[int] = []
        seen: set[tuple[int, str | None]] = set()
        result: list[DividendView] = []
        for row in rows:
            if row.business_year not in years:
                if len(years) >= limit_years:
                    continue
                years.append(row.business_year)
            key = (row.business_year, row.stock_kind)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                DividendView(
                    business_year=row.business_year,
                    stock_kind=row.stock_kind,
                    dps=row.dps,
                    currency=row.currency,
                    total_amount=row.total_amount,
                    fiscal_date=row.fiscal_date,
                    filing_date=row.filing_date,
                    receipt_no=row.receipt_no,
                    is_confirmed=row.is_confirmed,
                    is_estimate=row.is_estimate,
                    source_url=row.source_url,
                )
            )
        return tuple(result)

    def latest_audit(
        self,
        session: Session,
        stock_id: int,
        *,
        as_of_date: date | None = None,
    ) -> AuditOpinionView | None:
        statement = (
            select(AuditOpinion)
            .where(
                AuditOpinion.stock_id == stock_id,
                AuditOpinion.data_state == DataState.AVAILABLE.value,
            )
            .order_by(
                AuditOpinion.business_year.desc(),
                AuditOpinion.filing_date.desc(),
                AuditOpinion.receipt_no.desc(),
            )
        )
        if as_of_date is not None:
            statement = statement.where(AuditOpinion.filing_date <= as_of_date)
        row = session.scalar(statement)
        if row is None:
            return None
        return AuditOpinionView(
            business_year=row.business_year,
            auditor=row.auditor,
            opinion=row.opinion,
            fiscal_date=row.fiscal_date,
            filing_date=row.filing_date,
            receipt_no=row.receipt_no,
            special_matter=row.special_matter,
            emphasis_matter=row.emphasis_matter,
            core_audit_matter=row.core_audit_matter,
            going_concern_risk=row.going_concern_risk,
            going_concern_status=row.going_concern_status,
            emphasis_status=row.emphasis_status,
            source_url=row.source_url,
        )
