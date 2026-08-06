from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from app.models.financial import StockAnalysisSnapshot, TechnicalSnapshot
from app.models.metadata import DataState, FinancialScope
from app.models.stock import (
    ListingStatus,
    ProductType,
    ShareClass,
    StockQualityState,
    StockSearchResult,
)
from app.services.stock_analysis_service import StockAnalysisService
from app.ui import stock_search
from tests.helpers import make_settings

SEOUL = ZoneInfo("Asia/Seoul")


class _TrackedFinancialRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_stock(self, session: object, symbol: str) -> object:
        del session, symbol
        self.calls.append("stock")
        return SimpleNamespace(id=1)

    def latest_mapped_accounts(
        self, session: object, stock_id: int
    ) -> tuple[FinancialScope, tuple[()]]:
        del session, stock_id
        self.calls.append("accounts")
        return FinancialScope.UNKNOWN, ()

    def annual_mapped_account_history(
        self, session: object, stock_id: int, *, limit_years: int
    ) -> tuple[()]:
        del session, stock_id, limit_years
        self.calls.append("history")
        return ()

    def dividend_history(self, session: object, stock_id: int) -> tuple[()]:
        del session, stock_id
        self.calls.append("dividend")
        return ()

    def latest_audit(self, session: object, stock_id: int) -> None:
        del session, stock_id
        self.calls.append("audit")


class _TrackedDisclosureRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def dividend_decisions(self, session: object, stock_id: int) -> tuple[()]:
        del session, stock_id
        self.calls.append("source")
        return ()


class _TrackedPriceRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def history_for_symbol(self, session: object, symbol: str) -> list[object]:
        del session, symbol
        self.calls.append("technical")
        return []


@pytest.mark.parametrize(
    ("section", "financial_calls", "disclosure_calls", "price_calls"),
    [
        ("finance", ["stock", "accounts", "history"], [], []),
        ("dividend", ["stock", "dividend"], [], []),
        ("audit", ["stock", "audit"], [], []),
        ("source", ["stock"], ["source"], []),
        ("technical", ["stock"], [], ["technical"]),
    ],
)
def test_stock_analysis_snapshot_only_queries_requested_section(
    section: str,
    financial_calls: list[str],
    disclosure_calls: list[str],
    price_calls: list[str],
) -> None:
    financials = _TrackedFinancialRepository()
    disclosures = _TrackedDisclosureRepository()
    prices = _TrackedPriceRepository()
    service = StockAnalysisService.__new__(StockAnalysisService)
    service._financials = financials
    service._disclosures = disclosures
    service._prices = prices

    @contextmanager
    def sessions() -> Iterator[object]:
        yield object()

    service._sessions = sessions
    snapshot = service.snapshot("000001", sections=(section,))

    assert snapshot is not None
    assert financials.calls == financial_calls
    assert disclosures.calls == disclosure_calls
    assert prices.calls == price_calls
    if section != "technical":
        assert snapshot.technical.state == DataState.MISSING


def test_analysis_snapshot_cache_is_reused_per_symbol_and_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    class FakeAnalysisService:
        def __init__(self, settings: object) -> None:
            del settings

        def snapshot(self, symbol: str, *, sections: tuple[str, ...]) -> None:
            calls.append((symbol, sections))

        def close(self) -> None:
            pass

    monkeypatch.setattr(stock_search, "StockAnalysisService", FakeAnalysisService)
    stock_search._cached_analysis_snapshot.clear()
    settings = make_settings(database_url="sqlite+pysqlite:///:memory:")
    try:
        for _ in range(2):
            stock_search._cached_analysis_snapshot(
                settings.database_url,
                settings,
                "000001",
                ("finance",),
            )
        stock_search._cached_analysis_snapshot(
            settings.database_url,
            settings,
            "000001",
            ("dividend",),
        )
    finally:
        stock_search._cached_analysis_snapshot.clear()

    assert calls == [
        ("000001", ("finance",)),
        ("000001", ("dividend",)),
    ]


def _render_lazy_detail_test_app(settings: object) -> None:
    from app.ui.stock_search import render_stock_search

    render_stock_search(settings)  # type: ignore[arg-type]


