# pyright: reportArgumentType=false
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app.config import Settings, get_settings
from app.db.models.market import Stock
from app.db.session import create_db_engine, create_session_factory
from app.models.events import EarningsEstimateView
from app.models.metadata import DataState
from app.services.market_regime_service import MarketRegimeService
from app.services.phase2_service import Phase2ScoringService
from app.ui import market_dashboard as market_dashboard_ui
from app.ui.recommendations import _entry_readiness_label, _sorted_decisions
from app.ui.stock_search import (
    _dividend_frequency,
    _financial_chart_rows,
    _format_dividend_yield,
    _format_going_concern,
    _format_phase2_decision,
    _format_phase2_score,
    _forward_per_from_estimates,
    _stock_chart_rows,
)
from app.utils.dates import SEOUL
from app.utils.technical_indicators import AdjustedPricePoint
from tests.helpers import migrate_database

_API_CREDENTIAL_ENV_NAMES = (
    "KRX_API_KEY",
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "NCP_APIGW_API_KEY_ID",
    "NCP_APIGW_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "BOK_API_KEY",
    "ECOS_API_KEY",
)


@pytest.fixture(autouse=True)
def isolate_streamlit_tests_from_local_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _API_CREDENTIAL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


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
        str(element.value) for collection in collections for element in collection
    )


def test_forward_per_uses_nearest_future_period_and_latest_broker_values() -> None:
    estimates = (
        EarningsEstimateView(
            provider="TEST",
            broker="A증권",
            metric_code="EPS",
            fiscal_period="2026.12E",
            estimate_value=Decimal(900),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 6, 1),
            source_url=None,
            is_estimate=True,
        ),
        EarningsEstimateView(
            provider="TEST",
            broker="A증권",
            metric_code="EPS",
            fiscal_period="2026.12E",
            estimate_value=Decimal(1000),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 7, 1),
            source_url=None,
            is_estimate=True,
        ),
        EarningsEstimateView(
            provider="TEST",
            broker="B증권",
            metric_code="FORWARD_EPS",
            fiscal_period="2026.12E",
            estimate_value=Decimal(1200),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 7, 2),
            source_url=None,
            is_estimate=True,
        ),
        EarningsEstimateView(
            provider="TEST",
            broker="A증권",
            metric_code="EPS",
            fiscal_period="2027.12E",
            estimate_value=Decimal(2000),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 7, 3),
            source_url=None,
            is_estimate=True,
        ),
    )

    forward_per, period, sample_count = _forward_per_from_estimates(
        Decimal(11000),
        estimates,
        as_of_date=date(2026, 7, 31),
    )

    assert forward_per == Decimal(10)
    assert period == "2026.12E"
    assert sample_count == 2


def test_forward_per_rejects_trailing_or_unverified_eps() -> None:
    estimates = (
        EarningsEstimateView(
            provider="TEST",
            broker="A증권",
            metric_code="EPS",
            fiscal_period="2025.12",
            estimate_value=Decimal(1000),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 3, 1),
            source_url=None,
            is_estimate=True,
        ),
        EarningsEstimateView(
            provider="TEST",
            broker="B증권",
            metric_code="EPS",
            fiscal_period="2026.12E",
            estimate_value=Decimal(1100),
            unit="원/주",
            currency="KRW",
            published_date=date(2026, 7, 1),
            source_url=None,
            is_estimate=False,
        ),
    )

    assert _forward_per_from_estimates(
        Decimal(11000),
        estimates,
        as_of_date=date(2026, 7, 31),
    ) == (None, None, 0)


def test_entry_readiness_label_uses_configured_recommendation_threshold() -> None:
    threshold = Decimal(65)

    assert _entry_readiness_label(Decimal("64.999"), threshold) == "대기"
    assert _entry_readiness_label(Decimal(65), threshold) == "진입 검토 가능"
    assert _entry_readiness_label(None, threshold) == "계산 불가"


