from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db.models.disclosure import Disclosure
from app.db.models.financial import FinancialAccount
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.financial import DartFinancialAccountItem
from app.models.metadata import FinancialScope
from app.repositories.financial_repository import FinancialRepository
from tests.helpers import make_settings, migrate_database

SEOUL = ZoneInfo("Asia/Seoul")


def test_duplicate_nonstandard_accounts_are_merged_within_one_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "duplicate-account.db", monkeypatch)
    settings = make_settings(database_url=database_url)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    collected_at = datetime(2026, 7, 30, 18, 0, tzinfo=SEOUL)
    with sessions.begin() as session:
        stock = Stock(
            symbol="000660",
            name_ko="SK하이닉스",
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
            as_of_at=collected_at,
            collected_at=collected_at,
            data_timing="NOT_APPLICABLE",
        )
        session.add(stock)
        session.flush()
        disclosure = Disclosure(
            stock_id=stock.id,
            receipt_no="20260318000123",
            corp_code="00164779",
            report_name="사업보고서",
            receipt_date=date(2026, 3, 18),
            is_correction=False,
            source_url="https://dart.fss.or.kr/",
            source_provider="OpenDART",
            source_function="공시검색",
            data_state="AVAILABLE",
            collected_at=collected_at,
            data_timing="PERIODIC_DISCLOSURE",
        )
        session.add(disclosure)
        session.flush()
        base = {
            "rcept_no": disclosure.receipt_no,
            "reprt_code": "11011",
            "bsns_year": 2025,
            "corp_code": "00164779",
            "sj_div": "BS",
            "sj_nm": "재무상태표",
            "account_id": "-표준계정코드 미사용-",
            "account_nm": "기타수취채권",
            "account_detail": "",
            "thstrm_nm": "제78기",
            "frmtrm_nm": "제77기",
            "ord": 1,
            "currency": "KRW",
        }
        records = [
            DartFinancialAccountItem.model_validate(
                {**base, "thstrm_amount": Decimal(100)}
            ),
            DartFinancialAccountItem.model_validate(
                {**base, "thstrm_amount": Decimal(200)}
            ),
        ]
        statements, accounts = FinancialRepository().upsert_financial_accounts(
            session,
            stock=stock,
            records=records,
            scope=FinancialScope.CONSOLIDATED,
            disclosure=disclosure,
            raw_response_id=None,
            collected_at=collected_at,
        )
        assert statements == 1
        assert accounts == 1
    with sessions() as session:
        rows = session.scalars(select(FinancialAccount)).all()
        assert len(rows) == 1
        assert rows[0].current_amount == Decimal(200)
    engine.dispose()
