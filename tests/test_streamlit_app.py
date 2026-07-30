from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.config import get_settings
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.services.market_regime_service import MarketRegimeService
from app.services.phase2_service import Phase2ScoringService
from app.ui.stock_search import _format_going_concern
from app.utils.dates import SEOUL
from tests.helpers import migrate_database


def rendered_text(app: AppTest) -> str:
    collections = (
        app.title,
        app.subheader,
        app.markdown,
        app.caption,
        app.warning,
        app.error,
        app.info,
    )
    return "\n".join(
        str(element.value)
        for collection in collections
        for element in collection
    )


def test_verified_absence_of_going_concern_risk_is_not_shown_as_unknown() -> None:
    assert _format_going_concern("VERIFIED", False) == "중대한 불확실성 없음"
    assert (
        _format_going_concern("NOT_VERIFIED", False)
        == "확인 불가"
    )


def test_no_key_status_screen_opens_without_fake_market_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "streamlit.db", monkeypatch)
    get_settings.cache_clear()

    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    text = rendered_text(app)

    assert not app.exception
    assert "데이터 품질 · API 연결상태" in text
    assert "KRX" in text
    assert "OpenDART" in text
    assert "한국투자증권" in text
    assert "KIND" in text
    assert "네이버 뉴스" in text
    assert "ECOS" in text
    assert "데이터베이스" in text
    assert "키 미설정" in text
    assert "지원 보류" in text
    assert "연결됨" in text
    assert "추천 계산 가능 여부는 저장된 Phase 2" in text

    forbidden_operational_values = (
        "삼성전자",
        "SK하이닉스",
        "005930",
        "000660",
        "78,900",
        "2,669.81",
        "88점",
    )
    for forbidden_value in forbidden_operational_values:
        assert forbidden_value not in text


def test_market_dashboard_without_inputs_shows_specific_connection_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "menu.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=15).run()

    app.radio[0].set_value("시장국면 대시보드").run()
    text = rendered_text(app)

    assert not app.exception
    assert "저장된 Phase 3 시장 분석이 없습니다" in text
    assert "KRX 연결상태: 키 미설정" in text
    assert "삼성전자" not in text
    assert "005930" not in text


def test_saved_missing_market_snapshot_still_shows_provider_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = migrate_database(tmp_path / "missing-snapshot.db", monkeypatch)
    settings = get_settings()
    service = MarketRegimeService(
        settings.model_copy(update={"database_url": database_url})
    )
    try:
        service.analyze_and_store(
            as_of_date=datetime(2026, 7, 29, tzinfo=SEOUL).date(),
            as_of_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
        )
    finally:
        service.close()

    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.radio[0].set_value("시장국면 대시보드").run()
    text = rendered_text(app)

    assert not app.exception
    assert "핵심 데이터가 부족해 시장국면을 확정할 수 없습니다" in text
    assert "KRX 연결상태: 키 미설정" in text
    assert "OpenDART 연결상태: 키 미설정" in text
    assert "한국투자증권 연결상태: 키 미설정" in text


def test_phase5_menu_without_keys_shows_specific_reasons_and_no_fake_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "future-menu.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=15).run()

    app.radio[0].set_value("공시·뉴스").run()
    text = rendered_text(app)

    assert not app.exception
    assert "공시·뉴스·애널리스트·수급" in text
    assert "DART_API_KEY" in text
    assert "NCP_APIGW_API_KEY_ID" in text
    assert "KIND" in text
    assert "공식 공개 API 계약" in text
    assert "저장된 공식 이벤트가 없습니다" in text
    assert "자기주식 소각 결정" not in text
    assert "목표주가 100,000원" not in text