def test_recommendation_display_orders_investment_before_entry_readiness() -> None:
    high_investment = SimpleNamespace(
        investment_score=Decimal(82),
        entry_score=Decimal(60),
        data_confidence=Decimal(98),
    )
    entry_ready_but_weaker = SimpleNamespace(
        investment_score=Decimal(65),
        entry_score=Decimal(68),
        data_confidence=Decimal(98),
    )

    ordered = _sorted_decisions(
        (entry_ready_but_weaker, high_investment),
        entry_threshold=Decimal(65),
    )

    assert ordered == (high_investment, entry_ready_but_weaker)


def test_verified_absence_of_going_concern_risk_is_not_shown_as_unknown() -> None:
    assert _format_going_concern("VERIFIED", False) == "중대한 불확실성 없음"
    assert _format_going_concern("NOT_VERIFIED", False) == "확인 불가"


def test_phase2_decision_distinguishes_filter_failure_from_missing_data() -> None:
    failed_filter = SimpleNamespace(
        name="유동성",
        is_blocking=True,
        state=SimpleNamespace(value="FAIL"),
    )
    failed = SimpleNamespace(
        recommendation_computable=False,
        filters=[failed_filter],
        missing_core_data=[],
    )
    missing = SimpleNamespace(
        recommendation_computable=False,
        filters=[],
        missing_core_data=["MARKET_STATUS"],
    )

    assert _format_phase2_decision(failed) == "강제필터 미통과: 유동성"
    assert _format_phase2_decision(missing) == "데이터 부족으로 계산 불가"
    assert _format_phase2_score(None, failed) == "강제필터 미통과로 미산출 (유동성)"
    assert _format_phase2_score(None, missing) == "핵심 데이터 부족으로 미산출"


def test_dividend_summary_reports_frequency_and_simple_yield() -> None:
    annual = SimpleNamespace(
        dps=Decimal(330),
        dividend_type="CASH_DPS_ANNUAL",
    )
    first_quarter = SimpleNamespace(
        dps=Decimal(80),
        dividend_type="CASH_DPS_Q1",
    )
    latest_price = SimpleNamespace(
        close_price=Decimal(4190),
        currency="KRW",
    )

    assert _dividend_frequency((annual,)) == "연배당만 확인"
    assert _dividend_frequency((annual, first_quarter)) == "분기배당 이력 확인"
    assert _format_dividend_yield(Decimal(330), latest_price) == "7.88%"


def test_financial_chart_normalizes_scale_and_calculates_growth() -> None:
    values = {
        2023: Decimal(1000),
        2024: Decimal(1050),
        2025: Decimal("1102.5"),
    }

    index_rows, index_title = _financial_chart_rows(
        values,
        "첫해=100 변화지수",
    )
    growth_rows, growth_title = _financial_chart_rows(
        values,
        "전년 대비 증감률(%)",
    )

    assert [row["값"] for row in index_rows] == [100.0, 105.0, 110.25]
    assert index_title == "변화지수 (첫해=100)"
    assert [row["값"] for row in growth_rows] == [5.0, 5.0]
    assert growth_title == "전년 대비 증감률 (%)"


def test_stock_chart_rows_calculate_moving_averages_before_visible_slice() -> None:
    first_day = date(2026, 1, 1)
    history = [
        AdjustedPricePoint(
            trade_date=first_day + timedelta(days=index),
            open=Decimal(10_000 + index),
            high=Decimal(10_100 + index),
            low=Decimal(9_900 + index),
            close=Decimal(10_000 + index),
            volume=Decimal(1_000_000 + index),
            is_adjusted=True,
            adjustment_status="VERIFIED",
            source_provider="KIS",
        )
        for index in range(130)
    ]

    rows = _stock_chart_rows(history, visible_days=65)

    assert len(rows) == 65
    assert rows[0]["날짜"] == (first_day + timedelta(days=65)).isoformat()
    assert rows[-1]["MA5"] == pytest.approx(10_127)
    assert rows[-1]["MA20"] == pytest.approx(10_119.5)
    assert rows[-1]["MA60"] == pytest.approx(10_099.5)
    assert rows[-1]["MA120"] == pytest.approx(10_069.5)


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
    assert "연결 미검증" in text
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