def test_detail_tab_reruns_only_invoke_the_selected_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    rendered_score_tabs: list[tuple[object, object]] = []
    snapshot = StockAnalysisSnapshot(
        symbol="000001",
        financial_scope=FinancialScope.UNKNOWN,
        technical=TechnicalSnapshot(state=DataState.MISSING),
    )
    stock = StockSearchResult(
        symbol="000001",
        name="지연검증",
        is_kospi=True,
        market_name="KOSPI",
        official_product_name="보통주",
        product_type=ProductType.STOCK,
        official_share_class_name="보통주",
        share_class=ShareClass.COMMON,
        listing_status=ListingStatus.LISTED,
        dart_corp_code="00126380",
        dart_modified_on=None,
        dart_collected_at=None,
        dart_data_state=DataState.AVAILABLE,
        source_provider="KRX",
        as_of_at=None,
        collected_at=datetime(2026, 8, 6, 9, 0, tzinfo=SEOUL),
        quality_state=StockQualityState.VALID,
    )

    def stock_count(database_url: str, settings: object) -> int:
        del database_url, settings
        return 1

    def stock_results(
        database_url: str, settings: object, query: str
    ) -> tuple[list[StockSearchResult], dict[object, object], dict[object, object]]:
        del database_url, settings, query
        return [stock], {}, {}

    def summary_context(
        database_url: str, settings: object, symbol: str
    ) -> tuple[StockAnalysisSnapshot, list[object], None, list[object], None]:
        del database_url, settings
        calls.append(("summary", symbol))
        return snapshot, [], None, [], None

    def analysis_snapshot(
        database_url: str,
        settings: object,
        symbol: str,
        sections: tuple[str, ...],
    ) -> StockAnalysisSnapshot:
        del database_url, settings
        calls.append(("analysis", sections))
        assert symbol == "000001"
        return snapshot

    def phase2_context(
        database_url: str, settings: object, symbol: str
    ) -> tuple[None, None]:
        del database_url, settings
        calls.append(("phase2", symbol))
        return None, None

    def evaluate_phase2(
        settings: object, symbol: str, planned_order_amount: object
    ) -> None:
        del settings, planned_order_amount
        calls.append(("evaluate", symbol))

    summary_context.clear = lambda: calls.append(("clear", "summary"))  # type: ignore[attr-defined]
    phase2_context.clear = lambda: calls.append(("clear", "phase2"))  # type: ignore[attr-defined]
    monkeypatch.setattr(stock_search, "_cached_stock_count", stock_count)
    monkeypatch.setattr(stock_search, "_cached_stock_search", stock_results)
    monkeypatch.setattr(stock_search, "_cached_summary_context", summary_context)
    monkeypatch.setattr(stock_search, "_cached_analysis_snapshot", analysis_snapshot)
    monkeypatch.setattr(stock_search, "_cached_phase2_context", phase2_context)
    monkeypatch.setattr(stock_search, "_evaluate_phase2", evaluate_phase2)
    monkeypatch.setattr(stock_search, "_render_stock_price_panel", lambda *args: None)
    monkeypatch.setattr(
        stock_search,
        "_render_phase2_score",
        lambda result, readiness: rendered_score_tabs.append((result, readiness)),
    )

    settings = make_settings(database_url="sqlite+pysqlite:///:memory:")
    app = AppTest.from_function(
        _render_lazy_detail_test_app,
        kwargs={"settings": settings},
        default_timeout=15,
    )
    app.session_state["stock_search_query"] = "지연검증"
    app.run()
    app.selectbox[0].set_value("지연검증 (000001)").run()

    assert not app.exception
    assert calls == [("summary", "000001"), ("phase2", "000001")]
    assert rendered_score_tabs == []

    for label, sections in (
        ("배당", ("dividend",)),
        ("재무", ("finance",)),
        ("감사", ("audit",)),
        ("기술지표·진입시점", ("technical",)),
        ("공시·원자료", ("source",)),
    ):
        app.session_state["stock-detail-analysis-tab-000001"] = label
        app.run()
        assert not app.exception
        assert calls[-1] == ("analysis", sections)
        assert rendered_score_tabs == []
    assert calls.count(("summary", "000001")) == 1

    app.session_state["stock-detail-analysis-tab-000001"] = "강제필터·점수"
    app.run()
    assert not app.exception
    assert calls[-6:] == [
        ("analysis", ()),
        ("phase2", "000001"),
        ("evaluate", "000001"),
        ("clear", "phase2"),
        ("clear", "summary"),
        ("phase2", "000001"),
    ]
    assert rendered_score_tabs == [(None, None)]
