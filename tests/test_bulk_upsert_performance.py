from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, func, select

from app.db.models.disclosure import Disclosure
from app.db.models.financial import Dividend, DividendFact, FinancialAccount
from app.db.models.market import PriceDaily, Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.financial import DartDividendFactItem, DartFinancialAccountItem
from app.models.metadata import FinancialScope
from app.models.price import KisAdjustedDailyPriceItem
from app.repositories.financial_repository import FinancialRepository
from app.repositories.price_repository import PriceRepository
from tests.helpers import make_settings, migrate_database

SEOUL = ZoneInfo("Asia/Seoul")
COLLECTED_AT = datetime(2026, 8, 6, 9, 0, tzinfo=SEOUL)
BULK_SIZE = 1_000


def _stock() -> Stock:
    return Stock(
        symbol="000001",
        name_ko="대량저장검증",
        is_kospi=True,
        security_type="STOCK",
        share_class="COMMON",
        listing_status="LISTED",
        universe_status="INCLUDED",
        quality_state="VALID",
        is_active=True,
        source_provider="KRX",
        source_function="유가증권 종목기본정보",
        data_state="AVAILABLE",
        collected_at=COLLECTED_AT,
        data_timing="NOT_APPLICABLE",
    )


def _count_selects(engine: object) -> tuple[list[str], object]:
    statements: list[str] = []

    def record_select(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_select)
    return statements, record_select


def test_large_repository_upserts_use_constant_select_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "bulk-upserts.db", monkeypatch)
    engine = create_db_engine(make_settings(database_url=database_url))
    sessions = create_session_factory(engine)
    repository = FinancialRepository()

    with sessions.begin() as session:
        stock = _stock()
        session.add(stock)
        session.flush()
        disclosure = Disclosure(
            stock_id=stock.id,
            receipt_no="20260331000001",
            corp_code="00126380",
            report_name="사업보고서",
            receipt_date=date(2026, 3, 31),
            is_correction=False,
            source_url="https://dart.fss.or.kr/",
            source_provider="OpenDART",
            source_function="공시검색",
            data_state="AVAILABLE",
            collected_at=COLLECTED_AT,
            data_timing="PERIODIC_DISCLOSURE",
        )
        session.add(disclosure)
        session.flush()

        adjusted_prices = [
            KisAdjustedDailyPriceItem.model_validate(
                {
                    "stck_bsop_date": (
                        date(2025, 1, 1) + timedelta(days=index)
                    ).strftime("%Y%m%d"),
                    "stck_clpr": "10000",
                    "stck_oprc": "9900",
                    "stck_hgpr": "10100",
                    "stck_lwpr": "9800",
                    "acml_vol": "1000",
                    "acml_tr_pbmn": "10000000",
                }
            )
            for index in range(BULK_SIZE)
        ]
        financial_accounts = [
            DartFinancialAccountItem.model_validate(
                {
                    "rcept_no": disclosure.receipt_no,
                    "reprt_code": "11011",
                    "bsns_year": "2025",
                    "corp_code": disclosure.corp_code,
                    "sj_div": "BS",
                    "sj_nm": "재무상태표",
                    "account_id": f"custom_Account{index}",
                    "account_nm": f"계정 {index}",
                    "account_detail": "",
                    "thstrm_nm": "제 1 기",
                    "thstrm_amount": str(index),
                    "ord": str(index),
                    "currency": "KRW",
                }
            )
            for index in range(BULK_SIZE)
        ]
        dividend_facts = [
            DartDividendFactItem.model_validate(
                {
                    "rcept_no": f"20260331{index:06d}",
                    "corp_cls": "Y",
                    "corp_code": disclosure.corp_code,
                    "corp_name": "대량저장검증",
                    "se": "주당 현금배당금(원)",
                    "stock_knd": "보통주",
                    "thstrm": str(100 + index),
                    "frmtrm": "100",
                    "lwfr": "90",
                    "stlm_dt": "2025-12-31",
                }
            )
            for index in range(BULK_SIZE)
        ]
        dividend_disclosures = {
            item.receipt_no: Disclosure(
                stock_id=stock.id,
                receipt_no=item.receipt_no,
                corp_code=disclosure.corp_code,
                report_name="사업보고서",
                receipt_date=date(2026, 3, 31),
                is_correction=False,
                source_url=f"https://dart.fss.or.kr/{item.receipt_no}",
            )
            for item in dividend_facts
        }

        selects, listener = _count_selects(engine)
        try:
            assert PriceRepository().upsert_kis_adjusted_records(
                session,
                stock.symbol,
                adjusted_prices,
                as_of_at=COLLECTED_AT,
                collected_at=COLLECTED_AT,
            ) == BULK_SIZE
            assert len(selects) == 2

            selects.clear()
            assert repository.upsert_financial_accounts(
                session,
                stock=stock,
                records=financial_accounts,
                scope=FinancialScope.CONSOLIDATED,
                disclosure=disclosure,
                raw_response_id=None,
                collected_at=COLLECTED_AT,
            ) == (1, BULK_SIZE)
            assert len(selects) == 2

            selects.clear()
            assert repository.upsert_dividends(
                session,
                stock=stock,
                business_year=2025,
                records=dividend_facts,
                disclosures=dividend_disclosures,
                raw_response_id=None,
                collected_at=COLLECTED_AT,
            ) == (BULK_SIZE, BULK_SIZE)
            assert len(selects) == 2

            # The update path must retain the same constant query count and
            # must not create a second copy of any row.
            selects.clear()
            assert PriceRepository().upsert_kis_adjusted_records(
                session,
                stock.symbol,
                adjusted_prices,
                as_of_at=COLLECTED_AT,
                collected_at=COLLECTED_AT,
            ) == BULK_SIZE
            assert len(selects) == 2

            selects.clear()
            assert repository.upsert_financial_accounts(
                session,
                stock=stock,
                records=financial_accounts,
                scope=FinancialScope.CONSOLIDATED,
                disclosure=disclosure,
                raw_response_id=None,
                collected_at=COLLECTED_AT,
            ) == (1, BULK_SIZE)
            assert len(selects) == 2

            selects.clear()
            assert repository.upsert_dividends(
                session,
                stock=stock,
                business_year=2025,
                records=dividend_facts,
                disclosures=dividend_disclosures,
                raw_response_id=None,
                collected_at=COLLECTED_AT,
            ) == (BULK_SIZE, BULK_SIZE)
            assert len(selects) == 2
        finally:
            event.remove(engine, "before_cursor_execute", listener)

    with sessions() as session:
        assert (
            session.scalar(select(func.count()).select_from(PriceDaily)) == BULK_SIZE
        )
        assert (
            session.scalar(select(func.count()).select_from(FinancialAccount))
            == BULK_SIZE
        )
        assert (
            session.scalar(select(func.count()).select_from(DividendFact)) == BULK_SIZE
        )
        assert session.scalar(select(func.count()).select_from(Dividend)) == BULK_SIZE
    engine.dispose()