def test_phase6_menu_without_inputs_shows_no_fake_backtest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "phase6-menu.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=20).run()

    app.radio[0].set_value("백테스트").run()
    text = rendered_text(app)

    assert not app.exception
    assert "시점정보 기반 백테스트" in text
    assert "저장된 Phase 6 백테스트 실행이 없습니다" in text
    assert "시점별 유니버스" in text
    assert "상장폐지" in text
    assert "누적수익률 12.3%" not in text
    assert "삼성전자" not in text
    assert "005930" not in text


def test_phase4_menus_open_without_fake_recommendations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "phase4-menu.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=20).run()

    app.radio[0].set_value("추천종목").run()
    recommendation_text = rendered_text(app)
    assert not app.exception
    assert "저장된 Phase 4 추천 실행이 없습니다" in recommendation_text
    assert "가짜 추천 대신 데이터 부족 사유만 저장됩니다" in recommendation_text
    assert "005930" not in recommendation_text
    assert "88점" not in recommendation_text

    app.radio[0].set_value("포트폴리오").run()
    portfolio_text = rendered_text(app)
    assert not app.exception
    assert "사용자 포트폴리오 설정" in portfolio_text
    assert "사용자가 입력한 보유종목이 없습니다" in portfolio_text
    assert "005930" not in portfolio_text


def test_portfolio_money_inputs_use_integer_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "phase4-money-inputs.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=20).run()

    app.radio[0].set_value("포트폴리오").run()

    values = {item.label: item.value for item in app.number_input}
    assert isinstance(values["총 투자 가능자금(KRW, 0=미설정)"], int)
    assert isinstance(values["현재 보유현금(KRW)"], int)
    assert isinstance(values["평균매입가(KRW, 0=미입력)"], int)


def test_phase4_recommend_button_on_empty_database_saves_only_missing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "phase4-button.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=30).run()

    app.radio[0].set_value("추천종목").run()
    app.button[0].click().run()
    text = rendered_text(app)

    assert not app.exception
    assert "최신 추천 실행" in text
    assert "ACTIVE_KOSPI_UNIVERSE" in text
    assert "실제 KOSPI 유니버스가 저장되어 있지 않아" in text
    assert "005930" not in text
    assert "88점" not in text


def test_stock_search_with_empty_database_shows_connection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "empty-search.db", monkeypatch)
    get_settings.cache_clear()
    app = AppTest.from_file("app/main.py", default_timeout=15).run()

    app.radio[0].set_value("개별 종목 검색").run()
    text = rendered_text(app)

    assert not app.exception
    assert "실제 KRX 종목 데이터가 없습니다" in text
    assert "OpenDART: 키 미설정" in text
    assert "예시 종목을 대신 표시하지 않습니다" in text
    assert "005930" not in text
    assert "78,900" not in text


def test_stock_search_shows_saved_phase2_evidence_without_fake_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "phase2-ui.db", monkeypatch)
    settings = get_settings()
    as_of_at = datetime(2026, 7, 29, 15, 30, tzinfo=SEOUL)
    engine = create_db_engine(settings)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            Stock(
                symbol="000007",
                name_ko="Phase2검증종목",
                is_kospi=True,
                security_type="STOCK",
                share_class="COMMON",
                listing_status="LISTED",
                universe_status="INCLUDED",
                quality_state="VALID",
                is_active=True,
                source_provider="KRX",
                source_function="test fixture",
                data_state="AVAILABLE",
                as_of_at=as_of_at,
                collected_at=as_of_at,
            )
        )
    engine.dispose()
    scoring = Phase2ScoringService(settings)
    try:
        result = scoring.evaluate(
            "000007",
            as_of_at=as_of_at,
            planned_order_amount=Decimal(1000000),
        )
    finally:
        scoring.close()
    assert result is not None
    assert result.investment_score is None

    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.radio[0].set_value("개별 종목 검색").run()
    app.text_input[0].set_value("000007").run()
    text = rendered_text(app)

    assert not app.exception
    assert "강제필터" in text
    assert "누락된 핵심 데이터" in text
    assert "추천 계산 불가" in text
    assert "가짜" not in text