def test_krx_preview_menu_opens_with_truthful_empty_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "krx-preview.db", monkeypatch)
    get_settings.cache_clear()

    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.radio[0].set_value("통합 API 미리보기").run()
    text = rendered_text(app)

    assert not app.exception
    assert "통합 API 데이터 미리보기" in text
    assert [tab.label for tab in app.tabs] == [
        "종목 기본정보",
        "일별 가격",
        "KOSPI 지수",
        "OpenDART 공시 미리보기",
        "KIS 투자의견·수급·공매도",
        "네이버 종목 뉴스",
        "ECOS 금리·환율 차트",
        "전체 데이터 최신 수집 시각",
        "KRX 수집 이력",
    ]
    assert "조건에 맞는 KRX 종목 기본정보가 없습니다." in text
    assert "저장된 KRX 일별 가격이 없습니다." not in text


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
    assert any(button.label == "최신 시장국면 갱신" for button in app.button)
    assert "최신 확정 일별 데이터 기준" in text
    assert "삼성전자" not in text
    assert "005930" not in text


def test_market_dashboard_refresh_button_runs_data_and_regime_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate_database(tmp_path / "refresh-market.db", monkeypatch)
    get_settings.cache_clear()
    calls: list[str] = []

    class FakeDataService:
        def __init__(self, _: Settings) -> None:
            calls.append("data_init")

        async def refresh(self, *, as_of_date: object) -> SimpleNamespace:
            calls.append(f"data_refresh:{as_of_date}")
            return SimpleNamespace(errors=())

        def close(self) -> None:
            calls.append("data_close")

    class FakeRegimeService:
        def __init__(self, _: Settings) -> None:
            calls.append("regime_init")

        def analyze_and_store(self, **_: object) -> SimpleNamespace:
            calls.append("regime_analyze")
            return SimpleNamespace(
                state=DataState.AVAILABLE,
                market_regime=SimpleNamespace(value="GREEN"),
                missing_core_data=(),
            )

        def close(self) -> None:
            calls.append("regime_close")

    monkeypatch.setattr(
        market_dashboard_ui,
        "Phase3DataService",
        FakeDataService,
    )
    monkeypatch.setattr(
        market_dashboard_ui,
        "MarketRegimeService",
        FakeRegimeService,
    )

    app = AppTest.from_file("app/main.py", default_timeout=15).run()
    app.radio[0].set_value("시장국면 대시보드").run()
    refresh_button = next(
        button for button in app.button if button.label == "최신 시장국면 갱신"
    )
    refresh_button.click().run()

    assert not app.exception
    assert any("시장국면 갱신 완료" in item.value for item in app.success)
    assert "regime_analyze" in calls
    assert calls[-2:] == ["data_close", "regime_close"]


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
    assert "관심종목 · 0/50" in text
    assert "등록된 관심종목이 없습니다" in text
    assert [tab.label for tab in app.tabs] == ["관심종목", "종목별 조회"]
    assert "저장된 공식 이벤트가 없습니다" not in text
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
    assert "OpenDART: 미설정" in text
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
    app.button[0].click().run()
    assert not app.number_input
    app.selectbox[0].set_value(app.selectbox[0].options[0]).run()
    app.session_state["stock-detail-analysis-tab-000007"] = "강제필터·점수"
    app.run()
    text = rendered_text(app)

    assert not app.exception
    assert "강제필터" in text
    assert "누락된 핵심 데이터" in text
    assert "추천 계산 불가" in text
    assert "가짜" not in text
